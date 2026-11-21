"""Override `compose.gpu.yaml` (HW1/HW2): variante de torch del worker según `CERBERUS_TORCH_VARIANT`."""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from cerberus_api.config import REPO_ROOT


@pytest.fixture
def _require_docker_cli() -> None:
    if shutil.which("docker") is None:
        pytest.skip("Requiere el CLI Docker Compose; no utiliza el daemon ni red")
    probe = subprocess.run(["docker", "compose", "version"], capture_output=True, timeout=15, check=False)
    if probe.returncode != 0:
        pytest.skip("Requiere el plugin Docker Compose v2")


def _worker_config(tmp_path: Path, variant: str | None) -> dict[str, Any]:
    """Servicio `worker` de `docker compose config` sobre copias de los YAML, con `CERBERUS_*` limpio."""
    for name in ("compose.yaml", "compose.gpu.yaml"):
        shutil.copyfile(REPO_ROOT / name, tmp_path / name)
    environment = {name: value for name, value in os.environ.items() if not name.startswith("CERBERUS_")}
    if variant is not None:
        environment["CERBERUS_TORCH_VARIANT"] = variant
    result = subprocess.run(
        ["docker", "compose", "-f", "compose.yaml", "-f", "compose.gpu.yaml", "config", "--format", "json"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    worker: dict[str, Any] = json.loads(result.stdout)["services"]["worker"]
    return worker


@pytest.mark.usefixtures("_require_docker_cli")
@pytest.mark.parametrize(("variant", "expected"), [(None, "cu126"), ("cu130", "cu130")])
def test_gpu_override_tags_image_and_build_arg_by_variant(tmp_path: Path, variant: str | None, expected: str) -> None:
    worker = _worker_config(tmp_path, variant)
    assert worker["image"] == f"cerberus-backend:{expected}"
    assert worker["build"]["args"]["TORCH_VARIANT"] == expected
    assert worker["deploy"]["resources"]["reservations"]["devices"][0]["capabilities"] == ["gpu"]


def test_dockerfile_accepts_every_torch_group() -> None:
    """El `case` del Dockerfile acepta exactamente las variantes `torch-*` de pyproject.toml."""
    dockerfile = (REPO_ROOT / "docker" / "backend.Dockerfile").read_text(encoding="utf-8")
    accepted = re.search(r'case "\$TORCH_VARIANT" in ([a-z0-9|]+)\)', dockerfile)
    assert accepted is not None
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    groups = set(re.findall(r"^torch-([a-z0-9]+) = ", pyproject, flags=re.MULTILINE))
    assert set(accepted.group(1).split("|")) == groups == {"cpu", "cu126", "cu130"}
