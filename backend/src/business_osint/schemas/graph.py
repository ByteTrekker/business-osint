"""Kontrakty API dla grafu. Format node/edge jest gotowy pod Cytoscape.js."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from pydantic import BaseModel, Field


class NodeOut(BaseModel):
    id: uuid.UUID
    type: str = Field(description="company | person | address | foreign_entity | other")
    label: str
    degree: int = Field(description="Liczba wszystkich powiązań podmiotu w bazie")
    depth: int = Field(description="Odległość od węzła startowego")
    expandable: bool = Field(
        description="False, gdy węzeł jest hubem i nie został rozwinięty automatycznie"
    )


class EdgeOut(BaseModel):
    id: uuid.UUID
    source: uuid.UUID
    target: uuid.UUID
    type: str
    role: str | None = None
    valid_from: dt.date | None = None
    valid_to: dt.date | None = None
    current: bool
    confidence: str
    attributes: dict[str, Any] = Field(default_factory=dict)


class GraphMeta(BaseModel):
    root_id: uuid.UUID
    depth: int
    as_of: dt.date | None
    node_count: int
    edge_count: int
    truncated: bool = Field(description="True, gdy wynik został przycięty przez budżet zapytania")
    suppressed_hubs: int = Field(description="Liczba węzłów-hubów, których celowo nie rozwinięto")


class GraphOut(BaseModel):
    nodes: list[NodeOut]
    edges: list[EdgeOut]
    meta: GraphMeta
