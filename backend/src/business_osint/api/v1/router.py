from fastapi import APIRouter

from business_osint.api.v1 import entities, graph, health, search, stats
from business_osint.api.v1 import map as map_module
from business_osint.api.v1 import sources as sources_module

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(search.router)
api_router.include_router(entities.router)
api_router.include_router(graph.router)
api_router.include_router(stats.router)
api_router.include_router(map_module.router)
api_router.include_router(sources_module.router)
