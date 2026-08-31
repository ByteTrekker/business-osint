"""Wzbogacanie odpisem KRS: przeniesienie historii i czas życia dokumentu.

Historia z KRS była wcześniej **liczona i wyrzucana**: mapper ją produkował,
a `EntityResolver` wypełnia `companies` wyłącznie przy tworzeniu encji. Encja
z numerem KRS zwykle już istnieje — przyszła z GLEIF albo z CEIDG — więc
dopasowanie po identyfikatorze nie aktualizowało niczego.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import uuid

import pytest
from sqlalchemy import text

from business_osint.db.models import Company, Entity, EntityIdentifier, RawDocument
from business_osint.domain.enums import EntityType, SourceKind
from business_osint.etl.krs_enrichment import (
    _is_fresh,
    apply_company_facts,
)
from business_osint.etl.pipeline import get_or_create_source
from business_osint.etl.sources.krs_mapper import parse_krs_document

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

KRS = "0000028860"
ODPIS = json.loads(
    (pathlib.Path(__file__).parent.parent / "fixtures" / f"krs_odpis_pelny_{KRS}.json").read_text(
        encoding="utf-8"
    )
)


async def _company_with_krs(session, krs: str = KRS) -> uuid.UUID:
    """Encja, jaka powstałaby z GLEIF: ma numer KRS i nic poza tym."""
    entity_id = uuid.uuid4()
    session.add(
        Entity(
            id=entity_id,
            entity_type=EntityType.COMPANY,
            display_name="ORLEN",
            normalized_name="orlen",
        )
    )
    session.add(Company(entity_id=entity_id, krs=krs, status="active"))
    session.add(EntityIdentifier(id=uuid.uuid4(), entity_id=entity_id, scheme="krs", value=krs))
    await session.flush()
    return entity_id


async def test_history_reaches_an_entity_that_already_existed(db_session) -> None:
    """Odpis uzupełnia encję, która przyszła z innego źródła.

    To jest cały sens tej zmiany. Encja ORLEN-u istnieje w bazie z GLEIF-a
    i ma tam formę prawną zapisaną kodem `FJ0E`; dopiero odpis daje czytelną
    formę, datę rejestracji, kapitał i historię.
    """
    await _company_with_krs(db_session)
    parsed = parse_krs_document(ODPIS)

    entries = await apply_company_facts(db_session, KRS, parsed)

    row = (
        await db_session.execute(
            text("SELECT legal_form, registered_on, share_capital, attributes FROM companies")
        )
    ).one()
    assert row.legal_form == "SPÓŁKA AKCYJNA"
    assert row.registered_on == dt.date(2001, 7, 19)
    assert row.share_capital > 0
    assert len(row.attributes["name_history"]) == 2
    assert entries > 0


async def test_carried_attributes_do_not_wipe_what_was_there(db_session) -> None:
    """Odpis **uzupełnia** atrybuty, nie wymiata ich.

    `companies.attributes` może już nieść dane z innego źródła. Podmiana
    zamiast scalenia po cichu kasowałaby cudzy import.
    """
    entity_id = await _company_with_krs(db_session)
    await db_session.execute(
        text('UPDATE companies SET attributes = \'{"pkd_all": "6201Z"}\'::jsonb'),
    )

    await apply_company_facts(db_session, KRS, parse_krs_document(ODPIS))

    attributes = (
        await db_session.execute(
            text("SELECT attributes FROM companies WHERE entity_id = :id"), {"id": entity_id}
        )
    ).scalar_one()
    assert attributes["pkd_all"] == "6201Z"
    assert "name_history" in attributes


async def test_only_declared_attributes_are_carried_over(db_session) -> None:
    """Przenosimy jawną listę pól, nie wszystko, co przyszło z mappera.

    Cicha zgoda na dowolne pole oznacza, że zmiana po stronie mappera wsypuje
    do bazy rzeczy, na które nikt się nie zgodził.
    """
    await _company_with_krs(db_session)
    parsed = parse_krs_document(ODPIS)
    company = next(e for e in parsed.entities if e.entity_type is EntityType.COMPANY)
    company.attributes["cos_nowego"] = "wartość"

    await apply_company_facts(db_session, KRS, parsed)

    attributes = (await db_session.execute(text("SELECT attributes FROM companies"))).scalar_one()
    assert "cos_nowego" not in attributes
    assert "name_history" in attributes


async def test_krs_number_is_found_for_an_entity(db_session) -> None:
    """Bez numeru KRS nie ma czego wzbogacać — musimy go umieć znaleźć."""
    entity_id = await _company_with_krs(db_session)

    found = (
        await db_session.execute(
            text("SELECT value FROM entity_identifiers WHERE entity_id = :id AND scheme = 'krs'"),
            {"id": entity_id},
        )
    ).scalar_one()
    assert found == KRS


async def _document(session, *, fetched_at: dt.datetime) -> None:
    source_id = await get_or_create_source(session, SourceKind.KRS, "test", None)
    session.add(
        RawDocument(
            id=uuid.uuid4(),
            source_id=source_id,
            external_id=KRS,
            url=None,
            fetched_at=fetched_at,
            content_sha256="a" * 64,
            payload={},
        )
    )
    await session.flush()


async def test_recent_document_is_treated_as_fresh(db_session) -> None:
    """Świeży odpis blokuje ponowne pobranie — rejestr obciążamy raz."""
    await _document(db_session, fetched_at=dt.datetime.now(dt.UTC) - dt.timedelta(days=3))

    assert await _is_fresh(db_session, KRS, dt.timedelta(days=30)) is not None


async def test_document_past_its_ttl_is_not_fresh(db_session) -> None:
    """Po upływie czasu życia pobieramy ponownie — wpisy w KRS się zmieniają."""
    await _document(db_session, fetched_at=dt.datetime.now(dt.UTC) - dt.timedelta(days=40))

    assert await _is_fresh(db_session, KRS, dt.timedelta(days=30)) is None
