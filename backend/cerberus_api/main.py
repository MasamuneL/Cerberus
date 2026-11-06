"""Aplicación FastAPI de Cerberus (docs/PLAN_MVP.md §7, tickets B4, B6 y B7).

Arranque: `uv run uvicorn cerberus_api.main:app --reload --port 8000` (docs en `/docs`).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from cerberus_api import __version__
from cerberus_api.config import get_settings
from cerberus_api.deps import close_redis
from cerberus_api.oidc import OIDCForbidden, OIDCInvalid, OIDCUnavailable
from cerberus_api.routers import auth, jobs, studies, system, uploads
from cerberus_api.sessions import SessionUnavailable


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Cierra el pool de Redis al apagar (el pool se crea de forma lazy en `get_redis`)."""
    yield
    await close_redis()


def create_app() -> FastAPI:
    """Crea la app con CORS desde la configuración y los routers montados en `/api`."""
    settings = get_settings()
    app = FastAPI(title="Cerberus API", version=__version__, lifespan=lifespan)

    async def identity_unavailable(request: Request, error: Exception) -> JSONResponse:
        """Un fallo de Redis/proveedor no habilita acceso local ni revela detalles internos."""
        return JSONResponse(
            {"detail": "Servicio de identidad no disponible"}, status_code=503, headers={"Cache-Control": "no-store"}
        )

    async def identity_invalid(request: Request, error: Exception) -> JSONResponse:
        """Errores de firma, código y claims se presentan de forma genérica."""
        return JSONResponse(
            {"detail": "No se pudo validar el inicio de sesión"}, status_code=401, headers={"Cache-Control": "no-store"}
        )

    async def identity_forbidden(request: Request, error: Exception) -> JSONResponse:
        """Una identidad válida sin rol no obtiene una sesión de Cerberus."""
        return JSONResponse(
            {"detail": "La cuenta no tiene permisos de Cerberus"},
            status_code=403,
            headers={"Cache-Control": "no-store"},
        )

    app.add_exception_handler(SessionUnavailable, identity_unavailable)
    app.add_exception_handler(OIDCUnavailable, identity_unavailable)
    app.add_exception_handler(OIDCInvalid, identity_invalid)
    app.add_exception_handler(OIDCForbidden, identity_forbidden)
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
    app.include_router(system.router, prefix="/api")
    app.include_router(auth.router, prefix="/api")
    # Debe ser el último middleware añadido: cubre incluso rechazos previos a las dependencias del callback.
    app.add_middleware(auth.CallbackPrivacyMiddleware)
    return app


app = create_app()
