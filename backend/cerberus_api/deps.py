"""Dependencias de FastAPI compartidas por los routers.

En los tests se sustituyen con `app.dependency_overrides[settings_dep] = ...` (y `get_redis`).
"""

import asyncio
import dataclasses
import secrets
from typing import Annotated

from arq.connections import ArqRedis, RedisSettings, create_pool
from fastapi import Depends, HTTPException, Request
from redis.exceptions import RedisError

from cerberus_api.config import Settings
from cerberus_api.identity import Principal
from cerberus_api.oidc import OIDCClient
from cerberus_api.sessions import SessionData, SessionStore


def settings_dep(request: Request) -> Settings:
    """Ajustes de la app; dependencia separada de `get_settings` para poder sobreescribirla en tests."""
    return request.app.state.settings


# Alias para anotar parámetros de los endpoints: `settings: SettingsDep`
SettingsDep = Annotated[Settings, Depends(settings_dep)]

# Pool arq único, creado de forma lazy en la primera petición que lo necesita: así la app arranca aunque
# Redis esté apagado. El lock evita que dos peticiones concurrentes creen dos pools.
_redis_pool: ArqRedis | None = None
_redis_lock = asyncio.Lock()

REDIS_UNAVAILABLE = "Redis no disponible: inicia redis-server y el worker"


async def get_redis(settings: SettingsDep) -> ArqRedis:
    """Pool arq compartido; 503 si Redis no responde (sin reintentos largos para no colgar la petición)."""
    global _redis_pool
    if _redis_pool is not None:
        return _redis_pool
    async with _redis_lock:
        if _redis_pool is None:
            # arq reintenta 5 veces con 1 s de espera por defecto: en la API basta un reintento
            redis_settings = dataclasses.replace(RedisSettings.from_dsn(settings.redis_url), conn_retries=1)
            try:
                _redis_pool = await create_pool(redis_settings)
            except (RedisError, OSError, TimeoutError) as exc:
                raise HTTPException(status_code=503, detail=REDIS_UNAVAILABLE) from exc
        return _redis_pool


async def close_redis() -> None:
    """Cierra el pool si llegó a crearse (se llama al apagar la app)."""
    global _redis_pool
    if _redis_pool is not None:
        await _redis_pool.aclose()
        _redis_pool = None


# Alias para anotar parámetros de los endpoints: `redis: RedisDep`
RedisDep = Annotated[ArqRedis, Depends(get_redis)]

SESSION_COOKIE = "cerberus_session"
LOGIN_COOKIE = "cerberus_login"


def require_oidc(settings: SettingsDep) -> Settings:
    """El modo local no fabrica identidades ni expone rutas de sesión."""
    if settings.auth_mode != "oidc":
        raise HTTPException(404, "Autenticación no habilitada", headers={"Cache-Control": "no-store"})
    return settings


OIDCSettingsDep = Annotated[Settings, Depends(require_oidc)]


def oidc_dep(settings: OIDCSettingsDep) -> OIDCClient:
    """Cliente sustituible en pruebas; no abre conexiones al construirlo."""
    return OIDCClient(settings)


async def session_store_dep(request: Request, settings: OIDCSettingsDep) -> SessionStore:
    """Almacén de identidad sobre el pool compartido, con claves separadas de arq."""
    return await request.app.state.auth_session_factory()


SessionStoreDep = Annotated[SessionStore, Depends(session_store_dep)]
OIDCDep = Annotated[OIDCClient, Depends(oidc_dep)]


async def current_session(request: Request, store: SessionStoreDep) -> SessionData:
    """Devuelve una sesión válida; el navegador solo entrega su identificador opaco."""
    session = await store.read_session(request.cookies.get(SESSION_COOKIE, ""))
    if session is None:
        raise HTTPException(401, "Inicia sesión para continuar", headers={"Cache-Control": "no-store"})
    return session


SessionDep = Annotated[SessionData, Depends(current_session)]


def verify_csrf(request: Request, session: SessionData, settings: Settings) -> None:
    """Token sincronizado y origen explícito; SameSite no sustituye estas dos comprobaciones."""
    token = request.headers.get("x-csrf-token", "")
    if (
        request.headers.get("origin") not in {settings.app_origin, *settings.cors_origins}
        or not token.isascii()
        or not secrets.compare_digest(token, session.csrf_token)
    ):
        raise HTTPException(403, "Origen o token CSRF inválido", headers={"Cache-Control": "no-store"})


def current_principal(request: Request) -> Principal | None:
    """Identidad ya comprobada por la guarda; en modo local no se fabrica propietario."""
    session: SessionData | None = request.scope.get("cerberus_session")
    return session.principal if session is not None else None


PrincipalDep = Annotated[Principal | None, Depends(current_principal)]
