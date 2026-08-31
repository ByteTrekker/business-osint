"""Scalanie zduplikowanych adresów.

Operacja dotyka trzech niezmienników naraz, więc każdy ma własny test:
fakt nie znika (N1), pochodzenie idzie razem z krawędzią (N2), a miejscowości
o tej samej nazwie nie są scalane (N4).
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import text

from business_osint.db.models import (
    Address,
    Company,
    Entity,
    RawDocument,
    Relationship,
    RelationshipSource,
)
from business_osint.domain.enums import Confidence, EntityType, RelationshipType, SourceKind
from business_osint.etl.address_merge import MergeStats, merge_batch, merge_group
from business_osint.etl.pipeline import get_or_create_source
from business_osint.etl.quality import CHECKS, execute_checks

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _address(session, *, city="Płock", street="Chemików", building="7", **kwargs):
    entity_id = uuid.uuid4()
    label = f"{street} {building}, {city}"
    session.add(
        Entity(
            id=entity_id,
            entity_type=EntityType.ADDRESS,
            display_name=label,
            normalized_name=label.lower() + str(entity_id)[:8],
            degree=kwargs.pop("degree", 0),
        )
    )
    session.add(
        Address(
            entity_id=entity_id,
            city=city,
            street=street,
            building=building,
            normalized=(label + str(entity_id)[:8]).lower(),
            **kwargs,
        )
    )
    await session.flush()
    return entity_id


async def _company(session, name="FIRMA"):
    entity_id = uuid.uuid4()
    session.add(
        Entity(
            id=entity_id,
            entity_type=EntityType.COMPANY,
            display_name=name,
            normalized_name=name.lower() + str(entity_id)[:8],
        )
    )
    session.add(Company(entity_id=entity_id, status="active"))
    await session.flush()
    return entity_id


async def _registered(session, company, address, *, with_source=True, **kwargs):
    rel_id = uuid.uuid4()
    session.add(
        Relationship(
            id=rel_id,
            source_entity_id=company,
            target_entity_id=address,
            relationship_type=RelationshipType.REGISTERED_AT,
            confidence=Confidence.REGISTERED,
            **kwargs,
        )
    )
    await session.flush()
    if with_source:
        source_id = await get_or_create_source(session, SourceKind.CEIDG, "test", None)
        doc_id = uuid.uuid4()
        session.add(
            RawDocument(
                id=doc_id,
                source_id=source_id,
                external_id=str(rel_id),
                url=None,
                fetched_at=dt.datetime(2026, 8, 31, tzinfo=dt.UTC),
                content_sha256=f"{rel_id.int:064x}"[:64],
                payload={},
            )
        )
        await session.flush()
        session.add(
            RelationshipSource(relationship_id=rel_id, raw_document_id=doc_id, locator="nip:1")
        )
        await session.flush()
    return rel_id


async def test_edges_move_to_the_survivor(db_session) -> None:
    """Firma zarejestrowana pod duplikatem ma po scaleniu wskazywać ocalałego."""
    survivor = await _address(db_session, degree=5)
    loser = await _address(db_session)
    company = await _company(db_session)
    await _registered(db_session, company, loser)

    await merge_group(db_session, survivor, [loser])

    targets = (
        (
            await db_session.execute(
                text("SELECT target_entity_id FROM relationships WHERE superseded_at IS NULL")
            )
        )
        .scalars()
        .all()
    )
    assert targets == [survivor]


async def test_the_original_fact_is_closed_not_deleted(db_session) -> None:
    """N1: fakt nie znika, tylko przestaje obowiązywać w czasie systemowym.

    Skasowanie krawędzi usunęłoby ślad, że kiedykolwiek uznaliśmy te encje za
    różne — a to jest właśnie ta wiedza, którą poprawiamy.
    """
    survivor = await _address(db_session, degree=5)
    loser = await _address(db_session)
    original = await _registered(db_session, await _company(db_session), loser)

    await merge_group(db_session, survivor, [loser])

    row = (
        await db_session.execute(
            text("SELECT superseded_at, target_entity_id FROM relationships WHERE id = :id"),
            {"id": original},
        )
    ).one()
    assert row.superseded_at is not None
    assert row.target_entity_id == loser


async def test_provenance_travels_with_the_edge(db_session) -> None:
    """N2: nowa krawędź musi mieć źródło, inaczej scalanie kasuje pochodzenie.

    Sprawdzamy tą samą kontrolą, która pilnuje tego na produkcji.
    """
    survivor = await _address(db_session, degree=5)
    loser = await _address(db_session)
    await _registered(db_session, await _company(db_session), loser)

    await merge_group(db_session, survivor, [loser])

    report = await execute_checks(
        db_session, [c for c in CHECKS if c.name == "relationship_has_provenance"]
    )
    assert report.results[0].violations == 0, report.results[0].sample


async def test_merged_entity_keeps_no_active_edges(db_session) -> None:
    """Encja scalona nie może dalej trzymać krawędzi — traversal dublowałby fakty."""
    survivor = await _address(db_session, degree=5)
    loser = await _address(db_session)
    await _registered(db_session, await _company(db_session), loser)

    await merge_group(db_session, survivor, [loser])

    report = await execute_checks(
        db_session, [c for c in CHECKS if c.name == "merged_entity_has_no_active_edges"]
    )
    assert report.results[0].violations == 0, report.results[0].sample


async def test_merge_is_recorded_with_a_reason(db_session) -> None:
    """Bez zapisu w `entity_merges` nie da się później zrozumieć, co się stało."""
    survivor = await _address(db_session, degree=5)
    loser = await _address(db_session)

    await merge_group(db_session, survivor, [loser])

    row = (
        await db_session.execute(text("SELECT survivor_id, merged_id, reason FROM entity_merges"))
    ).one()
    assert (row.survivor_id, row.merged_id) == (survivor, loser)
    assert row.reason


async def test_localities_sharing_a_name_are_never_merged(db_session) -> None:
    """N4: dwie Agatówki w różnych województwach to dwa miejsca, nie duplikat."""
    await _address(db_session, city="Agatówka", voivodeship="podkarpackie")
    await _address(db_session, city="Agatówka", voivodeship="mazowieckie")

    stats = MergeStats()
    await merge_batch(db_session, batch_size=100, offset=0, stats=stats)

    assert stats.groups == 0
    assert stats.skipped_cross_voivodeship == 1


async def test_duplicate_edge_on_the_survivor_does_not_break_the_merge(db_session) -> None:
    """Ta sama firma pod oboma adresami: fakt jest już reprezentowany.

    Nowa krawędź wpadłaby w unikalność krawędzi aktywnych, więc wstawienie ma
    zostać pominięte, a duplikat i tak zamknięty.
    """
    survivor = await _address(db_session, degree=5)
    loser = await _address(db_session)
    company = await _company(db_session)
    await _registered(db_session, company, survivor)
    await _registered(db_session, company, loser)

    await merge_group(db_session, survivor, [loser])

    active = (
        await db_session.execute(
            text("SELECT count(*) FROM relationships WHERE superseded_at IS NULL")
        )
    ).scalar_one()
    assert active == 1
