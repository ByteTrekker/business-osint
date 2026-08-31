"""index address coordinates for map queries

Revision ID: 0010
Revises: 0009

Mapa zbiorcza odpytuje bazę przy każdym przesunięciu i przybliżeniu, więc
zapytanie musi kosztować milisekundy, nie setki. Bez indeksu agregacja po
siatce dla obszaru Warszawy przemiatała 2,4 mln wierszy i trwała 134 ms.

Indeks jest **częściowy** — obejmuje wyłącznie adresy ze współrzędnymi.
Po imporcie PRG ma je 1,95 mln z 2,42 mln, więc warunek odcina co piąty wiersz;
przy adresach bez współrzędnych nie ma czego szukać na mapie.
"""

from __future__ import annotations

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_addresses_coordinates",
        "addresses",
        ["latitude", "longitude"],
        unique=False,
        postgresql_where="latitude IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_index("ix_addresses_coordinates", table_name="addresses")
