"""Kontrakty API dla profili podmiotów."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

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


class PageMeta(BaseModel):
    """Ile poprosiliśmy, ile dostaliśmy i czy zostało coś dalej.

    Niezmiennik N3 mówi, że przycięcie wyniku jest częścią kontraktu, a nie
    cichą decyzją serwera. Bez tej struktury lista ucięta na dwustu wierszach
    wygląda dokładnie tak samo jak lista, która na dwustu się kończy.

    ``total`` bywa ``None`` świadomie. Dla powiązań policzenie ich jest tanie
    i podajemy dokładną liczbę. Dla wyszukiwania pełny przelicznik oznaczałby
    przejście przez wszystkie dopasowania — przy prefiksie „a" to 830 tys.
    wierszy — więc mówimy tylko, czy jest coś dalej. Zmyślona liczba byłaby
    gorsza od przyznania się do jej braku.
    """

    limit: int
    offset: int
    returned: int
    has_more: bool
    total: int | None = None


class SearchResultOut(BaseModel):
    query: str
    hits: list[SearchHitOut]
    meta: PageMeta


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
    attributes: dict[str, Any] = Field(default_factory=dict)
    provenance: list[ProvenanceOut] = Field(default_factory=list)


class RelationshipPageOut(BaseModel):
    """Powiązania podmiotu razem z informacją o przycięciu.

    Wcześniej endpoint zwracał gołą listę. Przy limicie 200 i podmiocie
    z tysiącem krawędzi klient nie miał **żadnego** sygnału, że czegoś nie widzi.
    """

    items: list[RelationshipOut]
    meta: PageMeta


class CoLocatedOut(BaseModel):
    """Podmiot dzielący adres z oglądanym."""

    id: uuid.UUID
    type: str
    name: str
    nip: str | None = None
    krs: str | None = None
    status: str | None = None
    valid_from: dt.date | None = None
    valid_to: dt.date | None = None
    degree: int


class CoLocatedPageOut(BaseModel):
    items: list[CoLocatedOut]
    meta: PageMeta


class FinancialReportOut(BaseModel):
    """Dane finansowe za okres sprawozdawczy."""

    period_from: dt.date
    period_to: dt.date
    revenue: float | None = None
    costs: float | None = None
    income: float | None = None
    loss: float | None = None
    tax_base: float | None = None
    tax_due: float | None = None
    currency: str = "PLN"


class LocationOut(BaseModel):
    """Współrzędne adresu wraz z jego postacią tekstową."""

    latitude: float
    longitude: float
    label: str


class EntityProfileOut(BaseModel):
    id: uuid.UUID
    type: str
    name: str
    degree: int
    identifiers: list[IdentifierOut] = Field(default_factory=list)
    company: dict[str, Any] | None = None
    person: dict[str, Any] | None = None
    address: dict[str, Any] | None = None
    financials: list[FinancialReportOut] = Field(default_factory=list)
    updated_at: dt.datetime | None = None
