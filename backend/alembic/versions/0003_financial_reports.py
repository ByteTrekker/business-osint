"""Dane finansowe podmiotów.

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "financial_reports",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "entity_id", UUID, sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("period_from", sa.Date, nullable=False),
        sa.Column("period_to", sa.Date, nullable=False),
        sa.Column("revenue", sa.Numeric(20, 2)),
        sa.Column("costs", sa.Numeric(20, 2)),
        sa.Column("income", sa.Numeric(20, 2)),
        sa.Column("loss", sa.Numeric(20, 2)),
        sa.Column("tax_base", sa.Numeric(20, 2)),
        sa.Column("tax_due", sa.Numeric(20, 2)),
        sa.Column("currency", sa.String(3), nullable=False, server_default="PLN"),
        sa.Column("raw_document_id", UUID, sa.ForeignKey("raw_documents.id", ondelete="SET NULL")),
        sa.Column("attributes", postgresql.JSONB, server_default="{}", nullable=False),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "entity_id", "period_from", "period_to", name="uq_financial_reports_period"
        ),
        sa.CheckConstraint("period_to >= period_from", name="period_valid"),
    )
    op.create_index("ix_financial_reports_entity", "financial_reports", ["entity_id", "period_to"])
    op.create_index("ix_financial_reports_revenue", "financial_reports", ["revenue"])


def downgrade() -> None:
    op.drop_table("financial_reports")
