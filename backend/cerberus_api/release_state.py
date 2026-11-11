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


async def active_job_count(client: Any) -> int:
    """Cuenta cola y trabajos en ejecución según constantes de arq instalado; falla cerrado."""
    from arq.constants import default_queue_name, in_progress_key_prefix

    count = int(await client.zcard(default_queue_name))
    async for _ in client.scan_iter(match=in_progress_key_prefix + "*"):
        count += 1
    return count


def main() -> int:
    """Comprueba candidato y cola sin escribir configuración ni datos."""
    import argparse
    import asyncio
    import os

    from redis.asyncio import Redis

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    args = parser.parse_args()

    async def validate() -> None:
        client = Redis.from_url(os.environ.get("CERBERUS_REDIS_URL", "redis://redis:6379/0"))
        try:
            count = await active_job_count(client)
            current = verify_package(args.current)
            candidate = verify_package(args.candidate)
            check_update(current, candidate, count)
        finally:
            await client.aclose()

    try:
        asyncio.run(validate())
    except Exception:
        print("Actualización bloqueada: comprueba integridad, compatibilidad de identidad y trabajos activos.")
        return 1
    print("Candidato íntegro y compatible; cola sin trabajos activos.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
