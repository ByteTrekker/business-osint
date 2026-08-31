"""Import danych finansowych z wykazu podatników CIT."""

from __future__ import annotations

import hashlib
import pathlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert

from business_osint.db.models import FinancialReport
from business_osint.db.session import get_etl_sessionmaker
from business_osint.domain.enums import EntityType, IdentifierScheme, SourceKind
from business_osint.domain.normalization import normalize_company_name
from business_osint.etl.loaders import EntityResolver, LoadStats, store_raw_document
from business_osint.etl.pipeline import get_or_create_source
from business_osint.etl.sources.cit_registry import CitRecord, parse_cit_workbook
from business_osint.etl.sources.krs_mapper import ParsedEntity


@dataclass(slots=True)
class CitStats:
    records: int = 0
    entities_created: int = 0
    entities_matched: int = 0
    reports_written: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "records": self.records,
            "entities_created": self.entities_created,
            "entities_matched": self.entities_matched,
            "reports_written": self.reports_written,
        }


async def import_cit_file(path: str, *, dataset: str, url: str | None = None) -> CitStats:
    """Ładuje jeden arkusz MF: encje po NIP-ie plus sprawozdania finansowe."""
    records = parse_cit_workbook(path, dataset=dataset)
    stats = CitStats(records=len(records))
    if not records:
        return stats

    # ASYNC230: jednorazowy odczyt lokalnego pliku przed jakimkolwiek I/O bazy;
    # asynchroniczny dostęp do plików nie jest tu wart dodatkowej zależności.
    digest = hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()  # noqa: ASYNC240

    factory = get_etl_sessionmaker()
    async with factory() as session, session.begin():
        source_id = await get_or_create_source(
            session, SourceKind.MANUAL, "wykaz CIT (art. 27b)", "https://www.gov.pl/web/finanse"
        )
        raw_id, _ = await store_raw_document(
            session,
            source_id=source_id,
            external_id=f"cit/{dataset}/{records[0].period_to.year}",
            url=url,
            fetched_at=datetime.now(UTC),
            content_sha256=digest,
            payload={"dataset": dataset, "records": len(records)},
        )

        resolver = EntityResolver(session)
        load_stats = LoadStats()
        for record in records:
            entity_id = await resolver.resolve(_as_entity(record), load_stats)
            stats.reports_written += await _write_report(session, entity_id, record, raw_id)

        stats.entities_created = load_stats.entities_created
        stats.entities_matched = load_stats.entities_matched
    return stats


def _as_entity(record: CitRecord) -> ParsedEntity:
    return ParsedEntity(
        entity_type=EntityType.COMPANY,
        display_name=record.name,
        normalized_name=normalize_company_name(record.name),
        identifiers={IdentifierScheme.NIP: record.nip},
        attributes={"cit_dataset": record.attributes.get("dataset")},
        local_key=f"nip:{record.nip}",
    )


async def _write_report(
    session: Any, entity_id: uuid.UUID, record: CitRecord, raw_id: uuid.UUID
) -> int:
    """Zapisuje sprawozdanie. Powtórny import tego samego roku aktualizuje wiersz,
    bo MF publikuje korekty — ale zostawia ślad w raw_document_id."""
    statement = (
        pg_insert(FinancialReport)
        .values(
            id=uuid.uuid4(),
            entity_id=entity_id,
            period_from=record.period_from,
            period_to=record.period_to,
            revenue=record.revenue,
            costs=record.costs,
            income=record.income,
            loss=record.loss,
            tax_base=record.tax_base,
            tax_due=record.tax_due,
            raw_document_id=raw_id,
            attributes=record.attributes,
        )
        .on_conflict_do_update(
            constraint="uq_financial_reports_period",
            set_={
                "revenue": record.revenue,
                "costs": record.costs,
                "income": record.income,
                "loss": record.loss,
                "tax_base": record.tax_base,
                "tax_due": record.tax_due,
                "raw_document_id": raw_id,
            },
        )
        .returning(FinancialReport.id)
    )
    result = await session.execute(statement)
    return 1 if result.scalars().first() else 0
