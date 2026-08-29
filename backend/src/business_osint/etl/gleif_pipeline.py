"""Import danych GLEIF: rekordy LEI dla Polski + globalne relacje właścicielskie.

Przebieg jest przerywany i wznawialny: każda strona rekordów LEI zapisuje się
w osobnej transakcji razem z ``raw_documents``, a ponowne uruchomienie pomija
strony o niezmienionej treści (dedup po sha256).
"""

from __future__ import annotations

import csv
import io
import pathlib
import zipfile
from dataclasses import dataclass, field
from typing import Any

import httpx

from business_osint.db.session import get_sessionmaker
from business_osint.domain.enums import SourceKind
from business_osint.etl.loaders import load_document, store_raw_document
from business_osint.etl.pipeline import get_or_create_source
from business_osint.etl.sources.gleif_api import GOLDEN_COPY_URL, GleifClient
from business_osint.etl.sources.gleif_mapper import parse_lei_page, parse_relationship_row
from business_osint.etl.sources.krs_mapper import ParsedDocument


@dataclass(slots=True)
class GleifImportStats:
    pages: int = 0
    entities_created: int = 0
    entities_matched: int = 0
    relationships_created: int = 0
    pages_skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "pages": self.pages,
            "entities_created": self.entities_created,
            "entities_matched": self.entities_matched,
            "relationships_created": self.relationships_created,
            "pages_skipped": self.pages_skipped,
            "errors": len(self.errors),
        }


async def import_lei_records(
    *, country: str = "PL", max_pages: int | None = None, progress: Any = None
) -> GleifImportStats:
    """Pobiera rekordy LEI dla kraju i ładuje je do bazy."""
    stats = GleifImportStats()
    client = GleifClient()
    factory = get_sessionmaker()
    try:
        async for document in client.iter_lei_records(country=country, max_pages=max_pages):
            async with factory() as session, session.begin():
                source_id = await get_or_create_source(
                    session, SourceKind.GLEIF, "api.gleif.org", "https://api.gleif.org"
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
                parsed = parse_lei_page(document.payload)
                # close_missing=False: strona LEI to wycinek, a nie pełny obraz
                # podmiotu — nie wolno na jej podstawie zamykać cudzych relacji.
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


async def import_relationships(
    *, only_known_leis: bool = True, local_path: str | None = None
) -> GleifImportStats:
    """Pobiera plik relacji właścicielskich (ok. 23 MB) i ładuje krawędzie.

    Domyślnie zapisujemy wyłącznie relacje, w których przynajmniej jedna strona
    jest już w naszej bazie — inaczej zaciągnęlibyśmy globalny graf 500 tys.
    krawędzi, w większości bez związku z polskimi podmiotami.
    """
    stats = GleifImportStats()
    if local_path:
        # Plik już pobrany — pozwala ponowić ładowanie bez ściągania 24 MB
        # od nowa po błędzie sieci albo po poprawce w mapperze.
        url = f"file://{local_path}"
        # ASYNC240: odczyt lokalnego pliku jest jednorazowy i wykonywany przed
        # jakimkolwiek I/O sieciowym, więc krótkie zablokowanie pętli jest tu
        # tańsze niż wciąganie zależności na asynchroniczny dostęp do plików.
        payload = pathlib.Path(local_path).read_bytes()  # noqa: ASYNC240
    else:
        url = await _latest_relationship_file_url()
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(600.0, read=600.0), follow_redirects=True
        ) as http:
            response = await http.get(url)
            response.raise_for_status()
            payload = response.content

    rows = _read_csv_zip(payload)
    factory = get_sessionmaker()

    async with factory() as session, session.begin():
        known = await _known_leis(session) if only_known_leis else None
        source_id = await get_or_create_source(
            session, SourceKind.GLEIF, "goldencopy.gleif.org", "https://goldencopy.gleif.org"
        )
        parsed = ParsedDocument()
        for row in rows:
            relationship = parse_relationship_row(row)
            if relationship is None:
                continue
            if known is not None:
                parent = relationship.source_key.removeprefix("lei:")
                child = relationship.target_key.removeprefix("lei:")
                if parent not in known and child not in known:
                    continue
            parsed.relationships.append(relationship)

        raw_id, _ = await store_raw_document(
            session,
            source_id=source_id,
            external_id="relationship-records",
            url=url,
            fetched_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
            content_sha256=__import__("hashlib").sha256(payload).hexdigest(),
            payload={"rows": len(rows), "matched": len(parsed.relationships)},
        )
        # Plik RR zawiera same krawędzie — obie strony muszą być rozwiązane
        # z bazy, inaczej loader nie ma czego z czym połączyć.
        known_keys = await _lei_to_entity_id(session)
        load_stats = await load_document(
            session,
            parsed,
            raw_document_id=raw_id,
            close_missing=False,
            known_keys=known_keys,
        )
        stats.relationships_created = load_stats.relationships_created
    return stats


async def _lei_to_entity_id(session: Any) -> dict[str, Any]:
    from sqlalchemy import text as sql

    rows = await session.execute(
        sql("SELECT value, entity_id FROM entity_identifiers WHERE scheme = 'lei'")
    )
    return {f"lei:{value}": entity_id for value, entity_id in rows}


async def _latest_relationship_file_url() -> str:
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0), follow_redirects=True) as http:
        response = await http.get(GOLDEN_COPY_URL, params={"per_page": 1})
        response.raise_for_status()
        publish = response.json()["data"][0]
        return str(publish["rr"]["full_file"]["csv"]["url"])


def _read_csv_zip(payload: bytes) -> list[dict[str, str]]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        name = archive.namelist()[0]
        with archive.open(name) as handle:
            text = io.TextIOWrapper(handle, encoding="utf-8")
            return list(csv.DictReader(text))


async def _known_leis(session: Any) -> set[str]:
    from sqlalchemy import text as sql

    rows = await session.execute(sql("SELECT value FROM entity_identifiers WHERE scheme = 'lei'"))
    return {row[0] for row in rows}
