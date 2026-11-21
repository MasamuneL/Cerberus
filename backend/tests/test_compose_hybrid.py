"""Override `compose.hybrid.yaml` (HW4): sin worker de Docker y Redis solo en loopback."""

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from cerberus_api.config import REPO_ROOT


def _compose_config(tmp_path: Path, *, profiles: tuple[str, ...] = (), redis_port: str | None = None) -> dict[str, Any]:
    """`docker compose config` sobre copias de los YAML (solo CLI: sin daemon ni red) con `CERBERUS_*` limpio."""
    for name in ("compose.yaml", "compose.hybrid.yaml"):
        shutil.copyfile(REPO_ROOT / name, tmp_path / name)
    environment = {name: value for name, value in os.environ.items() if not name.startswith("CERBERUS_")}
    if redis_port is not None:
        environment["CERBERUS_REDIS_PORT"] = redis_port
    command = ["docker", "compose", "-f", "compose.yaml", "-f", "compose.hybrid.yaml"]
    for profile in profiles:
        command.extend(["--profile", profile])
    result = subprocess.run(
        [*command, "config", "--format", "json"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    config: dict[str, Any] = json.loads(result.stdout)
    return config


@pytest.fixture(autouse=True)
def _require_docker_cli() -> None:
    if shutil.which("docker") is None:
        pytest.skip("Requiere el CLI Docker Compose; no utiliza el daemon ni red")


def test_hybrid_override_disables_docker_worker_by_default(tmp_path: Path) -> None:
    services = _compose_config(tmp_path)["services"]
    assert "worker" not in services
    # El resto del stack sigue en Docker
    assert {"api", "redis", "keycloak", "frontend"} <= set(services)


def test_hybrid_override_keeps_worker_behind_docker_worker_profile(tmp_path: Path) -> None:
    services = _compose_config(tmp_path, profiles=("docker-worker",))["services"]
    assert services["worker"]["command"] == ["python", "-m", "cerberus_api.worker"]


@pytest.mark.parametrize(("redis_port", "published"), [(None, "6379"), ("6391", "6391")])
def test_hybrid_override_publishes_redis_only_on_loopback(
    tmp_path: Path, redis_port: str | None, published: str
) -> None:
    redis_ports = _compose_config(tmp_path, redis_port=redis_port)["services"]["redis"]["ports"]
    assert len(redis_ports) == 1
    assert redis_ports[0]["host_ip"] == "127.0.0.1"
    assert redis_ports[0]["published"] == published
    assert redis_ports[0]["target"] == 6379
