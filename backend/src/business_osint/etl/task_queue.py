"""Kolejka zadań pobierania oparta o PostgreSQL.

``FOR UPDATE SKIP LOCKED`` pozwala wielu workerom brać rozłączne partie zadań
bez brokera i bez wyścigów. To jest cała infrastruktura kolejkowa potrzebna na
tym etapie — Redis wchodzi dopiero wtedy, gdy zadania przestaną być jednorodne.

Zasada „nie padamy”: worker nigdy nie przerywa przebiegu z powodu jednego
zadania. Zadanie kończy się jako ``done``, ``skipped`` albo wraca do puli
z opóźnieniem i licznikiem prób.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import CursorResult, text
from sqlalchemy.ext.asyncio import AsyncSession

#: Po tylu nieudanych podejściach zadanie przestaje wracać do puli.
MAX_TASK_ATTEMPTS = 5

#: Domyślne opóźnienie przed ponowieniem zadania.
DEFAULT_RETRY_DELAY = dt.timedelta(minutes=10)


@dataclass(frozen=True, slots=True)
class ClaimedTask:
    id: uuid.UUID
    external_id: str
    task_type: str
    attempts: int


_CLAIM_SQL = text(
    """
    WITH claimed AS (
        SELECT id
        FROM ingestion_tasks
        WHERE source_id = :source_id
          AND status = 'pending'
          AND scheduled_for <= now()
        ORDER BY priority DESC, scheduled_for
        LIMIT :batch_size
        FOR UPDATE SKIP LOCKED
    )
    UPDATE ingestion_tasks t
    SET status = 'running',
        locked_at = now(),
        locked_by = :worker,
        attempts = t.attempts + 1,
        updated_at = now()
    FROM claimed
    WHERE t.id = claimed.id
    RETURNING t.id, t.external_id, t.task_type, t.attempts
    """
)


class TaskQueue:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue(
        self,
        *,
        source_id: uuid.UUID,
        external_ids: list[str],
        task_type: str,
        priority: int = 0,
    ) -> int:
        """Dokłada zadania. Ponowne zakolejkowanie tego samego podmiotu nie duplikuje."""
        if not external_ids:
            return 0
        result = await self._session.execute(
            text(
                """
                INSERT INTO ingestion_tasks (id, source_id, external_id, task_type, priority)
                SELECT gen_random_uuid(), :source_id, x, :task_type, :priority
                FROM unnest(CAST(:external_ids AS text[])) AS x
                ON CONFLICT ON CONSTRAINT uq_ingestion_tasks_identity DO NOTHING
                """
            ),
            {
                "source_id": source_id,
                "external_ids": external_ids,
                "task_type": task_type,
                "priority": priority,
            },
        )
        return cast(CursorResult[Any], result).rowcount or 0

    async def claim(
        self, *, source_id: uuid.UUID, batch_size: int, worker: str
    ) -> list[ClaimedTask]:
        """Rezerwuje partię zadań dla tego workera."""
        rows = (
            (
                await self._session.execute(
                    _CLAIM_SQL,
                    {"source_id": source_id, "batch_size": batch_size, "worker": worker},
                )
            )
            .mappings()
            .all()
        )
        return [
            ClaimedTask(
                id=row["id"],
                external_id=row["external_id"],
                task_type=row["task_type"],
                attempts=row["attempts"],
            )
            for row in rows
        ]

    async def mark_done(self, task_id: uuid.UUID, *, status: str = "done") -> None:
        await self._session.execute(
            text(
                """
                UPDATE ingestion_tasks
                SET status = :status, locked_at = NULL, locked_by = NULL,
                    last_error = NULL, updated_at = now()
                WHERE id = :id
                """
            ),
            {"id": task_id, "status": status},
        )

    async def mark_failed(
        self, task_id: uuid.UUID, *, error: str, retry_in: dt.timedelta | None = None
    ) -> None:
        """Zwraca zadanie do puli albo oznacza jako trwale nieudane.

        Zadanie, które wyczerpało próby, zostaje w bazie ze statusem ``failed``
        i treścią błędu — nie znika po cichu.
        """
        await self._session.execute(
            text(
                """
                UPDATE ingestion_tasks
                SET status = CASE
                        WHEN attempts >= :max_attempts THEN 'failed'
                        ELSE 'pending'
                    END,
                    -- make_interval zamiast rzutowania napisu na interval: asyncpg
                    -- wnioskuje typ parametru z rzutowania i próbuje zakodować napis
                    -- jako interwał, co kończy się DataError. Uwaga: SQLAlchemy
                    -- parsuje parametry także w komentarzach, więc nie piszemy tu
                    -- nazw poprzedzonych dwukropkiem.
                    scheduled_for = now() + make_interval(secs => :retry_seconds),
                    locked_at = NULL,
                    locked_by = NULL,
                    last_error = :error,
                    updated_at = now()
                WHERE id = :id
                """
            ),
            {
                "id": task_id,
                "error": error[:2000],
                "max_attempts": MAX_TASK_ATTEMPTS,
                # `retry_in or default` byłoby błędem: timedelta(0) jest falsy,
                # więc natychmiastowe ponowienie zamieniałoby się w 10 minut.
                "retry_seconds": int(
                    (retry_in if retry_in is not None else DEFAULT_RETRY_DELAY).total_seconds()
                ),
            },
        )

    async def release_stale_locks(self, *, older_than: dt.timedelta) -> int:
        """Odzyskuje zadania po workerze, który padł w trakcie.

        Bez tego zabity proces zostawia zadania w stanie ``running`` na zawsze.
        """
        result = await self._session.execute(
            text(
                """
                UPDATE ingestion_tasks
                SET status = 'pending', locked_at = NULL, locked_by = NULL, updated_at = now()
                WHERE status = 'running'
                  AND locked_at < now() - make_interval(secs => :age_seconds)
                """
            ),
            {"age_seconds": int(older_than.total_seconds())},
        )
        return cast(CursorResult[Any], result).rowcount or 0

    async def stats(self, *, source_id: uuid.UUID) -> dict[str, int]:
        rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT status, count(*) AS n FROM ingestion_tasks "
                        "WHERE source_id = :source_id GROUP BY status"
                    ),
                    {"source_id": source_id},
                )
            )
            .mappings()
            .all()
        )
        return {row["status"]: row["n"] for row in rows}
