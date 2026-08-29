from fastapi import APIRouter

from business_osint.api.v1 import entities, graph, health, search

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(search.router)
api_router.include_router(entities.router)
api_router.include_router(graph.router)
