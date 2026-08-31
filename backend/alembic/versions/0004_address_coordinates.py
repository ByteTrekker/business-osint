"""Współrzędne adresów z geokodowania.

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Indeksy wyszukiwania: prefiksowy btree (0,3 ms) i GiST pod tryb rozmyty.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_entities_name_prefix "
        "ON entities (normalized_name text_pattern_ops) INCLUDE (entity_type, degree)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_entities_normalized_name_gist "
        "ON entities USING gist (normalized_name gist_trgm_ops)"
    )
    op.add_column("addresses", sa.Column("latitude", sa.Numeric(9, 6)))
    op.add_column("addresses", sa.Column("longitude", sa.Numeric(9, 6)))
    op.add_column("addresses", sa.Column("geocoded_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    for column in ("geocoded_at", "longitude", "latitude"):
        op.drop_column("addresses", column)
    op.execute("DROP INDEX IF EXISTS ix_entities_normalized_name_gist")
    op.execute("DROP INDEX IF EXISTS ix_entities_name_prefix")
