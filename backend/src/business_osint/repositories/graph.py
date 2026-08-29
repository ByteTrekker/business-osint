"""Ekspansja sąsiedztwa w grafie.

Dlaczego BFS iteracyjny w Pythonie, a nie jedno ``WITH RECURSIVE``:

* limit rozgałęzień per węzeł (``fanout``) i globalny budżet węzłów są
  w rekurencyjnym CTE trudne do wyrażenia — ``LIMIT`` w członie rekurencyjnym
  nie ma zdefiniowanej semantyki, a odwołanie rekurencyjne wewnątrz
  podzapytania/LATERAL jest w Postgresie zabronione;
* przy głębokości <= 3 to i tak są maksymalnie 3 round-tripy, każdy na
  indeksie — narzut sieciowy jest pomijalny wobec kosztu I/O;
* logika przycinania hubów jest testowalna bez bazy (``domain/graph_budget.py``).

Wariant czysto-SQL (rekurencyjny CTE) opisuję w docs/adr/0004 — wraca do gry
dopiero przy shortest-path między odległymi podmiotami.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from business_osint.domain.enums import DERIVED_RELATIONSHIP_TYPES
from business_osint.domain.graph_budget import ExpansionState, GraphBudget

_LEVEL_SQL = text(
    """
    WITH candidate_edges AS (
        SELECT
            e.relationship_id,
            e.from_id,
            e.to_id,
            e.direction,
            e.relationship_type,
            e.role,
            e.valid_from,
            e.valid_to,
            e.confidence,
            e.confidence_score,
            e.attributes,
            row_number() OVER (
                PARTITION BY e.from_id
                ORDER BY e.confidence_score DESC,
                         (e.valid_to IS NULL) DESC,
                         e.valid_from DESC NULLS LAST,
                         e.relationship_id
            ) AS rn,
            count(*) OVER (PARTITION BY e.from_id) AS matched_degree
        FROM graph_edges e
        WHERE e.from_id = ANY(:frontier)
          AND e.superseded_at IS NULL
          AND (
                :include_historical
                OR (
                    (e.valid_from IS NULL OR e.valid_from <= :as_of)
                    AND (e.valid_to IS NULL OR e.valid_to >= :as_of)
                )
              )
          AND (:rel_types IS NULL OR e.relationship_type = ANY(:rel_types))
    )
    SELECT
        ce.relationship_id,
        ce.from_id,
        ce.to_id,
        ce.direction,
        ce.relationship_type,
        ce.role,
        ce.valid_from,
        ce.valid_to,
        ce.confidence,
        ce.confidence_score,
        ce.attributes,
        ce.matched_degree,
        n.entity_type,
        n.display_name,
        n.degree AS target_degree
    FROM candidate_edges ce
    JOIN entities n ON n.id = ce.to_id AND n.merged_into_id IS NULL
    WHERE ce.rn <= :fanout
    ORDER BY ce.from_id, ce.rn
    """
).bindparams(
    bindparam("frontier", type_=ARRAY(PG_UUID(as_uuid=True))),
    bindparam("rel_types", type_=ARRAY(str)),
)


@dataclass(slots=True)
class GraphNode:
    id: uuid.UUID
    entity_type: str
    label: str
    degree: int
    depth: int
    #: True, jeżeli węzeł jest hubem i celowo nie został rozwinięty.
    truncated_expansion: bool = False


@dataclass(slots=True)
class GraphEdge:
    id: uuid.UUID
    source_id: uuid.UUID
    target_id: uuid.UUID
    relationship_type: str
    role: str | None
    valid_from: dt.date | None
    valid_to: dt.date | None
    confidence: str
    is_current: bool
    attributes: dict


@dataclass(slots=True)
class Neighborhood:
    root_id: uuid.UUID
    depth: int
    as_of: dt.date | None
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    truncated: bool = False
    suppressed_hubs: int = 0

    @property
    def stats(self) -> dict[str, int | bool]:
        return {
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
            "truncated": self.truncated,
            "suppressed_hubs": self.suppressed_hubs,
        }


class GraphRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def neighborhood(
        self,
        root_id: uuid.UUID,
        *,
        budget: GraphBudget,
        depth: int,
        as_of: dt.date | None = None,
        relationship_types: list[str] | None = None,
        include_historical: bool = False,
        include_derived: bool = False,
    ) -> Neighborhood:
        """Zwraca podgraf wokół ``root_id`` — poziom po poziomie, w budżecie."""
        as_of = as_of or dt.date.today()
        depth = budget.clamp_depth(depth)

        root = await self._load_root(root_id)
        if root is None:
            raise KeyError(root_id)

        rel_types = self._effective_types(relationship_types, include_derived)
        state = ExpansionState.start(str(root_id), budget)
        result = Neighborhood(
            root_id=root_id, depth=depth, as_of=None if include_historical else as_of
        )
        result.nodes.append(root)

        frontier = [root_id]
        seen_edges: set[uuid.UUID] = set()

        for level in range(1, depth + 1):
            if not frontier or state.remaining_nodes <= 0:
                break
            rows = (
                await self._session.execute(
                    _LEVEL_SQL,
                    {
                        "frontier": frontier,
                        "as_of": as_of,
                        "include_historical": include_historical,
                        "rel_types": rel_types,
                        "fanout": budget.fanout_per_node,
                    },
                )
            ).mappings().all()

            next_frontier: list[uuid.UUID] = []
            for row in rows:
                if row["matched_degree"] > budget.fanout_per_node:
                    state.truncated = True
                new_ids = state.accept([str(row["to_id"])])
                is_new = bool(new_ids)
                if is_new:
                    node = GraphNode(
                        id=row["to_id"],
                        entity_type=row["entity_type"],
                        label=row["display_name"],
                        degree=row["target_degree"],
                        depth=level,
                    )
                    # should_expand ma efekt uboczny (licznik hubów), więc wołamy
                    # je tylko wtedy, gdy faktycznie rozważamy rozwinięcie węzła.
                    if level < depth:
                        if state.should_expand(str(row["to_id"]), row["target_degree"]):
                            next_frontier.append(row["to_id"])
                        else:
                            node.truncated_expansion = True
                    result.nodes.append(node)
                if row["relationship_id"] not in seen_edges and str(row["to_id"]) in state.visited:
                    seen_edges.add(row["relationship_id"])
                    result.edges.append(self._to_edge(row, as_of))

            frontier = next_frontier

        result.truncated = state.truncated
        result.suppressed_hubs = state.suppressed_hubs
        return result

    @staticmethod
    def _effective_types(
        relationship_types: list[str] | None, include_derived: bool
    ) -> list[str] | None:
        if relationship_types:
            return relationship_types
        # Relacje wyprowadzone (wspólny adres itd.) tworzą gigantyczne kliki —
        # domyślnie ich nie rozwijamy.
        return None if include_derived else _NON_DERIVED_TYPES

    @staticmethod
    def _to_edge(row, as_of: dt.date) -> GraphEdge:
        # Kierunek 'in' oznacza, że wiersz przyszedł z odwróconej połowy widoku —
        # przywracamy oryginalną orientację krawędzi, bo ona niesie znaczenie
        # (osoba -> spółka to nie to samo, co spółka -> osoba).
        if row["direction"] == "out":
            source_id, target_id = row["from_id"], row["to_id"]
        else:
            source_id, target_id = row["to_id"], row["from_id"]
        valid_to = row["valid_to"]
        return GraphEdge(
            id=row["relationship_id"],
            source_id=source_id,
            target_id=target_id,
            relationship_type=row["relationship_type"],
            role=row["role"],
            valid_from=row["valid_from"],
            valid_to=valid_to,
            confidence=row["confidence"],
            is_current=valid_to is None or valid_to >= as_of,
            attributes=row["attributes"] or {},
        )

    async def _load_root(self, root_id: uuid.UUID) -> GraphNode | None:
        row = (
            await self._session.execute(
                text(
                    """
                    SELECT id, entity_type, display_name, degree, merged_into_id
                    FROM entities WHERE id = :id
                    """
                ),
                {"id": root_id},
            )
        ).mappings().first()
        if row is None:
            return None
        return GraphNode(
            id=row["id"],
            entity_type=row["entity_type"],
            label=row["display_name"],
            degree=row["degree"],
            depth=0,
        )


_NON_DERIVED_TYPES: list[str] = []  # wypełniane niżej, po imporcie enumów


def _init_non_derived() -> None:
    from business_osint.domain.enums import RelationshipType

    _NON_DERIVED_TYPES.extend(
        t.value for t in RelationshipType if t not in DERIVED_RELATIONSHIP_TYPES
    )


_init_non_derived()
