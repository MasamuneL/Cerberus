"""Aplicación FastAPI de Cerberus (docs/PLAN_MVP.md §7, tickets B4, B6 y B7).

Arranque: `uv run uvicorn cerberus_api.main:app --reload --port 8000` (docs en `/docs`).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from cerberus_api import __version__
from cerberus_api.access import AccessMiddleware, SessionFactory
from cerberus_api.config import Settings, get_settings
from cerberus_api.deps import close_redis, get_redis
from cerberus_api.oidc import OIDCForbidden, OIDCInvalid, OIDCUnavailable
from cerberus_api.routers import auth, jobs, studies, system, uploads
from cerberus_api.sessions import SessionStore, SessionUnavailable


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Cierra el pool de Redis al apagar (el pool se crea de forma lazy en `get_redis`)."""
    yield
    await close_redis()


def create_app(settings: Settings | None = None, *, session_factory: SessionFactory | None = None) -> FastAPI:
    """Crea la app con CORS desde la configuración y los routers montados en `/api`."""
    settings = settings or get_settings()
    configured = settings

    async def default_session_factory() -> SessionStore:
        """El pool sigue siendo lazy y sus fallos nunca habilitan acceso local."""
        try:
            return SessionStore(await get_redis(configured), configured)
        except HTTPException as error:
            raise SessionUnavailable("Sesiones no disponibles") from error

    docs = settings.auth_mode == "off"
    app = FastAPI(
        title="Cerberus API",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )
    app.state.settings = settings
    app.state.auth_session_factory = session_factory or default_session_factory

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
    app.add_middleware(AccessMiddleware, settings=settings, session_factory=app.state.auth_session_factory)
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=[urlsplit(settings.app_origin).hostname or "localhost", "localhost", "127.0.0.1", "[::1]"],
        www_redirect=False,
    )
    # Debe ser el último middleware añadido: cubre incluso rechazos previos a las dependencias del callback.
    app.add_middleware(auth.CallbackPrivacyMiddleware)
    return app


app = create_app()
