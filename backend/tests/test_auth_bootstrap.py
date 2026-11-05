"""Bootstrap local: secretos privados y repetición sin sobrescribir configuración."""

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from cerberus_api.config import REPO_ROOT

SECRET_NAMES = (
    "CERBERUS_AUTH_DB_PASSWORD",
    "CERBERUS_KEYCLOAK_ADMIN_PASSWORD",
    "CERBERUS_OIDC_CLIENT_SECRET",
)


def run_bootstrap(path: Path, values: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = {key: value for key, value in os.environ.items() if key not in SECRET_NAMES}
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools/auth/bootstrap.py"), "--env-file", str(path)],
        env=env | (values or {}),
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_bootstrap_creates_private_distinct_secrets(tmp_path: Path) -> None:
    path = tmp_path / ".env.auth"
    result = run_bootstrap(path)
    assert result.returncode == 0, result.stderr
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    values = dict(line.split("=", 1) for line in path.read_text().splitlines() if line and not line.startswith("#"))
    assert set(values) == set(SECRET_NAMES)
    assert len(set(values.values())) == 3
    for value in values.values():
        assert len(value) >= 32
        assert value not in result.stdout + result.stderr


def test_bootstrap_uses_environment_and_does_not_overwrite(tmp_path: Path) -> None:
    path = tmp_path / ".env.auth"
    supplied = {name: f"secret_{index}_" + "x" * 40 for index, name in enumerate(SECRET_NAMES)}
    assert run_bootstrap(path, supplied).returncode == 0
    original = path.read_bytes()
    for key, value in supplied.items():
        assert f"{key}={value}" in original.decode()
    assert run_bootstrap(path).returncode == 0
    assert path.read_bytes() == original


@pytest.mark.parametrize("value", ["", "short", "x" * 32 + "\nINJECTED=true", "x" * 32 + "$VAR"])
def test_bootstrap_rejects_unsafe_environment_without_echo(tmp_path: Path, value: str) -> None:
    path = tmp_path / ".env.auth"
    result = run_bootstrap(path, {"CERBERUS_OIDC_CLIENT_SECRET": value})
    assert result.returncode != 0
    assert "CERBERUS_OIDC_CLIENT_SECRET requiere" in result.stderr
    assert not path.exists()
    if value:
        assert value not in result.stdout + result.stderr


def test_bootstrap_does_not_replace_existing_symlink(tmp_path: Path) -> None:
    target = tmp_path / "existing"
    target.write_text("configuración existente")
    path = tmp_path / ".env.auth"
    path.symlink_to(target)
    assert run_bootstrap(path).returncode == 0
    assert path.is_symlink()
    assert target.read_text() == "configuración existente"
