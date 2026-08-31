"""Ranking wyszukiwarki na prawdziwym Postgresie.

Kolejność wyników rodzi się w SQL-u — w warunkach etapów i w wyrażeniu
trafności — więc bez bazy nie da się jej sprawdzić. Testy opisują **reguły**,
nie implementację: który wynik ma być wyżej i dlaczego.
"""

from __future__ import annotations

import uuid

import pytest

from business_osint.db.models import Company, Entity
from business_osint.domain.enums import EntityType
from business_osint.repositories.entities import EntityRepository

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

# Prefiks nieobecny w prawdziwych danych, żeby test nie zależał od zawartości
# bazy deweloperskiej ani od kolejności uruchamiania.
PREFIX = "zzqtest"


async def _company(
    session,
    name: str,
    *,
    krs: str | None = None,
    status: str = "active",
    degree: int = 0,
) -> uuid.UUID:
    entity_id = uuid.uuid4()
    session.add(
        Entity(
            id=entity_id,
            entity_type=EntityType.COMPANY,
            display_name=name.upper(),
            normalized_name=name,
            degree=degree,
        )
    )
    session.add(Company(entity_id=entity_id, krs=krs, status=status))
    await session.flush()
    return entity_id


async def _names(session, query: str) -> list[str]:
    hits = await EntityRepository(session).search(query, limit=10)
    return [h.display_name for h in hits]


async def test_exact_name_outranks_longer_name_with_same_prefix(db_session):
    """Dokładna nazwa bije dłuższą, która tylko się tak zaczyna.

    Regresja z produkcji: „orlen" zwracało „Orlena Hintzke" przed ORLEN S.A.,
    bo jedynym kryterium był stopień węzła.
    """
    await _company(db_session, PREFIX, degree=0)
    await _company(db_session, f"{PREFIX}a hintzke", degree=9)

    assert (await _names(db_session, PREFIX))[0] == PREFIX.upper()


async def test_word_boundary_prefix_outranks_mid_word_prefix(db_session):
    """„zzqtest termika" jest bliżej „zzqtest" niż „zzqtesta hintzke".

    Granica słowa jest sygnałem znaczeniowym: „orlena" to inne słowo niż
    „orlen", nawet jeżeli różni je jedna litera.
    """
    await _company(db_session, f"{PREFIX}a hintzke", degree=9)
    await _company(db_session, f"{PREFIX} termika", degree=0)

    names = await _names(db_session, PREFIX)
    assert names.index(f"{PREFIX} termika".upper()) < names.index(f"{PREFIX}a hintzke".upper())


async def test_registered_company_outranks_sole_trader_at_equal_match(db_session):
    """Przy równym dopasowaniu wyżej stoi podmiot z KRS.

    KRS ma 23 683 podmiotów z 3,6 mln, więc jego obecność jest w tych danych
    najsilniejszym dostępnym sygnałem istotności.
    """
    await _company(db_session, f"{PREFIX} alfa", krs=None, degree=0)
    await _company(db_session, f"{PREFIX} beta", krs="0000123456", degree=0)

    names = await _names(db_session, PREFIX)
    assert names.index(f"{PREFIX} beta".upper()) < names.index(f"{PREFIX} alfa".upper())


async def test_inactive_company_ranks_below_active_one(db_session):
    """Wykreślona spółka schodzi poniżej działającej o tym samym dopasowaniu."""
    await _company(db_session, f"{PREFIX} alfa", status="inactive", degree=0)
    await _company(db_session, f"{PREFIX} beta", status="active", degree=0)

    names = await _names(db_session, PREFIX)
    assert names.index(f"{PREFIX} beta".upper()) < names.index(f"{PREFIX} alfa".upper())


async def test_degree_never_overrides_a_better_name_match(db_session):
    """Stopień jest sygnałem najsłabszym i nie odwraca lepszego dopasowania.

    Stopień mówi, ile krawędzi zdążyliśmy zaimportować — jest artefaktem
    postępu ETL, nie miarą znaczenia podmiotu.
    """
    await _company(db_session, PREFIX, degree=0)
    await _company(db_session, f"{PREFIX} bardzo dluga nazwa spolki", degree=4000)

    assert (await _names(db_session, PREFIX))[0] == PREFIX.upper()


async def test_query_matching_no_prefix_still_finds_entity_by_trigram(db_session):
    """Zapytanie niebędące prefiksem żadnej nazwy nie może dawać pustki.

    „PKN ORLEN" zwracało zero wyników mimo obecności ORLEN S.A. w bazie.
    Trigram uruchamia się sam, gdy tańsze etapy nic nie znalazły.
    """
    await _company(db_session, f"{PREFIX} termika", degree=0)

    assert await _names(db_session, f"pkn {PREFIX} termika")
