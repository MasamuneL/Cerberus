"""Arranque Compose: secretos persistentes y migración sin red ni contenedores."""

import importlib
import json
import stat
from pathlib import Path
from types import ModuleType

import httpx2 as httpx
import pytest


def setup_module_api() -> ModuleType:
    """Carga el inicializador y presenta su ausencia como la función pendiente."""
    try:
        return importlib.import_module("cerberus_api.container_setup")
    except ModuleNotFoundError:
        pytest.fail("Falta la inicialización automática de Compose")


def test_fresh_setup_generates_distinct_persistent_secrets(tmp_path: Path) -> None:
    setup = setup_module_api()
    database = tmp_path / "database"
    database.mkdir()
    root = tmp_path / "secrets"
    setup.prepare_secrets(root, database, {})
    values = {name: setup.read_secret(root / relative) for name, relative in setup.SECRET_FILES.items()}
    assert len(set(values.values())) == 3
    assert all(len(value) >= 32 for value in values.values())
    original = {p: p.read_bytes() for p in root.rglob("secret")}
    setup.prepare_secrets(root, database, {})
    assert all(p.read_bytes() == value for p, value in original.items())
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o444 for p in original)


def test_migration_adopts_existing_secrets_without_reset(tmp_path: Path) -> None:
    setup = setup_module_api()
    database = tmp_path / "database"
    database.mkdir()
    (database / "18").mkdir()
    values = {name: f"test_{index}_" + "x" * 40 for index, name in enumerate(setup.SECRET_FILES)}
    root = tmp_path / "secrets"
    setup.prepare_secrets(root, database, values)
    assert {name: setup.read_secret(root / relative) for name, relative in setup.SECRET_FILES.items()} == values
    setup.prepare_secrets(root, database, {})


def test_explicit_compose_seeds_take_priority_over_optional_legacy_file(tmp_path: Path) -> None:
    setup = setup_module_api()
    database = tmp_path / "database"
    database.mkdir()
    (database / "18").mkdir()
    environment = {name: "old_" + "x" * 40 for name in setup.SECRET_FILES}
    environment.update(
        {"CERBERUS_SEED_" + name.removeprefix("CERBERUS_"): "explicit_" + "y" * 40 for name in setup.SECRET_FILES}
    )
    root = tmp_path / "secrets"
    setup.prepare_secrets(root, database, environment)
    assert all(setup.read_secret(root / path) == "explicit_" + "y" * 40 for path in setup.SECRET_FILES.values())


def test_existing_database_without_recoverable_secrets_fails_closed(tmp_path: Path) -> None:
    setup = setup_module_api()
    database = tmp_path / "database"
    database.mkdir()
    (database / "18").mkdir()
    with pytest.raises(ValueError, match="existente"):
        setup.prepare_secrets(tmp_path / "secrets", database, {})
    assert not (tmp_path / "secrets").exists()


@pytest.mark.parametrize("value", ["short", "x" * 32 + "\n", "x" * 32 + "$oops"])
def test_invalid_seed_never_writes_or_echoes_secret(tmp_path: Path, value: str) -> None:
    setup = setup_module_api()
    database = tmp_path / "database"
    database.mkdir()
    with pytest.raises(ValueError) as error:
        setup.prepare_secrets(tmp_path / "secrets", database, {"CERBERUS_AUTH_DB_PASSWORD": value})
    assert value not in str(error.value)
    assert not (tmp_path / "secrets").exists()


def test_persisted_secret_cannot_be_replaced_by_environment(tmp_path: Path) -> None:
    setup = setup_module_api()
    database = tmp_path / "database"
    database.mkdir()
    root = tmp_path / "secrets"
    setup.prepare_secrets(root, database, {})
    before = (root / "db/secret").read_bytes()
    with pytest.raises(ValueError, match="difiere"):
        setup.prepare_secrets(root, database, {"CERBERUS_AUTH_DB_PASSWORD": "other_" + "x" * 40})
    assert (root / "db/secret").read_bytes() == before


def test_backend_loads_only_configured_client_file(tmp_path: Path) -> None:
    setup = setup_module_api()
    path = tmp_path / "client"
    path.write_text("x" * 40)
    environment = {"CERBERUS_OIDC_CLIENT_SECRET_FILE": str(path), "KEEP": "value"}
    result = setup.backend_environment(environment)
    assert result["CERBERUS_OIDC_CLIENT_SECRET"] == "x" * 40
    assert result["KEEP"] == "value"
    assert "CERBERUS_OIDC_CLIENT_SECRET" not in environment
    assert setup.backend_environment({"KEEP": "value"}) == {"KEEP": "value"}


