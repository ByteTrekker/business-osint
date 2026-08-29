from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from business_osint.api.deps import SessionDep

router = APIRouter(tags=["system"])


@router.get("/healthz", summary="Liveness")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", summary="Readiness — sprawdza połączenie z bazą")
async def readyz(session: SessionDep) -> dict[str, str]:
    await session.execute(text("SELECT 1"))
    return {"status": "ready", "database": "ok"}
