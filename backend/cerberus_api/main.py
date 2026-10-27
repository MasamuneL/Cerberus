"""Aplicación FastAPI de Cerberus (docs/PLAN_MVP.md §7, tickets B4, B6 y B7).

Arranque: `uv run uvicorn cerberus_api.main:app --reload --port 8000` (docs en `/docs`).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from cerberus_api import __version__
from cerberus_api.config import get_settings
from cerberus_api.deps import close_redis
from cerberus_api.routers import jobs, studies, uploads


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Cierra el pool de Redis al apagar (el pool se crea de forma lazy en `get_redis`)."""
    yield
    await close_redis()


def create_app() -> FastAPI:
    """Crea la app con CORS desde la configuración y los routers montados en `/api`."""
    settings = get_settings()
    app = FastAPI(title="Cerberus API", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        """Comprobación de vida."""
        return {"status": "ok"}

    app.include_router(studies.router, prefix="/api")
    app.include_router(jobs.router, prefix="/api")
    app.include_router(uploads.router, prefix="/api")
    return app


app = create_app()
