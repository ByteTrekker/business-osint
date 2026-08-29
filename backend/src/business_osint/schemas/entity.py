"""Kontrakty API dla profili podmiotów."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, Field


class IdentifierOut(BaseModel):
    scheme: str
    value: str


class SearchHitOut(BaseModel):
    id: uuid.UUID
    type: str
    name: str
    subtitle: str | None = None
    score: float
    degree: int


class SearchResultOut(BaseModel):
    query: str
    hits: list[SearchHitOut]


class ProvenanceOut(BaseModel):
    """„Skąd to wiemy” — obowiązkowe przy każdym fakcie w produkcie OSINT."""

    source: str
    external_id: str | None = None
    url: str | None = None
    fetched_at: dt.datetime | None = None
    locator: str | None = Field(default=None, description="Miejsce w dokumencie źródłowym")


class RelationshipOut(BaseModel):
    id: uuid.UUID
    direction: str = Field(description="out = podmiot jest źródłem krawędzi")
    type: str
    role: str | None = None
    other_id: uuid.UUID
    other_type: str
    other_name: str
    valid_from: dt.date | None = None
    valid_to: dt.date | None = None
    confidence: str
    attributes: dict = Field(default_factory=dict)
    provenance: list[ProvenanceOut] = Field(default_factory=list)


class EntityProfileOut(BaseModel):
    id: uuid.UUID
    type: str
    name: str
    degree: int
    identifiers: list[IdentifierOut] = Field(default_factory=list)
    company: dict | None = None
    person: dict | None = None
    address: dict | None = None
    updated_at: dt.datetime | None = None
