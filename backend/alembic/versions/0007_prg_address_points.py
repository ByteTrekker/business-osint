"""add prg address points

Punkty adresowe z Państwowego Rejestru Granic — dane referencyjne pod
dopasowanie współrzędnych. Świadomie osobna tabela, a nie encje: 7 mln punktów
adresowych nie jest podmiotami, z którymi ktokolwiek jest powiązany.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-31 09:38:40.352420+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "address_points",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("match_key", sa.Text(), nullable=False),
        sa.Column("city", sa.String(length=128), nullable=True),
        sa.Column("street", sa.String(length=255), nullable=True),
        sa.Column("building", sa.String(length=32), nullable=True),
        sa.Column("postal_code", sa.String(length=16), nullable=True),
        sa.Column("teryt", sa.String(length=16), nullable=True),
        sa.Column("simc", sa.String(length=16), nullable=True),
        sa.Column("ulic", sa.String(length=16), nullable=True),
        sa.Column("latitude", sa.Numeric(precision=9, scale=6), nullable=False),
        sa.Column("longitude", sa.Numeric(precision=9, scale=6), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_address_points")),
    )
    op.create_index("ix_address_points_match_key", "address_points", ["match_key"], unique=False)

    # Klucz po naszej stronie liczymy w Pythonie i trzymamy w kolumnie, żeby
    # dopasowanie było zwykłym złączeniem po równości. Alternatywa — odtworzenie
    # normalizacji w SQL-u — to druga implementacja tej samej reguły.
    op.add_column("addresses", sa.Column("match_key", sa.Text(), nullable=True))
    op.create_index("ix_addresses_match_key", "addresses", ["match_key"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_addresses_match_key", table_name="addresses")
    op.drop_column("addresses", "match_key")
    op.drop_index("ix_address_points_match_key", table_name="address_points")
    op.drop_table("address_points")
