"""Genera el Compose de distribución desde el contrato de desarrollo, sin secretos del host."""

import copy
import json
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
MIN_COMPOSE = "2.30.0"


def distribution_config(source: dict[str, Any], backend: str, frontend: str) -> dict[str, Any]:
    """Conserva auth/redes/volúmenes; elimina builds y ordena permisos antes de escribir."""
    for image in (backend, frontend):
        if re.fullmatch(r"[a-z0-9./:_-]+@sha256:[a-f0-9]{64}", image) is None:
            raise ValueError("Las imágenes de distribución requieren digest SHA-256")
    result = copy.deepcopy(source)
    for key in list(result):
        if key.startswith("x-"):
            del result[key]
    services = result["services"]
    for name, service in services.items():
        service.pop("build", None)
        if name in {"api", "worker", "setup-secrets", "setup-identity"}:
            service["image"] = backend
        elif name == "frontend":
            service["image"] = frontend
    # El worker de desarrollo dependía solo de Redis; la distribución necesita escritura preparada.
    services["worker"]["depends_on"]["setup-secrets"] = {"condition": "service_completed_successfully"}
    services["setup-secrets"]["volumes"].append(
        {"type": "bind", "source": "${CERBERUS_DATA_PATH:-./Data}", "target": "/app/Data"}
    )
    services["setup-secrets"]["environment"]["CERBERUS_PREPARE_DATA"] = "true"
    return result


def source_config() -> dict[str, Any]:
    """Lee únicamente el YAML, sin resolver rutas, archivos de secretos ni variables locales."""
    output = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(ROOT / "compose.yaml"),
            "config",
            "--no-interpolate",
            "--no-env-resolution",
            "--no-path-resolution",
            "--no-normalize",
            "--format",
            "json",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return json.loads(output.stdout)
