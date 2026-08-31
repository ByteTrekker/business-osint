"""Asercje jakości danych na prawdziwym Postgresie.

Każdy test sadzi w bazie **konkretne** naruszenie i sprawdza, że kontrola je
widzi. Test kontroli, który patrzy tylko na czyste dane, sprawdza wyłącznie to,
że zapytanie się parsuje.
"""

from __future__ import annotations

import uuid

import pytest

from business_osint.db.models import Entity, EntityIdentifier, Relationship
from business_osint.domain.enums import Confidence, EntityType, RelationshipType
from business_osint.etl.quality import CHECKS, Check, execute_checks

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _check(name: str) -> Check:
    return next(c for c in CHECKS if c.name == name)


async def _entity(session, name: str = "ALFA", **kwargs) -> uuid.UUID:
    entity_id = uuid.uuid4()
    session.add(
        Entity(
            id=entity_id,
            entity_type=EntityType.COMPANY,
            display_name=name,
            normalized_name=name.lower(),
            **kwargs,
        )
    )
    await session.flush()
    return entity_id


async def _edge(session, src: uuid.UUID, dst: uuid.UUID, **kwargs) -> uuid.UUID:
    rel_id = uuid.uuid4()
    session.add(
        Relationship(
            id=rel_id,
            source_entity_id=src,
            target_entity_id=dst,
            relationship_type=kwargs.pop("relationship_type", RelationshipType.PARENT_OF),
            confidence=Confidence.REGISTERED,
            **kwargs,
        )
    )
    await session.flush()
    return rel_id


async def _violations(session, name: str) -> int:
    report = await execute_checks(session, [_check(name)])
    return report.results[0].violations


async def test_two_tax_numbers_on_one_entity_are_reported(db_session) -> None:
    """Dwa NIP-y na jednej encji to dwie encje sklejone w jedną.

    Tak wyglądała awaria z 69 438 firmami: import CEIDG łączył wiersze po
    znormalizowanej nazwie, więc jednoosobowe działalności nazwane imieniem
    i nazwiskiem trafiały do wspólnego węzła.
    """
    entity_id = await _entity(db_session, "JAN KOWALSKI")
    for value in ("5252445170", "7671625618"):
        db_session.add(
            EntityIdentifier(id=uuid.uuid4(), entity_id=entity_id, scheme="nip", value=value)
        )
    await db_session.flush()

    assert await _violations(db_session, "entity_holds_one_identifier_per_scheme") == 1


async def test_one_tax_number_per_entity_passes(db_session) -> None:
    """Dwa różne schematy na jednej encji są normą, nie naruszeniem."""
    entity_id = await _entity(db_session)
    db_session.add(
        EntityIdentifier(id=uuid.uuid4(), entity_id=entity_id, scheme="nip", value="5252445170")
    )
    db_session.add(
        EntityIdentifier(id=uuid.uuid4(), entity_id=entity_id, scheme="krs", value="0000111111")
    )
    await db_session.flush()

    assert await _violations(db_session, "entity_holds_one_identifier_per_scheme") == 0


async def test_relationship_without_a_source_document_is_reported(db_session) -> None:
    """Krawędź bez pochodzenia łamie N2 — twierdzenie bez źródła."""
    src = await _entity(db_session, "ALFA")
    dst = await _entity(db_session, "BETA")
    await _edge(db_session, src, dst)

    assert await _violations(db_session, "relationship_has_provenance") == 1


async def test_entity_without_a_name_is_reported(db_session) -> None:
    """Encja bez nazwy jest nieodróżnialna od każdej innej takiej encji."""
    await _entity(db_session, "   ")

    assert await _violations(db_session, "entity_has_a_display_name") == 1


async def test_merged_entity_keeping_active_edges_is_reported(db_session) -> None:
    """Encja scalona nie może trzymać własnych krawędzi.

    Inaczej traversal pokaże ten sam fakt dwa razy — raz na każdym z węzłów.
    """
    survivor = await _entity(db_session, "ALFA")
    merged = await _entity(db_session, "ALFA DUPLIKAT", merged_into_id=survivor)
    other = await _entity(db_session, "BETA")
    await _edge(db_session, merged, other)

    assert await _violations(db_session, "merged_entity_has_no_active_edges") == 1


async def test_company_registered_at_many_addresses_is_reported(db_session) -> None:
    """Jedna firma pod wieloma adresami to skutek scalenia, nie fakt.

    Tak wyszedł GABAR z 734 adresami, gdy EntityResolver łączył encje po
    dwunastu pierwszych znakach nazwy.
    """
    company = await _entity(db_session, "GABAR")
    for i in range(13):
        address = await _entity(db_session, f"ADRES {i}")
        await _edge(db_session, company, address, relationship_type=RelationshipType.REGISTERED_AT)

    assert await _violations(db_session, "company_is_not_registered_at_many_addresses") == 1


async def test_degree_drifting_from_reality_is_reported(db_session) -> None:
    """Rozjechany stopień psuje tłumienie hubów, a przez nie `meta.truncated`."""
    src = await _entity(db_session, "ALFA", degree=99)
    dst = await _entity(db_session, "BETA", degree=1)
    await _edge(db_session, src, dst)

    assert await _violations(db_session, "degree_matches_actual_edge_count") == 1


async def test_clean_database_passes_every_check(db_session) -> None:
    """Pusta baza nie może zgłaszać naruszeń — inaczej raport jest bezużyteczny."""
    report = await execute_checks(db_session, CHECKS)

    assert report.ok, [r.check.name for r in report.failed]
    assert len(report.results) == len(CHECKS)
