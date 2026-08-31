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


#: Rodzaj ulicy jest w polskich rejestrach zapisywany niekonsekwentnie: „ul.",
#: „ul", „aleja", albo wcale. Nie niesie informacji odróżniającej adresy, więc
#: przy dopasowaniu go usuwamy — inaczej „ul. Chemików" i „Chemików" byłyby
#: dwoma różnymi ulicami.
_STREET_PREFIX_RE = re.compile(
    r"^(ul\.|ul\b|al\.|al\b|aleja|aleje|pl\.|plac|os\.|osiedle|rondo|skwer)\s*",
    re.IGNORECASE,
)


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


def format_address(*, street: str, building: str, unit: str, postal_code: str, city: str) -> str:
    """Adres w zapisie polskim: `ul. Kąty 14/2, 34-443 Sromowce Wyżne`.

    Przecinek oddziela wyłącznie ulicę od kodu pocztowego. Wcześniejsza wersja
    wstawiała go między każdy człon („ul. Kąty, 14, 34-443, Sromowce Wyżne"),
    co jest poprawne maszynowo, ale nie jest adresem, jaki ktokolwiek napisze.
    """
    line = street
    if building:
        line = f"{line} {building}".strip()
        if unit:
            line = f"{line}/{unit}"
    elif unit:
        line = f"{line} {unit}".strip()

    locality = " ".join(part for part in (postal_code, city) if part)
    return ", ".join(part for part in (line.strip(), locality) if part)


def street_from_address_line(line: str, *, city: str, building: str | None) -> str:
    """Wyciąga samą nazwę ulicy z jednoliniowego zapisu adresu.

    Rejestry potrafią wpisać w jedno pole miejscowość, ulicę i numer:
    GLEIF podaje `addressLines: ["PŁOCK BIELSKA 67"]` i dopiero obok, w polu
    `addressNumber`, sam numer. Wrzucenie takiej linii do kolumny `street` —
    co robiliśmy — powoduje, że ten sam adres z dwóch źródeł ma różne kolumny
    i nie da się go ani scalić, ani dopasować do punktu adresowego.

    Usuwamy to, co wiemy skądinąd: nazwę miejscowości i numer budynku. Reszta
    jest ulicą. Świadomie nie zgadujemy niczego ponadto — linia, której nie da
    się rozłożyć, wraca w całości, bo lepszy pełny zapis niż okrojony.

    >>> street_from_address_line("PŁOCK BIELSKA 67", city="PŁOCK", building="67")
    'BIELSKA'
    >>> street_from_address_line("ul. Chemików 7", city="Płock", building="7")
    'Chemików'
    >>> street_from_address_line("Bielska", city="Płock", building=None)
    'Bielska'
    """
    rest = line.strip()
    if city and _fold(rest).startswith(_fold(city)):
        rest = rest[len(city) :].strip(" ,")
    rest = _STREET_PREFIX_RE.sub("", rest).strip()
    if building:
        # Numer bierzemy z końca: „Bielska 67" tak, ale „3 Maja 5" nie może
        # stracić trójki z nazwy ulicy.
        suffix = building.strip()
        if rest.lower().endswith(suffix.lower()):
            rest = rest[: -len(suffix)].strip(" ,/")
    return rest or line.strip()


def address_point_key(*, city: str, street: str, building: str) -> str:
    """Klucz dopasowania adresu do punktu adresowego z rejestru geodezyjnego.

    Osobna funkcja, a nie `address_natural_key` na sklejonym napisie, bo obie
    strony dopasowania mają **kolumny**, nie zdania. PRG podaje miejscowość,
    ulicę i numer w osobnych polach, my też — a napis, który by z nich powstał,
    różniłby się interpunkcją po każdej ze stron i dopasowanie padłoby na czymś,
    co nie jest różnicą w adresie.

    Kolejność jest ustalona: miejscowość, ulica, numer. Numer bywa zapisany
    z literą albo z ukośnikiem (`28a`, `14/2`) i to jest część adresu, więc
    zostaje — znika tylko to, co nie niesie informacji.

    >>> address_point_key(city="Płock", street="ul. Chemików", building="7")
    'plock|chemikow|7'
    >>> address_point_key(city="PŁOCK", street="Chemików", building="7")
    'plock|chemikow|7'
    >>> address_point_key(city="Gdańsk", street="Leczkowa", building="28a/7")
    'gdansk|leczkowa|28a 7'
    """
    return "|".join(
        (
            _fold(city),
            _fold(_STREET_PREFIX_RE.sub("", street.strip())),
            # Bez sklejania: `14/2` i `1/42` po usunięciu spacji dają ten sam
            # napis `142`, czyli dwa różne mieszkania trafiłyby w jeden punkt
            # adresowy. Człony klucza rozdziela `|`, więc spacja w numerze
            # niczego nie psuje.
            _fold(building),
        )
    )


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
