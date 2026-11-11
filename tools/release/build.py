"""Construye un ZIP determinista por lista permitida; no construye ni publica imágenes."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

try:
    from .package import ROOT, distribution_config, source_config
except ImportError:
    from package import ROOT, distribution_config, source_config

INSTRUCTIONS = """# Cerberus: instalación persistente

Instala Docker con contenedores Linux y Compose 2.30.0 o posterior. El backend requiere
Linux amd64; Apple Silicon usa emulación. La matriz real de sistemas sigue pendiente de QA.
Extrae el ZIP en una carpeta permanente. No extraigas otra versión encima ni muevas la carpeta.

Ejecuta start.ps1 en Windows, start.command en macOS o ./start.sh en Linux si están incluidos.
Alternativa desde esta carpeta: `docker compose up -d --wait`.
Abre http://localhost:8080 e inicia sesión con demo / demo. Los lanzadores informan la URL
si eligieron otros puertos. Se necesita red en la primera instalación para imágenes y muestra.

Detener conservando datos: `docker compose stop`. Iniciar: `docker compose up -d --wait`.
Conserva Data/, storage/, models/, .env y los volúmenes de Docker. No borres volúmenes.
La actualización es explícita: revisa la guía de actualización incluida antes de cambiar versión.
La cuenta demo es para uso académico local; no expongas el servicio a Internet.

release.json identifica versión, commit y digests. SHA256SUMS contiene los hashes de todos los
archivos del paquete salvo el propio listado. No se incluyen imágenes, DICOM ni secretos locales.
La procedencia, licencia y atribución de la muestra están en docs/D3_SAMPLE.md cuando se incluye.
"""


def release_manifest(version: str, revision: str, backend: str, frontend: str) -> dict[str, Any]:
    """Valida identidad de versión y exige referencias inmutables de ambas imágenes."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", version) or version.lower() in {"latest", "dev"}:
        raise ValueError("La versión debe ser explícita y segura para nombres de archivo")
    if not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError("La revisión requiere un SHA Git completo de 40 caracteres")
    for image in (backend, frontend):
        if not re.fullmatch(r"[a-z0-9./:_-]+@sha256:[a-f0-9]{64}", image):
            raise ValueError("Las imágenes requieren digest SHA-256")
        if ":latest@" in image:
            raise ValueError("No se permite latest en la distribución")
    return {"format": 1, "version": version, "revision": revision, "images": {"backend": backend, "frontend": frontend}}


def allowed_resource(name: str) -> bool:
    """Permite solo recursos operativos públicos; nunca datos, secretos o cachés del host."""
    path = PurePosixPath(name)
    if not re.fullmatch(r"[A-Za-z0-9_./-]+", name):
        return False
    if path.is_absolute() or ".." in path.parts or "\\" in name:
        return False
    if any(part.startswith(".") or part == "__pycache__" for part in path.parts):
        return False
    if name in {
        "start.sh",
        "start.command",
        "start.ps1",
        "LICENSE",
        "NOTICE",
        "docker/keycloak/realm.json",
        "tools/release/sample-manifest.json",
        "docs/D3_SAMPLE.md",
        "docs/D3_INSTALL.md",
        "docs/D3_UPDATE.md",
        "docs/INSTALL.md",
        "tools/release/BUILD.md",
    }:
        return True
    if name.startswith("tools/setup/"):
        return path.suffix in {".py", ".sh", ".ps1", ".md"}
    if name.startswith("docker/keycloak/themes/cerberus/"):
        return path.suffix in {".ftl", ".properties", ".css", ".woff2", ".txt", ".svg", ".png"}
    return False


def committed_resources(root: Path, revision: str) -> dict[str, bytes]:
    """Lee blobs del commit declarado: archivos locales y enlaces no pueden filtrarse al ZIP."""
    output = subprocess.run(
        ["git", "ls-tree", "-rz", "--full-tree", revision],
        cwd=root,
        check=True,
        capture_output=True,
        timeout=30,
    ).stdout
    resources = {}
    for entry in output.split(b"\0"):
        if not entry:
            continue
        metadata, raw_name = entry.split(b"\t", 1)
        mode, kind, blob = metadata.decode("ascii").split()
        name = raw_name.decode("utf-8")
        if not allowed_resource(name):
            continue
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise ValueError(f"Recurso no regular en el commit: {name}")
        resources[name] = subprocess.run(
            ["git", "cat-file", "blob", blob],
            cwd=root,
            check=True,
            capture_output=True,
            timeout=30,
        ).stdout
    return resources


def json_bytes(value: Any) -> bytes:
    """Serializa metadatos de manera estable e independiente del sistema operativo."""
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def build_archive(
    output: Path,
    source: dict[str, Any],
    manifest: dict[str, Any],
    resources: dict[str, bytes],
) -> str:
    """Escribe atómicamente un ZIP estable y devuelve su SHA-256; no altera instalaciones."""
    validated = release_manifest(manifest["version"], manifest["revision"], **manifest["images"])
    if manifest != validated:
        raise ValueError("El manifest no coincide con el formato público de distribución")
    if any(not allowed_resource(name) for name in resources):
        raise ValueError("El paquete contiene recursos fuera de la lista permitida")
    required = {
        "docker/keycloak/realm.json",
        "docker/keycloak/themes/cerberus/login/theme.properties",
        "docker/keycloak/themes/cerberus/login/resources/fonts/OFL.txt",
    }
    if not required <= resources.keys():
        raise ValueError("Faltan realm, tema o licencia de fuentes de identidad")
    files = dict(resources)
    files["compose.yaml"] = json_bytes(distribution_config(source, **manifest["images"]))
    files["release.json"] = json_bytes(validated)
    files["LEEME.md"] = INSTRUCTIONS.encode("utf-8")
    files["SHA256SUMS"] = "".join(
        f"{hashlib.sha256(content).hexdigest()}  {name}\n" for name, content in sorted(files.items())
    ).encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".cerberus-release-", dir=output.parent)
    try:
        with (
            os.fdopen(descriptor, "wb") as target,
            zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive,
        ):
            for name, content in sorted(files.items()):
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.compress_type = zipfile.ZIP_DEFLATED
                mode = 0o755 if name.endswith((".sh", ".command")) else 0o644
                info.external_attr = (0o100000 | mode) << 16
                archive.writestr(info, content)
        os.replace(temporary, output)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return hashlib.sha256(output.read_bytes()).hexdigest()


def main() -> None:
    """Empaqueta exclusivamente el checkout limpio del commit declarado en las imágenes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--backend", required=True)
    parser.add_argument("--frontend", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    manifest = release_manifest(args.version, args.revision, args.backend, args.frontend)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if head != args.revision or dirty:
        parser.error("Se requiere el checkout limpio del commit declarado")
    checksum = build_archive(args.output, source_config(), manifest, committed_resources(ROOT, args.revision))
    print(f"{checksum}  {args.output.name}")


if __name__ == "__main__":
    main()
