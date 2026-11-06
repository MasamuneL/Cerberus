"""Entrada OIDC, sesión pública y logout local de Cerberus (PLAN_MVP §17.4)."""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from starlette._utils import get_route_path
from starlette.types import ASGIApp, Receive, Scope, Send

from cerberus_api.config import Settings
from cerberus_api.deps import (
    LOGIN_COOKIE,
    SESSION_COOKIE,
    OIDCDep,
    OIDCSettingsDep,
    SessionDep,
    SessionStoreDep,
    SettingsDep,
    verify_csrf,
)
from cerberus_api.schemas import AuthConfig, AuthSession
from cerberus_api.sessions import TRANSACTION_TTL

router = APIRouter(prefix="/auth", tags=["auth"])
_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


class CallbackPrivacyMiddleware:
    """El servidor conserva un scope sin query; el router recibe una copia solo durante el callback."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and get_route_path(scope).rstrip("/") == "/api/auth/callback":
            query = scope.get("query_string", b"")
            scope["query_string"] = b""
            inner = dict(scope)
            inner["query_string"] = query
            try:
                await self.app(inner, receive, send)
            finally:
                inner["query_string"] = b""
        else:
            await self.app(scope, receive, send)


def _set_cookie(response: Response, name: str, value: str, lifetime: int, settings: Settings) -> None:
    """Cookies del host, opacas y HttpOnly; HTTP solo en la demo de loopback validada por Settings."""
    response.set_cookie(
        name, value, max_age=lifetime, httponly=True, secure=settings.auth_cookie_secure, samesite="lax", path="/"
    )


def _delete_cookie(response: Response, name: str, settings: Settings) -> None:
    """Usa los mismos atributos al retirar la cookie que al crearla."""
    response.delete_cookie(name, path="/", httponly=True, secure=settings.auth_cookie_secure, samesite="lax")


@router.get("/config", response_model=AuthConfig)
def config(response: Response, settings: SettingsDep) -> AuthConfig:
    """Público y sin secretos; el modo off conserva el flujo local heredado."""
    response.headers.update(_HEADERS)
    return AuthConfig(mode=settings.auth_mode)


@router.get("/login")
async def login(settings: OIDCSettingsDep, store: SessionStoreDep, provider: OIDCDep) -> RedirectResponse:
    """Guarda la transacción de cinco minutos antes de redirigir al proveedor."""
    transaction = await store.create_transaction()
    url = await provider.authorization_url(transaction)
    response = RedirectResponse(url, status_code=302, headers=_HEADERS)
    _set_cookie(response, LOGIN_COOKIE, transaction.browser_token, TRANSACTION_TTL, settings)
    return response


@router.get("/callback")
async def callback(
    request: Request, settings: OIDCSettingsDep, store: SessionStoreDep, provider: OIDCDep
) -> RedirectResponse:
    """Consume state una sola vez, verifica OIDC y renueva la sesión; no registra code/state."""
    try:
        query = request.query_params
        if (
            query.get("error")
            or len(query.getlist("code")) != 1
            or len(query.getlist("state")) != 1
            or not query.get("code")
        ):
            raise HTTPException(400, "Inicio de sesión inválido", headers=_HEADERS)
        transaction = await store.consume_transaction(query.get("state", ""), request.cookies.get(LOGIN_COOKIE, ""))
        if transaction is None:
            raise HTTPException(400, "Inicio de sesión inválido o caducado", headers=_HEADERS)
        principal = await provider.exchange_code(query["code"], transaction)
        token, _ = await store.create_session(principal, previous_token=request.cookies.get(SESSION_COOKIE))
        response = RedirectResponse("/", status_code=303, headers=_HEADERS)
        _set_cookie(response, SESSION_COOKIE, token, settings.auth_absolute_timeout_seconds, settings)
        _delete_cookie(response, LOGIN_COOKIE, settings)
        return response
    finally:
        # Uvicorn consulta el scope al emitir el access log; el callback ya consumió sus parámetros.
        request.scope["query_string"] = b""


@router.get("/me", response_model=AuthSession)
def me(response: Response, settings: OIDCSettingsDep, session: SessionDep) -> AuthSession:
    """Roles, vencimiento efectivo y CSRF; nunca issuer/sub ni tokens del proveedor."""
    response.headers.update(_HEADERS)
    return AuthSession(
        roles=sorted(session.principal.roles),
        expires_at=datetime.fromtimestamp(session.expires_at, UTC),
        csrf_token=session.csrf_token,
    )


@router.post("/logout", status_code=204)
async def logout(request: Request, settings: OIDCSettingsDep, session: SessionDep, store: SessionStoreDep) -> Response:
    """Invalida Redis antes de borrar cookies; no cierra sesiones de otras aplicaciones del proveedor."""
    verify_csrf(request, session, settings)
    await store.delete_session(request.cookies.get(SESSION_COOKIE, ""))
    response = Response(status_code=204, headers=_HEADERS)
    _delete_cookie(response, SESSION_COOKIE, settings)
    _delete_cookie(response, LOGIN_COOKIE, settings)
    return response
