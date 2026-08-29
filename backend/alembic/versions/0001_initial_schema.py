"""Schemat początkowy: encje, relacje bitemporalne, provenance.

Revision ID: 0001
Revises:
Create Date: 2026-08-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gin")
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")

    op.create_table(
        "entities",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("display_name", sa.Text, nullable=False),
        sa.Column("normalized_name", sa.Text, nullable=False),
        sa.Column("blocking_key", sa.Text),
        sa.Column("degree", sa.Integer, nullable=False, server_default="0"),
        sa.Column("merged_into_id", UUID, sa.ForeignKey("entities.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "entity_type IN ('company','person','address','foreign_entity','other')",
            name="entity_type_valid",
        ),
    )
    op.create_index("ix_entities_type_normalized_name", "entities", ["entity_type", "normalized_name"])
    op.create_index("ix_entities_blocking_key", "entities", ["blocking_key"])
    op.create_index("ix_entities_degree", "entities", ["degree"])
    # Wyszukiwanie rozmyte po nazwie — bez tego indeksu `%` na 1 mln wierszy to seq scan.
    op.execute(
        "CREATE INDEX ix_entities_normalized_name_trgm ON entities "
        "USING gin (normalized_name gin_trgm_ops)"
    )
    # Aktywne encje to 99% odczytów — indeks częściowy jest mniejszy i cieplejszy w cache.
    op.execute(
        "CREATE INDEX ix_entities_active ON entities (entity_type, degree DESC) "
        "WHERE merged_into_id IS NULL"
    )

    op.create_table(
        "entity_identifiers",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("entity_id", UUID, sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scheme", sa.String(32), nullable=False),
        sa.Column("value", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("scheme", "value", name="uq_entity_identifiers_scheme_value"),
    )
    op.create_index("ix_entity_identifiers_entity_id", "entity_identifiers", ["entity_id"])
    op.create_index("ix_entity_identifiers_value", "entity_identifiers", ["value"])

    op.create_table(
        "companies",
        sa.Column("entity_id", UUID, sa.ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("legal_form", sa.String(32)),
        sa.Column("krs", sa.String(10)),
        sa.Column("nip", sa.String(10)),
        sa.Column("regon", sa.String(14)),
        sa.Column("status", sa.String(32)),
        sa.Column("registered_on", sa.Date),
        sa.Column("deregistered_on", sa.Date),
        sa.Column("share_capital", sa.Numeric(18, 2)),
        sa.Column("pkd_main", sa.String(8)),
        sa.Column("attributes", JSONB, server_default="{}", nullable=False),
    )
    op.create_index("ix_companies_krs", "companies", ["krs"])
    op.create_index("ix_companies_nip", "companies", ["nip"])
    op.create_index("ix_companies_regon", "companies", ["regon"])

    op.create_table(
        "people",
        sa.Column("entity_id", UUID, sa.ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("first_names", sa.Text, nullable=False, server_default=""),
        sa.Column("last_name", sa.Text, nullable=False),
        sa.Column("former_names", JSONB, server_default="{}", nullable=False),
        sa.Column("birth_year", sa.SmallInteger),
        sa.Column("pesel_hash", sa.String(32)),
        sa.Column("attributes", JSONB, server_default="{}", nullable=False),
    )
    op.create_index("ix_people_last_name", "people", ["last_name"])
    op.create_index("ix_people_pesel_hash", "people", ["pesel_hash"])

    op.create_table(
        "addresses",
        sa.Column("entity_id", UUID, sa.ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("country", sa.String(2), nullable=False, server_default="PL"),
        sa.Column("voivodeship", sa.String(64)),
        sa.Column("city", sa.String(128)),
        sa.Column("postal_code", sa.String(16)),
        sa.Column("street", sa.String(255)),
        sa.Column("building", sa.String(32)),
        sa.Column("unit", sa.String(32)),
        sa.Column("normalized", sa.Text, nullable=False),
        sa.Column("teryt", sa.String(16)),
        sa.UniqueConstraint("normalized", name="uq_addresses_normalized"),
    )
    op.create_index("ix_addresses_city", "addresses", ["city"])

    op.create_table(
        "sources",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("base_url", sa.Text),
        sa.Column("license", sa.Text),
        sa.Column("refresh_interval_hours", sa.Integer),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("kind", "name", name="uq_sources_kind_name"),
    )

    op.create_table(
        "raw_documents",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("source_id", UUID, sa.ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("external_id", sa.String(128), nullable=False),
        sa.Column("url", sa.Text),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("payload", JSONB),
        sa.Column("storage_uri", sa.Text),
        sa.UniqueConstraint(
            "source_id", "external_id", "content_sha256", name="uq_raw_documents_identity"
        ),
    )
    op.create_index(
        "ix_raw_documents_external_id", "raw_documents", ["source_id", "external_id", "fetched_at"]
    )

    op.create_table(
        "ingestion_runs",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("source_id", UUID, sa.ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(16), nullable=False, server_default="running"),
        sa.Column("stats", JSONB, server_default="{}", nullable=False),
        sa.Column("error", sa.Text),
    )

    op.create_table(
        "relationships",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("source_entity_id", UUID, sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_entity_id", UUID, sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("relationship_type", sa.String(48), nullable=False),
        sa.Column("role", sa.Text),
        sa.Column("valid_from", sa.Date),
        sa.Column("valid_to", sa.Date),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True)),
        sa.Column("confidence", sa.String(16), nullable=False, server_default="registered"),
        sa.Column("confidence_score", sa.Numeric(3, 2), nullable=False, server_default="1.0"),
        sa.Column("attributes", JSONB, server_default="{}", nullable=False),
        sa.CheckConstraint("source_entity_id <> target_entity_id", name="no_self_loop"),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from",
            name="valid_period",
        ),
    )
    # Klucz naturalny aktywnej krawędzi — gwarantuje idempotencję ponownego importu.
    op.execute(
        "CREATE UNIQUE INDEX uq_relationships_active ON relationships "
        "(source_entity_id, target_entity_id, relationship_type, COALESCE(valid_from, '1970-01-01'::date)) "
        "WHERE superseded_at IS NULL"
    )
    # Dwa indeksy = traversal w obie strony po jednym index scanie.
    # INCLUDE pozwala zbudować krawędź bez sięgania do heapu (index-only scan).
    op.execute(
        "CREATE INDEX ix_relationships_out ON relationships "
        "(source_entity_id, relationship_type) "
        "INCLUDE (target_entity_id, valid_from, valid_to, confidence_score) "
        "WHERE superseded_at IS NULL"
    )
    op.execute(
        "CREATE INDEX ix_relationships_in ON relationships "
        "(target_entity_id, relationship_type) "
        "INCLUDE (source_entity_id, valid_from, valid_to, confidence_score) "
        "WHERE superseded_at IS NULL"
    )
    # Zapytania „stan na dzień X" po zakresie dat.
    op.create_index("ix_relationships_valid", "relationships", ["valid_from", "valid_to"])
    op.create_index("ix_relationships_type", "relationships", ["relationship_type"])

    op.create_table(
        "relationship_sources",
        sa.Column("relationship_id", UUID, sa.ForeignKey("relationships.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("raw_document_id", UUID, sa.ForeignKey("raw_documents.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("locator", sa.Text),
        sa.Column("extracted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "entity_sources",
        sa.Column("entity_id", UUID, sa.ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("raw_document_id", UUID, sa.ForeignKey("raw_documents.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("locator", sa.Text),
        sa.Column("extracted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "entity_merges",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("survivor_id", UUID, sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("merged_id", UUID, sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("score", sa.Numeric(4, 3)),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("decided_by", sa.String(64), nullable=False, server_default="auto"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("reverted_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_entity_merges_merged_id", "entity_merges", ["merged_id"])

    # Widok dwukierunkowy: traversal nie musi wiedzieć, po której stronie krawędzi
    # stoi węzeł. Każda gałąź UNION ALL trafia we własny indeks częściowy.
    op.execute(
        """
        CREATE VIEW graph_edges AS
        SELECT id AS relationship_id, source_entity_id AS from_id, target_entity_id AS to_id,
               'out'::text AS direction, relationship_type, role, valid_from, valid_to,
               recorded_at, superseded_at, confidence, confidence_score, attributes
        FROM relationships
        UNION ALL
        SELECT id, target_entity_id, source_entity_id,
               'in'::text, relationship_type, role, valid_from, valid_to,
               recorded_at, superseded_at, confidence, confidence_score, attributes
        FROM relationships
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS graph_edges")
    for table in (
        "entity_merges", "entity_sources", "relationship_sources", "relationships",
        "ingestion_runs", "raw_documents", "sources", "addresses", "people",
        "companies", "entity_identifiers", "entities",
    ):
        op.drop_table(table)
