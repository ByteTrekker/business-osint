"""Dziennik zmian podmiotu.

Fundament monitoringu. Wpisy powstają przez **wyzwalacze bazy**, nie przez kod
aplikacji — do `companies` i `entities` pisze kilka niezależnych ścieżek (ORM,
zbiorczy SQL importu CEIDG, wzbogacanie z KRS) i wpięcie się w każdą z osobna
oznaczałoby, że następna dopisana po cichu przestanie logować.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from business_osint.db.models import Company, Entity, Relationship
from business_osint.domain.enums import Confidence, EntityType, RelationshipType
from business_osint.repositories.entities import EntityRepository

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _company(session, name: str = "ALFA", status: str = "active") -> uuid.UUID:
    entity_id = uuid.uuid4()
    session.add(
        Entity(
            id=entity_id,
            entity_type=EntityType.COMPANY,
            display_name=name,
            normalized_name=name.lower() + str(entity_id)[:8],
        )
    )
    session.add(Company(entity_id=entity_id, status=status))
    await session.flush()
    return entity_id


async def _zmiany(session, entity_id: uuid.UUID) -> list[dict]:
    return await EntityRepository(session).changes(entity_id)


async def test_status_change_is_recorded(db_session) -> None:
    """Zmiana statusu to zdarzenie, o którym obserwujący ma wiedzieć.

    Import nadpisuje status w miejscu, więc bez dziennika poprzednia wartość
    znika bezpowrotnie — i to jest jedyny powód, dla którego ta tabela istnieje.
    """
    entity_id = await _company(db_session, status="active")
    await db_session.execute(
        text("UPDATE companies SET status = 'suspended' WHERE entity_id = :id"), {"id": entity_id}
    )

    zmiany = [z for z in await _zmiany(db_session, entity_id) if z["rodzaj"] == "status"]

    assert len(zmiany) == 1
    assert (zmiany[0]["z"], zmiany[0]["na"]) == ("active", "suspended")


async def test_writing_the_same_value_is_not_a_change(db_session) -> None:
    """Ponowny import z tą samą wartością nie może produkować zdarzeń.

    Bez tego każdy przebieg CEIDG zalałby dziennik milionami wpisów „active
    zmieniło się na active", a monitoring stałby się bezużyteczny.
    """
    entity_id = await _company(db_session, status="active")
    await db_session.execute(
        text("UPDATE companies SET status = 'active' WHERE entity_id = :id"), {"id": entity_id}
    )

    assert [z for z in await _zmiany(db_session, entity_id) if z["rodzaj"] == "status"] == []


async def test_appearing_value_counts_as_a_change(db_session) -> None:
    """Przejście z „brak danych" na wartość jest zmianą.

    Naiwne porównanie `<>` daje przy NULL-u wynik NULL, czyli fałsz, i takie
    zdarzenie przepadłoby po cichu. Stąd `IS DISTINCT FROM` w wyzwalaczu.
    """
    entity_id = await _company(db_session)
    await db_session.execute(
        text("UPDATE companies SET legal_form = 'SPÓŁKA AKCYJNA' WHERE entity_id = :id"),
        {"id": entity_id},
    )

    zmiany = [z for z in await _zmiany(db_session, entity_id) if z["rodzaj"] == "legal_form"]

    assert len(zmiany) == 1
    assert (zmiany[0]["z"], zmiany[0]["na"]) == (None, "SPÓŁKA AKCYJNA")


async def test_a_rename_is_recorded(db_session) -> None:
    """Zmiana nazwy podmiotu jest zdarzeniem pierwszej kategorii."""
    entity_id = await _company(db_session, name="STARA NAZWA")
    await db_session.execute(
        text("UPDATE entities SET display_name = 'NOWA NAZWA' WHERE id = :id"), {"id": entity_id}
    )

    zmiany = [z for z in await _zmiany(db_session, entity_id) if z["rodzaj"] == "display_name"]

    assert (zmiany[0]["z"], zmiany[0]["na"]) == ("STARA NAZWA", "NOWA NAZWA")


async def test_bulk_sql_is_logged_just_like_the_orm(db_session) -> None:
    """Import zbiorczy omija ORM — i właśnie dlatego mechanizmem jest wyzwalacz.

    Ten test istnieje po to, żeby nikt nie przeniósł logowania do kodu
    aplikacji: zbiorczy `UPDATE ... FROM` nigdy przez ten kod nie przejdzie.
    """
    pierwsza = await _company(db_session, name="A", status="active")
    druga = await _company(db_session, name="B", status="active")
    await db_session.execute(
        text("""
            UPDATE companies c SET status = nowe.wartosc
            FROM (SELECT unnest(CAST(:ids AS uuid[])) AS id, 'inactive' AS wartosc) AS nowe
            WHERE c.entity_id = nowe.id
        """),
        {"ids": [pierwsza, druga]},
    )

    for entity_id in (pierwsza, druga):
        zmiany = [z for z in await _zmiany(db_session, entity_id) if z["rodzaj"] == "status"]
        assert (zmiany[0]["z"], zmiany[0]["na"]) == ("active", "inactive")


async def test_relationship_history_is_not_duplicated_in_the_log(db_session) -> None:
    """Powiązania są bitemporalne, więc ich historii nie logujemy drugi raz.

    Dublowanie podwoiłoby zapis przy imporcie milionów krawędzi i nie dołożyło
    ani jednej informacji. Kanał zmian scala oba źródła dopiero przy odczycie.
    """
    firma = await _company(db_session, name="FIRMA")
    inna = await _company(db_session, name="INNA")
    db_session.add(
        Relationship(
            id=uuid.uuid4(),
            source_entity_id=firma,
            target_entity_id=inna,
            relationship_type=RelationshipType.PARENT_OF,
            confidence=Confidence.REGISTERED,
        )
    )
    await db_session.flush()

    w_dzienniku = (
        await db_session.execute(
            text("SELECT count(*) FROM entity_changes WHERE entity_id = :id"), {"id": firma}
        )
    ).scalar_one()
    w_kanale = [z for z in await _zmiany(db_session, firma) if z["rodzaj"] == "powiazanie_dodane"]

    assert w_dzienniku == 0
    assert len(w_kanale) == 1


async def test_closing_an_edge_appears_as_an_event(db_session) -> None:
    """Zakończone powiązanie musi być widoczne — to najczęstszy powód alertu."""
    firma = await _company(db_session, name="FIRMA")
    inna = await _company(db_session, name="INNA")
    rel = uuid.uuid4()
    db_session.add(
        Relationship(
            id=rel,
            source_entity_id=firma,
            target_entity_id=inna,
            relationship_type=RelationshipType.PARENT_OF,
            confidence=Confidence.REGISTERED,
        )
    )
    await db_session.flush()
    await db_session.execute(
        text("UPDATE relationships SET superseded_at = now() WHERE id = :id"), {"id": rel}
    )

    rodzaje = [z["rodzaj"] for z in await _zmiany(db_session, firma)]

    assert "powiazanie_zamkniete" in rodzaje


async def test_timeline_is_newest_first(db_session) -> None:
    """Kolejność jest częścią użyteczności: alert dotyczy tego, co właśnie zaszło."""
    entity_id = await _company(db_session, status="active")
    for status in ("suspended", "inactive"):
        await db_session.execute(
            text("UPDATE companies SET status = :s WHERE entity_id = :id"),
            {"s": status, "id": entity_id},
        )

    zmiany = [z for z in await _zmiany(db_session, entity_id) if z["rodzaj"] == "status"]

    assert [z["na"] for z in zmiany] == ["inactive", "suspended"]
