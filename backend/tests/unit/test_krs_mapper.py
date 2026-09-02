"""Mapper KRS na zamrożonym, **prawdziwym** odpisie pełnym.

Fixture to nietknięta odpowiedź `api-krs.ms.gov.pl` dla KRS 0000028860
(ORLEN S.A.) — 419 KB, 786 pól zamaskowanych przez ministerstwo. Jest w repo
celowo: gdy schemat się zmieni, ten test zrobi się czerwony, zanim graf
zacznie po cichu pustoszeć.

Poprzednia wersja pliku opisywała schemat **wymyślony** — z niezamaskowanymi
nazwiskami wspólników i zarządu, i z `naglowekA` wewnątrz `dane`. Prawdziwe API
nie ma ani jednego, ani drugiego. Testy przechodziły, a opisywały interfejs,
który nie istnieje; to jest gorsze niż brak testu, bo daje fałszywą pewność.

Dane osobowe w fixture są zamaskowane u źródła (`M***********`), łącznie
z PESEL-em. Nie ma tu czego anonimizować — ministerstwo zrobiło to za nas
i właśnie dlatego z KRS nie zbudujemy warstwy osobowej.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib

from business_osint.domain.enums import EntityType, RelationshipType
from business_osint.etl.sources.krs_mapper import parse_krs_document

ODPIS = json.loads(
    (
        pathlib.Path(__file__).parent.parent / "fixtures" / "krs_odpis_pelny_0000028860.json"
    ).read_text(encoding="utf-8")
)


def test_company_is_extracted_with_identifiers() -> None:
    parsed = parse_krs_document(ODPIS)
    company = next(e for e in parsed.entities if e.entity_type is EntityType.COMPANY)
    assert "orlen" in company.normalized_name
    assert "0000028860" in set(company.identifiers.values())


def test_current_name_wins_over_historical_one() -> None:
    """Podmiot ma dwie nazwy w odpisie; encja dostaje obowiązującą.

    Nazwa jest w KRS polem wersjonowanym — wzięcie pierwszego elementu tablicy
    na ślepo dałoby nazwę sprzed zmiany.
    """
    parsed = parse_krs_document(ODPIS)
    company = next(e for e in parsed.entities if e.entity_type is EntityType.COMPANY)
    assert len(ODPIS["odpis"]["dane"]["dzial1"]["danePodmiotu"]["nazwa"]) > 1
    assert company.display_name == "ORLEN SPÓŁKA AKCYJNA"


def test_no_person_entity_is_ever_created_from_krs() -> None:
    """KRS maskuje nazwiska, więc osoba z tego źródła nie może powstać.

    To nie jest ograniczenie implementacji, tylko niezmiennik N4 od strony
    źródła: „M***********" pasuje do setek tysięcy ludzi. Encja zbudowana
    na takim ciągu scalałaby obcych sobie ludzi w jeden węzeł.
    """
    parsed = parse_krs_document(ODPIS)
    assert not [e for e in parsed.entities if e.entity_type is EntityType.PERSON]
    assert not [
        r for r in parsed.relationships if r.relationship_type is RelationshipType.BOARD_MEMBER_OF
    ]


def test_every_relationship_carries_a_locator_for_provenance() -> None:
    parsed = parse_krs_document(ODPIS)
    assert parsed.relationships
    assert all(r.locator for r in parsed.relationships)


def test_address_becomes_its_own_node() -> None:
    parsed = parse_krs_document(ODPIS)
    addresses = [e for e in parsed.entities if e.entity_type is EntityType.ADDRESS]
    assert addresses
    assert any(r.relationship_type is RelationshipType.REGISTERED_AT for r in parsed.relationships)


def test_registered_seat_edge_is_dated_from_the_entry() -> None:
    """Krawędź siedziby dostaje datę wpisu, nie datę importu.

    ORLEN nigdy nie zmienił siedziby, więc krawędź jest jedna — ale jej
    `valid_from` musi pochodzić z wpisu nr 1 w rejestrze (2001-07-19),
    a nie z chwili, w której akurat pobraliśmy dokument.
    """
    parsed = parse_krs_document(ODPIS)
    seat = next(
        r for r in parsed.relationships if r.relationship_type is RelationshipType.REGISTERED_AT
    )
    assert seat.valid_from == dt.date(2001, 7, 19)
    assert seat.valid_to is None


def test_name_and_capital_history_carry_real_dates() -> None:
    """Pola wersjonowane zamieniają się w datowaną historię.

    To jedyne źródło prawdziwej historii, jakie mamy — CEIDG i GLEIF dają
    wyłącznie stan bieżący. Numery wpisów z odpisu (`nrWpisuWprow`,
    `nrWpisuWykr`) muszą zostać przetłumaczone na daty, bo sam numer nic
    użytkownikowi nie mówi.
    """
    parsed = parse_krs_document(ODPIS)
    company = next(e for e in parsed.entities if e.entity_type is EntityType.COMPANY)

    names = company.attributes["name_history"]
    assert [n["to"] for n in names][-1] is None, "ostatnia nazwa jest otwarta"
    assert names[0]["value"].startswith("POLSKI KONCERN NAFTOWY")
    assert names[0]["to"] == "2023-07-03"

    capital = company.attributes["capital_history"]
    assert len(capital) > 1
    assert all(entry["from"] for entry in capital)


def test_board_is_counted_but_never_identified() -> None:
    """Zarząd zostaje jako liczba i adnotacja, nie jako węzły osób.

    Informacja „68 wpisów w organie reprezentacji" jest prawdziwa i użyteczna.
    Zbudowanie z nich encji nie jest możliwe, bo nazwiska są zamaskowane.
    """
    parsed = parse_krs_document(ODPIS)
    company = next(e for e in parsed.entities if e.entity_type is EntityType.COMPANY)
    assert company.attributes["board_size"] > 0
    assert company.attributes["board_note"]


def test_empty_document_does_not_explode() -> None:
    assert parse_krs_document({}).entities == []


# --- GLEIF: okresy relacji ------------------------------------------------


def test_gleif_uses_relationship_period_not_accounting_period() -> None:
    """Rok obrotowy w slocie 1 nie może trafić do okresu obowiązywania relacji.

    Wzięcie slotu pierwszego na ślepo sprawiało, że 1006 z 1122 krawędzi
    właścicielskich wyglądało na zakończone 31 grudnia i znikało z grafu.
    """
    from business_osint.etl.sources.gleif_mapper import parse_relationship_row

    row = {
        "Relationship.StartNode.NodeID": "CHILD00000000000001",
        "Relationship.EndNode.NodeID": "PARENT0000000000001",
        "Relationship.RelationshipType": "IS_DIRECTLY_CONSOLIDATED_BY",
        "Relationship.RelationshipStatus": "ACTIVE",
        "Relationship.Period.1.startDate": "2021-01-01T01:00:00+01:00",
        "Relationship.Period.1.endDate": "2021-12-31T01:00:00+01:00",
        "Relationship.Period.1.periodType": "ACCOUNTING_PERIOD",
        "Relationship.Period.2.startDate": "2017-12-06T01:00:00+01:00",
        "Relationship.Period.2.periodType": "RELATIONSHIP_PERIOD",
    }
    parsed = parse_relationship_row(row)
    assert parsed is not None
    assert parsed.valid_from == dt.date(2017, 12, 6)
    assert parsed.valid_to is None, "relacja bez daty końca jest wciąż aktualna"
    # Kierunek: GLEIF mówi „dziecko jest konsolidowane przez rodzica",
    # my zapisujemy „rodzic jest podmiotem dominującym wobec dziecka".
    assert parsed.source_key == "lei:PARENT0000000000001"
    assert parsed.target_key == "lei:CHILD00000000000001"


def test_gleif_without_relationship_period_is_treated_as_current() -> None:
    from business_osint.etl.sources.gleif_mapper import parse_relationship_row

    parsed = parse_relationship_row(
        {
            "Relationship.StartNode.NodeID": "A" * 20,
            "Relationship.EndNode.NodeID": "B" * 20,
            "Relationship.RelationshipType": "IS_ULTIMATELY_CONSOLIDATED_BY",
            "Relationship.RelationshipStatus": "ACTIVE",
            "Relationship.Period.1.startDate": "2024-01-01T00:00:00Z",
            "Relationship.Period.1.endDate": "2024-12-31T00:00:00Z",
            "Relationship.Period.1.periodType": "ACCOUNTING_PERIOD",
        }
    )
    assert parsed is not None
    assert parsed.valid_from is None
    assert parsed.valid_to is None


class TestPrzejeciaSpolek:
    """Dział 6: połączenia i przejęcia jako krawędzie `successor_of`."""

    def test_acquisitions_become_successor_edges(self) -> None:
        wynik = parse_krs_document(ODPIS)

        przejecia = [
            r for r in wynik.relationships if r.relationship_type is RelationshipType.SUCCESSOR_OF
        ]
        assert przejecia, "odpis z działem 6 musi dać krawędzie przejęcia"
        # Kierunek czyta się jak zdanie: PRZEJMUJĄCY --successor_of--> PRZEJMOWANA.
        for krawedz in przejecia:
            assert krawedz.source_key.startswith("company:")
            assert krawedz.target_key != krawedz.source_key

    def test_acquired_company_is_identified_by_krs_not_by_name(self) -> None:
        """Dział 6 opisuje połączenie prozą, ale `podmiotyPrzejmowane` niesie
        twarde identyfikatory — i tylko na nich wolno budować krawędź (N4)."""
        wynik = parse_krs_document(ODPIS)

        cele = {
            r.target_key
            for r in wynik.relationships
            if r.relationship_type is RelationshipType.SUCCESSOR_OF
        }
        przejete = [e for e in wynik.entities if e.local_key in cele]
        assert przejete
        for encja in przejete:
            assert encja.identifiers, f"{encja.display_name} bez identyfikatora"

    def test_acquisition_carries_the_date_of_its_register_entry(self) -> None:
        wynik = parse_krs_document(ODPIS)

        przejecia = [
            r for r in wynik.relationships if r.relationship_type is RelationshipType.SUCCESSOR_OF
        ]
        assert all(r.valid_from is not None for r in przejecia)
        # Przejęcie jest zdarzeniem, nie stanem, który się kończy.
        assert all(r.valid_to is None for r in przejecia)

    def test_a_pre_krs_register_number_is_not_taken_for_a_krs_number(self) -> None:
        """Wpisy sprzed 2001 wskazują rejestr RHB. Wzięcie jego numeru za KRS
        przypisałoby spółce cudzy identyfikator."""
        wynik = parse_krs_document(
            {
                "odpis": {
                    "naglowekP": {"numerKRS": "0000000001", "wpis": []},
                    "dane": {
                        "dzial1": {"danePodmiotu": {"nazwa": [{"nazwa": "TESTOWA S.A."}]}},
                        "dzial6": {
                            "polaczeniePodzialPrzeksztalcenie": [
                                {
                                    "podmiotyPrzejmowane": [
                                        {
                                            "nazwa": [{"nazwa": "STARA SPÓŁKA"}],
                                            "krajNazwaRejestru": [
                                                {"krajNazwaRejestru": "------,RHB"}
                                            ],
                                            "numerWRejestrzeAlboEwidencji": [
                                                {"numerWRejestrzeAlboEwidencji": "780"}
                                            ],
                                        }
                                    ]
                                }
                            ]
                        },
                    },
                }
            }
        )

        klucze = [e.local_key for e in wynik.entities]
        assert "company:780" not in klucze
        # Bez twardego identyfikatora krawędź w ogóle nie powstaje.
        assert not [
            r for r in wynik.relationships if r.relationship_type is RelationshipType.SUCCESSOR_OF
        ]
