"""Stronicowanie wyników i powiązań.

Niezmiennik N3 mówi, że przycięcie wyniku jest częścią kontraktu API. Lista
ucięta na dwustu wierszach i lista, która na dwustu się kończy, wyglądały
z zewnątrz identycznie — klient nie miał żadnego sygnału, że czegoś nie widzi.
"""

from __future__ import annotations

import uuid

import pytest

from business_osint.db.models import Company, Entity, Relationship
from business_osint.domain.enums import Confidence, EntityType, RelationshipType
from business_osint.repositories.entities import EntityRepository

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

PREFIX = "zzqpage"


async def _company(session, name: str) -> uuid.UUID:
    entity_id = uuid.uuid4()
    session.add(
        Entity(
            id=entity_id,
            entity_type=EntityType.COMPANY,
            display_name=name.upper(),
            normalized_name=name,
        )
    )
    session.add(Company(entity_id=entity_id, status="active"))
    await session.flush()
    return entity_id


async def _edge(session, src: uuid.UUID, dst: uuid.UUID) -> None:
    session.add(
        Relationship(
            id=uuid.uuid4(),
            source_entity_id=src,
            target_entity_id=dst,
            relationship_type=RelationshipType.PARENT_OF,
            confidence=Confidence.REGISTERED,
        )
    )
    await session.flush()


async def test_pages_do_not_overlap_or_lose_results(db_session) -> None:
    """Sklejone strony muszą dać dokładnie ten sam zbiór co jedno duże zapytanie.

    To jest właściwy test stronicowania. Sprawdzenie samych liczników przeszłoby
    także wtedy, gdyby wyniki się dublowały albo gubiły między stronami —
    a dokładnie to robił pierwszy szkic, bo etap szerokiego prefiksu zwraca
    nadzbiór poprzednich i duplikaty zjadały jego limit.
    """
    for i in range(12):
        await _company(db_session, f"{PREFIX} spolka {i:02}")
    repo = EntityRepository(db_session)

    wszystkie, _ = await repo.search(PREFIX, limit=50)
    sklejone: list[uuid.UUID] = []
    for offset in (0, 5, 10):
        page, _ = await repo.search(PREFIX, limit=5, offset=offset)
        sklejone.extend(h.id for h in page)

    assert len(sklejone) == len(set(sklejone)), "wynik powtórzony między stronami"
    assert sklejone == [h.id for h in wszystkie]


async def test_has_more_tells_the_truth_on_the_last_page(db_session) -> None:
    """Ostatnia strona musi mówić, że nic dalej nie ma — inaczej klient pyta w pustkę."""
    for i in range(7):
        await _company(db_session, f"{PREFIX} spolka {i:02}")
    repo = EntityRepository(db_session)

    _, more_on_first = await repo.search(PREFIX, limit=5, offset=0)
    last, more_on_last = await repo.search(PREFIX, limit=5, offset=5)

    assert more_on_first is True
    assert more_on_last is False
    assert len(last) == 2


async def test_offset_past_the_end_is_empty_not_an_error(db_session) -> None:
    """Przesunięcie za koniec zwraca pustą stronę, nie wyjątek."""
    await _company(db_session, f"{PREFIX} spolka")

    page, has_more = await EntityRepository(db_session).search(PREFIX, limit=5, offset=100)

    assert page == []
    assert has_more is False


async def test_relationship_count_matches_what_paging_walks_through(db_session) -> None:
    """Licznik i strony muszą opisywać ten sam zbiór.

    `entities.degree` tu nie wystarczy: liczy obie strony krawędzi i nie zna
    filtra historyczności, więc jako liczba wyników byłby liczbą wyglądającą
    na prawdziwą.
    """
    root = await _company(db_session, f"{PREFIX} root")
    for i in range(23):
        await _edge(db_session, root, await _company(db_session, f"{PREFIX} dziecko {i:02}"))
    repo = EntityRepository(db_session)

    total = await repo.count_relationships(root)
    zebrane: list[uuid.UUID] = []
    for offset in (0, 10, 20):
        rows = await repo.relationships(root, limit=10, offset=offset)
        zebrane.extend(row["relationship_id"] for row in rows)

    assert total == 23
    assert len(zebrane) == 23
    assert len(set(zebrane)) == 23, "krawędź powtórzona między stronami"
