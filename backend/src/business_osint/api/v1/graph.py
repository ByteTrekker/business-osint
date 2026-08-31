from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status

from business_osint.api.deps import BudgetDep, SessionDep
from business_osint.repositories.graph import GraphRepository
from business_osint.schemas.graph import EdgeOut, GraphMeta, GraphOut, NodeOut

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get(
    "/{entity_id}",
    response_model=GraphOut,
    summary="Podgraf powiązań wokół podmiotu",
    description=(
        "Zwraca węzły i krawędzie do zadanej głębokości. Wynik zawsze mieści się "
        "w budżecie planu — pole `meta.truncated` mówi, czy coś przycięto. "
        "Eksplorację w głąb realizuje się wywołując ten sam endpoint dla klikniętego węzła "
        "(depth=1), a nie zwiększając głębokość jednego zapytania."
    ),
)
async def get_graph(
    session: SessionDep,
    budget: BudgetDep,
    response: Response,
    entity_id: uuid.UUID,
    depth: Annotated[int | None, Query(ge=1, le=4, description="Głębokość eksploracji")] = None,
    as_of: Annotated[dt.date | None, Query(description="Stan powiązań na dany dzień")] = None,
    types: Annotated[list[str] | None, Query(description="Filtr typów relacji")] = None,
    include_historical: Annotated[
        bool, Query(description="Uwzględnij zakończone powiązania")
    ] = False,
    include_derived: Annotated[bool, Query(description="Uwzględnij relacje wyprowadzone")] = False,
) -> GraphOut:
    try:
        neighborhood = await GraphRepository(session).neighborhood(
            entity_id,
            budget=budget,
            depth=budget.clamp_depth(depth),
            as_of=as_of,
            relationship_types=types,
            include_historical=include_historical,
            include_derived=include_derived,
        )
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Nie znaleziono podmiotu") from exc

    # Podgraf historyczny jest niezmienny — można go cache'ować agresywnie.
    response.headers["Cache-Control"] = (
        "public, max-age=86400" if as_of and as_of < dt.date.today() else "public, max-age=300"
    )
    return GraphOut(
        nodes=[
            NodeOut(
                id=n.id,
                type=n.entity_type,
                label=n.label,
                degree=n.degree,
                depth=n.depth,
                expandable=not n.truncated_expansion,
            )
            for n in neighborhood.nodes
        ],
        edges=[
            EdgeOut(
                id=e.id,
                source=e.source_id,
                target=e.target_id,
                type=e.relationship_type,
                role=e.role,
                valid_from=e.valid_from,
                valid_to=e.valid_to,
                current=e.is_current,
                confidence=e.confidence,
                attributes=e.attributes,
            )
            for e in neighborhood.edges
        ],
        meta=GraphMeta(
            root_id=neighborhood.root_id,
            depth=neighborhood.depth,
            as_of=neighborhood.as_of,
            node_count=len(neighborhood.nodes),
            edge_count=len(neighborhood.edges),
            truncated=neighborhood.truncated,
            suppressed_hubs=neighborhood.suppressed_hubs,
        ),
    )
