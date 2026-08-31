"""Wzbogacanie podmiotu odpisem KRS — na żądanie, z czasem życia dokumentu.

Dlaczego na żądanie, a nie masowo: art. 60a ustawy o KRS penalizuje
nieuprawnione pozyskiwanie danych z rejestru przez usługi sieciowe, a zakres
tego pojęcia jest niejasny. Pobranie odpisu podmiotu, którego ktoś właśnie
ogląda, jest zwykłym korzystaniem z usługi publicznej. Przemiatanie rejestru
nią nie jest, i czeka na opinię prawnika.

Co to daje, czego nie ma nigdzie indziej:

* **Datowaną historię.** CEIDG i GLEIF dają wyłącznie stan bieżący. Odpis pełny
  niesie każdą zmianę nazwy, siedziby i kapitału z numerem i datą wpisu — dla
  ORLEN-u jest to 25 lat.
* **Wspólny identyfikator.** Odpis podaje KRS i NIP naraz, co jest jedyną
  legalną w rozumieniu niezmiennika N4 podstawą scalenia encji, które przyszły
  z różnych źródeł i dotąd nie miały czym się połączyć.

Czego to nie daje: **osób**. Rejestr maskuje dane osobowe do pierwszej litery.
Patrz `krs_mapper`.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from business_osint.db.models import IngestionRun
from business_osint.db.session import get_etl_sessionmaker
from business_osint.domain.enums import SourceKind
from business_osint.etl.fetching.errors import FetchError
from business_osint.etl.loaders import load_document, store_raw_document
from business_osint.etl.pipeline import get_or_create_source
from business_osint.etl.sources.krs_api import KrsClient
from business_osint.etl.sources.krs_mapper import parse_krs_document

#: Jak długo odpis uznajemy za świeży. Wpisy w KRS zmieniają się w tempie
#: miesięcy, nie godzin, a każde pobranie obciąża rejestr ministerstwa. Trzydzieści
#: dni to kompromis między aktualnością a niebyciem uciążliwym; przy podejrzeniu
#: świeżej zmiany jest `force`.
DEFAULT_TTL = dt.timedelta(days=30)

#: Atrybuty z odpisu, które przenosimy do `companies.attributes`. Lista jest
#: jawna, a nie „wszystko, co przyszło": mapper może kiedyś zacząć zwracać pola,
#: których nie chcemy trzymać, a cicha zgoda na wszystko to zła domyślna.
CARRIED_ATTRIBUTES = ("name_history", "capital_history", "board_size", "board_note")


@dataclass(slots=True)
class EnrichmentResult:
    krs: str
    fetched: bool = False
    skipped_reason: str | None = None
    entities_created: int = 0
    relationships_created: int = 0
    history_entries: int = 0
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "krs": self.krs,
            "fetched": self.fetched,
            "skipped_reason": self.skipped_reason,
            "entities_created": self.entities_created,
            "relationships_created": self.relationships_created,
            "history_entries": self.history_entries,
            "error": self.error,
        }


@dataclass(slots=True)
class BatchResult:
    results: list[EnrichmentResult] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "processed": len(self.results),
            "fetched": sum(1 for r in self.results if r.fetched),
            "skipped": sum(1 for r in self.results if r.skipped_reason),
            "failed": sum(1 for r in self.results if r.error),
        }


_KRS_OF_ENTITY = text("""
    SELECT i.value
    FROM entity_identifiers i
    WHERE i.entity_id = :entity_id AND i.scheme = 'krs'
    LIMIT 1
""")


async def krs_of_entity(entity_id: uuid.UUID) -> str | None:
    """Numer KRS encji albo ``None``. Bez niego nie ma czego wzbogacać."""
    async with get_etl_sessionmaker()() as session:
        return (await session.execute(_KRS_OF_ENTITY, {"entity_id": entity_id})).scalar()


async def enrich_entity(entity_id: uuid.UUID, *, force: bool = False) -> EnrichmentResult:
    """Wzbogaca encję, o ile ma numer KRS."""
    krs = await krs_of_entity(entity_id)
    if krs is None:
        return EnrichmentResult(krs="", skipped_reason="encja nie ma numeru KRS")
    return await enrich_one(krs, force=force)


# Świeżość liczymy po **dokumencie**, nie po encji. Ten sam odpis potrafi
# dotyczyć kilku encji (spółka plus jej wspólnicy korporacyjni), a pobranie
# obciąża rejestr raz.
_LAST_FETCH = text("""
    SELECT max(d.fetched_at)
    FROM raw_documents d
    JOIN sources s ON s.id = d.source_id
    WHERE s.kind = 'krs' AND d.external_id = :external_id
""")

#: Encje, które mają numer KRS, ale nie mają jeszcze ani jednego odpisu.
#: Kolejność po stopniu: najpierw podmioty, które faktycznie coś w grafie trzymają.
_MISSING_DOCUMENTS = text("""
    SELECT i.value
    FROM entity_identifiers i
    JOIN entities e ON e.id = i.entity_id AND e.merged_into_id IS NULL
    WHERE i.scheme = 'krs'
      AND NOT EXISTS (
          SELECT 1 FROM raw_documents d
          JOIN sources s ON s.id = d.source_id
          WHERE s.kind = 'krs' AND d.external_id = i.value
      )
    ORDER BY e.degree DESC
    LIMIT :limit
