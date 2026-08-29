"""Odczyt profili podmiotów i wyszukiwarka."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from business_osint.domain.normalization import (
    is_valid_krs,
    is_valid_nip,
    is_valid_regon,
    normalize_company_name,
)


@dataclass(slots=True)
class SearchHit:
    id: uuid.UUID
    entity_type: str
    display_name: str
    score: float
    subtitle: str | None
    degree: int


# Uwaga: dialekt asyncpg używa paramstyle numeric_dollar ($1), więc znak `%`
# NIE jest tu podwajany. Przy przeniesieniu zapytania na psycopg (pyformat)
# trzeba go zapisać jako `%%`.
#
# Wyszukiwanie hybrydowe: najpierw dokładny identyfikator (NIP/KRS/REGON),
# potem podobieństwo trigramowe nazwy. Jedno zapytanie, jeden ranking.
_SEARCH_SQL = text(
    """
    WITH by_identifier AS (
        SELECT e.id, e.entity_type, e.display_name, e.degree, 1.0::float8 AS score
        FROM entity_identifiers i
        JOIN entities e ON e.id = i.entity_id AND e.merged_into_id IS NULL
        WHERE :identifier IS NOT NULL AND i.value = :identifier
    ),
    by_name AS (
        SELECT e.id, e.entity_type, e.display_name, e.degree,
               similarity(e.normalized_name, :normalized) AS score
        FROM entities e
        WHERE e.merged_into_id IS NULL
          AND e.normalized_name % :normalized  -- operator pg_trgm, korzysta z indeksu GIN
          AND (:entity_type IS NULL OR e.entity_type = :entity_type)
        ORDER BY score DESC, e.degree DESC
        LIMIT :limit
    ),
    merged AS (
        SELECT * FROM by_identifier
        UNION ALL
        SELECT * FROM by_name WHERE id NOT IN (SELECT id FROM by_identifier)
    )
    SELECT m.*, c.nip, c.krs, c.status, a.city
    FROM merged m
    LEFT JOIN companies c ON c.entity_id = m.id
    LEFT JOIN addresses a ON a.entity_id = m.id
    ORDER BY m.score DESC, m.degree DESC
    LIMIT :limit
    """
)


class EntityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search(
        self, query: str, *, entity_type: str | None = None, limit: int = 20
    ) -> list[SearchHit]:
        cleaned = query.strip()
        digits = "".join(ch for ch in cleaned if ch.isdigit())
        identifier = (
            digits
            if digits and (is_valid_nip(digits) or is_valid_regon(digits) or is_valid_krs(digits))
            else None
        )
        rows = (
            await self._session.execute(
                _SEARCH_SQL,
                {
                    "identifier": identifier,
                    "normalized": normalize_company_name(cleaned) or cleaned.lower(),
                    "entity_type": entity_type,
                    "limit": limit,
                },
            )
        ).mappings().all()
        return [
            SearchHit(
                id=row["id"],
                entity_type=row["entity_type"],
                display_name=row["display_name"],
                score=float(row["score"]),
                subtitle=self._subtitle(row),
                degree=row["degree"],
            )
            for row in rows
        ]

    @staticmethod
    def _subtitle(row) -> str | None:
        parts = [row.get("krs") and f"KRS {row['krs']}", row.get("nip") and f"NIP {row['nip']}",
                 row.get("city")]
        return " · ".join(p for p in parts if p) or None

    async def get_profile(self, entity_id: uuid.UUID) -> dict | None:
        """Profil podmiotu razem z atrybutami typu i licznikiem powiązań."""
        row = (
            await self._session.execute(
                text(
                    """
                    SELECT
                        e.id, e.entity_type, e.display_name, e.degree, e.merged_into_id,
                        e.created_at, e.updated_at,
                        to_jsonb(c) - 'entity_id' AS company,
                        to_jsonb(p) - 'entity_id' AS person,
                        to_jsonb(a) - 'entity_id' AS address,
                        (SELECT jsonb_agg(jsonb_build_object('scheme', i.scheme, 'value', i.value)
                                          ORDER BY i.scheme)
                         FROM entity_identifiers i WHERE i.entity_id = e.id) AS identifiers
                    FROM entities e
                    LEFT JOIN companies c ON c.entity_id = e.id
                    LEFT JOIN people p ON p.entity_id = e.id
                    LEFT JOIN addresses a ON a.entity_id = e.id
                    WHERE e.id = :id
                    """
                ),
                {"id": entity_id},
            )
        ).mappings().first()
        return dict(row) if row else None

    async def relationships(
        self, entity_id: uuid.UUID, *, include_historical: bool = True, limit: int = 200
    ) -> list[dict]:
        """Płaska lista powiązań podmiotu wraz z provenance — do zakładki „Powiązania”."""
        rows = (
            await self._session.execute(
                text(
                    """
                    SELECT
                        e.relationship_id, e.direction, e.relationship_type, e.role,
                        e.valid_from, e.valid_to, e.confidence,
                        e.attributes, n.id AS other_id, n.entity_type AS other_type,
                        n.display_name AS other_name,
                        (SELECT jsonb_agg(jsonb_build_object(
                                    'source', s.kind,
                                    'external_id', d.external_id,
                                    'url', d.url,
                                    'fetched_at', d.fetched_at,
                                    'locator', rs.locator))
                         FROM relationship_sources rs
                         JOIN raw_documents d ON d.id = rs.raw_document_id
                         JOIN sources s ON s.id = d.source_id
                         WHERE rs.relationship_id = e.relationship_id) AS provenance
                    FROM graph_edges e
                    JOIN entities n ON n.id = e.to_id AND n.merged_into_id IS NULL
                    WHERE e.from_id = :id
                      AND e.superseded_at IS NULL
                      AND (:include_historical OR e.valid_to IS NULL OR e.valid_to >= CURRENT_DATE)
                    ORDER BY (e.valid_to IS NULL) DESC, e.valid_from DESC NULLS LAST
                    LIMIT :limit
                    """
                ),
                {"id": entity_id, "include_historical": include_historical, "limit": limit},
            )
        ).mappings().all()
        return [dict(row) for row in rows]
