"""Podmioty pod wspólnym adresem.

Wspólny adres to najczęstszy widoczny ślad powiązania między spółkami, których
nie łączy ani wspólnik, ani nazwa. Jest też najczęstszym źródłem fałszywych
tropów, więc zapytanie ma **liczyć**, a nie oceniać.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest

from business_osint.db.models import Address, Company, Entity, Relationship
from business_osint.domain.enums import Confidence, EntityType, RelationshipType
from business_osint.repositories.entities import EntityRepository

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


async def _address(session, label: str) -> uuid.UUID:
    entity_id = uuid.uuid4()
    session.add(
        Entity(
            id=entity_id,
            entity_type=EntityType.ADDRESS,
            display_name=label,
            normalized_name=label.lower(),
        )
    )
    session.add(Address(entity_id=entity_id, normalized=label.lower().replace(" ", "")))
    await session.flush()
    return entity_id


async def _registered(session, company: uuid.UUID, address: uuid.UUID, **kwargs) -> None:
    session.add(
        Relationship(
            id=uuid.uuid4(),
            source_entity_id=company,
            target_entity_id=address,
            relationship_type=RelationshipType.REGISTERED_AT,
            confidence=Confidence.REGISTERED,
            **kwargs,
        )
    )
    await session.flush()


async def test_neighbours_are_listed_from_an_address(db_session) -> None:
    """Wejście po id adresu daje wszystkie zarejestrowane tam podmioty."""
    address = await _address(db_session, "Batorego 18")
    for i in range(3):
        await _registered(db_session, await _company(db_session, f"FIRMA {i}"), address)

    repo = EntityRepository(db_session)

    assert await repo.count_co_located(address) == 3
    assert len(await repo.co_located(address)) == 3


async def test_neighbours_are_listed_from_a_company_without_clicking_the_address(
    db_session,
) -> None:
    """Wejście po id firmy ma działać tak samo.

    Użytkownik ogląda profil spółki i chce sąsiadów jej siedziby. Wymaganie,
    żeby najpierw kliknął w adres, byłoby przerzuceniem na niego pracy, którą
    baza wykonuje jednym złączeniem.
    """
    address = await _address(db_session, "Batorego 18")
    mine = await _company(db_session, "MOJA")
    await _registered(db_session, mine, address)
    await _registered(db_session, await _company(db_session, "SASIAD"), address)

    repo = EntityRepository(db_session)
    rows = await repo.co_located(mine)

    assert [row["display_name"] for row in rows] == ["SASIAD"]


async def test_the_entity_itself_is_never_its_own_neighbour(db_session) -> None:
    """Oglądany podmiot nie może pojawić się na liście sąsiadów."""
    address = await _address(db_session, "Batorego 18")
    mine = await _company(db_session, "MOJA")
    await _registered(db_session, mine, address)

    repo = EntityRepository(db_session)

    assert await repo.count_co_located(mine) == 0
    assert await repo.co_located(mine) == []


async def test_former_neighbours_are_kept_but_ranked_below_current_ones(db_session) -> None:
    """Kto się wyprowadził, zostaje na liście — z datą.

    „Już tu nie siedzi" to inna informacja niż „siedzi", a w śledzeniu powiązań
    zwykle ważniejsza od milczenia. Ale bieżący idą pierwsi.
    """
    address = await _address(db_session, "Batorego 18")
    mine = await _company(db_session, "MOJA")
    await _registered(db_session, mine, address)
    await _registered(
        db_session,
        await _company(db_session, "BYLY"),
        address,
        valid_from=dt.date(2015, 1, 1),
        valid_to=dt.date(2020, 1, 1),
    )
    await _registered(db_session, await _company(db_session, "OBECNY"), address)

    rows = await EntityRepository(db_session).co_located(mine)

    assert [row["display_name"] for row in rows] == ["OBECNY", "BYLY"]
    assert rows[1]["valid_to"] == dt.date(2020, 1, 1)


async def test_an_entity_without_an_address_has_no_neighbours(db_session) -> None:
    """Brak adresu ma dawać pustą listę, nie błąd."""
    lonely = await _company(db_session, "BEZ ADRESU")

    repo = EntityRepository(db_session)

    assert await repo.count_co_located(lonely) == 0
    assert await repo.co_located(lonely) == []
