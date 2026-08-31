"""add voivodeship to address points

Revision ID: 0009
Revises: 0008

Nazwa miejscowości nie identyfikuje miejsca. „Zawada", „Buczków" i „Lubień"
istnieją w kilku województwach naraz, a dopasowanie punktu adresowego wyłącznie
po nazwie, ulicy i numerze przypisało 7 459 adresom współrzędne oddalone
o kilkaset kilometrów — z jednego tylko województwa wczytanego na próbę.

Województwo wyliczamy z TERYT gminy przy wczytaniu i trzymamy w kolumnie, żeby
dopasowanie mogło go użyć jako warunku rozstrzygającego.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("address_points", sa.Column("voivodeship", sa.String(length=64), nullable=True))
    # Dopasowanie pyta o klucz **razem** z województwem, więc indeks musi objąć
    # oba pola — sam klucz zostawiałby filtrowanie po województwie na heapie.
    op.create_index(
        "ix_address_points_match", "address_points", ["match_key", "voivodeship"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_address_points_match", table_name="address_points")
    op.drop_column("address_points", "voivodeship")