def test_secret_symlink_is_rejected(tmp_path: Path) -> None:
    setup = setup_module_api()
    real = tmp_path / "real"
    real.write_text("x" * 40)
    link = tmp_path / "link"
    link.symlink_to(real)
    with pytest.raises(ValueError):
        setup.read_secret(link)


def test_exec_passes_secret_only_to_child_and_redacts_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    setup = setup_module_api()
    path = tmp_path / "client"
    path.write_text("x" * 40)
    seen: list[object] = []

    def execute(command: str, arguments: list[str], environment: dict[str, str]) -> None:
        assert command == "uvicorn"
        assert arguments == ["uvicorn", "example:app"]
        assert environment["CERBERUS_OIDC_CLIENT_SECRET"] == "x" * 40
        seen.append(command)
        raise OSError("sensitive error " + "x" * 40)

    monkeypatch.setattr(setup.os, "execvpe", execute)
    assert setup.main(["exec", "uvicorn", "example:app"], {"CERBERUS_OIDC_CLIENT_SECRET_FILE": str(path)}) == 1
    assert seen
    output = capsys.readouterr()
    assert "x" * 40 not in output.out + output.err
    assert setup.main(["exec"], {}) == 1


def test_container_sync_uses_internal_provider_and_preserves_admin_secret(tmp_path: Path) -> None:
    setup = setup_module_api()
    (tmp_path / "admin").mkdir()
    (tmp_path / "admin/secret").write_text("x" * 40)
    (tmp_path / "admin/username").write_text("existing-admin")
    origins: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "keycloak"
        if request.url.path.endswith("/token"):
            assert b"existing-admin" in request.content and b"x" * 40 in request.content
            return httpx.Response(200, json={"access_token": "fake-token"})
        if request.url.path.endswith("/partialImport"):
            return httpx.Response(200, json={"added": 0})
        if request.url.path.endswith("/clients"):
            return httpx.Response(200, json=[{"id": "client-id", "clientId": "cerberus-web"}])
        if "/clients/" in request.url.path:
            origins.extend(json.loads(request.content)["webOrigins"])
            return httpx.Response(204)
        if request.method == "GET":
            return httpx.Response(200, json={"realm": "cerberus"})
        return httpx.Response(204)

    assert "client-origin" in setup.synchronize_identity(
        tmp_path, {"CERBERUS_APP_ORIGIN": "http://localhost:8082"}, httpx.MockTransport(respond)
    )
    assert origins == ["http://localhost:8082"]


def test_custom_admin_name_is_persisted_during_migration(tmp_path: Path) -> None:
    setup = setup_module_api()
    database = tmp_path / "database"
    database.mkdir()
    root = tmp_path / "secrets"
    setup.prepare_secrets(root, database, {"CERBERUS_KEYCLOAK_ADMIN_USERNAME": "existing-admin"})
    setup.prepare_secrets(root, database, {})
    assert (root / "admin/username").read_text() == "existing-admin"
    with pytest.raises(ValueError, match="usuario administrativo"):
        setup.prepare_secrets(root, database, {"CERBERUS_KEYCLOAK_ADMIN_USERNAME": "different-admin"})


def test_fresh_writable_directory_gets_container_owner_without_recursive_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup = setup_module_api()
    ownership: list[tuple[Path, int, int]] = []
    monkeypatch.setattr(setup.os, "chown", lambda path, uid, gid: ownership.append((path, uid, gid)))
    setup.prepare_writable_directory(tmp_path, 1001, 1002)
    assert ownership == [(tmp_path, 1001, 1002)]
    marker = tmp_path / "preserved"
    marker.write_text("datos existentes")
    setup.prepare_writable_directory(tmp_path, 1001, 1002)
    assert len(ownership) == 1
    assert marker.read_text() == "datos existentes"


def test_verify_writable_directories(tmp_path: Path) -> None:
    from cerberus_api.container_setup import verify_writable_directories

    environment = {"CERBERUS_VERIFY_WRITABLE": "true"}
    for key in ("DATA", "STORAGE", "MODELS"):
        directory = tmp_path / key
        directory.mkdir()
        environment[f"CERBERUS_{key}_DIR"] = str(directory)
    verify_writable_directories(environment)
    assert all(not list(directory.iterdir()) for directory in tmp_path.iterdir())
    environment["CERBERUS_DATA_DIR"] = str(tmp_path / "missing")
    with pytest.raises(OSError):
        verify_writable_directories(environment)
    verify_writable_directories({})
