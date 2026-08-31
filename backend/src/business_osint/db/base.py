"""Deklaratywna baza SQLAlchemy 2.0 + wspólne typy kolumn."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Any

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, mapped_column

# Jawna konwencja nazw — bez niej Alembic generuje losowe nazwy constraintów
# i migracje przestają być odwracalne.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

uuid_pk = Annotated[
    uuid.UUID,
    mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
]
utc_now = Annotated[
    dt.datetime,
    mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False),
]
json_col = Annotated[dict[str, Any], mapped_column(JSONB, server_default="{}", nullable=False)]


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
