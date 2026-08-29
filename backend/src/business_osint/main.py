"""Punkt wejścia aplikacji."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from business_osint.api.v1.router import api_router
from business_osint.config import get_settings
from business_osint.db.session import dispose_engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="business-osint API",
        version="0.1.0",
        summary="Graf powiązań polskich firm i osób na danych z rejestrów publicznych",
        description=(
            "Wszystkie dane pochodzą z publicznych rejestrów. Każda relacja ma provenance "
            "(`/entities/{id}/relationships`), a każdy podgraf ma budżet — patrz `meta.truncated`."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    app.include_router(api_router, prefix="/api/v1")
    return app


app = create_app()
