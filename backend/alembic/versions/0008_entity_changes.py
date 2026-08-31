"""record attribute changes that would otherwise be overwritten

Revision ID: 0008
Revises: 0007

Dziennik zmian podmiotu — pod monitoring i alerty.

Zakres jest **celowo wąski**: rejestrujemy wyłącznie te pola, które import
nadpisuje w miejscu. Relacje są bitemporalne (`recorded_at`, `superseded_at`),
więc ich historia jest odtwarzalna z samej tabeli i dublowanie jej w dzienniku
podwoiłoby zapis przy imporcie 3,5 mln krawędzi, nic nie wnosząc.

Nadpisywane w miejscu są: status działalności, forma prawna, kapitał zakładowy
i nazwa. Tam każdy import bez tego dziennika kasuje poprzednią wartość
bezpowrotnie — i to jest jedyny powód, dla którego ta zmiana jest pilna.

Mechanizmem są **wyzwalacze bazy, nie kod aplikacji**. Do tych tabel pisze
kilka niezależnych ścieżek: ORM przez `EntityResolver`, zbiorczy SQL importu
CEIDG i wzbogacanie z KRS. Wpięcie się w każdą z nich osobno oznaczałoby, że
następna dopisana ścieżka po cichu przestanie logować. Wyzwalacza nie da się
ominąć.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "entity_changes",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("entity_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("field", sa.String(length=32), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["entities.id"],
            name=op.f("fk_entity_changes_entity_id_entities"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entity_changes")),
    )
    op.create_index(
        "ix_entity_changes_entity", "entity_changes", ["entity_id", "observed_at"], unique=False
    )
    op.create_index("ix_entity_changes_observed", "entity_changes", ["observed_at"], unique=False)

    # `IS DISTINCT FROM` zamiast `<>`: porównanie z NULL-em przez `<>` daje NULL,
    # czyli fałsz — a przejście z „brak danych" na wartość jest właśnie tą zmianą,
    # o której chcemy wiedzieć.
    op.execute("""
        CREATE OR REPLACE FUNCTION zapisz_zmiane_firmy() RETURNS trigger AS $$
        BEGIN
            IF NEW.status IS DISTINCT FROM OLD.status THEN
                INSERT INTO entity_changes (entity_id, field, old_value, new_value)
                VALUES (NEW.entity_id, 'status', OLD.status, NEW.status);
            END IF;
            IF NEW.legal_form IS DISTINCT FROM OLD.legal_form THEN
                INSERT INTO entity_changes (entity_id, field, old_value, new_value)
                VALUES (NEW.entity_id, 'legal_form', OLD.legal_form, NEW.legal_form);
            END IF;
            IF NEW.share_capital IS DISTINCT FROM OLD.share_capital THEN
                INSERT INTO entity_changes (entity_id, field, old_value, new_value)
                VALUES (NEW.entity_id, 'share_capital',
                        OLD.share_capital::text, NEW.share_capital::text);
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER trg_zmiana_firmy
        AFTER UPDATE ON companies
        FOR EACH ROW EXECUTE FUNCTION zapisz_zmiane_firmy();
    """)

    # Nazwa i scalenie encji. Scalenie nie jest zmianą faktu o podmiocie, ale
    # jest zmianą tego, czym podmiot dla nas jest — i obserwujący ma prawo
    # wiedzieć, że śledzona przez niego encja przestała być osobnym bytem.
    op.execute("""
        CREATE OR REPLACE FUNCTION zapisz_zmiane_encji() RETURNS trigger AS $$
        BEGIN
            IF NEW.display_name IS DISTINCT FROM OLD.display_name THEN
                INSERT INTO entity_changes (entity_id, field, old_value, new_value)
                VALUES (NEW.id, 'display_name', OLD.display_name, NEW.display_name);
            END IF;
            IF NEW.merged_into_id IS DISTINCT FROM OLD.merged_into_id
               AND NEW.merged_into_id IS NOT NULL THEN
                INSERT INTO entity_changes (entity_id, field, old_value, new_value)
                VALUES (NEW.id, 'merged_into', NULL, NEW.merged_into_id::text);
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER trg_zmiana_encji
        AFTER UPDATE ON entities
        FOR EACH ROW EXECUTE FUNCTION zapisz_zmiane_encji();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_zmiana_encji ON entities")
    op.execute("DROP TRIGGER IF EXISTS trg_zmiana_firmy ON companies")
    op.execute("DROP FUNCTION IF EXISTS zapisz_zmiane_encji()")
    op.execute("DROP FUNCTION IF EXISTS zapisz_zmiane_firmy()")
    op.drop_index("ix_entity_changes_observed", table_name="entity_changes")
    op.drop_index("ix_entity_changes_entity", table_name="entity_changes")
    op.drop_table("entity_changes")
