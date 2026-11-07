"""Errores del navegador vuelven a una pantalla de la app sin code/state; JSON conserva su contrato."""

import pytest
from test_auth_routes import AuthClient, login
from test_auth_routes import auth_client as auth_client

from cerberus_api.oidc import OIDCForbidden, OIDCInvalid, OIDCUnavailable


@pytest.mark.parametrize(
    "error,code,status",
    [(OIDCForbidden(), "forbidden", 403), (OIDCInvalid(), "failed", 401), (OIDCUnavailable(), "unavailable", 503)],
)
@pytest.mark.parametrize("browser", [False, True])
def test_callback_identity_error_navigation(
    auth_client: AuthClient, error: Exception, code: str, status: int, browser: bool
) -> None:
    client, _, _, provider, _ = auth_client
    state, _ = login(client)
    provider.error = error
    response = client.get(
        "/api/auth/callback",
        params={"code": "synthetic", "state": state},
        headers={"Accept": "text/html" if browser else "application/json"},
    )
    assert response.status_code == (303 if browser else status)
    assert response.headers["cache-control"] == "no-store"
    if browser:
        assert response.headers["location"] == "/?auth_error=" + code
        assert not client.cookies.get("cerberus_session")


def test_invalid_transaction_navigation_and_provider_down(auth_client: AuthClient) -> None:
    client, _, _, provider, _ = auth_client
    response = client.get("/api/auth/callback?code=synthetic&state=invalid", headers={"Accept": "text/html"})
    assert response.status_code == 303
    assert response.headers["location"] == "/?auth_error=failed"
    provider.error = OIDCUnavailable()
    response = client.get("/api/auth/login", headers={"Accept": "text/html"})
    assert response.status_code == 303
    assert response.headers["location"] == "/?auth_error=unavailable"


def test_successful_callback_marks_only_fixed_login_event(auth_client: AuthClient) -> None:
    client, _, _, _, _ = auth_client
    state, _ = login(client)
    response = client.get("/api/auth/callback", params={"code": "synthetic", "state": state})
    assert response.status_code == 303
    assert response.headers["location"] == "/?auth_event=login"
    assert "code=" not in response.headers["location"] and "state=" not in response.headers["location"]
