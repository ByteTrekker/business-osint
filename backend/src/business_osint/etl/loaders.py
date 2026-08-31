"""Zapis sparsowanego dokumentu do bazy: resolve -> upsert -> provenance.

Reguły, których loader pilnuje:

1. **Idempotencja.** Ten sam odpis wgrany drugi raz nie tworzy nowych encji
   ani nowych krawędzi (dedup po ``content_sha256`` i po naturalnych kluczach).
2. **Nic nie znika.** Fakt, który zniknął ze źródła, dostaje ``valid_to`` /
   ``superseded_at`` — nie ma DELETE.
3. **Każdy zapis ma źródło.** Krawędź bez wpisu w ``relationship_sources``
   to błąd programisty, nie stan dopuszczalny.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import CursorResult, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from business_osint.db.models import (
    Address,
    Company,
    Entity,
    EntityIdentifier,
    EntitySource,
    Person,
    RawDocument,
    Relationship,
    RelationshipSource,
)
from business_osint.domain.enums import Confidence, EntityType, IdentifierScheme
from business_osint.domain.normalization import company_name_blocking_key, person_blocking_key
from business_osint.etl.sources.krs_mapper import ParsedDocument, ParsedEntity, ParsedRelationship


@dataclass(slots=True)
class LoadStats:
    entities_created: int = 0
    entities_matched: int = 0
    relationships_created: int = 0
    relationships_closed: int = 0
    document_skipped: bool = False

    def as_dict(self) -> dict[str, int | bool]:
        return {
            "entities_created": self.entities_created,
            "entities_matched": self.entities_matched,
            "relationships_created": self.relationships_created,
            "relationships_closed": self.relationships_closed,
            "document_skipped": self.document_skipped,
        }


class EntityResolver:
    """Deterministyczne dopasowanie encji. Heurystyki idą do kolejki review."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def resolve(self, parsed: ParsedEntity, stats: LoadStats) -> uuid.UUID:
        if parsed.identifiers:
            existing = await self._by_identifier(parsed.identifiers)
            if existing:
                await self._attach_identifiers(existing, parsed.identifiers)
                stats.entities_matched += 1
                return existing

        if parsed.entity_type is EntityType.ADDRESS:
            existing = await self._by_normalized_address(parsed.normalized_name)
            if existing:
                stats.entities_matched += 1
                return existing

        # ŻADNEGO automatycznego scalania po nazwie — ani dla osób, ani dla firm.
        #
        # Klucz blokujący to dwanaście pierwszych znaków znormalizowanej nazwy.
        # W polskich danych dzieli go 49 704 firm zaczynających się od
        # „PRZEDSIĘBIORSTWO", 52 041 od „INDYWIDUALNA" i 40 640 od „FIRMA
        # HANDLOWA". Scalanie po nim wrzuciło 734 cudze adresy do jednej JDG.
        #
        # Klucz zostaje zapisany, bo służy jako generator kandydatów do kolejki
        # przeglądu — ale kandydat to nie dowód. Duplikat widać i da się scalić;
        # fałszywe scalenie tworzy powiązania, które nie istnieją (niezmiennik N4).
        blocking_key = self._blocking_key(parsed)
        entity_id = await self._create(parsed, blocking_key)
        stats.entities_created += 1
        return entity_id

    async def _by_identifier(self, identifiers: dict[IdentifierScheme, str]) -> uuid.UUID | None:
        pairs = [(scheme.value, value) for scheme, value in identifiers.items() if value]
        if not pairs:
            return None
        # Dwie tablice zamiast krotki krotek: asyncpg nie potrafi zbindować
        # `(scheme, value) IN :pairs` jako pojedynczego parametru.
        result = await self._session.execute(
            text(
                """
                SELECT entity_id FROM entity_identifiers
                WHERE (scheme, value) IN (
                    SELECT * FROM unnest(CAST(:schemes AS text[]), CAST(:values AS text[]))
                )
                LIMIT 1
                """
            ),
            {"schemes": [p[0] for p in pairs], "values": [p[1] for p in pairs]},
        )
        return result.scalars().first()

    async def _by_normalized_address(self, normalized: str) -> uuid.UUID | None:
        """Adres ma naturalny klucz w `addresses.normalized` — po nim dopasowujemy.

        Klucz blokujący na `entities` tu nie wystarcza: źródła masowe (CEIDG)
        wstawiają adresy zapytaniem zbiorczym i nie wypełniają `blocking_key`,
        więc resolver ich nie widział i próbował wstawić duplikat, łamiąc
        `uq_addresses_normalized`.
        """
        return (
            (
                await self._session.execute(
                    text("SELECT entity_id FROM addresses WHERE normalized = :normalized LIMIT 1"),
                    {"normalized": normalized},
                )
            )
            .scalars()
            .first()
        )

    async def _attach_identifiers(
        self, entity_id: uuid.UUID, identifiers: dict[IdentifierScheme, str]
    ) -> None:
        for scheme, value in identifiers.items():
            if not value:
                continue
            await self._session.execute(
                pg_insert(EntityIdentifier)
                .values(entity_id=entity_id, scheme=scheme.value, value=value)
                .on_conflict_do_nothing(constraint="uq_entity_identifiers_scheme_value")
            )

    async def _create(self, parsed: ParsedEntity, blocking_key: str | None) -> uuid.UUID:
        entity_id = uuid.uuid4()
        self._session.add(
            Entity(
                id=entity_id,
                entity_type=parsed.entity_type,
                display_name=parsed.display_name,
                normalized_name=parsed.normalized_name,
                blocking_key=blocking_key,
            )
        )
        await self._session.flush()
        await self._attach_identifiers(entity_id, parsed.identifiers)

        attrs = parsed.attributes
        match parsed.entity_type:
            case EntityType.COMPANY:
                self._session.add(
                    Company(
                        entity_id=entity_id,
                        legal_form=attrs.get("legal_form"),
                        krs=parsed.identifiers.get(IdentifierScheme.KRS),
                        nip=parsed.identifiers.get(IdentifierScheme.NIP),
                        regon=parsed.identifiers.get(IdentifierScheme.REGON),
                        status=attrs.get("status", "active"),
                    )
                )
            case EntityType.PERSON:
                self._session.add(
                    Person(
                        entity_id=entity_id,
                        first_names=attrs.get("first_names", ""),
                        last_name=attrs.get("last_name", parsed.display_name),
                        birth_year=attrs.get("birth_year"),
                    )
                )
            case EntityType.ADDRESS:
                self._session.add(
                    Address(
                        entity_id=entity_id,
                        city=attrs.get("city"),
                        street=attrs.get("street"),
                        building=attrs.get("building"),
                        unit=attrs.get("unit"),
                        postal_code=attrs.get("postal_code"),
                        voivodeship=attrs.get("voivodeship"),
                        normalized=parsed.normalized_name,
                    )
                )
        await self._session.flush()
        return entity_id

    @staticmethod
    def _blocking_key(parsed: ParsedEntity) -> str | None:
        match parsed.entity_type:
            case EntityType.COMPANY:
                return company_name_blocking_key(parsed.display_name)
            case EntityType.PERSON:
                return person_blocking_key(
                    parsed.attributes.get("first_names", ""),
                    parsed.attributes.get("last_name", parsed.display_name),
                    parsed.attributes.get("birth_year"),
                )
            case EntityType.ADDRESS:
                return parsed.normalized_name[:32]
        return None


