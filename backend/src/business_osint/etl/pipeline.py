"""Orkiestracja pobrania i załadowania danych ze źródeł."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from business_osint.db.models import IngestionRun, Source
from business_osint.db.session import get_sessionmaker
from business_osint.domain.enums import SourceKind
from business_osint.etl.loaders import load_document, store_raw_document
from business_osint.etl.sources.krs_api import KrsClient
from business_osint.etl.sources.krs_mapper import parse_krs_document


async def get_or_create_source(
    session: AsyncSession, kind: SourceKind, name: str, base_url: str | None = None
) -> uuid.UUID:
    existing = (
        await session.execute(select(Source.id).where(Source.kind == kind, Source.name == name))
    ).scalars().first()
    if existing:
        return existing
    source = Source(id=uuid.uuid4(), kind=kind, name=name, base_url=base_url)
    session.add(source)
    await session.flush()
    return source.id


async def ingest_single_krs(krs: str, *, registry: str = "P") -> dict[str, Any]:
    """Pobiera odpis pełny KRS i ładuje go do bazy razem z provenance."""
    client = KrsClient()
    try:
        document = await client.fetch_full(krs, registry=registry)
    finally:
        await client.aclose()

    async with get_sessionmaker()() as session, session.begin():
        source_id = await get_or_create_source(
            session, SourceKind.KRS, "api-krs.ms.gov.pl", "https://api-krs.ms.gov.pl"
        )
        run = IngestionRun(id=uuid.uuid4(), source_id=source_id, status="running")
        session.add(run)
        await session.flush()

        raw_id, is_new = await store_raw_document(
            session,
            source_id=source_id,
            external_id=document.external_id,
            url=document.url,
            fetched_at=document.fetched_at,
            content_sha256=document.content_sha256,
            payload=document.payload,
        )
        if not is_new:
            # Treść identyczna z poprzednim pobraniem — nie ma czego przetwarzać.
            run.status = "skipped"
            run.finished_at = dt.datetime.now(dt.UTC)
            run.stats = {"reason": "unchanged_content"}
            return {"krs": krs, "skipped": True}

        parsed = parse_krs_document(document.payload)
        stats = await load_document(session, parsed, raw_document_id=raw_id)
        run.status = "success"
        run.finished_at = dt.datetime.now(dt.UTC)
        run.stats = stats.as_dict()
        return {"krs": krs, **stats.as_dict()}
