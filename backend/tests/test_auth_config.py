"""Configuración e identidad de la demo OIDC (docs/PLAN_MVP.md §17, A0)."""

import os
import subprocess
import sys
from typing import Any

import pytest
from pydantic import ValidationError

from cerberus_api.config import REPO_ROOT, Settings

ISSUER = "https://identity.example/realms/cerberus"
SECRET = "secreto-sintetico-solo-para-tests"


def test_collection_isolates_and_restores_external_auth_environment() -> None:
    code = (
        "import os, pytest; "
        "result = pytest.main(['backend/tests/test_api_studies.py', '--collect-only', '-q']); "
        "assert os.environ['CERBERUS_AUTH_MODE'] == 'oidc'; "
        "assert os.environ['CERBERUS_APP_ORIGIN'] == 'origen-invalido'; "
        "raise SystemExit(result)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=os.environ | {"CERBERUS_AUTH_MODE": "oidc", "CERBERUS_APP_ORIGIN": "origen-invalido"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def oidc_settings(**overrides: Any) -> Settings:
    """Configuración explícita sin proveedor ni conexiones de red."""
    values: dict[str, Any] = {
        "auth_mode": "oidc",
        "app_origin": "https://cerberus.example",
        "oidc_issuer_url": ISSUER,
        "oidc_client_secret": SECRET,
    }
    values.update(overrides)
    return Settings(**values)


def test_local_mode_does_not_require_oidc() -> None:
    settings = Settings()
    assert settings.auth_mode == "off"
    assert settings.app_origin == "http://localhost:5173"
    assert settings.oidc_issuer_url is None
    assert settings.oidc_backchannel_url is None
    assert settings.oidc_client_secret is None
    assert settings.auth_cookie_secure is True
    assert settings.auth_idle_timeout_seconds == 1800
    assert settings.auth_absolute_timeout_seconds == 3600


def test_oidc_defaults_and_exact_issuer() -> None:
    settings = oidc_settings(oidc_issuer_url=ISSUER + "/")
    assert settings.auth_mode == "oidc"
    assert settings.oidc_client_id == "cerberus-web"
    assert settings.oidc_issuer_url == ISSUER + "/"
    assert settings.oidc_backchannel_url == ISSUER + "/"


def test_oidc_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in {
        "AUTH_MODE": "oidc",
        "APP_ORIGIN": "http://localhost:8080",
        "OIDC_ISSUER_URL": "http://localhost:8081/realms/cerberus",
        "OIDC_BACKCHANNEL_URL": "http://keycloak:8080/realms/cerberus",
        "OIDC_CLIENT_ID": "otro-cliente",
        "OIDC_CLIENT_SECRET": SECRET,
        "AUTH_COOKIE_SECURE": "false",
        "AUTH_IDLE_TIMEOUT_SECONDS": "60",
        "AUTH_ABSOLUTE_TIMEOUT_SECONDS": "120",
    }.items():
        monkeypatch.setenv(f"CERBERUS_{name}", value)
    settings = Settings()
    assert settings.auth_mode == "oidc"
    assert settings.app_origin == "http://localhost:8080"
    assert settings.oidc_issuer_url == "http://localhost:8081/realms/cerberus"
    assert settings.oidc_backchannel_url == "http://keycloak:8080/realms/cerberus"
    assert settings.oidc_client_id == "otro-cliente"
    assert settings.oidc_client_secret is not None
    assert settings.oidc_client_secret.get_secret_value() == SECRET
    assert settings.auth_cookie_secure is False
    assert settings.auth_idle_timeout_seconds == 60
    assert settings.auth_absolute_timeout_seconds == 120


@pytest.mark.parametrize("mode", ["", "OIDC", "auto", "disabled"])
def test_unknown_mode_rejected(mode: str) -> None:
    with pytest.raises(ValidationError):
        Settings(auth_mode=mode)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("oidc_issuer_url", None),
        ("oidc_issuer_url", ""),
        ("oidc_client_secret", None),
        ("oidc_client_secret", ""),
        ("oidc_client_secret", "   "),
        ("oidc_client_id", ""),
        ("oidc_client_id", "   "),
    ],
)
def test_oidc_requires_provider_and_credentials(field: str, value: str | None) -> None:
    with pytest.raises(ValidationError):
        oidc_settings(**{field: value})


def test_secrets_hidden_in_settings_and_validation_errors() -> None:
    settings = oidc_settings()
    assert SECRET not in repr(settings)
    assert SECRET not in settings.model_dump_json()
    with pytest.raises(ValidationError) as error:
        oidc_settings(auth_absolute_timeout_seconds=1)
    assert SECRET not in str(error.value)


def test_malformed_url_error_does_not_echo_embedded_credentials() -> None:
    with pytest.raises(ValidationError) as error:
        oidc_settings(oidc_issuer_url=f"https://user:{SECRET}@identity.example:wrong")
    assert SECRET not in str(error.value)


@pytest.mark.parametrize("origin", ["http://localhost:8080", "http://127.0.0.1:8080", "http://[::1]:8080"])
def test_insecure_cookie_allowed_for_http_loopback(origin: str) -> None:
    assert oidc_settings(app_origin=origin, auth_cookie_secure=False).auth_cookie_secure is False


