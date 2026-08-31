"""Odczyt stanu rejestracji LEI z odpowiedzi GLEIF."""

from __future__ import annotations

from business_osint.etl.sources.gleif_mapper import parse_lei_registrations

ODPOWIEDZ = {
    "data": [
        {
            "id": "259400PT570TS4W3OQ80",
            "attributes": {
                "lei": "259400PT570TS4W3OQ80",
                "registration": {"status": "LAPSED"},
                "entity": {"legalName": {"name": "PLATINIUM M.M. SPÓŁKA KOMANDYTOWA"}},
            },
        },
        {
            "id": "549300C1770XZTTOQ626",
            "attributes": {
                "lei": "549300C1770XZTTOQ626",
                "registration": {"status": "DUPLICATE"},
                "entity": {"legalName": {"name": "PLATINIUM M.M SPÓŁKA KOMANDYTOWA"}},
            },
        },
    ]
}


def test_status_and_name_are_read_for_every_record() -> None:
    """To jest cała wartość tej funkcji: numer bez stanu niczego nie wyjaśnia."""
    records = parse_lei_registrations(ODPOWIEDZ)

    assert [r["status"] for r in records] == ["LAPSED", "DUPLICATE"]
    assert records[0]["lei"] == "259400PT570TS4W3OQ80"
    assert records[1]["name"] == "PLATINIUM M.M SPÓŁKA KOMANDYTOWA"


def test_record_without_a_number_is_skipped() -> None:
    """Rekord bez LEI nie ma czym być zidentyfikowany — pomijamy, nie zgadujemy."""
    assert parse_lei_registrations({"data": [{"attributes": {}}]}) == []


def test_number_is_taken_from_id_when_the_attribute_is_absent() -> None:
    """GLEIF powtarza numer w dwóch miejscach; brak jednego nie ma gubić rekordu."""
    records = parse_lei_registrations({"data": [{"id": "X", "attributes": {}}]})

    assert [r["lei"] for r in records] == ["X"]


def test_missing_status_or_name_gives_none_not_an_error() -> None:
    """Niekompletny rekord ma dać puste pola, a nie wywrócić import."""
    records = parse_lei_registrations({"data": [{"id": "X", "attributes": {"lei": "X"}}]})

    assert records == [{"lei": "X", "status": None, "name": None}]


def test_empty_response_yields_nothing() -> None:
    assert parse_lei_registrations({}) == []
    assert parse_lei_registrations({"data": None}) == []
