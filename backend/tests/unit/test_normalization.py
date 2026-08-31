"""Normalizacja to fundament entity resolution — testujemy ją najgęściej."""

from __future__ import annotations

import pytest

from business_osint.domain.normalization import (
    address_natural_key,
    address_search_key,
    company_name_blocking_key,
    is_valid_krs,
    is_valid_nip,
    is_valid_regon,
    normalize_company_name,
    normalize_person_name,
    person_blocking_key,
    pesel_hash,
    split_person_name,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ALFA TECHNOLOGIE Sp. z o.o.", "alfa technologie"),
        ('"ALFA TECHNOLOGIE" SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ', "alfa technologie"),
        ("ALFA TECHNOLOGIE sp. z o.o. w likwidacji", "alfa technologie"),
        ("ALFA  TECHNOLOGIE   S.A.", "alfa technologie"),
        ("Łódzka Fabryka Żarówek Sp.J.", "lodzka fabryka zarowek"),
    ],
)
def test_company_names_collapse_to_same_form(raw: str, expected: str) -> None:
    assert normalize_company_name(raw) == expected


def test_legal_form_variants_produce_identical_blocking_key() -> None:
    variants = [
        "BETA LOGISTYKA Sp. z o.o.",
        "BETA LOGISTYKA SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ",
        "beta logistyka sp.zo.o.",
    ]
    keys = {company_name_blocking_key(v) for v in variants}
    assert len(keys) == 1, f"warianty formy prawnej rozjechały się: {keys}"


def test_normalize_does_not_swallow_meaningful_letters() -> None:
    # "SP" w środku nazwy nie jest formą prawną — nie wolno go wyciąć.
    assert "spawmet" in normalize_company_name("SPAWMET Sp. z o.o.")


def test_person_name_is_diacritic_insensitive() -> None:
    assert normalize_person_name("Michał Wójcik") == "michal wojcik"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Jan Kowalski", ("Jan", "Kowalski")),
        ("KOWALSKI, JAN ANDRZEJ", ("JAN ANDRZEJ", "KOWALSKI")),
        ("Jan Andrzej Kowalski", ("Jan Andrzej", "Kowalski")),
    ],
)
def test_split_person_name(raw: str, expected: tuple[str, str]) -> None:
    assert split_person_name(raw) == expected


def test_person_blocking_key_separates_namesakes_by_birth_year() -> None:
    a = person_blocking_key("Jan", "Kowalski", 1975)
    b = person_blocking_key("Jan", "Kowalski", 1990)
    assert a != b


@pytest.mark.parametrize("nip", ["5252445170", "525-244-51-70", "1132456789"])
def test_valid_nip(nip: str) -> None:
    assert is_valid_nip(nip)


@pytest.mark.parametrize("nip", ["5252445172", "1234567890", "525244517", ""])
def test_invalid_nip(nip: str) -> None:
    assert not is_valid_nip(nip)


def test_regon_9_and_14_digits() -> None:
    assert is_valid_regon("012345675")
    assert not is_valid_regon("012345678")


def test_krs_is_format_only() -> None:
    assert is_valid_krs("0000111111")
    assert not is_valid_krs("111111")


def test_pesel_is_never_stored_in_plaintext() -> None:
    digest = pesel_hash("44051401359", pepper="test-pepper")
    assert "44051401359" not in digest
    assert len(digest) == 32
    # Ten sam PESEL + ten sam pepper = ten sam identyfikator (stabilne dopasowanie).
    assert digest == pesel_hash("44051401359", pepper="test-pepper")
    # Inny pepper = inny identyfikator (wyciek bazy nie pozwala na rainbow table).
    assert digest != pesel_hash("44051401359", pepper="other-pepper")


def test_pesel_hash_rejects_malformed_input() -> None:
    with pytest.raises(ValueError, match="11 cyfr"):
        pesel_hash("123", pepper="x")


