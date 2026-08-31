"""Pochodzenie krawędzi z importu masowego CEIDG.

Import masowy pisze relacje zbiorczym SQL-em, z pominięciem `load_document`,
które pilnuje pochodzenia dla pozostałych źródeł. Ta ścieżka nie miała żadnego
testu i skutek był widoczny w produkcji: 6 392 682 z 6 466 459 krawędzi bez
źródła, czyli 98,9% grafu i złamany niezmiennik N2.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import text

from business_osint.domain.enums import SourceKind
from business_osint.etl.ceidg_pipeline import (
    _CREATE_STAGE,
    _DROP_STAGE,
    load_staged,
    prepare_row,
    stage_rows,
)
from business_osint.etl.loaders import store_raw_document
from business_osint.etl.pipeline import get_or_create_source
from business_osint.etl.quality import CHECKS, execute_checks

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

#: Nagłówki są takie, jak w raportach hurtowni CEIDG. Trzymamy je dosłownie,
#: bo zmiana nazwy kolumny po stronie urzędu ma dawać czerwony test, a nie ciche
#: pomijanie wierszy w imporcie.
ROW = {
    "Nip": "7671625618",
    "Regon": "012345675",
    "NazwaPodmiotu": "TESTOWA DZIAŁALNOŚĆ",
    "Imie": "JAN",
    "Nazwisko": "KOWALSKI",
    "Ulica": "Konrada Leczkowa",
    "NrBudynku": "28a",
    "NrLokalu": "7",
    "KodPocztowy": "80-432",
    "Miejscowosc": "Gdańsk",
    "StatusDzialalnosci": "AKTYWNY",
    "DataRozpoczeciaDzialalnosci": "2015-03-01",
}


async def _document(session) -> uuid.UUID:
    source_id = await get_or_create_source(session, SourceKind.CEIDG, "test", None)
    document_id, _ = await store_raw_document(
        session,
        source_id=source_id,
        external_id="raport-testowy",
        url=None,
        fetched_at=dt.datetime(2026, 8, 31, tzinfo=dt.UTC),
        content_sha256="0" * 64,
        payload={"region": "pomorskie"},
    )
    return document_id


async def _import(session, stats, row=None):
    await session.execute(_DROP_STAGE)
    await session.execute(_CREATE_STAGE)
    prepared = prepare_row(row or ROW, region="pomorskie")
    assert prepared is not None
    await stage_rows(session, [prepared])
    await load_staged(session, stats, raw_document_id=await _document(session))


async def test_every_edge_from_a_bulk_import_has_provenance(db_session) -> None:
    """Krawędź z importu masowego musi mieć wpis w `relationship_sources`.

    To jest niezmiennik N2. Sprawdzamy go tą samą kontrolą, która wykryła
    naruszenie na produkcji, żeby test i monitoring mówiły to samo.
    """
    from business_osint.etl.ceidg_pipeline import CeidgStats

    await _import(db_session, CeidgStats())

    # Sprawdzamy liczbę naruszeń, nie `report.ok`. Kontrola ma próg 733 na
    # dług z importu sprzed wprowadzenia pochodzenia, a w teście każde
    # naruszenie jest regresją tej zmiany.
    report = await execute_checks(
        db_session, [c for c in CHECKS if c.name == "relationship_has_provenance"]
    )
    assert report.results[0].violations == 0, report.results[0].sample


async def test_locator_points_at_the_row_inside_the_report(db_session) -> None:
    """Dokumentem jest raport, więc `locator` musi wskazać wiersz w raporcie.

    Bez tego pochodzenie mówi „to gdzieś w pliku na kilkaset tysięcy wierszy",
    co nie pozwala niczego zweryfikować.
    """
    from business_osint.etl.ceidg_pipeline import CeidgStats

    await _import(db_session, CeidgStats())

    locators = (
        (await db_session.execute(text("SELECT DISTINCT locator FROM relationship_sources")))
        .scalars()
        .all()
    )
    assert locators == [f"nip:{ROW['Nip']}"]


async def test_second_import_backfills_edges_left_without_provenance(db_session) -> None:
    """Powtórny import dopina pochodzenie do krawędzi, które go nie miały.

    Wstawianie idzie z `ON CONFLICT DO NOTHING`, więc bez dopinania reimport
    przeszedłby bez skutku i 6,39 mln krawędzi zostałoby bez źródła na zawsze.
    """
    from business_osint.etl.ceidg_pipeline import CeidgStats

    await _import(db_session, CeidgStats())
    await db_session.execute(text("DELETE FROM relationship_sources"))

    stats = CeidgStats()
    await _import(db_session, stats)

    assert stats.provenance_backfilled > 0
    # Sprawdzamy liczbę naruszeń, nie `report.ok`. Kontrola ma próg 733 na
    # dług z importu sprzed wprowadzenia pochodzenia, a w teście każde
    # naruszenie jest regresją tej zmiany.
    report = await execute_checks(
        db_session, [c for c in CHECKS if c.name == "relationship_has_provenance"]
    )
    assert report.results[0].violations == 0, report.results[0].sample


async def test_building_and_unit_land_in_their_own_columns(db_session) -> None:
    """Numer budynku i lokalu muszą być osobno, nie tylko w napisie adresu.

    Dopasowanie do punktów adresowych PRG idzie po tych kolumnach; wcześniej
    stały puste, bo import wpisywał je wyłącznie do `display_name`.
    """
    from business_osint.etl.ceidg_pipeline import CeidgStats

    await _import(db_session, CeidgStats())

    row = (
        await db_session.execute(text("SELECT building, unit, city FROM addresses LIMIT 1"))
    ).one()
    assert (row.building, row.unit, row.city) == ("28a", "7", "Gdańsk")


async def test_address_is_written_the_polish_way(db_session) -> None:
    """`ul. Konrada Leczkowa 28a/7, 80-432 Gdańsk`, nie człony po przecinku."""
    from business_osint.etl.ceidg_pipeline import CeidgStats

    await _import(db_session, CeidgStats())

    name = (
        await db_session.execute(
            text("SELECT display_name FROM entities WHERE entity_type = 'address'")
        )
    ).scalar_one()
    assert name == "Konrada Leczkowa 28a/7, 80-432 Gdańsk"
