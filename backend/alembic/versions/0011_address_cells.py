"""precompute the map grid instead of aggregating 2.4M addresses per pan

Revision ID: 0011
Revises: 0010

Mapa zbiorcza liczona w locie kosztowała 1,8 s na jedno przesunięcie widoku.
Powód widać w planie: złączenie z `entities` po stopień węzła wymusza skan
9,5 mln wierszy, a grupowanie po wyrażeniu `round(latitude/:cell)` jest dla
planisty nieprzejrzyste — szacował 356 tys. grup, faktycznych było 723, więc
wybierał sortowanie z zrzutem na dysk zamiast agregacji mieszającej.

Kluczowa obserwacja: **ta agregacja nie zależy od zapytania**. Siatka jest
stała, a dane zmieniają się wyłącznie przy imporcie. Liczenie jej przy każdym
przesunięciu myszy to powtarzanie tej samej pracy.

Dlatego trzymamy jeden poziom — komórki 0,005 stopnia, 297 246 wierszy — a
poziomy zgrubniejsze **zwijamy z niego w locie**. Zwijanie jest dokładne, bo
wszystkie boki komórek z `SIATKA` są całkowitymi wielokrotnościami 0,005,
a binowanie idzie przez `floor` po indeksach całkowitych: `floor(floor(x/f)/k)`
równa się `floor(x/(f*k))` dla całkowitego `k`. Przy `round` ta równość nie
zachodzi — stąd `floor`, mimo że komórka jest wtedy opisana rogiem, nie środkiem.

Pozycję znacznika bierzemy ze **środka masy**, nie z rogu komórki: sumy
współrzędnych są addytywne, więc zwijają się razem z licznikami, a skupisko
ląduje tam, gdzie faktycznie stoją adresy, zamiast na sztucznym punkcie siatki.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels = None
depends_on = None

#: Bok komórki bazowej. Musi być zgodny z `repositories.map.SIATKA_BAZOWA` —
#: rozjazd tych dwóch wartości przesunąłby całą mapę.
BAZA = "0.005"


def upgrade() -> None:
    op.create_table(
        "address_cells",
        sa.Column("lat_idx", sa.Integer(), nullable=False),
        sa.Column("lon_idx", sa.Integer(), nullable=False),
        sa.Column("addresses", sa.Integer(), nullable=False),
        sa.Column("entities", sa.BigInteger(), nullable=False),
        sa.Column("lat_sum", sa.Numeric(), nullable=False),
        sa.Column("lon_sum", sa.Numeric(), nullable=False),
        sa.Column(
            "refreshed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("lat_idx", "lon_idx", name=op.f("pk_address_cells")),
    )

    # Kolejność kolumn odpowiada zapytaniu: prostokąt widoku tnie najpierw po
    # szerokości, potem po długości.
    op.create_index("ix_address_cells_bbox", "address_cells", ["lat_idx", "lon_idx"])

    # Przeliczenie siatki jako funkcja bazy, nie kod aplikacji — z tego samego
    # powodu co wyzwalacze z migracji 0008: do adresów pisze kilka niezależnych
    # ścieżek (import CEIDG, dopasowanie PRG, scalanie adresów) i każda musi
    # móc odświeżyć siatkę jednym wywołaniem, bez importowania Pythona.
    op.execute(f"""
        CREATE OR REPLACE FUNCTION odswiez_siatke_adresow() RETURNS bigint AS $$
        DECLARE
            wstawione bigint;
        BEGIN
            TRUNCATE address_cells;
            INSERT INTO address_cells
                (lat_idx, lon_idx, addresses, entities, lat_sum, lon_sum)
            SELECT floor(a.latitude / {BAZA})::int,
                   floor(a.longitude / {BAZA})::int,
                   count(*),
                   COALESCE(sum(e.degree), 0),
                   sum(a.latitude),
                   sum(a.longitude)
            FROM addresses a
            JOIN entities e ON e.id = a.entity_id AND e.merged_into_id IS NULL
            WHERE a.latitude IS NOT NULL AND a.longitude IS NOT NULL
            GROUP BY 1, 2;
            GET DIAGNOSTICS wstawione = ROW_COUNT;
            ANALYZE address_cells;
            RETURN wstawione;
        END;
        $$ LANGUAGE plpgsql;
    """)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS odswiez_siatke_adresow()")
    op.drop_index("ix_address_cells_bbox", table_name="address_cells")
    op.drop_table("address_cells")
