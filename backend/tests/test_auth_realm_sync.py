"""Actualización acotada del proveedor: transporte falso, sin red ni credenciales reales."""

import copy
import json
import runpy
from pathlib import Path
from urllib.parse import parse_qs

import httpx2 as httpx
import pytest

from cerberus_api.config import REPO_ROOT

SYNC = runpy.run_path(str(REPO_ROOT / "tools/auth/sync_realm.py"))
SECRET = "fake-admin-password-only-for-offline-tests"
TOKEN = "fake-token-only-for-offline-tests"
ENV = {"CERBERUS_KEYCLOAK_ADMIN_PASSWORD": SECRET}


def test_patch_changes_only_presentation_remember_and_locales() -> None:
    current = {
        "realm": "cerberus",
        "displayName": "Anterior",
        "loginTheme": "keycloak",
        "rememberMe": False,
        "supportedLocales": ["fr", "es"],
        "defaultLocale": "fr",
        "ssoSessionIdleTimeout": 73,
        "ssoSessionMaxLifespan": 91,
        "ssoSessionIdleTimeoutRememberMe": 6500,
        "ssoSessionMaxLifespanRememberMe": 9000,
        "clients": [{"redirectUris": ["https://example.test/callback"]}],
        "users": [{"username": "preservado", "credentials": ["sin cambios"]}],
        "roles": {"realm": ["propio"]},
        "attributes": {"custom": "value"},
    }
    original = copy.deepcopy(current)
    patch = SYNC["build_realm_patch"](current)
    assert current == original
    assert set(patch) == {
        "displayName",
        "loginTheme",
        "rememberMe",
        "internationalizationEnabled",
        "supportedLocales",
        "defaultLocale",
    }
    assert patch["rememberMe"] is True
    assert patch["loginTheme"] == "cerberus"
    assert patch["supportedLocales"] == ["en", "es", "fr"]
    assert SYNC["build_realm_patch"](current | patch) == {}


def test_sync_is_idempotent_and_preserves_existing_realm(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    realm = {
        "realm": "cerberus",
        "clients": [{"redirectUris": ["https://example.test/custom"]}],
        "users": [{"username": "existing"}],
        "roles": {"custom": "existing"},
        "ssoSessionIdleTimeout": 120,
        "supportedLocales": ["de"],
    }
    original = copy.deepcopy(realm)
    calls: list[tuple[str, str]] = []
    updates: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/token"):
            data = parse_qs(request.content.decode())
            assert request.method == "POST"
            assert data == {
                "grant_type": ["password"],
                "client_id": ["admin-cli"],
                "username": ["cerberus-admin"],
                "password": [SECRET],
            }
            assert not request.url.query
            return httpx.Response(200, json={"access_token": TOKEN})
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        if request.url.path == "/admin/realms/cerberus/partialImport":
            assert request.method == "POST"
            assert json.loads(request.content)["ifResourceExists"] == "SKIP"
            return httpx.Response(200, json={"added": 0, "skipped": 1})
        assert request.url.path == "/admin/realms/cerberus"
        if request.method == "GET":
            return httpx.Response(200, json=realm)
        assert request.method == "PUT"
        patch = json.loads(request.content)
        updates.append(patch)
        realm.update(patch)
        return httpx.Response(204)

    for _ in range(2):
        assert SYNC["main"](["--env-file", str(tmp_path / "absent")], ENV, httpx.MockTransport(respond)) == 0
    assert len(updates) == 1
    assert calls == [
        ("POST", "/realms/master/protocol/openid-connect/token"),
        ("GET", "/admin/realms/cerberus"),
        ("PUT", "/admin/realms/cerberus"),
        ("POST", "/admin/realms/cerberus/partialImport"),
        ("POST", "/realms/master/protocol/openid-connect/token"),
        ("GET", "/admin/realms/cerberus"),
        ("POST", "/admin/realms/cerberus/partialImport"),
    ]
    for key in ("clients", "users", "roles", "ssoSessionIdleTimeout"):
        assert realm[key] == original[key]
    output = capsys.readouterr()
    assert SECRET not in output.out + output.err
    assert TOKEN not in output.out + output.err
    assert "sin cambios" in output.out.lower()


def test_env_file_is_literal_and_environment_wins(tmp_path: Path) -> None:
    path = tmp_path / ".env.auth"
    path.write_text(
        '# local\nCERBERUS_KEYCLOAK_ADMIN_PASSWORD="file_password"\n'
        "CERBERUS_KEYCLOAK_ADMIN_USERNAME='demo-admin'\n"
        "CERBERUS_KEYCLOAK_HTTP_PORT=8089\nUNRELATED_SECRET=ignored\n"
    )
    settings = SYNC["read_settings"](path, ENV)
    assert settings == ENV | {"CERBERUS_KEYCLOAK_ADMIN_USERNAME": "demo-admin", "CERBERUS_KEYCLOAK_HTTP_PORT": "8089"}
    assert SYNC["read_settings"](tmp_path / "absent", ENV) == ENV


@pytest.mark.parametrize("body", [{}, {"access_token": ""}, {"access_token": 7}, [TOKEN]])
def test_invalid_token_response_has_no_update(tmp_path: Path, body: object) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/token")
        return httpx.Response(200, json=body)

    assert SYNC["main"](["--env-file", str(tmp_path / "absent")], ENV, httpx.MockTransport(respond)) == 1


@pytest.mark.parametrize("status", [302, 401, 403, 404, 500])
def test_remote_errors_do_not_echo_bodies_or_follow_redirects(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    status: int,
) -> None:
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, text=f"{SECRET} {TOKEN}", headers={"Location": "https://elsewhere.test"})

    assert SYNC["main"](["--env-file", str(tmp_path / "absent")], ENV, httpx.MockTransport(respond)) == 1
    assert calls == 1
    output = capsys.readouterr()
    assert SECRET not in output.out + output.err
    assert TOKEN not in output.out + output.err


