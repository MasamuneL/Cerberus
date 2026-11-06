"""Guardas de acceso previas al body y propiedad de recursos pendientes (PLAN_MVP §17.3)."""

import json
import re
import uuid
from collections.abc import Awaitable, Callable
from typing import Literal

from arq.connections import ArqRedis
from arq.jobs import Job
from fastapi import HTTPException
from redis.asyncio import Redis
from redis.exceptions import RedisError
from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from cerberus_api.config import Settings
from cerberus_api.deps import SESSION_COOKIE, verify_csrf
from cerberus_api.identity import Principal
from cerberus_api.sessions import SessionStore, SessionUnavailable

SessionFactory = Callable[[], Awaitable[SessionStore]]
ResourceKind = Literal["jobs", "uploads"]
_RESOURCE_ID = re.compile(r"[0-9a-f]{32}", re.ASCII)
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class OwnerStore:
    """La identidad estable vive fuera de manifests, logs y cookies; nunca se adopta metadata ausente."""

    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    @staticmethod
    def key(kind: ResourceKind, resource_id: str) -> str:
        """Valida el ID antes de interpolarlo en una clave de propiedad."""
        if not _RESOURCE_ID.fullmatch(resource_id):
            raise ValueError("Identificador de recurso inválido")
        return f"cerberus:auth:owners:{kind}:{resource_id}"

    @staticmethod
    def _identity(principal: Principal) -> str:
        """Los roles y la sesión no forman parte de la identidad del propietario."""
        return json.dumps([principal.issuer, principal.sub], ensure_ascii=True, separators=(",", ":"))

    async def register(self, kind: ResourceKind, resource_id: str, principal: Principal) -> None:
        """Registra antes de publicar el recurso; los UUID nuevos no deben colisionar."""
        try:
            created = await self.redis.set(self.key(kind, resource_id), self._identity(principal), nx=True)
        except (RedisError, OSError) as error:
            raise SessionUnavailable("Propiedad no disponible") from error
        if not created:
            raise SessionUnavailable("No se pudo registrar el propietario")

    async def owns(self, kind: ResourceKind, resource_id: str, principal: Principal) -> bool:
        """False para IDs inválidos, metadata ausente y cualquier otra identidad."""
        try:
            key = self.key(kind, resource_id)
        except ValueError:
            return False
        try:
            raw = await self.redis.get(key)
        except (RedisError, OSError) as error:
            raise SessionUnavailable("Propiedad no disponible") from error
        expected = self._identity(principal)
        return raw == expected or raw == expected.encode()

    async def delete(self, kind: ResourceKind, resource_id: str) -> None:
        """Borra únicamente la metadata del recurso descartado."""
        try:
            await self.redis.delete(self.key(kind, resource_id))
        except (RedisError, OSError) as error:
            raise SessionUnavailable("Propiedad no disponible") from error


class AccessMiddleware:
    """Autentica antes de que FastAPI lea multipart/JSON y antes de cualquier acceso a disco."""

    def __init__(self, app: ASGIApp, settings: Settings, session_factory: SessionFactory) -> None:
        self.app = app
        self.settings = settings
        self.session_factory = session_factory

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope["path"]
        is_api = path == "/api" or path.startswith("/api/")
        public = path.rstrip("/") == "/api/health" or path.startswith("/api/auth/")
        if not is_api or public or scope["method"] == "OPTIONS":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        try:
            if self.settings.auth_mode == "off":
                if scope["method"] not in _SAFE_METHODS and (
                    request.headers.get("x-cerberus") != "1"
                    or (
                        "origin" in request.headers
                        and request.headers["origin"] not in {self.settings.app_origin, *self.settings.cors_origins}
                    )
                ):
                    raise HTTPException(403, "Origen o cabecera de aplicación inválidos")
            else:
                token = request.cookies.get(SESSION_COOKIE, "")
                if not token:
                    raise HTTPException(401, "Inicia sesión para continuar")
                store = await self.session_factory()
                session = await store.read_session(token)
                if session is None:
                    raise HTTPException(401, "Inicia sesión para continuar")
                scope["cerberus_session"] = session
                parts = path.strip("/").split("/")
                kind = parts[1] if len(parts) > 1 else ""
                if (
                    scope["method"] not in _SAFE_METHODS or kind in {"jobs", "uploads"}
                ) and "analyst" not in session.principal.roles:
                    raise HTTPException(403, "Se requiere permiso de analista")
                if scope["method"] not in _SAFE_METHODS:
                    verify_csrf(request, session, self.settings)
                if kind in {"jobs", "uploads"} and len(parts) > 2:
                    resource_kind: ResourceKind = "jobs" if kind == "jobs" else "uploads"
                    if not await OwnerStore(store.redis).owns(resource_kind, parts[2], session.principal):
                        raise HTTPException(404, "Recurso no encontrado")
        except (HTTPException, SessionUnavailable) as error:
            status = error.status_code if isinstance(error, HTTPException) else 503
            detail = error.detail if isinstance(error, HTTPException) else "Servicio de identidad no disponible"
            await JSONResponse({"detail": detail}, status_code=status, headers={"Cache-Control": "no-store"})(
                scope, receive, send
            )
            return

        async def cache_policy(message: Message) -> None:
            """La revalidación de archivos ocurre después de autenticar cada GET/HEAD."""
            if self.settings.auth_mode == "oidc" and message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Cache-Control"] = (
                    "private, no-cache"
                    if path.endswith(".nii.gz") and message["status"] in {200, 206, 304}
                    else "no-store"
                )
            await send(message)

        await self.app(scope, receive, cache_policy)


async def enqueue_owned_job(redis: ArqRedis, principal: Principal | None, function: str, *args: object) -> Job | None:
    """Publica la propiedad antes del job y la revierte si el encolado falla."""
    job_id = uuid.uuid4().hex
    owners = OwnerStore(redis)
    if principal is not None:
        await owners.register("jobs", job_id, principal)
    try:
        job = await redis.enqueue_job(function, *args, _job_id=job_id)
        if job is not None:
            return job
    except BaseException:
        if principal is not None:
            await owners.delete("jobs", job_id)
        raise
    if principal is not None:
        await owners.delete("jobs", job_id)
    return None
