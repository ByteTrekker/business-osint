"""Normalizacja nazw i walidacja identyfikatorów rejestrowych.

Moduł jest czysty (bez I/O i bez bazy) — dzięki temu testuje się go w milisekundach
i można go wołać zarówno z ETL, jak i z API.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

__all__ = [
    "LEGAL_FORM_TOKENS",
    "company_name_blocking_key",
    "is_valid_krs",
    "is_valid_nip",
    "is_valid_regon",
    "normalize_company_name",
    "normalize_person_name",
    "person_blocking_key",
    "pesel_hash",
    "split_person_name",
]

#: Formy prawne i skróty usuwane przy porównywaniu nazw.
#: Klucz -> forma kanoniczna (przydatna do wypełnienia companies.legal_form).
LEGAL_FORM_TOKENS: dict[str, str] = {
    "spolka z ograniczona odpowiedzialnoscia": "sp_zoo",
    "sp z o o": "sp_zoo",
    "spzoo": "sp_zoo",
    "sp z oo": "sp_zoo",
    "z o o": "sp_zoo",
    "spolka akcyjna": "sa",
    "s a": "sa",
    "prosta spolka akcyjna": "psa",
    "p s a": "psa",
    "spolka komandytowa": "sk",
    "sp k": "sk",
    "spolka komandytowo akcyjna": "ska",
    "s k a": "ska",
    "spolka jawna": "sj",
    "sp j": "sj",
    "spolka cywilna": "sc",
    "s c": "sc",
    "spolka partnerska": "sp",
    "spolka z o o spolka komandytowa": "sp_zoo_sk",
    "w likwidacji": "",
    "w organizacji": "",
    "w upadlosci": "",
    "w restrukturyzacji": "",
}

_WS_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^0-9a-z ]+")
_DIGITS_RE = re.compile(r"\D+")

# Znaki, których NFKD nie rozkłada — trzeba je zmapować ręcznie.
_MANUAL_TRANSLIT = str.maketrans({"ł": "l", "Ł": "L", "ø": "o", "æ": "ae", "ß": "ss"})


def _fold(text: str) -> str:
    """Usuwa diakrytykę, sprowadza do lowercase, zostawia [a-z0-9 ]."""
    folded = text.translate(_MANUAL_TRANSLIT)
    folded = unicodedata.normalize("NFKD", folded)
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    folded = folded.lower()
    folded = _NON_ALNUM_RE.sub(" ", folded)
    return _WS_RE.sub(" ", folded).strip()


def normalize_company_name(raw: str) -> str:
    """Nazwa firmy sprowadzona do postaci porównywalnej.

    >>> normalize_company_name('"ACME" Sp. z o.o. w likwidacji')
    'acme'
    >>> normalize_company_name("ACME SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ")
    'acme'
    """
    name = _fold(raw)
    # Najdłuższe frazy najpierw, żeby "spolka z o o spolka komandytowa" wygrało z "sp k".
    for token in sorted(LEGAL_FORM_TOKENS, key=len, reverse=True):
        name = re.sub(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", " ", name)
    return _WS_RE.sub(" ", name).strip()


def normalize_person_name(raw: str) -> str:
    """Imię i nazwisko bez diakrytyki, w stałej kolejności tokenów."""
    return _fold(raw)


def address_search_key(raw: str) -> str:
    """Adres w postaci, po której da się **szukać** — z zachowanymi granicami słów.

    Adres pełni w tym systemie dwie różne role i przez długi czas dzielił dla
    obu jedną wartość, co uniemożliwiało wyszukiwanie:

    * **klucz naturalny** (`addresses.normalized`) służy do scalania i musi być
      sklejony w jeden ciąg, żeby „ul. Chemików 7" i „Chemików 7" trafiły w ten
      sam wiersz. Robi to `address_natural_key`.
    * **pole wyszukiwania** (`entities.normalized_name`) musi mieć spacje, bo
      indeks pełnotekstowy dzieli po słowach. Bez nich cały adres jest jednym
      tokenem i zapytanie „chemikow plock" nie ma czego dopasować.

    >>> address_search_key("Chemików 7, 09-411 Płock")
    'chemikow 7 09 411 plock'
    """
    return _fold(raw)


def address_natural_key(raw: str) -> str:
    """Adres jako klucz scalania — bez spacji, bo różnice w zapisie mają zniknąć.

    >>> address_natural_key("ul. Chemików 7, 09-411 Płock")
    'ulchemikow709411plock'
    >>> address_natural_key("Chemików 7, 09-411, Płock") == address_natural_key(
    ...     "Chemików 7, 09-411 Płock"
    ... )
    True
    """
    return _fold(raw).replace(" ", "")


def split_person_name(raw: str) -> tuple[str, str]:
    """Rozdziela 'KOWALSKI JAN ANDRZEJ' / 'Jan Kowalski' na (imiona, nazwisko).

    KRS podaje osoby jako trzy osobne pola; ten helper jest dla źródeł,
    które zwracają jeden string. Heurystyka: jeżeli jest przecinek, to
    'NAZWISKO, IMIONA'; w przeciwnym razie ostatni token to nazwisko.
    """
    cleaned = _WS_RE.sub(" ", raw.strip())
    if "," in cleaned:
        last, _, first = cleaned.partition(",")
        return first.strip(), last.strip()
    parts = cleaned.split(" ")
    if len(parts) == 1:
        return "", parts[0]
    return " ".join(parts[:-1]), parts[-1]


def company_name_blocking_key(raw: str) -> str:
    """Klucz blokujący do entity resolution: pierwsze 12 znaków nazwy bez spacji."""
    return normalize_company_name(raw).replace(" ", "")[:12]


def person_blocking_key(first_names: str, last_name: str, birth_year: int | None = None) -> str:
    """Klucz blokujący dla osoby: pierwsze imię + nazwisko (+ rocznik, jeśli znany)."""
    first = normalize_person_name(first_names).split(" ")[0] if first_names.strip() else ""
    last = normalize_person_name(last_name).replace(" ", "")
    key = f"{first}|{last}"
    return f"{key}|{birth_year}" if birth_year else key


def _checksum(digits: str, weights: tuple[int, ...], modulo: int) -> int:
    """Suma kontrolna wg wag rejestru.

    ``strict=True`` celowo: przy ``strict=False`` zły wycinek cyfr (np. ``[:10]``
    zamiast ``[:9]``) byłby po cichu ucinany do długości wag i dawał poprawny
    wynik mimo błędu. Testy mutacyjne pokazały, że taka pomyłka przechodzi
    niezauważona — teraz kończy się wyjątkiem.
    """
    return sum(int(d) * w for d, w in zip(digits, weights, strict=True)) % modulo


def is_valid_nip(value: str) -> bool:
    """Walidacja sumy kontrolnej NIP (10 cyfr)."""
    digits = _DIGITS_RE.sub("", value)
    if len(digits) != 10 or digits == "0" * 10:
        return False
    control = _checksum(digits[:9], (6, 5, 7, 2, 3, 4, 5, 6, 7), 11)
    # Reszta 10 nie ma reprezentacji jako cyfra kontrolna, więc taki prefiks
    # nigdy nie utworzy poprawnego NIP-u — porównanie z cyfrą (0-9) załatwia to
    # samo, co jawny strażnik `control != 10`, który był martwym kodem.
    return control == int(digits[9])


def is_valid_regon(value: str) -> bool:
    """Walidacja sumy kontrolnej REGON (9 lub 14 cyfr)."""
    digits = _DIGITS_RE.sub("", value)
    if len(digits) == 9:
        control = _checksum(digits[:8], (8, 9, 2, 3, 4, 5, 6, 7), 11) % 10
        return control == int(digits[8])
    if len(digits) == 14:
        if not is_valid_regon(digits[:9]):
            return False
        control = _checksum(digits[:13], (2, 4, 8, 5, 0, 9, 7, 3, 6, 1, 2, 4, 8), 11) % 10
        return control == int(digits[13])
    return False


def is_valid_krs(value: str) -> bool:
    """KRS nie ma sumy kontrolnej — sprawdzamy tylko format (10 cyfr)."""
    digits = _DIGITS_RE.sub("", value)
    return len(digits) == 10


def pesel_hash(pesel: str, pepper: str) -> str:
    """Nieodwracalny identyfikator osoby.

    PESEL jest daną wrażliwą (RODO) — nigdy nie zapisujemy go jawnie.
    Pepper trzymamy w sekrecie aplikacji, żeby utrudnić atak słownikowy
    (przestrzeń PESEL jest mała i da się ją przeliczyć w całości).
    """
    digits = _DIGITS_RE.sub("", pesel)
    if len(digits) != 11:
        raise ValueError("PESEL musi mieć 11 cyfr")
    return hashlib.blake2b(f"{pepper}:{digits}".encode(), digest_size=16).hexdigest()
