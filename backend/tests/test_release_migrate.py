"""Migración sin Docker: preserva rutas e identidad sin copiar secretos."""

import importlib.util
from pathlib import Path

import pytest

from cerberus_api.config import REPO_ROOT

spec = importlib.util.spec_from_file_location("migration", REPO_ROOT / "tools/release/migrate.py")
assert spec and spec.loader
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


def test_migration_preserves_paths_and_identity(tmp_path: Path) -> None:
    config = {
        "name": "custom",
        "volumes": {
            key: {}
            for key in (
                "redis-data",
                "auth-db-data",
                "keycloak-data",
                "auth-db-secret",
                "keycloak-admin-secret",
                "oidc-client-secret",
            )
        },
        "services": {
            "api": {
                "user": "1001:1002",
                "environment": {"CERBERUS_APP_ORIGIN": "http://localhost:8880"},
                "volumes": [
                    {"type": "bind", "target": target, "source": str(tmp_path / "datos con ñ" / name)}
                    for name, target in (("Data", "/app/Data"), ("storage", "/app/storage"), ("models", "/app/models"))
                ],
            },
            "frontend": {"ports": [{"published": "8880", "host_ip": "127.0.0.1"}]},
            "keycloak": {"ports": [{"published": "8881", "host_ip": "127.0.0.1"}]},
        },
    }
    (tmp_path / ".env.auth").write_text("SYNTHETIC_SECRET=DO_NOT_EXPORT_8675309")
    result = migration.migration_environment(config, tmp_path)
    assert result["COMPOSE_PROJECT_NAME"] == "custom"
    assert result["CERBERUS_DATA_PATH"] == str(tmp_path / "datos con ñ" / "Data")
    assert result["CERBERUS_LEGACY_AUTH_ENV_FILE"] == str(tmp_path / ".env.auth")
    assert "DO_NOT_EXPORT_8675309" not in str(result)
    config["volumes"]["redis-data"] = {"name": "another"}
    with pytest.raises(ValueError):
        migration.migration_environment(config, tmp_path)


def test_environment_is_literal_and_never_replaced(tmp_path: Path) -> None:
    output = tmp_path / ".env"
    migration.write_environment(output, {"CERBERUS_DATA_PATH": "/data with ñ/$(touch pwn)"})
    assert output.read_text() == "CERBERUS_DATA_PATH='/data with ñ/$(touch pwn)'\n"
    with pytest.raises(FileExistsError):
        migration.write_environment(output, {"X": "y"})
    with pytest.raises(ValueError):
        migration.write_environment(tmp_path / "bad", {"X": "a\nb"})