""")

# Atrybuty dopisujemy scaleniem, nie podmianą: `companies.attributes` może już
# nieść dane z innego źródła, a odpis KRS ma je uzupełnić, nie wymieść.
_APPLY_COMPANY_FACTS = text("""
    UPDATE companies c
    SET attributes = c.attributes || CAST(:attributes AS jsonb),
        legal_form = COALESCE(CAST(:legal_form AS varchar), c.legal_form),
        registered_on = COALESCE(CAST(:registered_on AS date), c.registered_on),
        share_capital = COALESCE(CAST(:share_capital AS numeric), c.share_capital)
    FROM entity_identifiers i
    WHERE i.entity_id = c.entity_id
      AND i.scheme = 'krs'
      AND i.value = :krs
""")


# asyncpg wnioskuje typ parametru z `CAST(... AS date)` i **odrzuca napis** —
# potrzebuje `datetime.date` i `Decimal`. Lint ani mypy tego nie widzą, bo to
# surowy SQL; wychodzi dopiero na żywym połączeniu.


def _as_date(value: Any) -> dt.date | None:
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _latest_capital(history: list[dict[str, Any]]) -> Decimal | None:
    """Ostatni wpis kapitału, czyli obowiązujący. Historia jest chronologiczna."""
    current = [entry for entry in history if entry.get("to") is None]
    chosen = current[-1] if current else (history[-1] if history else None)
    if chosen is None:
        return None
    value = chosen.get("value")
    if value is None:
        return None
    try:
        return Decimal(str(value).replace(",", ".").replace(" ", ""))
    except InvalidOperation:
        return None


async def _is_fresh(session: AsyncSession, krs: str, ttl: dt.timedelta) -> dt.datetime | None:
    """Zwraca datę ostatniego pobrania, jeżeli mieści się w czasie życia."""
    last = (await session.execute(_LAST_FETCH, {"external_id": krs})).scalar()
    if last is None:
        return None
    if dt.datetime.now(dt.UTC) - last < ttl:
        return last  # type: ignore[no-any-return]
    return None


async def enrich_one(
    krs: str,
    *,
    registry: str = "P",
    ttl: dt.timedelta = DEFAULT_TTL,
    force: bool = False,
) -> EnrichmentResult:
    """Pobiera odpis pełny i przenosi go do grafu. Nie rzuca — zwraca błąd w wyniku.

    Wzbogacanie jest wywoływane z warstwy HTTP, gdy ktoś ogląda profil. Awaria
    rejestru nie może wtedy wywrócić żądania: profil ma się pokazać z tym, co
    już mamy, a informacja o nieudanym pobraniu ma trafić do wyniku.
    """
    result = EnrichmentResult(krs=krs)
    factory = get_etl_sessionmaker()

    if not force:
        async with factory() as session:
            fresh_at = await _is_fresh(session, krs, ttl)
        if fresh_at is not None:
            result.skipped_reason = f"odpis z {fresh_at.date().isoformat()} jest w czasie życia"
            return result

    client = KrsClient()
    try:
        document = await client.fetch_full(krs, registry=registry)
    except FetchError as error:
        result.error = str(error)
        return result
    finally:
        await client.aclose()

    async with factory() as session, session.begin():
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
        result.fetched = True

        parsed = parse_krs_document(document.payload)
        load_stats = await load_document(
            session, parsed, raw_document_id=raw_id, close_missing=False
        )
        result.entities_created = load_stats.entities_created
        result.relationships_created = load_stats.relationships_created

        result.history_entries = await apply_company_facts(session, krs, parsed)

        run.status = "success" if is_new else "unchanged"
        run.finished_at = dt.datetime.now(dt.UTC)
        run.stats = load_stats.as_dict()

    return result


async def apply_company_facts(session: AsyncSession, krs: str, parsed: Any) -> int:
    """Przenosi fakty z odpisu na istniejący wiersz `companies`. Zwraca liczbę wpisów historii.

    To jest krok, którego wcześniej nie było i przez który historia z KRS była
    **liczona i wyrzucana**: `EntityResolver` wypełnia `companies` tylko przy
    tworzeniu encji, a encja z numerem KRS zwykle już istnieje — przyszła
    z GLEIF albo z CEIDG. Dopasowanie po identyfikatorze nie aktualizowało
    niczego.
    """
    company = next(
        (e for e in parsed.entities if e.entity_type.value == "company"),
        None,
    )
    if company is None:
        return 0

    attributes = {k: v for k, v in company.attributes.items() if k in CARRIED_ATTRIBUTES}
    capital_history = company.attributes.get("capital_history") or []

    await session.execute(
        _APPLY_COMPANY_FACTS,
        {
            "krs": krs,
            "attributes": json.dumps(attributes, ensure_ascii=False),
            "legal_form": company.attributes.get("legal_form"),
            "registered_on": _as_date(company.attributes.get("registered_on")),
            "share_capital": _latest_capital(capital_history),
        },
    )
    return len(company.attributes.get("name_history") or []) + len(capital_history)


async def enrich_missing(*, limit: int = 25, progress: Any = None) -> BatchResult:
    """Wzbogaca podmioty z numerem KRS, dla których nie mamy jeszcze odpisu.

    Świadomie z limitem i bez współbieżności. To nie jest przemiatanie rejestru,
    tylko nadrabianie zaległości w tempie, które nie obciąża ministerstwa —
    granica z art. 60a jest niejasna i nie ma powodu jej dotykać.
    """
    batch = BatchResult()
    async with get_etl_sessionmaker()() as session:
        numbers = list((await session.execute(_MISSING_DOCUMENTS, {"limit": limit})).scalars())

    for krs in numbers:
        result = await enrich_one(krs)
        batch.results.append(result)
        if progress is not None:
            progress(result)
    return batch
