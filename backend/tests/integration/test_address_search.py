"""Wyszukiwanie po adresie.

Adres nie dawał się wyszukać wcale — nie z powodu rankingu ani kolejności słów,
tylko dlatego, że `entities.normalized_name` niósł klucz scalania: ciąg bez
spacji, `chemikow709411plock`. Indeks pełnotekstowy widział tam jeden token.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from business_osint.db.models import Address, Entity
from business_osint.domain.enums import EntityType
from business_osint.domain.normalization import address_natural_key, address_search_key
from business_osint.repositories.entities import EntityRepository

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

ADRES = "Chemików 7, 09-411 Płock"


async def _address(session, display: str = ADRES) -> uuid.UUID:
    entity_id = uuid.uuid4()
    session.add(
        Entity(
            id=entity_id,
            entity_type=EntityType.ADDRESS,
            display_name=display,
            normalized_name=address_search_key(display),
        )
    )
    session.add(Address(entity_id=entity_id, city="Płock", normalized=address_natural_key(display)))
    await session.flush()
    return entity_id


async def test_address_is_found_by_street_and_city(db_session) -> None:
    """„chemikow plock" ma trafić w adres — to jest cały sens tej zmiany."""
    await _address(db_session)

    hits, _ = await EntityRepository(db_session).search("chemikow plock", limit=5)

    assert [h.display_name for h in hits] == [ADRES]


async def test_address_is_found_regardless_of_word_order(db_session) -> None:
    """„plock chemikow" tak samo — zapisu adresu nikt nie pamięta w kolejności."""
    await _address(db_session)

    hits, _ = await EntityRepository(db_session).search("plock chemikow", limit=5)

    assert [h.display_name for h in hits] == [ADRES]


async def test_postal_code_is_searchable_too(db_session) -> None:
    """Kod pocztowy rozpada się na tokeny i musi dawać się wyszukać."""
    await _address(db_session)

    hits, _ = await EntityRepository(db_session).search("09 411 chemikow", limit=5)

    assert [h.display_name for h in hits] == [ADRES]


async def test_merging_key_stays_glued_and_keeps_merging(db_session) -> None:
    """Rozdzielenie ról nie może popsuć scalania adresów.

    `addresses.normalized` ma dalej sklejać zapisy różniące się interpunkcją,
    inaczej ta zmiana zamieniłaby jeden defekt na drugi — duplikaty adresów.
    """
    await _address(db_session, ADRES)

    natural = (await db_session.execute(text("SELECT normalized FROM addresses"))).scalar_one()
    assert natural == address_natural_key("Chemików 7, 09-411, Płock")
    assert " " not in natural


async def test_the_search_field_and_the_merging_key_differ(db_session) -> None:
    """Encja i adres trzymają **różne** wartości — to jest istota poprawki."""
    entity_id = await _address(db_session)

    row = (
        await db_session.execute(
            text("""
            SELECT e.normalized_name AS wyszukiwanie, a.normalized AS scalanie
            FROM entities e JOIN addresses a ON a.entity_id = e.id
            WHERE e.id = :id
            """),
            {"id": entity_id},
        )
    ).one()
    assert row.wyszukiwanie != row.scalanie
    assert " " in row.wyszukiwanie
