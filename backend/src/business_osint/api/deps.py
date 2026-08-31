"""Zależności FastAPI."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from business_osint.config import Settings, get_settings
from business_osint.db.session import get_session
from business_osint.domain.graph_budget import GraphBudget

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


async def current_plan(
    settings: SettingsDep,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> str:
    """Plan taryfowy żądania.

    MVP: brak klucza = plan darmowy. Docelowo klucz -> tabela ``api_keys``
    z limitem zapytań i planem; to jest jedyne miejsce, które trzeba zmienić.
    """
    if x_api_key:
        return "b2b"
    return settings.default_plan


async def graph_budget(plan: Annotated[str, Depends(current_plan)]) -> GraphBudget:
    return GraphBudget.for_plan(plan)


BudgetDep = Annotated[GraphBudget, Depends(graph_budget)]
