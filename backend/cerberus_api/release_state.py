"""Guardas de actualización: paquetes íntegros y compatibilidad de identidad explícita."""

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

IDENTITY_SERVICES = ("auth-db", "keycloak", "redis")


def verify_package(root: Path) -> dict[str, Any]:
    """Verifica checksums locales antes de tocar la instalación; nunca acepta enlaces ni rutas externas."""
    checksums = root / "SHA256SUMS"
    if checksums.is_symlink():
        raise ValueError("Lista de integridad inválida")
    verified: set[str] = set()
    for line in checksums.read_text().splitlines():
        match = re.fullmatch(r"([a-f0-9]{64})  (.+)", line)
        if match is None:
            raise ValueError("Lista de integridad inválida")
        digest, name = match.groups()
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts or "\\" in name or name in verified:
            raise ValueError("Ruta de paquete inválida")
        path = root / name
        if any(parent.is_symlink() for parent in (path, *path.parents)) or not path.is_file():
            raise ValueError("Archivo de paquete ausente o enlazado")
        if hashlib.file_digest(path.open("rb"), "sha256").hexdigest() != digest:
            raise ValueError("Paquete corrupto; versión actual conservada")
        verified.add(name)
    if not {"compose.yaml", "release.json"}.issubset(verified):
        raise ValueError("Paquete incompleto")
    manifest = json.loads((root / "release.json").read_text())
    if manifest.get("format") != 1 or not re.fullmatch(r"[a-f0-9]{40}", manifest.get("revision", "")):
        raise ValueError("Manifest incompatible")
    compose = json.loads((root / "compose.yaml").read_text())
    for component, services in {
        "backend": ("api", "worker", "setup-secrets", "setup-identity"),
        "frontend": ("frontend",),
    }.items():
        image = manifest["images"][component]
        if re.fullmatch(r"[a-z0-9./:_-]+@sha256:[a-f0-9]{64}", image) is None:
            raise ValueError("Imagen sin digest")
        if any(compose["services"][service]["image"] != image for service in services):
            raise ValueError("Imágenes mezcladas")
    return compose


def check_update(current: Mapping[str, Any], candidate: Mapping[str, Any], active_jobs: int) -> None:
    """No mezcla upgrades de identidad ni actualiza con trabajos activos."""
    if active_jobs != 0:
        raise ValueError("Hay trabajos activos o no se pudo comprobar la cola; posponer actualización")
    for service in IDENTITY_SERVICES:
        if current["services"][service]["image"] != candidate["services"][service]["image"]:
            raise ValueError("Cambio de identidad requiere backup y restauración validados por separado")
    if current.get("name") != candidate.get("name") or current.get("volumes") != candidate.get("volumes"):
        raise ValueError("Identidad del proyecto o volúmenes incompatibles")