def test_regon_14_digits_validates_both_parts() -> None:
    """REGON 14-cyfrowy (jednostka lokalna) ma dwie sumy kontrolne — obie muszą się zgadzać."""
    # Poprawny 9-cyfrowy rdzeń, ale błędna cyfra kontrolna części 14-cyfrowej.
    assert not is_valid_regon("01234567500001")
    # Błędny rdzeń dyskwalifikuje cały numer, niezależnie od reszty.
    assert not is_valid_regon("01234567800001")


def test_regon_rejects_other_lengths() -> None:
    assert not is_valid_regon("0123456")
    assert not is_valid_regon("")


def test_single_token_name_is_treated_as_surname() -> None:
    """Rejestry bywają niekompletne — jeden token traktujemy jako nazwisko."""
    assert split_person_name("Kowalski") == ("", "Kowalski")


# --- luki wykryte przez testy mutacyjne (`make mutation`) -------------------


@pytest.mark.parametrize("regon", ["012345675", "274837620"])
def test_valid_9_digit_regon_is_accepted(regon: str) -> None:
    """Numery dobrane tak, by każda waga miała wpływ na wynik.

    Zestaw pochodzi z analizy testów mutacyjnych: numer z zerami na pozycjach
    ważonych nie odróżnia zmiany wagi, bo 0 * w == 0 dla dowolnego w.
    """
    assert is_valid_regon(regon)


@pytest.mark.parametrize("regon", ["01234567500008", "27483762063480", "89889439383283"])
def test_valid_14_digit_regon_is_accepted(regon: str) -> None:
    """Numer jednostki lokalnej: obie sumy kontrolne muszą się zgadzać."""
    assert is_valid_regon(regon)


def test_regon_control_digit_ten_maps_to_zero() -> None:
    """Reszta 10 zapisywana jest jako cyfra kontrolna 0 — stąd podwójne modulo."""
    assert is_valid_regon("274837620")
    assert not is_valid_regon("274837621")


@pytest.mark.parametrize(
    ("value", "checker"),
    [
        ("012-345-675", is_valid_regon),
        ("525-244-51-70", is_valid_nip),
        ("KRS 0000111111", is_valid_krs),
    ],
)
def test_identifiers_ignore_separators(value: str, checker: object) -> None:
    """Rejestry i użytkownicy wklejają numery z myślnikami, spacjami i prefiksem."""
    assert checker(value)  # type: ignore[operator]


def test_all_zero_nip_is_rejected() -> None:
    """0000000000 przechodzi sumę kontrolną, ale nie jest numerem podatnika."""
    assert not is_valid_nip("0000000000")


def test_checksum_rejects_wrong_digit_slice() -> None:
    """Zły wycinek cyfr ma się kończyć wyjątkiem, a nie cichym obcięciem."""
    from business_osint.domain.normalization import _checksum

    with pytest.raises(ValueError, match=r"argument 2 is shorter|zip\(\)"):
        _checksum("1234567890", (6, 5, 7, 2, 3, 4, 5, 6, 7), 11)


def test_company_blocking_key_truncates_at_twelve_characters() -> None:
    """Klucz blokujący ma stałą długość — inaczej długie nazwy tworzą osobne bloki."""
    key = company_name_blocking_key("PRZEDSIĘBIORSTWO WIELOBRANŻOWE BUDOWLANE Sp. z o.o.")
    assert key == "przedsiebior"
    assert len(key) == 12


def test_company_blocking_key_removes_spaces() -> None:
    assert company_name_blocking_key("ALFA TECH Sp. z o.o.") == "alfatech"


def test_person_blocking_key_uses_only_the_first_given_name() -> None:
    """Drugie imię bywa pomijane w rejestrach — nie może różnicować klucza."""
    assert person_blocking_key("Jan Andrzej", "Kowalski") == person_blocking_key("Jan", "Kowalski")
    assert person_blocking_key("Jan Andrzej", "Kowalski") == "jan|kowalski"