@pytest.mark.parametrize(
    "origin",
    [
        "http://cerberus.example",
        "http://192.168.1.2:8080",
        "http://0.0.0.0:8080",
        "http://localhost.attacker.example",
        "http://127.0.0.1.attacker.example",
        "http://localhost.",
        "http://127.1:8080",
        "http://2130706433:8080",
        "https://localhost:8080",
        "https://cerberus.example",
    ],
)
def test_insecure_cookie_rejected_elsewhere(origin: str) -> None:
    with pytest.raises(ValidationError):
        oidc_settings(app_origin=origin, auth_cookie_secure=False)


@pytest.mark.parametrize("field", ["app_origin", "oidc_issuer_url"])
def test_public_http_requires_loopback_even_with_secure_cookie(field: str) -> None:
    with pytest.raises(ValidationError):
        oidc_settings(**{field: "http://public.example"})


@pytest.mark.parametrize(
    "url",
    [
        "https://user:password@cerberus.example",
        "https://cerberus.example?redirect=elsewhere",
        "https://cerberus.example#fragment",
        "https://cerberus.example?",
        "https://cerberus.example#",
        "https://cerberus.example:99999",
        "https://cerberus.example:wrong",
        "https://",
        "//cerberus.example",
        "ftp://cerberus.example",
        "https://cerberus.example\n",
        " https://cerberus.example",
        "https://cerberus.exa mple",
        "https://cerberus.example\\@localhost",
    ],
)
@pytest.mark.parametrize("field", ["app_origin", "oidc_issuer_url", "oidc_backchannel_url"])
def test_invalid_auth_urls_rejected(field: str, url: str) -> None:
    with pytest.raises(ValidationError):
        oidc_settings(**{field: url})


@pytest.mark.parametrize("path", ["/", "/app", "/api/auth/callback"])
def test_app_origin_cannot_include_path(path: str) -> None:
    with pytest.raises(ValidationError):
        oidc_settings(app_origin="https://cerberus.example" + path)


def test_internal_backchannel_does_not_replace_public_issuer() -> None:
    settings = oidc_settings(oidc_backchannel_url="http://keycloak:8080/realms/cerberus")
    assert settings.oidc_issuer_url == ISSUER
    assert settings.oidc_backchannel_url == "http://keycloak:8080/realms/cerberus"


@pytest.mark.parametrize("field", ["auth_idle_timeout_seconds", "auth_absolute_timeout_seconds"])
@pytest.mark.parametrize("value", [0, -1])
def test_timeouts_must_be_positive(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        oidc_settings(**{field: value})


def test_absolute_timeout_cannot_be_less_than_idle() -> None:
    with pytest.raises(ValidationError):
        oidc_settings(auth_idle_timeout_seconds=60, auth_absolute_timeout_seconds=59)
    assert oidc_settings(auth_idle_timeout_seconds=60, auth_absolute_timeout_seconds=60)


def test_oidc_rejects_cors_wildcards() -> None:
    with pytest.raises(ValidationError):
        oidc_settings(cors_origins=["*"])
    assert Settings(cors_origins=["*"]).auth_mode == "off"


def test_principal_is_immutable_and_uses_issuer_and_subject() -> None:
    from cerberus_api.identity import Principal

    principal = Principal(issuer=ISSUER, sub="subject-1", roles=frozenset({"analyst"}))
    assert principal != Principal(issuer="https://other.example", sub="subject-1", roles=principal.roles)
    assert principal.roles == frozenset({"analyst"})
    with pytest.raises(ValidationError):
        principal.sub = "otro"


@pytest.mark.parametrize(
    "values",
    [{"issuer": ""}, {"sub": ""}, {"roles": []}, {"roles": ["admin"]}],
)
def test_principal_rejects_empty_identity_and_unknown_roles(values: dict[str, Any]) -> None:
    from cerberus_api.identity import Principal

    data = {"issuer": ISSUER, "sub": "subject-1", "roles": ["reader"]} | values
    with pytest.raises(ValidationError):
        Principal.model_validate(data)


def test_public_auth_contracts_serialize_without_identity_or_secrets() -> None:
    from cerberus_api.schemas import AuthConfig, AuthSession

    assert AuthConfig(mode="off").model_dump(mode="json") == {"mode": "off"}
    assert AuthConfig(mode="oidc").model_dump(mode="json") == {"mode": "oidc"}
    session = AuthSession.model_validate(
        {"roles": ["analyst"], "expires_at": "2026-11-05T12:00:00Z", "csrf_token": "csrf-sintetico"}
    )
    assert session.model_dump(mode="json") == {
        "roles": ["analyst"],
        "expires_at": "2026-11-05T12:00:00Z",
        "csrf_token": "csrf-sintetico",
    }


@pytest.mark.parametrize(
    "values", [{"roles": ["admin"]}, {"roles": []}, {"expires_at": "2026-11-05T12:00:00"}, {"csrf_token": ""}]
)
def test_public_session_rejects_invalid_payload(values: dict[str, Any]) -> None:
    from cerberus_api.schemas import AuthSession

    data = {"roles": ["reader"], "expires_at": "2026-11-05T12:00:00Z", "csrf_token": "csrf-sintetico"} | values
    with pytest.raises(ValidationError):
        AuthSession.model_validate(data)
