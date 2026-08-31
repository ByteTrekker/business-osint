"""Testy traversalu na prawdziwym Postgresie.

Weryfikują to, czego nie da się sprawdzić bez bazy: poprawność SQL-a,
działanie widoku dwukierunkowego i egzekwowanie budżetu na realnych danych.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest

from business_osint.db.models import Company, Entity, Person, Relationship
from business_osint.domain.enums import Confidence, EntityType, RelationshipType
from business_osint.domain.graph_budget import GraphBudget
from business_osint.repositories.graph import GraphRepository

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _company(session, name: str) -> uuid.UUID:
    entity_id = uuid.uuid4()
    session.add(
        Entity(
            id=entity_id,
            entity_type=EntityType.COMPANY,
            display_name=name,
            normalized_name=name.lower(),
        )
    )
    session.add(Company(entity_id=entity_id, status="active"))
    await session.flush()
    return entity_id


async def _person(session, name: str) -> uuid.UUID:
    entity_id = uuid.uuid4()
    session.add(
        Entity(
            id=entity_id,
            entity_type=EntityType.PERSON,
            display_name=name,
            normalized_name=name.lower(),
        )
    )
    session.add(
        Person(entity_id=entity_id, first_names=name.split()[0], last_name=name.split()[-1])
    )
    await session.flush()
    return entity_id


async def _edge(session, src, dst, rel_type, valid_from=None, valid_to=None) -> None:
    session.add(
        Relationship(
            id=uuid.uuid4(),
            source_entity_id=src,
            target_entity_id=dst,
            relationship_type=rel_type,
            valid_from=valid_from,
            valid_to=valid_to,
            confidence=Confidence.REGISTERED,
            confidence_score=1.0,
        )
    )
    await session.flush()


async def test_company_person_company_chain(db_session) -> None:
    """Główny scenariusz produktu: Firma A -> osoba -> Firma B."""
    firma_a = await _company(db_session, "ALFA")
    firma_b = await _company(db_session, "BETA")
    kowalski = await _person(db_session, "Jan Kowalski")
    await _edge(db_session, kowalski, firma_a, RelationshipType.BOARD_MEMBER_OF)
    await _edge(db_session, kowalski, firma_b, RelationshipType.SHAREHOLDER_OF)

    result = await GraphRepository(db_session).neighborhood(
        firma_a, budget=GraphBudget.for_plan("pro"), depth=2
    )

    node_ids = {node.id for node in result.nodes}
    assert node_ids == {firma_a, kowalski, firma_b}
    assert len(result.edges) == 2
    # Kierunek krawędzi jest zachowany mimo traversalu "pod prąd".
    assert all(edge.source_id == kowalski for edge in result.edges)


async def test_historical_edges_are_hidden_by_default(db_session) -> None:
    firma = await _company(db_session, "GAMMA")
    osoba = await _person(db_session, "Anna Nowak")
    await _edge(
        db_session,
        osoba,
        firma,
        RelationshipType.BOARD_MEMBER_OF,
        dt.date(2020, 1, 1),
        dt.date(2023, 6, 30),
    )
    repo = GraphRepository(db_session)

    current = await repo.neighborhood(firma, budget=GraphBudget(), depth=1)
    assert len(current.nodes) == 1  # tylko węzeł startowy

    historical = await repo.neighborhood(
        firma, budget=GraphBudget(), depth=1, include_historical=True
    )
    assert len(historical.nodes) == 2
    assert historical.edges[0].is_current is False


async def test_as_of_returns_state_from_the_past(db_session) -> None:
    firma = await _company(db_session, "DELTA")
    osoba = await _person(db_session, "Piotr Zieliński")
    await _edge(
        db_session,
        osoba,
        firma,
        RelationshipType.BOARD_MEMBER_OF,
        dt.date(2020, 1, 1),
        dt.date(2023, 6, 30),
    )
    result = await GraphRepository(db_session).neighborhood(
        firma, budget=GraphBudget(), depth=1, as_of=dt.date(2022, 1, 1)
    )
    assert len(result.nodes) == 2


async def test_hub_is_not_expanded_and_is_reported(db_session) -> None:
    """Adres z setką spółek nie może wysadzić zapytania."""
    hub = await _company(db_session, "HUB")
    root = await _company(db_session, "ROOT")
    await _edge(db_session, root, hub, RelationshipType.REGISTERED_AT)
    for i in range(60):
        shell = await _company(db_session, f"SHELL {i}")
        await _edge(db_session, shell, hub, RelationshipType.REGISTERED_AT)

    # Test steruje instrukcjami wprost, bo `recompute_degrees()` celowo
    # pracuje na własnym silniku ETL i w osobnych transakcjach — nie zobaczyłby
    # danych zapisanych w transakcji testu. Sprawdzamy tu ten sam SQL, który
    # idzie na produkcję, łącznie z aktualizacją partiami.
    from business_osint.etl.maintenance import _BUILD_DEGREES, _UPDATE_BATCH

    for statement in _BUILD_DEGREES:
        await db_session.execute(statement)
    await db_session.execute(_UPDATE_BATCH, {"batch_size": 1000})

    budget = GraphBudget(max_depth=3, max_nodes=500, fanout_per_node=100, hub_degree=20)
    result = await GraphRepository(db_session).neighborhood(root, budget=budget, depth=3)

    assert result.suppressed_hubs >= 1
    assert len(result.nodes) == 2  # root + hub, bez 60 spółek-widm


async def test_node_budget_truncates_result(db_session) -> None:
    root = await _company(db_session, "ROOT")
    for i in range(40):
        other = await _company(db_session, f"OTHER {i}")
        await _edge(db_session, root, other, RelationshipType.PARENT_OF)

    budget = GraphBudget(max_depth=1, max_nodes=10, fanout_per_node=100)
    result = await GraphRepository(db_session).neighborhood(root, budget=budget, depth=1)

    assert len(result.nodes) == 10
    assert result.truncated is True
