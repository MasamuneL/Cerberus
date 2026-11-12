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


def test_migration_uses_runtime_project_ports_and_mounts(tmp_path: Path) -> None:
    containers = []
    mounts = {
        "api": [("oidc-client-secret", "/run/cerberus/client")],
        "redis": [("redis-data", "/data")],
        "auth-db": [("auth-db-data", "/var/lib/postgresql"), ("auth-db-secret", "/run/cerberus/db")],
        "keycloak": [("keycloak-data", "/opt/keycloak/data"), ("keycloak-admin-secret", "/run/cerberus/admin")],
        "frontend": [],
    }
    for service, volumes in mounts.items():
        container = {
            "Config": {
                "Labels": {
                    "com.docker.compose.project": "clase",
                    "com.docker.compose.project.working_dir": str(tmp_path),
                    "com.docker.compose.service": service,
                },
                "User": "1002:1003",
                "Env": ["CERBERUS_APP_ORIGIN=http://localhost:18990", "SECRET=never-export"],
            },
            "HostConfig": {
                "PortBindings": {
                    "8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "18990" if service == "frontend" else "18991"}]
                }
            },
            "Mounts": [
                {"Type": "volume", "Name": "clase_" + volume, "Destination": target} for volume, target in volumes
            ],
        }
        if service == "api":
            container["Mounts"].extend(
                {"Type": "bind", "Source": str(tmp_path / name), "Destination": target}
                for name, target in (
                    ("datos con ñ", "/app/Data"),
                    ("results", "/app/storage"),
                    ("models", "/app/models"),
                )
            )
        containers.append(container)
    config = migration.runtime_config(containers, tmp_path)
    result = migration.migration_environment(config, tmp_path)
    assert result["COMPOSE_PROJECT_NAME"] == "clase"
    assert result["CERBERUS_HTTP_PORT"] == "18990"
    assert result["CERBERUS_KEYCLOAK_HTTP_PORT"] == "18991"
    assert result["CERBERUS_DATA_PATH"] == str(tmp_path / "datos con ñ")
    assert "never-export" not in str(result)
    with pytest.raises(ValueError, match="ambigua"):
        migration.runtime_config([*containers, containers[0]], tmp_path)
    with pytest.raises(ValueError):
        migration.runtime_config([], tmp_path)
