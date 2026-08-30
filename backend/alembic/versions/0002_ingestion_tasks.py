"""Wznawialna kolejka zadań pobierania.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "ingestion_tasks",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "source_id", UUID, sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("external_id", sa.String(128), nullable=False),
        sa.Column("task_type", sa.String(48), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("priority", sa.Integer, nullable=False, server_default="0"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "scheduled_for",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("locked_at", sa.DateTime(timezone=True)),
        sa.Column("locked_by", sa.String(64)),
        sa.Column("last_error", sa.Text),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "source_id", "external_id", "task_type", name="uq_ingestion_tasks_identity"
        ),
        sa.CheckConstraint(
            "status IN ('pending','running','done','failed','skipped')",
            name="status_valid",
        ),
    )
    # Indeks częściowy pod pobieranie partii: tylko zadania czekające.
    # Bez `WHERE status = 'pending'` indeks rósłby razem z historią wykonanych zadań.
    op.execute(
        "CREATE INDEX ix_ingestion_tasks_queue ON ingestion_tasks "
        "(source_id, priority DESC, scheduled_for) WHERE status = 'pending'"
    )


def downgrade() -> None:
    op.drop_table("ingestion_tasks")
