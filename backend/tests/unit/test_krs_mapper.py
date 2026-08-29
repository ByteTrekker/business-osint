"""Mapper KRS na zamrożonym fragmencie odpisu.

Fixture jest celowo w repo: gdy ministerstwo zmieni schemat, ten test
zrobi się czerwony zanim graf zacznie po cichu pustoszeć.
"""

from __future__ import annotations

import datetime as dt

from business_osint.domain.enums import EntityType, RelationshipType
from business_osint.etl.sources.krs_mapper import parse_krs_document

ODPIS = {
    "odpis": {
        "dane": {
            "naglowekA": {"numerKRS": "0000111111", "dataRejestracjiWKRS": "2015-03-01"},
            "dzial1": {
                "danePodmiotu": {
                    "nazwa": "ALFA TECHNOLOGIE SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ",
                    "formaPrawna": "SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ",
                    "identyfikatory": {"nip": "5252445170", "regon": "012345675"},
                },
                "siedzibaIAdres": {
                    "siedziba": {"wojewodztwo": "MAZOWIECKIE", "miejscowosc": "WARSZAWA"},
                    "adres": {
                        "ulica": "ALEJE JEROZOLIMSKIE",
                        "nrDomu": "100",
                        "kodPocztowy": "00-807",
                        "miejscowosc": "WARSZAWA",
                    },
                },
                "wspolnicy": [
                    {
                        "nazwisko": {"nazwiskoICzlonPierwszyNazwiskaZlozonego": "KOWALSKI"},
                        "imiona": {"imiePierwsze": "JAN"},
                        "udzialy": {"liczbaUdzialow": "100", "wartoscUdzialow": "50000"},
                        "dataOd": "2019-01-08",
                    }
                ],
            },
            "dzial2": {
                "reprezentacja": {
                    "nazwaOrganu": "ZARZĄD",
                    "sklad": [
                        {
                            "nazwisko": {"nazwiskoICzlonPierwszyNazwiskaZlozonego": "KOWALSKI"},
                            "imiona": {"imiePierwsze": "JAN"},
                            "funkcjaWOrganie": "PREZES ZARZĄDU",
                            "dataOd": "2018-05-12",
                        },
                        {
                            "nazwisko": {"nazwiskoICzlonPierwszyNazwiskaZlozonego": "NOWAK"},
                            "imiona": {"imiePierwsze": "ANNA"},
                            "funkcjaWOrganie": "CZŁONEK ZARZĄDU",
                            "dataOd": "2020-02-01",
                            "dataDo": "2023-06-30",
                        },
                    ],
                }
            },
        }
    }
}


def test_company_is_extracted_with_identifiers() -> None:
    parsed = parse_krs_document(ODPIS)
    company = next(e for e in parsed.entities if e.entity_type is EntityType.COMPANY)
    assert company.normalized_name == "alfa technologie"
    assert set(company.identifiers.values()) == {"0000111111", "5252445170", "012345675"}


def test_board_members_become_relationships_with_validity_period() -> None:
    parsed = parse_krs_document(ODPIS)
    board = [
        r for r in parsed.relationships if r.relationship_type is RelationshipType.BOARD_MEMBER_OF
    ]
    assert len(board) == 2
    active = next(r for r in board if r.valid_to is None)
    former = next(r for r in board if r.valid_to is not None)
    assert active.role == "PREZES ZARZĄDU"
    assert active.valid_from == dt.date(2018, 5, 12)
    # To jest dokładnie przypadek "był członkiem zarządu 2020-2023".
    assert former.valid_from == dt.date(2020, 2, 1)
    assert former.valid_to == dt.date(2023, 6, 30)


def test_every_relationship_carries_a_locator_for_provenance() -> None:
    parsed = parse_krs_document(ODPIS)
    assert parsed.relationships
    assert all(r.locator for r in parsed.relationships)


def test_address_becomes_its_own_node() -> None:
    parsed = parse_krs_document(ODPIS)
    address = next(e for e in parsed.entities if e.entity_type is EntityType.ADDRESS)
    assert "100" in address.display_name
    assert any(
        r.relationship_type is RelationshipType.REGISTERED_AT for r in parsed.relationships
    )


def test_shareholder_shares_are_preserved() -> None:
    parsed = parse_krs_document(ODPIS)
    shareholder = next(
        r for r in parsed.relationships if r.relationship_type is RelationshipType.SHAREHOLDER_OF
    )
    assert shareholder.attributes["shares_count"] == "100"


def test_empty_document_does_not_explode() -> None:
    assert parse_krs_document({}).entities == []
