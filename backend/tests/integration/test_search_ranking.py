"""Ranking wyszukiwarki na prawdziwym Postgresie.

Kolejność wyników rodzi się w SQL-u — w warunkach etapów i w wyrażeniu
trafności — więc bez bazy nie da się jej sprawdzić. Testy opisują **reguły**,
nie implementację: który wynik ma być wyżej i dlaczego.
"""

from __future__ import annotations

import uuid

import pytest

from business_osint.db.models import Company, Entity, EntityIdentifier
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


async def _names(session, query: str, **kwargs) -> list[str]:
    hits, _ = await EntityRepository(session).search(query, limit=10, **kwargs)
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


async def test_word_order_does_not_matter(db_session) -> None:
    """„termika orlen" ma trafić w ORLEN TERMIKA.

    Żaden etap prefiksowy tego nie zrobi, bo zapytanie nie jest początkiem
    nazwy. Wcześniej ratował to dopiero trigram — poprawnie, ale w setkach
    milisekund zamiast w ułamku jednej.
    """
    await _company(db_session, f"{PREFIX} termika")
    await _company(db_session, f"{PREFIX} energia")

    assert await _names(db_session, f"termika {PREFIX}") == [f"{PREFIX} termika".upper()]


async def test_a_word_outside_the_name_falls_through_to_fuzzy(db_session) -> None:
    """Dopasowanie po słowach jest koniunkcyjne — brakujące słowo wyklucza trafienie.

    Sprawdzamy to po **paśmie wyniku**, nie po jego obecności: podmiot i tak
    wraca, bo przy pustym rezultacie uruchamia się trigram. Gdyby etap słowny
    był alternatywą, „jan kowalski" zwracałby pół bazy — a tu wyszłoby to jako
    wynik z pasma 0,55–0,69 zamiast trigramowego 0,30–0,39.
    """
    await _company(db_session, f"{PREFIX} termika")

    hits, _ = await EntityRepository(db_session).search(f"{PREFIX} termika elektrownia", limit=5)

    assert [h.display_name for h in hits] == [f"{PREFIX} termika".upper()]
    assert hits[0].score < 0.40, "trafienie przyszło z etapu słownego, a nie z trigramu"


async def test_status_filter_narrows_the_result(db_session) -> None:
    """Filtr stanu zawęża, a nie tylko przestawia kolejność."""
    await _company(db_session, f"{PREFIX} alfa", status="active")
    await _company(db_session, f"{PREFIX} beta", status="suspended")

    assert await _names(db_session, PREFIX, status="suspended") == [f"{PREFIX} beta".upper()]
    assert await _names(db_session, PREFIX, status="inactive") == []


async def test_status_filter_does_not_hide_a_hit_found_by_identifier(db_session) -> None:
    """Kto podał NIP, chce tę encję — nawet jeżeli jest wykreślona.

    Filtr stanu jest narzędziem przeglądania, nie cenzurą wyniku dokładnego.
    """
    entity_id = await _company(db_session, f"{PREFIX} zamknieta", status="inactive")
    db_session.add(
        EntityIdentifier(id=uuid.uuid4(), entity_id=entity_id, scheme="nip", value="5252445170")
    )
    await db_session.flush()

    assert await _names(db_session, "5252445170", status="active") == [
        f"{PREFIX} zamknieta".upper()
    ]
