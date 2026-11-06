"""Flujo HTTP de auth con Redis en memoria y proveedor sustituible, sin red."""

from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from fakeredis import FakeAsyncRedis, FakeServer
from fastapi.testclient import TestClient
from pydantic import SecretStr
from test_sessions import Clock

from cerberus_api.config import Settings
from cerberus_api.deps import settings_dep
from cerberus_api.identity import Principal
from cerberus_api.main import app
from cerberus_api.sessions import LoginTransaction, SessionStore


class Provider:
    error: Exception | None = None

    async def authorization_url(self, transaction: LoginTransaction) -> str:
        if self.error:
            raise self.error
        return "https://identity.example/authorize?" + urlencode({"state": transaction.state})

    async def exchange_code(self, code: str, transaction: LoginTransaction) -> Principal:
        if self.error:
            raise self.error
        return Principal(issuer="https://identity.example", sub="subject-1", roles=frozenset({"analyst"}))


AuthClient = tuple[TestClient, Settings, Clock, Provider, FakeServer]


@pytest.fixture
def auth_client() -> Iterator[AuthClient]:
    from cerberus_api.deps import oidc_dep, session_store_dep

    settings = Settings(
        auth_mode="oidc",
        app_origin="http://localhost:8080",
        oidc_issuer_url="https://identity.example",
        oidc_client_secret=SecretStr("secreto-sintetico-para-tests"),
        auth_cookie_secure=False,
        auth_idle_timeout_seconds=5,
        auth_absolute_timeout_seconds=12,
    )
    clock = Clock()
    server = FakeServer()
    store = SessionStore(FakeAsyncRedis(server=server), settings, clock=clock)
    provider = Provider()
    app.dependency_overrides[settings_dep] = lambda: settings
    app.dependency_overrides[session_store_dep] = lambda: store
    app.dependency_overrides[oidc_dep] = lambda: provider
    try:
        with TestClient(app, base_url="http://localhost:8080", follow_redirects=False) as client:
            yield client, settings, clock, provider, server
    finally:
        app.dependency_overrides.clear()


def login(client: TestClient) -> tuple[str, str]:
    response = client.get("/api/auth/login")
    assert response.status_code == 302
    state = parse_qs(urlsplit(response.headers["location"]).query)["state"][0]
    cookie = client.cookies.get("cerberus_login")
    assert cookie
    return state, cookie


def authenticate(client: TestClient) -> dict[str, Any]:
    state, _ = login(client)
    response = client.get("/api/auth/callback", params={"code": "code", "state": state})
    assert response.status_code == 303 and response.headers["location"] == "/"
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    return me.json()


def test_public_config_and_complete_session_flow(auth_client: AuthClient) -> None:
    client, _, _, _, _ = auth_client
    assert client.get("/api/auth/config").json() == {"mode": "oidc"}
    assert client.get("/api/auth/me").status_code == 401
    state, browser_token = login(client)
    response = client.get("/api/auth/callback", params={"code": "code", "state": state})
    assert response.status_code == 303
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/" in cookie
    assert "Domain=" not in cookie
    assert client.cookies.get("cerberus_session") != browser_token
    assert not client.cookies.get("cerberus_login")
    me = client.get("/api/auth/me")
    assert me.headers["cache-control"] == "no-store"
    assert set(me.json()) == {"roles", "expires_at", "csrf_token"}
    assert me.json()["roles"] == ["analyst"]
    assert client.get("/api/auth/callback", params={"code": "code", "state": state}).status_code == 400
    csrf = me.json()["csrf_token"]
    logout = client.post("/api/auth/logout", headers={"Origin": "http://localhost:8080", "X-CSRF-Token": csrf})
    assert logout.status_code == 204
    assert not client.cookies.get("cerberus_session")
    assert client.get("/api/auth/me").status_code == 401


@pytest.mark.parametrize("mutation", ["missing_state", "wrong_state", "missing_cookie", "other_browser", "expired"])
def test_callback_rejects_invalid_transaction(auth_client: AuthClient, mutation: str) -> None:
    client, _, clock, _, _ = auth_client
    state, _ = login(client)
    if mutation == "missing_state":
        state = ""
    elif mutation == "wrong_state":
        state = "x" * 43
    elif mutation in ("missing_cookie", "other_browser"):
        client.cookies.clear()
        if mutation == "other_browser":
            client.cookies.set("cerberus_login", "x" * 43)
    else:
        clock.now += 300
    assert client.get("/api/auth/callback", params={"code": "code", "state": state}).status_code == 400
    assert not client.cookies.get("cerberus_session")


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Origin": "http://attacker.example"},
        {"Origin": "null"},
        {"Origin": "http://localhost:8080", "X-CSRF-Token": "wrong"},
    ],
)
def test_logout_requires_origin_and_csrf(auth_client: AuthClient, headers: dict[str, str]) -> None:
    client, _, _, _, _ = auth_client
    authenticate(client)
    assert client.post("/api/auth/logout", headers=headers).status_code == 403
    assert client.get("/api/auth/me").status_code == 200


def test_idle_expiration_and_session_id_rotation(auth_client: AuthClient) -> None:
    client, _, clock, _, _ = auth_client
    authenticate(client)
    old = client.cookies.get("cerberus_session")
    authenticate(client)
    assert client.cookies.get("cerberus_session") != old
    clock.now += 5
    assert client.get("/api/auth/me").status_code == 401


def test_auth_routes_disabled_in_local_mode(auth_client: AuthClient) -> None:
    client, settings, _, _, _ = auth_client
    settings.auth_mode = "off"
    assert client.get("/api/auth/config").json() == {"mode": "off"}
    for path in ("login", "callback", "me"):
        assert client.get("/api/auth/" + path).status_code == 404
    assert client.post("/api/auth/logout").status_code == 404


@pytest.mark.parametrize("secure", [True, False])
def test_cookie_transport_configuration(auth_client: AuthClient, secure: bool) -> None:
    client, settings, _, _, _ = auth_client
    settings.auth_cookie_secure = secure
    response = client.get("/api/auth/login")
    assert response.status_code == 302
    assert ("; Secure" in response.headers["set-cookie"]) is secure


@pytest.mark.parametrize("query", ["state=x", "code=x", "code=x&code=y&state=z", "code=x&state=z&error=access_denied"])
def test_malformed_callback_is_generic(auth_client: AuthClient, query: str) -> None:
    client, _, _, _, _ = auth_client
    response = client.get("/api/auth/callback?" + query)
    assert response.status_code == 400
    assert response.headers["cache-control"] == "no-store"
    assert not client.cookies.get("cerberus_session")


@pytest.mark.parametrize("failure", ["provider", "redis", "invalid", "forbidden"])
def test_failures_are_generic_and_do_not_create_session(auth_client: AuthClient, failure: str) -> None:
    from cerberus_api.oidc import OIDCForbidden, OIDCInvalid, OIDCUnavailable

    client, _, _, provider, server = auth_client
    state, _ = login(client)
    if failure == "redis":
        server.connected = False
        expected = 503
    else:
        provider.error = {
            "provider": OIDCUnavailable("secret-token"),
            "invalid": OIDCInvalid("secret-token"),
            "forbidden": OIDCForbidden("secret-token"),
        }[failure]
        expected = 503 if failure == "provider" else 401 if failure == "invalid" else 403
    response = client.get("/api/auth/callback", params={"code": "secret-code", "state": state})
    assert response.status_code == expected
    assert "secret" not in response.text
    assert not client.cookies.get("cerberus_session")
