"""Model danych.

Kluczowe decyzje (szerzej w docs/adr/):

* **Hybryda entity + tabele szczegółów.** ``entities`` to jedyna tabela węzłów
  grafu — dzięki temu ``relationships`` ma dwa zwykłe FK i traversal jest jednym
  zapytaniem. Atrybuty specyficzne dla typu leżą w ``companies`` / ``people`` /
  ``addresses`` (1:1, PK = FK), więc nie tracimy typów ani constraintów.
* **Bitemporalność.** ``valid_from``/``valid_to`` = czas rzeczywisty (kiedy fakt
  obowiązywał). ``recorded_at``/``superseded_at`` = czas systemowy (kiedy my się
  o nim dowiedzieliśmy). Nic nie kasujemy — wersjonujemy.
* **Provenance.** Każda krawędź i każdy atrybut ma powiązanie z ``source_records``,
  a każdy ``source_record`` wskazuje na niezmienny ``raw_documents`` (surowa odpowiedź
  rejestru + sha256). Zawsze da się odpowiedzieć „skąd to wiemy”.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from business_osint.db.base import Base, json_col, utc_now, uuid_pk
from business_osint.domain.enums import (
    Confidence,
    EntityType,
    IdentifierScheme,
    RelationshipType,
    SourceKind,
)


class Entity(Base):
    """Węzeł grafu. Wszystko, co można kliknąć, jest encją."""

    __tablename__ = "entities"

    id: Mapped[uuid_pk]
    entity_type: Mapped[EntityType] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    #: Nazwa po normalizacji — po niej szukamy i deduplikujemy.
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False)
    #: Klucz blokujący do entity resolution (patrz domain/normalization.py).
    blocking_key: Mapped[str | None] = mapped_column(Text)
    #: Zdenormalizowany stopień węzła — czyta go graph API, żeby wykryć huby
    #: bez liczenia COUNT(*) na relationships przy każdym rozwinięciu.
    degree: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    #: Encja scalona (deduplikacja) wskazuje na ocalałą; NULL = encja aktywna.
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="SET NULL")
    )
    created_at: Mapped[utc_now]
    updated_at: Mapped[utc_now]

    __table_args__ = (
        CheckConstraint(
            "entity_type IN ('company','person','address','foreign_entity','other')",
            name="entity_type_valid",
        ),
        Index("ix_entities_type_normalized_name", "entity_type", "normalized_name"),
        Index("ix_entities_blocking_key", "blocking_key"),
        Index("ix_entities_degree", "degree"),
        # Wyszukiwanie rozmyte po nazwie — bez tego operator `%` to seq scan.
        Index(
            "ix_entities_normalized_name_trgm",
            "normalized_name",
            postgresql_using="gin",
            postgresql_ops={"normalized_name": "gin_trgm_ops"},
        ),
        # Aktywne encje to 99% odczytow — indeks czesciowy jest mniejszy i cieplejszy.
        Index(
            "ix_entities_active",
            "entity_type",
            text("degree DESC"),
            postgresql_where=text("merged_into_id IS NULL"),
        ),
    )


class EntityIdentifier(Base):
    """Twarde identyfikatory encji — kręgosłup entity resolution.

    UNIQUE(scheme, value) sprawia, że ponowny import KRS nie tworzy duplikatu,
    tylko trafia w istniejącą encję.
    """

    __tablename__ = "entity_identifiers"

    id: Mapped[uuid_pk]
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    scheme: Mapped[IdentifierScheme] = mapped_column(String(32), nullable=False)
    value: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[utc_now]

    __table_args__ = (
        UniqueConstraint("scheme", "value", name="uq_entity_identifiers_scheme_value"),
        Index("ix_entity_identifiers_entity_id", "entity_id"),
        Index("ix_entity_identifiers_value", "value"),
    )


class Company(Base):
    """Atrybuty podmiotu gospodarczego (1:1 z ``entities``)."""

    __tablename__ = "companies"

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True
    )
    legal_form: Mapped[str | None] = mapped_column(String(32))
    krs: Mapped[str | None] = mapped_column(String(10))
    nip: Mapped[str | None] = mapped_column(String(10))
    regon: Mapped[str | None] = mapped_column(String(14))
    status: Mapped[str | None] = mapped_column(String(32))  # active / liquidation / deleted
    registered_on: Mapped[dt.date | None] = mapped_column(Date)
    deregistered_on: Mapped[dt.date | None] = mapped_column(Date)
    share_capital: Mapped[float | None] = mapped_column(Numeric(18, 2))
    pkd_main: Mapped[str | None] = mapped_column(String(8))
    attributes: Mapped[json_col]

    entity: Mapped[Entity] = relationship(Entity, lazy="joined")

    __table_args__ = (
        Index("ix_companies_krs", "krs"),
        Index("ix_companies_nip", "nip"),
        Index("ix_companies_regon", "regon"),
    )


class Person(Base):
    """Osoba fizyczna. Świadomie minimalny zakres danych osobowych."""

    __tablename__ = "people"

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True
    )
    first_names: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    last_name: Mapped[str] = mapped_column(Text, nullable=False)
    #: Poprzednie nazwiska (zmiana nazwiska po ślubie itd.) — tekst + źródło.
    former_names: Mapped[json_col]
    birth_year: Mapped[int | None] = mapped_column(SmallInteger)
    #: Nigdy nie trzymamy PESEL jawnie — tylko peppered hash.
    pesel_hash: Mapped[str | None] = mapped_column(String(32))
    attributes: Mapped[json_col]

    entity: Mapped[Entity] = relationship(Entity, lazy="joined")

    __table_args__ = (
        Index("ix_people_last_name", "last_name"),
        Index("ix_people_pesel_hash", "pesel_hash"),
    )


class Address(Base):
    """Adres jako pełnoprawny węzeł grafu — pozwala pytać „kto jeszcze tu siedzi”."""

    __tablename__ = "addresses"

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True
    )
    country: Mapped[str] = mapped_column(String(2), nullable=False, server_default="PL")
    voivodeship: Mapped[str | None] = mapped_column(String(64))
    city: Mapped[str | None] = mapped_column(String(128))
    postal_code: Mapped[str | None] = mapped_column(String(16))
    street: Mapped[str | None] = mapped_column(String(255))
    building: Mapped[str | None] = mapped_column(String(32))
    unit: Mapped[str | None] = mapped_column(String(32))
    #: Kanoniczny zapis adresu — po nim łączymy podmioty pod tym samym adresem.
    normalized: Mapped[str] = mapped_column(Text, nullable=False)
    #: TERYT/ULIC, jeśli uda się dopasować do rejestru adresowego.
    teryt: Mapped[str | None] = mapped_column(String(16))

    entity: Mapped[Entity] = relationship(Entity, lazy="joined")

    __table_args__ = (
        UniqueConstraint("normalized", name="uq_addresses_normalized"),
        Index("ix_addresses_city", "city"),
    )


class Source(Base):
    """Rejestr / dostawca danych (KRS, CRBR, CEIDG...)."""

    __tablename__ = "sources"

    id: Mapped[uuid_pk]
    kind: Mapped[SourceKind] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[str | None] = mapped_column(Text)
    license: Mapped[str | None] = mapped_column(Text)
    #: Częstotliwość odświeżania w godzinach — używane przez scheduler ETL.
    refresh_interval_hours: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[utc_now]

    __table_args__ = (UniqueConstraint("kind", "name", name="uq_sources_kind_name"),)


class RawDocument(Base):
    """Niezmienna kopia odpowiedzi rejestru. Fundament reprodukowalności.

    Duże payloady docelowo lądują w S3/MinIO (``storage_uri``), w bazie zostaje
    hash i metadane. Na MVP trzymamy JSONB — prościej i wystarcza.
    """

    __tablename__ = "raw_documents"

    id: Mapped[uuid_pk]
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False
    )
    #: Identyfikator w systemie źródłowym (np. numer KRS).
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    storage_uri: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        # Ten sam dokument o tej samej treści zapisujemy raz — deduplikacja snapshotów.
        UniqueConstraint(
            "source_id", "external_id", "content_sha256", name="uq_raw_documents_identity"
        ),
        Index("ix_raw_documents_external_id", "source_id", "external_id", "fetched_at"),
    )


class Relationship(Base):
    """Krawędź grafu — bitemporalna i z provenance.

    Nigdy nie robimy UPDATE na istniejącym wierszu przy zmianie faktu:
    stary wiersz dostaje ``superseded_at``, nowy wchodzi obok. Dzięki temu
    „co wiedzieliśmy 3 miesiące temu” jest zwykłym zapytaniem SELECT.
    """

    __tablename__ = "relationships"

    id: Mapped[uuid_pk]
    source_entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    target_entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    relationship_type: Mapped[RelationshipType] = mapped_column(String(48), nullable=False)
    #: Dosłowna rola ze źródła, np. "PREZES ZARZĄDU" — nie mapujemy jej na enum,
    #: bo rejestry używają dziesiątek wariantów i chcemy zachować oryginał.
    role: Mapped[str | None] = mapped_column(Text)

    # --- czas rzeczywisty (kiedy fakt obowiązywał) ---
    valid_from: Mapped[dt.date | None] = mapped_column(Date)
    valid_to: Mapped[dt.date | None] = mapped_column(Date)

    # --- czas systemowy (kiedy my o tym wiedzieliśmy) ---
    recorded_at: Mapped[utc_now]
    superseded_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    confidence: Mapped[Confidence] = mapped_column(
        String(16), nullable=False, server_default=Confidence.REGISTERED.value
    )
    confidence_score: Mapped[float] = mapped_column(
        Numeric(3, 2), nullable=False, server_default="1.0"
    )
    attributes: Mapped[json_col]  # np. {"share_percent": 51, "shares": 5100}

    __table_args__ = (
        CheckConstraint("source_entity_id <> target_entity_id", name="no_self_loop"),
        CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from", name="valid_period"
        ),
        # Nie duplikujemy tej samej aktywnej krawędzi z tego samego okresu.
        # COALESCE, bo NULL != NULL — bez tego dwa wiersze z valid_from IS NULL
        # przeszłyby przez unique index.
        Index(
            "uq_relationships_active",
            "source_entity_id",
            "target_entity_id",
            "relationship_type",
            text("COALESCE(valid_from, '1970-01-01'::date)"),
            unique=True,
            postgresql_where=text("superseded_at IS NULL"),
        ),
        # Dwa indeksy pokrywające traversal w obie strony. INCLUDE daje index-only
        # scan — krawędź da się zbudować bez dotykania heapu.
        Index(
            "ix_relationships_out",
            "source_entity_id",
            "relationship_type",
            postgresql_include=["target_entity_id", "valid_from", "valid_to", "confidence_score"],
            postgresql_where=text("superseded_at IS NULL"),
        ),
        Index(
            "ix_relationships_in",
            "target_entity_id",
            "relationship_type",
            postgresql_include=["source_entity_id", "valid_from", "valid_to", "confidence_score"],
            postgresql_where=text("superseded_at IS NULL"),
        ),
        Index("ix_relationships_valid", "valid_from", "valid_to"),
        Index("ix_relationships_type", "relationship_type"),
    )


class RelationshipSource(Base):
    """M:N krawędź -> dokument źródłowy. Jedna relacja może mieć wiele potwierdzeń."""

    __tablename__ = "relationship_sources"

    relationship_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("relationships.id", ondelete="CASCADE"), primary_key=True
    )
    raw_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("raw_documents.id", ondelete="RESTRICT"), primary_key=True
    )
    #: Wskaźnik na konkretne miejsce w dokumencie (JSON Pointer / numer działu KRS).
    locator: Mapped[str | None] = mapped_column(Text)
    extracted_at: Mapped[utc_now]


class EntitySource(Base):
    """M:N encja -> dokument źródłowy (dla atrybutów, nie relacji)."""

    __tablename__ = "entity_sources"

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True
    )
    raw_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("raw_documents.id", ondelete="RESTRICT"), primary_key=True
    )
    locator: Mapped[str | None] = mapped_column(Text)
    extracted_at: Mapped[utc_now]


class EntityMerge(Base):
    """Dziennik scaleń przy deduplikacji — odwracalny z założenia."""

    __tablename__ = "entity_merges"

    id: Mapped[uuid_pk]
    survivor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    merged_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    score: Mapped[float | None] = mapped_column(Numeric(4, 3))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    decided_by: Mapped[str] = mapped_column(String(64), nullable=False, server_default="auto")
    created_at: Mapped[utc_now]
    reverted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_entity_merges_merged_id", "merged_id"),)


class FinancialReport(Base):
    """Dane finansowe podmiotu za okres sprawozdawczy.

    Osobna tabela, a nie JSONB w ``companies``, bo finanse są z natury
    szeregiem czasowym i będą filtrowane („spółki o przychodzie > 100 mln").
    Wartości trzymamy w groszach jako NUMERIC — kwoty podatkowe nie znoszą
    zmiennoprzecinkowych zaokrągleń.
    """

    __tablename__ = "financial_reports"

    id: Mapped[uuid_pk]
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    period_from: Mapped[dt.date] = mapped_column(Date, nullable=False)
    period_to: Mapped[dt.date] = mapped_column(Date, nullable=False)
    revenue: Mapped[float | None] = mapped_column(Numeric(20, 2))
    costs: Mapped[float | None] = mapped_column(Numeric(20, 2))
    income: Mapped[float | None] = mapped_column(Numeric(20, 2))
    loss: Mapped[float | None] = mapped_column(Numeric(20, 2))
    tax_base: Mapped[float | None] = mapped_column(Numeric(20, 2))
    tax_due: Mapped[float | None] = mapped_column(Numeric(20, 2))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="PLN")
    #: Skąd pochodzi ten wiersz — bez tego nie da się rozstrzygnąć rozbieżności
    #: między zeznaniem CIT a sprawozdaniem finansowym.
    raw_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("raw_documents.id", ondelete="SET NULL")
    )
    attributes: Mapped[json_col]
    recorded_at: Mapped[utc_now]

    __table_args__ = (
        UniqueConstraint(
            "entity_id", "period_from", "period_to", name="uq_financial_reports_period"
        ),
        CheckConstraint("period_to >= period_from", name="period_valid"),
        Index("ix_financial_reports_entity", "entity_id", "period_to"),
        Index("ix_financial_reports_revenue", "revenue"),
    )


class IngestionTask(Base):
    """Jednostka pracy pobierania — wznawialna i idempotentna.

    Kolejka leży w Postgresie, a nie w Redisie, z dwóch powodów: nie dokłada
    infrastruktury na MVP i jest w tej samej transakcji, co zapis wyniku, więc
    zadanie nie może zniknąć między pobraniem a zapisem.

    To także granica G1 z ADR-0005: crawler w innym języku potrzebuje wyłącznie
    tej tabeli i ``raw_documents`` — żadnego wspólnego kodu z API.
    """

    __tablename__ = "ingestion_tasks"

    id: Mapped[uuid_pk]
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id", ondelete="CASCADE"), nullable=False
    )
    #: Identyfikator w systemie źródłowym (numer KRS, NIP, data paczki).
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    #: Rodzaj pracy, np. "odpis_pelny" albo "odpis_aktualny".
    task_type: Mapped[str] = mapped_column(String(48), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    #: Wyższa wartość = pilniejsze. Spółki z ruchem odświeżamy częściej.
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    #: Backoff między przebiegami: zadanie nie wraca do puli przed tym czasem.
    scheduled_for: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    locked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(64))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[utc_now]
    updated_at: Mapped[utc_now]

    __table_args__ = (
        # Ponowne zakolejkowanie tego samego podmiotu nie tworzy duplikatu.
        UniqueConstraint(
            "source_id", "external_id", "task_type", name="uq_ingestion_tasks_identity"
        ),
        CheckConstraint(
            "status IN ('pending','running','done','failed','skipped')",
            name="status_valid",
        ),
        # Indeks pobierania partii: tylko zadania czekające, w kolejności priorytetu.
        Index(
            "ix_ingestion_tasks_queue",
            "source_id",
            text("priority DESC"),
            "scheduled_for",
            postgresql_where=text("status = 'pending'"),
        ),
    )


class IngestionRun(Base):
    """Jeden przebieg ETL. Bez tego nie da się debugować „skąd ten śmieć w bazie”."""

    __tablename__ = "ingestion_runs"

    id: Mapped[uuid_pk]
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False
    )
    started_at: Mapped[utc_now]
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="running")
    stats: Mapped[json_col]
    error: Mapped[str | None] = mapped_column(Text)
