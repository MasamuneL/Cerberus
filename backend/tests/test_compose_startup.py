"""Contrato de arranque: Compose resuelve un clon sin secretos y coordina origen/puertos."""

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from cerberus_api.config import REPO_ROOT


@pytest.mark.parametrize("legacy_overlay", [False, True])
@pytest.mark.parametrize("port", ["8080", "8082"])
def test_fresh_compose_requires_no_host_secrets_and_derives_callback(
    tmp_path: Path, legacy_overlay: bool, port: str
) -> None:
    if shutil.which("docker") is None:
        pytest.skip("Requiere el CLI Docker Compose; no utiliza el daemon ni red")
    for name in ("compose.yaml", "compose.auth.yaml"):
        shutil.copyfile(REPO_ROOT / name, tmp_path / name)
    environment = {name: value for name, value in os.environ.items() if not name.startswith("CERBERUS_")}
    environment["CERBERUS_HTTP_PORT"] = port
    command = ["docker", "compose", "-f", "compose.yaml"]
    if legacy_overlay:
        command.extend(["-f", "compose.auth.yaml"])
    result = subprocess.run(
        [*command, "config", "--format", "json"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    services: dict[str, Any] = json.loads(result.stdout)["services"]
    origin = "http://localhost:" + port
    assert services["frontend"]["ports"][0]["published"] == port
    for name in ("api", "keycloak", "setup-identity"):
        assert services[name]["environment"]["CERBERUS_APP_ORIGIN"] == origin
    assert services["api"]["environment"]["CERBERUS_AUTH_MODE"] == "oidc"
    assert services["api"]["depends_on"]["setup-identity"]["condition"] == "service_completed_successfully"
    assert services["auth-db"]["depends_on"]["setup-secrets"]["condition"] == "service_completed_successfully"
    assert "CERBERUS_OIDC_CLIENT_SECRET" not in services["api"]["environment"]
    mounts = services["api"]["volumes"]
    assert not any(v.get("source") in ("auth-db-secret", "keycloak-admin-secret") for v in mounts)
    assert services["setup-secrets"]["network_mode"] == "none"
