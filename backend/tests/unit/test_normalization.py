"""Normalizacja to fundament entity resolution — testujemy ją najgęściej."""

from __future__ import annotations

import pytest

from business_osint.domain.normalization import (
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
