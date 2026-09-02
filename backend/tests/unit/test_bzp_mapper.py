"""Mapper BZP na zamrożonym ogłoszeniu o wyniku.

Fixture jest **prawdziwą odpowiedzią** z e-Zamówień, nie wymyśloną. Powód jest
zapisany w CLAUDE.md i wynika z wpadki: raz opisaliśmy w fixture API KRS,
którego ministerstwo nigdy nie wystawiło, i testy przechodziły, opisując
interfejs nieistniejący. To jest gorsze niż brak testu, bo czyta się jak pokrycie.

Zmiana schematu po stronie urzędu ma dawać czerwony test, a nie ciche
pustoszenie grafu.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from business_osint.domain.enums import RelationshipType
from business_osint.etl.sources.bzp_mapper import parse_notices

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "bzp_wyniki.json"


@pytest.fixture(scope="module")
def ogloszenia() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_result_notice_links_a_contractor_to_the_buyer(ogloszenia: dict) -> None:
    wynik = parse_notices(ogloszenia)

    assert wynik.relationships, "ogłoszenie o wyniku musi dać krawędź"
    krawedz = wynik.relationships[0]
    assert krawedz.relationship_type is RelationshipType.CONTRACTOR_OF
    # Kierunek czyta się jak zdanie: WYKONAWCA --contractor_of--> ZAMAWIAJĄCY.
    assert krawedz.source_key != krawedz.target_key


def test_both_sides_are_identified_by_nip_not_by_name(ogloszenia: dict) -> None:
    """Węzeł tworzony po samej nazwie prowadziłby do fałszywych scaleń (N4)."""
    wynik = parse_notices(ogloszenia)

    assert wynik.entities
    for encja in wynik.entities:
        assert encja.local_key.startswith("nip:")
        assert encja.identifiers


def test_edge_carries_the_fields_the_source_actually_provides(ogloszenia: dict) -> None:
    """Regres na zawężenie mappera.

    Źródło daje trzydzieści kilka pól; braliśmy jedenaście. Ten test pilnuje,
    żeby te, które umiemy przepisać, nie wypadły przy kolejnej zmianie.
    """
    wynik = parse_notices(ogloszenia)
    atrybuty = wynik.relationships[0].attributes

    assert atrybuty["notice_number"]
    assert atrybuty["notice_type"]
    # Te akurat są w zamrożonym ogłoszeniu; gdyby zniknęły ze źródła,
    # chcemy o tym wiedzieć.
    for pole in ("procedure_result", "tender_id", "order_type", "client_type"):
        assert pole in atrybuty, f"brak {pole} — sprawdź, czy źródło je jeszcze podaje"


def test_empty_fields_do_not_reach_the_attributes(ogloszenia: dict) -> None:
    """Pusty klucz w JSON-ie to śmieć, nie informacja o braku."""
    wynik = parse_notices(ogloszenia)

    for krawedz in wynik.relationships:
        assert all(v not in (None, "") for v in krawedz.attributes.values())


def test_a_notice_without_contractors_yields_no_edge() -> None:
    """Ogłoszenie o wszczęciu postępowania nie mówi jeszcze, kto wygrał."""
    wynik = parse_notices(
        {
            "items": [
                {
                    "organizationName": "GMINA TESTOWA",
                    "organizationNationalId": "7740001454",
                    "noticeNumber": "2026/BZP 00000001",
                    "noticeType": "ContractNotice",
                    "contractors": [],
                }
            ]
        }
    )

    assert wynik.relationships == []
    assert len(wynik.entities) == 1


def test_a_contractor_without_a_valid_nip_is_skipped() -> None:
    """Bez twardego identyfikatora nie tworzymy węzła — patrz niezmiennik N4."""
    wynik = parse_notices(
        {
            "items": [
                {
                    "organizationName": "GMINA TESTOWA",
                    "organizationNationalId": "7740001454",
                    "noticeNumber": "2026/BZP 00000002",
                    "contractors": [
                        {"contractorName": "FIRMA BEZ NIP", "contractorNationalId": ""}
                    ],
                }
            ]
        }
    )

    assert wynik.relationships == []
