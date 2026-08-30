"""Import ogłoszeń o zamówieniach publicznych."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from business_osint.db.session import get_sessionmaker
from business_osint.domain.enums import SourceKind
from business_osint.etl.loaders import load_document, store_raw_document
from business_osint.etl.pipeline import get_or_create_source
from business_osint.etl.sources.bzp_api import BzpClient
from business_osint.etl.sources.bzp_mapper import parse_notices


@dataclass(slots=True)
class BzpStats:
    pages: int = 0
    entities_created: int = 0
    entities_matched: int = 0
    relationships_created: int = 0
    pages_skipped: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "pages": self.pages,
            "entities_created": self.entities_created,
            "entities_matched": self.entities_matched,
            "relationships_created": self.relationships_created,
            "pages_skipped": self.pages_skipped,
        }


async def import_notices(*, days_back: int = 30, progress: Any = None) -> BzpStats:
    stats = BzpStats()
    client = BzpClient()
    factory = get_sessionmaker()
    try:
        async for document in client.iter_notices(days_back=days_back):
            async with factory() as session, session.begin():
                source_id = await get_or_create_source(
                    session, SourceKind.BZP, "ezamowienia.gov.pl", "https://ezamowienia.gov.pl"
                )
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
                    stats.pages_skipped += 1
                    continue
                parsed = parse_notices(document.payload)
                # Ogłoszenie to zdarzenie punktowe — nie zamyka innych relacji podmiotu.
                load_stats = await load_document(
                    session, parsed, raw_document_id=raw_id, close_missing=False
                )
                stats.entities_created += load_stats.entities_created
                stats.entities_matched += load_stats.entities_matched
                stats.relationships_created += load_stats.relationships_created
            stats.pages += 1
            if progress is not None:
                progress(stats)
    finally:
        await client.aclose()
    return stats