@pytest.mark.parametrize(
    "environment",
    [
        {},
        ENV | {"CERBERUS_KEYCLOAK_HTTP_PORT": "bad"},
        ENV | {"CERBERUS_KEYCLOAK_HTTP_PORT": "65536"},
        ENV | {"CERBERUS_KEYCLOAK_ADMIN_USERNAME": ""},
    ],
)
def test_invalid_settings_do_not_contact_provider(tmp_path: Path, environment: dict[str, str]) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        pytest.fail("La configuración inválida no debe enviar credenciales")

    assert SYNC["main"](["--env-file", str(tmp_path / "absent")], environment, httpx.MockTransport(respond)) == 1


def test_transport_timeout_is_recoverable_and_redacted(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(SECRET, request=request)

    assert SYNC["main"](["--env-file", str(tmp_path / "absent")], ENV, httpx.MockTransport(respond)) == 1
    output = capsys.readouterr()
    assert SECRET not in output.out + output.err


def test_realm_seed_and_theme_preserve_provider_forms() -> None:
    seed = json.loads((REPO_ROOT / "docker/keycloak/realm.json").read_text())
    theme = REPO_ROOT / "docker/keycloak/themes/cerberus/login"
    assert seed["loginTheme"] == "cerberus"
    assert seed["rememberMe"] is True
    assert seed["ssoSessionIdleTimeoutRememberMe"] == seed["ssoSessionMaxLifespanRememberMe"] == 0
    assert "parent=keycloak.v2" in (theme / "theme.properties").read_text()
    assert not (theme / "login.ftl").exists()
    assert not (theme / "template.ftl").exists()
    footer = (theme / "footer.ftl").read_text()
    assert "<#macro content>" in footer
    assert "cerberusRememberHelp" in footer


def test_realm_seed_creates_demo_analyst_without_password_change_required() -> None:
    seed = json.loads((REPO_ROOT / "docker/keycloak/realm.json").read_text())
    assert seed["users"] == [
        {
            "username": "demo",
            "firstName": "Demo",
            "lastName": "Cerberus",
            "email": "demo@example.invalid",
            "enabled": True,
            "requiredActions": [],
            "credentials": [{"type": "password", "value": "demo", "temporary": False}],
            "clientRoles": {"cerberus-web": ["analyst"]},
        }
    ]


@pytest.mark.parametrize("added", [0, 1])
def test_sync_imports_only_missing_demo_with_skip_policy(added: int) -> None:
    calls: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": TOKEN})
        if request.url.path == "/admin/realms/cerberus" and request.method == "GET":
            return httpx.Response(
                200,
                json=SYNC["DESIRED_FIELDS"]
                | {
                    "realm": "cerberus",
                    "supportedLocales": ["es", "en"],
                },
            )
        assert request.method == "POST"
        assert request.url.path == "/admin/realms/cerberus/partialImport"
        body = json.loads(request.content)
        assert body["ifResourceExists"] == "SKIP"
        assert set(body) == {"ifResourceExists", "users"}
        assert body["users"] == json.loads((REPO_ROOT / "docker/keycloak/realm.json").read_text())["users"]
        calls.append(body)
        return httpx.Response(200, json={"added": added, "skipped": 1 - added})

    with httpx.Client(base_url="http://localhost:8081", transport=httpx.MockTransport(respond)) as client:
        changed = SYNC["sync_realm"](client, "cerberus-admin", SECRET)
    assert calls
    assert changed == (["demo"] if added else [])


def test_failed_demo_import_is_reported_without_credentials(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": TOKEN})
        if request.url.path.endswith("/partialImport"):
            return httpx.Response(500, text=SECRET)
        if request.method == "GET":
            return httpx.Response(200, json={"realm": "cerberus"})
        return httpx.Response(204)

    assert SYNC["main"](["--env-file", str(tmp_path / "absent")], ENV, httpx.MockTransport(respond)) == 1
    output = capsys.readouterr()
    assert SECRET not in output.out + output.err


@pytest.mark.parametrize("body", [{}, [], {"added": True}, {"added": -1}, {"added": 2}, {"added": "1"}])
def test_unexpected_import_result_is_recoverable(tmp_path: Path, body: object) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": TOKEN})
        if request.url.path.endswith("/partialImport"):
            return httpx.Response(200, json=body)
        if request.method == "GET":
            return httpx.Response(200, json={"realm": "cerberus"})
        return httpx.Response(204)

    assert SYNC["main"](["--env-file", str(tmp_path / "absent")], ENV, httpx.MockTransport(respond)) == 1


@pytest.mark.parametrize(
    "realm",
    [
        [],
        {"realm": "master"},
        {"realm": "cerberus", "supportedLocales": "es"},
        {"realm": "cerberus", "supportedLocales": [7]},
    ],
)
def test_unexpected_realm_or_locales_never_update(tmp_path: Path, realm: object) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": TOKEN})
        assert request.method == "GET"
        return httpx.Response(200, json=realm)

    assert SYNC["main"](["--env-file", str(tmp_path / "absent")], ENV, httpx.MockTransport(respond)) == 1


def test_locale_order_is_not_a_configuration_change() -> None:
    current = SYNC["DESIRED_FIELDS"] | {"supportedLocales": ["es", "en"]}
    assert SYNC["build_realm_patch"](current) == {}


@pytest.mark.parametrize("failing_method", ["GET", "PUT"])
def test_realm_read_or_write_failure_is_recoverable(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    failing_method: str,
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.extensions["timeout"]["read"] == 10
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": TOKEN})
        if request.method == failing_method:
            return httpx.Response(403, text=SECRET)
        assert request.method == "GET"
        return httpx.Response(200, json={"realm": "cerberus"})

    assert SYNC["main"](["--env-file", str(tmp_path / "absent")], ENV, httpx.MockTransport(respond)) == 1
    output = capsys.readouterr()
    assert SECRET not in output.out + output.err