async def store_raw_document(
    session: AsyncSession,
    *,
    source_id: uuid.UUID,
    external_id: str,
    url: str | None,
    fetched_at: dt.datetime,
    content_sha256: str,
    payload: dict[str, Any],
) -> tuple[uuid.UUID, bool]:
    """Zapisuje surowy dokument. Zwraca (id, czy_nowy).

    Ten sam dokument o niezmienionej treści nie tworzy nowego snapshotu —
    dzięki temu codzienny crawl 1 mln podmiotów nie rośnie w nieskończoność.
    """
    stmt = (
        pg_insert(RawDocument)
        .values(
            id=uuid.uuid4(),
            source_id=source_id,
            external_id=external_id,
            url=url,
            fetched_at=fetched_at,
            content_sha256=content_sha256,
            payload=payload,
        )
        .on_conflict_do_nothing(constraint="uq_raw_documents_identity")
        .returning(RawDocument.id)
    )
    inserted = (await session.execute(stmt)).scalars().first()
    if inserted:
        return inserted, True
    existing = (
        (
            await session.execute(
                select(RawDocument.id).where(
                    RawDocument.source_id == source_id,
                    RawDocument.external_id == external_id,
                    RawDocument.content_sha256 == content_sha256,
                )
            )
        )
        .scalars()
        .one()
    )
    return existing, False