def test_person_blocking_key_collapses_compound_surname() -> None:
    assert person_blocking_key("Anna", "Nowak Kowalska") == "anna|nowakkowalska"


def test_person_blocking_key_without_given_name() -> None:
    assert person_blocking_key("", "Kowalski") == "|kowalski"


def test_person_blocking_key_appends_birth_year_only_when_known() -> None:
    assert person_blocking_key("Jan", "Kowalski", 1975) == "jan|kowalski|1975"
    assert person_blocking_key("Jan", "Kowalski", None) == "jan|kowalski"


def test_pesel_hash_ignores_formatting() -> None:
    assert pesel_hash("44051401359", pepper="p") == pesel_hash("440 514 013 59", pepper="p")


def test_pesel_hash_error_message_is_exact() -> None:
    with pytest.raises(ValueError, match=r"^PESEL musi mieć 11 cyfr$"):
        pesel_hash("123", pepper="x")


def test_split_person_name_splits_on_the_first_comma() -> None:
    """Format 'NAZWISKO, IMIONA' — dzielimy na pierwszym przecinku.

    Przy dzieleniu od końca 'KOWALSKI, JAN, ANDRZEJ' dałoby nazwisko
    'KOWALSKI, JAN', czyli sklejenie nazwiska z imieniem.
    """
    assert split_person_name("KOWALSKI, JAN ANDRZEJ") == ("JAN ANDRZEJ", "KOWALSKI")
    assert split_person_name("KOWALSKI, JAN, ANDRZEJ") == ("JAN, ANDRZEJ", "KOWALSKI")


def test_nip_prefix_with_remainder_ten_is_always_rejected() -> None:
    """Reszta 10 nie ma reprezentacji jako cyfra kontrolna.

    Taki prefiks jest odrzucany dla każdej z dziesięciu możliwych cyfr —
    dlatego jawny strażnik `control != 10` był martwym kodem.
    """
    assert not any(is_valid_nip("701001234" + str(digit)) for digit in range(10))


# --- Adres: dwa klucze, dwie role -------------------------------------------


def test_address_search_key_keeps_word_boundaries() -> None:
    """Klucz wyszukiwania musi mieć spacje — indeks pełnotekstowy dzieli po słowach.

    Bez nich cały adres jest jednym tokenem i zapytanie „chemikow plock" nie ma
    czego dopasować. Dokładnie tak wyglądało 2,4 mln adresów w bazie.
    """
    assert address_search_key("Chemików 7, 09-411 Płock") == "chemikow 7 09 411 plock"


def test_address_natural_key_removes_them_on_purpose() -> None:
    """Klucz scalania musi być sklejony, żeby różnice w zapisie zniknęły."""
    assert address_natural_key("ul. Chemików 7, 09-411 Płock") == "ulchemikow709411plock"


def test_the_two_address_keys_are_not_the_same_value() -> None:
    """Jedna wartość w dwóch rolach była właśnie tym defektem.

    Ten test istnieje po to, żeby ktoś nie „uprościł" ich z powrotem do jednej
    funkcji: klucz scalania i pole wyszukiwania mają sprzeczne wymagania.
    """
    adres = "Chemików 7, 09-411 Płock"

    assert address_search_key(adres) != address_natural_key(adres)


def test_differently_punctuated_addresses_merge_to_one_key() -> None:
    """„Chemików 7, 09-411, Płock" i „Chemików 7, 09-411 Płock" to ten sam adres."""
    assert address_natural_key("Chemików 7, 09-411, Płock") == address_natural_key(
        "Chemików 7, 09-411 Płock"
    )


def test_address_without_a_street_still_yields_searchable_words() -> None:
    """Adresy wiejskie to sam numer i miejscowość — muszą być wyszukiwalne tak samo."""
    assert address_search_key("18, 46-310 Jamy") == "18 46 310 jamy"
