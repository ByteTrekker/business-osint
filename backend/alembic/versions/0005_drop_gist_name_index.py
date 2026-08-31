"""drop redundant gist trigram index on entities.normalized_name

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Indeks powstał pod wyszukiwanie KNN (`<->`), którego nie używamy: zmierzone
    # 2,9 s przy 9,5 mln encji zdecydowało o etapowej wyszukiwarce. Został 2,1 GB
    # martwego indeksu, który dodatkowo psuł plany — planer sięgał po niego przy
    # `normalized_name = 'orlen'` i zamieniał 0,2 ms na 555 ms.
    # Dopasowanie rozmyte (operator `%`) obsługuje indeks GIN i zostaje.
    op.drop_index("ix_entities_normalized_name_gist", table_name="entities")


def downgrade() -> None:
    op.create_index(
        "ix_entities_normalized_name_gist",
        "entities",
        ["normalized_name"],
        postgresql_using="gist",
        postgresql_ops={"normalized_name": "gist_trgm_ops"},
    )