async def load_document(
    session: AsyncSession,
    parsed: ParsedDocument,
    *,
    raw_document_id: uuid.UUID,
    close_missing: bool = True,
    known_keys: dict[str, uuid.UUID] | None = None,
) -> LoadStats:
    """Ładuje sparsowany dokument. Jedna transakcja = jeden spójny stan wiedzy.

    ``known_keys`` pozwala podać klucze lokalne rozwiązane wcześniej, poza tym
    dokumentem. Potrzebne dla źródeł, które publikują **same krawędzie** —
    jak plik relacji właścicielskich GLEIF, gdzie obie strony relacji są już
    w bazie, a dokument nie zawiera żadnych encji.
    """
    stats = LoadStats()
    resolver = EntityResolver(session)

    key_to_id: dict[str, uuid.UUID] = dict(known_keys or {})
    for entity in parsed.entities:
        if entity.local_key in key_to_id:
            continue
        entity_id = await resolver.resolve(entity, stats)
        key_to_id[entity.local_key] = entity_id
        await session.execute(
            pg_insert(EntitySource)
            .values(entity_id=entity_id, raw_document_id=raw_document_id)
            .on_conflict_do_nothing()
        )

    seen_relationship_ids: set[uuid.UUID] = set()
    root_ids = {
        key_to_id[e.local_key] for e in parsed.entities if e.entity_type == EntityType.COMPANY
    }

    for rel in parsed.relationships:
        source_id = key_to_id.get(rel.source_key)
        target_id = key_to_id.get(rel.target_key)
        if source_id is None or target_id is None or source_id == target_id:
            continue
        rel_id = await _upsert_relationship(session, rel, source_id, target_id, stats)
        seen_relationship_ids.add(rel_id)
        await session.execute(
            pg_insert(RelationshipSource)
            .values(
                relationship_id=rel_id,
                raw_document_id=raw_document_id,
                locator=rel.locator,
            )
            .on_conflict_do_nothing()
        )

    if close_missing and root_ids:
        stats.relationships_closed += await _close_disappeared(
            session, root_ids, seen_relationship_ids
        )

    await session.flush()
    return stats


async def _upsert_relationship(
    session: AsyncSession,
    rel: ParsedRelationship,
    source_id: uuid.UUID,
    target_id: uuid.UUID,
    stats: LoadStats,
) -> uuid.UUID:
    existing = (
        (
            await session.execute(
                select(Relationship).where(
                    Relationship.source_entity_id == source_id,
                    Relationship.target_entity_id == target_id,
                    Relationship.relationship_type == rel.relationship_type,
                    Relationship.valid_from.is_not_distinct_from(rel.valid_from),
                    Relationship.superseded_at.is_(None),
                )
            )
        )
        .scalars()
        .first()
    )

    if existing is not None:
        # Zmiana daty zakończenia to nowy fakt: zamykamy stary wiersz i piszemy nowy.
        if existing.valid_to != rel.valid_to:
            existing.superseded_at = dt.datetime.now(dt.UTC)
            await session.flush()
        else:
            return existing.id

    relationship = Relationship(
        id=uuid.uuid4(),
        source_entity_id=source_id,
        target_entity_id=target_id,
        relationship_type=rel.relationship_type,
        role=rel.role,
        valid_from=rel.valid_from,
        valid_to=rel.valid_to,
        confidence=Confidence.REGISTERED,
        confidence_score=1.0,
        attributes=rel.attributes or {},
    )
    session.add(relationship)
    await session.flush()
    stats.relationships_created += 1
    return relationship.id


async def _close_disappeared(
    session: AsyncSession, root_ids: set[uuid.UUID], seen: set[uuid.UUID]
) -> int:
    """Fakty, których nie ma już w źródle, oznaczamy jako nieaktualne.

    To jest ta operacja, która daje odpowiedź „Jan Kowalski przestał być
    członkiem zarządu” nawet wtedy, gdy rejestr nie podaje daty wykreślenia.
    """
    result = await session.execute(
        update(Relationship)
        .where(
            Relationship.target_entity_id.in_(root_ids),
            Relationship.superseded_at.is_(None),
            Relationship.valid_to.is_(None),
            Relationship.id.notin_(seen) if seen else text("TRUE"),
        )
        .values(valid_to=dt.date.today(), superseded_at=dt.datetime.now(dt.UTC))
    )
    return cast(CursorResult[Any], result).rowcount or 0
