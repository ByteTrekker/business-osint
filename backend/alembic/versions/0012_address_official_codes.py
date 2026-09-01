"""carry official TERYT/SIMC/ULIC codes on addresses, not only on PRG points

Revision ID: 0012
Revises: 0011

`address_points` (PRG) ma te kody od migracji 0007, ale `addresses` — czyli
adresy podmiotów — miały wyłącznie `teryt`, i to uzupełniany **dopasowaniem**
po znormalizowanym napisie. Dopasowanie nie powiodło się dla 475 707 adresów.

Pojedynczy wpis CEIDG (`/firma`) podaje `terc`, `simc` i `ulic` **wprost
z rejestru**, bez zgadywania. Pobieramy go i tak — dla pola `spolki` — więc
te kody już leżą w `raw_documents` i wystarczy je przepisać.

Kod urzędowy jest twardszym identyfikatorem adresu niż napis: dwie ulice
o tej samej nazwie w tym samym mieście mają różny ULIC, a normalizacja nazwy
ich nie rozróżni.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("addresses", sa.Column("simc", sa.String(length=16), nullable=True))
    op.add_column("addresses", sa.Column("ulic", sa.String(length=16), nullable=True))
    # Po SIMC szukamy „kto jeszcze jest w tej miejscowości" — to jest pytanie
    # o tej samej naturze co dzisiejsze „kto jeszcze jest pod tym adresem".
    op.create_index("ix_addresses_simc", "addresses", ["simc"])


def downgrade() -> None:
    op.drop_index("ix_addresses_simc", table_name="addresses")
    op.drop_column("addresses", "ulic")
    op.drop_column("addresses", "simc")
