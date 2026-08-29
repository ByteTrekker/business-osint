"""Kolejka zadań na prawdziwym Postgresie.

Sprawdzamy dokładnie te własności, których nie da się zweryfikować bez bazy:
FOR UPDATE SKIP LOCKED, indeks częściowy i semantykę odzyskiwania blokad.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import text

from business_osint.domain.enums import SourceKind
from business_osint.etl.task_queue import MAX_TASK_ATTEMPTS, TaskQueue

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _source(session) -> uuid.UUID:
    source_id = uuid.uuid4()
    await session.execute(
        text("INSERT INTO sources (id, kind, name) VALUES (:id, :kind, :name)"),
        {"id": source_id, "kind": SourceKind.KRS.value, "name": "test"},
    )
    await session.flush()
    return source_id


async def test_enqueue_is_idempotent(db_session) -> None:
    """Ponowne zakolejkowanie tej samej listy nie tworzy duplikatów."""
    source_id = await _source(db_session)
    queue = TaskQueue(db_session)

    first = await queue.enqueue(
        source_id=source_id, external_ids=["0000111111", "0000222222"], task_type="odpis_pelny"
    )
    second = await queue.enqueue(
        source_id=source_id, external_ids=["0000111111", "0000222222"], task_type="odpis_pelny"
    )

    assert first == 2
    assert second == 0
    assert await queue.stats(source_id=source_id) == {"pending": 2}


async def test_claim_respects_priority(db_session) -> None:
    source_id = await _source(db_session)
    queue = TaskQueue(db_session)
    await queue.enqueue(source_id=source_id, external_ids=["zwykly"], task_type="t", priority=0)
    await queue.enqueue(source_id=source_id, external_ids=["pilny"], task_type="t", priority=10)

    claimed = await queue.claim(source_id=source_id, batch_size=1, worker="w1")
    assert [t.external_id for t in claimed] == ["pilny"]


async def test_two_workers_never_claim_the_same_task(db_session, db_engine) -> None:
    """SKIP LOCKED: drugi worker pomija zablokowane wiersze zamiast czekać."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    source_id = await _source(db_session)
    await TaskQueue(db_session).enqueue(
        source_id=source_id, external_ids=[f"krs{i}" for i in range(6)], task_type="t"
    )
    await db_session.commit()

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as a, factory() as b, a.begin():
        first = await TaskQueue(a).claim(source_id=source_id, batch_size=3, worker="a")
        async with b.begin():
            second = await TaskQueue(b).claim(source_id=source_id, batch_size=3, worker="b")

    assert len(first) == 3
    assert len(second) == 3
    assert {t.id for t in first}.isdisjoint({t.id for t in second})


async def test_failed_task_returns_to_the_pool_with_backoff(db_session) -> None:
    source_id = await _source(db_session)
    queue = TaskQueue(db_session)
    await queue.enqueue(source_id=source_id, external_ids=["0000111111"], task_type="t")
    task = (await queue.claim(source_id=source_id, batch_size=1, worker="w"))[0]

    await queue.mark_failed(task.id, error="HTTP 503", retry_in=dt.timedelta(minutes=5))

    assert await queue.stats(source_id=source_id) == {"pending": 1}
    # Zadanie nie wróci do puli przed upływem backoffu.
    assert await queue.claim(source_id=source_id, batch_size=5, worker="w") == []


async def test_task_gives_up_after_max_attempts(db_session) -> None:
    """Zadanie, które ciągle pada, przestaje krążyć — ale zostaje z treścią błędu."""
    source_id = await _source(db_session)
    queue = TaskQueue(db_session)
    await queue.enqueue(source_id=source_id, external_ids=["0000111111"], task_type="t")

    for _ in range(MAX_TASK_ATTEMPTS):
        claimed = await queue.claim(source_id=source_id, batch_size=1, worker="w")
        if not claimed:
            break
        await queue.mark_failed(claimed[0].id, error="boom", retry_in=dt.timedelta(seconds=0))

    assert await queue.stats(source_id=source_id) == {"failed": 1}
    error = (await db_session.execute(text("SELECT last_error FROM ingestion_tasks"))).scalar_one()
    assert error == "boom"


async def test_stale_lock_is_recovered_after_a_worker_dies(db_session) -> None:
    source_id = await _source(db_session)
    queue = TaskQueue(db_session)
    await queue.enqueue(source_id=source_id, external_ids=["0000111111"], task_type="t")
    await queue.claim(source_id=source_id, batch_size=1, worker="zabity-worker")

    # Symulujemy blokadę sprzed godziny.
    await db_session.execute(
        text("UPDATE ingestion_tasks SET locked_at = now() - interval '1 hour'")
    )

    released = await queue.release_stale_locks(older_than=dt.timedelta(minutes=30))
    assert released == 1
    assert await queue.stats(source_id=source_id) == {"pending": 1}


async def test_zero_retry_delay_means_immediately(db_session) -> None:
    """`timedelta(0)` jest w Pythonie falsy — `retry_in or default` zamieniłby
    natychmiastowe ponowienie w dziesięciominutowe oczekiwanie."""
    source_id = await _source(db_session)
    queue = TaskQueue(db_session)
    await queue.enqueue(source_id=source_id, external_ids=["0000111111"], task_type="t")
    task = (await queue.claim(source_id=source_id, batch_size=1, worker="w"))[0]

    await queue.mark_failed(task.id, error="boom", retry_in=dt.timedelta(seconds=0))

    assert len(await queue.claim(source_id=source_id, batch_size=1, worker="w")) == 1
