"""add a full-text index on entities.normalized_name

Revision ID: 0006
Revises: 0005
"""

from __future__ import annotations

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Konfiguracja `simple`, nie `polish` — tej drugiej PostgreSQL nie ma, a i tak
    # byłaby niewłaściwa: nazwy firm nie są językiem naturalnym i sprowadzanie
    # „POLSKIE" do rdzenia zlepiałoby nazwy, które są odrębnymi znakami towarowymi.
    # `simple` dzieli po prostu na słowa, i o to tu chodzi.
    #
    # Indeks jest wyrażeniowy, a nie na kolumnie `tsvector`. Kolumna oznaczałaby
    # przepisanie 9,5 mln wierszy i stałe utrzymywanie jej w spójności; wyrażenie
    # kosztuje tylko przy zapisie do indeksu.
    op.execute(
        "CREATE INDEX ix_entities_name_fts ON entities "
        "USING gin (to_tsvector('simple', normalized_name))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX ix_entities_name_fts")
