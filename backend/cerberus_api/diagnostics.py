"""Diagnóstico local D3e; solo exporta códigos, servicios y mensajes de una lista permitida.

El snapshot procede del wrapper del host. Nunca se muestran sus textos, logs, nombres,
rutas, variables ni errores originales. Las comprobaciones de muestra son offline.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from cerberus_api.sequences import validate_patient, validate_sequence, validate_timepoint

SERVICES = (
    "setup-secrets",
    "setup-sample",
    "redis",
    "auth-db",
    "keycloak",
    "setup-identity",
    "api",
    "worker",
    "frontend",
)
INITIALIZERS = {"setup-secrets", "setup-sample", "setup-identity"}
MESSAGES = {
    "DOCKER_READY": ("ok", "Docker accesible en el contexto elegido."),
    "DOCKER_UNAVAILABLE": ("error", "Inicia Docker y comprueba el contexto elegido; los servicios no se comprobaron."),
    "DOCKER_UNKNOWN": ("pending", "Ejecuta el diagnóstico desde el lanzador para comprobar Docker y los servicios."),
    "SERVICE_MISSING": ("pending", "Servicio ausente; inicia el proyecto desde su carpeta de instalación."),
    "SERVICE_HEALTHY": ("ok", "Servicio listo."),
    "SERVICE_RUNNING": ("pending", "Servicio en ejecución sin verificación de salud disponible."),
    "SERVICE_STARTING": ("pending", "Espera la preparación del servicio y vuelve a comprobar."),
    "SERVICE_FAILED": ("error", "Servicio detenido o no saludable; comprueba sus dependencias y recursos."),
    "RESOURCE_OOM": ("error", "Docker terminó el servicio por falta de memoria; revisa memoria disponible y límites."),
    "DISK_INSUFFICIENT": (
        "error",
        "Espacio insuficiente incluso para un archivo pendiente de muestra; libera espacio sin borrar resultados.",
    ),
    "INITIALIZER_COMPLETED": ("ok", "Inicializador completado; su salida 0 es normal."),
    "INITIALIZER_FAILED": (
        "error",
        "Inicializador fallido; comprueba muestra, permisos o secretos persistentes sin borrarlos.",
    ),
    "PORT_OCCUPIED": (
        "error",
        "Puerto ocupado sin el servicio esperado; elige otro puerto o revisa la instancia anterior.",
    ),
    "PORT_AVAILABLE": ("ok", "Puerto disponible para el servicio esperado."),
    "PORT_EXPECTED": ("ok", "El servicio del proyecto publica el puerto configurado."),
    "PORT_UNKNOWN": ("pending", "No se pudo comprobar el puerto local."),
    "IMAGE_MATCH": ("ok", "Referencia de imagen coincide con el digest de la release."),
    "IMAGE_MISMATCH": (
        "error",
        "Imagen distinta de la release; actualiza explícitamente al conjunto de digests declarado.",
    ),
    "IMAGE_UNKNOWN": ("pending", "No hay digest verificable de la release o falta el contenedor."),
    "SAMPLE_MISSING": ("error", "Muestra ausente; ejecuta su preparación o configura datos propios explícitamente."),
    "SAMPLE_UNVERIFIED": ("pending", "Hay archivos de muestra; falta un manifest válido para verificar su integridad."),
    "SAMPLE_VERIFIED": ("ok", "Archivos de muestra verificados por tamaño y SHA-256 sin consultar la red."),
    "SAMPLE_CORRUPT": (
        "error",
        "Muestra incompleta o corrupta; conserva datos propios y repite la preparación verificada.",
    ),
    "SAMPLE_LFS_POINTER": (
        "error",
        "La muestra contiene punteros Git LFS; utiliza el artefacto de muestra verificado.",
    ),
    "SAMPLE_MANIFEST_INVALID": ("error", "Manifest de muestra inválido; utiliza el manifest de la release."),
    "STORAGE_PERMISSIONS": (
        "error",
        "Directorio persistente no escribible por el usuario actual; revisa UID/GID sin cambios recursivos.",
    ),
    "STORAGE_ACCESSIBLE": ("ok", "Directorio persistente accesible para escritura por el usuario actual."),
    "STORAGE_MISSING": (
        "pending",
        "Directorio persistente ausente; completa su preparación antes de iniciar trabajos.",
    ),
    "SNAPSHOT_INVALID": ("error", "No se pudo interpretar el estado local; repite el diagnóstico desde el lanzador."),
    "EXPORT_FAILED": (
        "error",
        "No se pudo crear el reporte privado; utiliza un archivo nuevo en una carpeta escribible.",
    ),
    "DIAGNOSTIC_UNAVAILABLE": (
        "pending",
        "Conserva la instalación; el diagnóstico completo necesita la imagen backend local.",
    ),
}


def check(code: str, service: str) -> dict[str, str]:
    """Construye únicamente campos públicos permitidos; nunca interpola valores externos."""
    if code not in MESSAGES or service not in (*SERVICES, "docker", "sample", "storage", "models", "report"):
        raise ValueError("Código o servicio no permitido")
    status, action = MESSAGES[code]
    return {"code": code, "service": service, "status": status, "action": action}


def sample_check(data_dir: Path, manifest: object) -> dict[str, str]:
    """Verifica solo archivos regulares de 001/t0; rechaza enlaces y traversal sin leer fuera de Data."""
    try:
        if any(path.is_symlink() for path in (data_dir, data_dir / "001", data_dir / "001/t0")):
            return check("SAMPLE_CORRUPT", "sample")
        if manifest is None:
            files = list((data_dir / "001/t0").glob("*.nii.gz"))
            if not files:
                return check("SAMPLE_MISSING", "sample")
            for path in files:
                if path.is_symlink() or not path.is_file():
                    return check("SAMPLE_CORRUPT", "sample")
                with path.open("rb") as source:
                    if source.read(128).startswith(b"version https://git-lfs.github.com/spec/v1"):
                        return check("SAMPLE_LFS_POINTER", "sample")
            return check("SAMPLE_UNVERIFIED", "sample")
        if not isinstance(manifest, dict) or manifest.get("format") != 1:
            return check("SAMPLE_MANIFEST_INVALID", "sample")
        entries = manifest.get("files")
        if not isinstance(entries, list) or not entries or len(entries) > 100:
            return check("SAMPLE_MANIFEST_INVALID", "sample")
        seen: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict):
                return check("SAMPLE_MANIFEST_INVALID", "sample")
            name, size, digest = entry.get("path"), entry.get("size"), entry.get("sha256")
            if (
                not isinstance(name, str)
                or re.fullmatch(r"001/t0/1_t0_[a-z0-9_]+\.nii\.gz", name) is None
                or name in seen
                or type(size) is not int
                or size <= 0
                or not isinstance(digest, str)
                or re.fullmatch(r"[a-f0-9]{64}", digest) is None
            ):
                return check("SAMPLE_MANIFEST_INVALID", "sample")
            seen.add(name)
            try:
                validate_patient("001")
                validate_timepoint("t0")
                validate_sequence(name.removeprefix("001/t0/1_t0_").removesuffix(".nii.gz"))
            except ValueError:
                return check("SAMPLE_MANIFEST_INVALID", "sample")
            path = data_dir
            for component in PurePosixPath(name).parts:
                path = path / component
                if path.is_symlink():
                    return check("SAMPLE_CORRUPT", "sample")
            if not path.is_file():
                if data_dir.is_dir() and shutil.disk_usage(data_dir).free < size:
                    return check("DISK_INSUFFICIENT", "sample")
                return check("SAMPLE_MISSING", "sample")
            with path.open("rb") as source:
                if source.read(128).startswith(b"version https://git-lfs.github.com/spec/v1"):
                    return check("SAMPLE_LFS_POINTER", "sample")
                source.seek(0)
                actual = hashlib.file_digest(source, "sha256").hexdigest()
            if path.stat().st_size != size or actual != digest:
                return check("SAMPLE_CORRUPT", "sample")
        return check("SAMPLE_VERIFIED", "sample")
    except OSError:
        return check("SAMPLE_CORRUPT", "sample")


def build_report(
    snapshot: Mapping[str, Any],
    *,
    data_dir: Path,
    storage_dir: Path | None = None,
    models_dir: Path | None = None,
) -> dict[str, Any]:
    """Reduce datos locales no confiables a decisiones públicas de una lista cerrada."""
    docker = snapshot.get("docker", {})
    state = docker.get("status") if isinstance(docker, dict) else None
    docker_code = (
        "DOCKER_READY" if state == "ready" else ("DOCKER_UNAVAILABLE" if state == "unavailable" else "DOCKER_UNKNOWN")
    )
    checks = [check(docker_code, "docker")]
    services = snapshot.get("services", [])
    known = (
        {
            item["service"]: item
            for item in services
            if isinstance(item, dict) and isinstance(item.get("service"), str) and item["service"] in SERVICES
        }
        if isinstance(services, list)
        else {}
    )
    if state == "ready":
        for name in SERVICES:
            if name == "setup-sample" and name not in known:
                continue  # El inicializador de muestra se incorpora en D3c.
            service = known.get(name, {})
            running = service.get("state") == "running"
            health = service.get("health")
            code = "SERVICE_MISSING"
            if service:
                if service.get("oom_killed") is True:
                    code = "RESOURCE_OOM"
                elif name in INITIALIZERS and service.get("state") == "exited":
                    code = "INITIALIZER_COMPLETED" if service.get("exit_code") == 0 else "INITIALIZER_FAILED"
                elif running and health == "healthy":
                    code = "SERVICE_HEALTHY"
                elif running and health == "starting":
                    code = "SERVICE_STARTING"
                elif running and health in (None, "", "none"):
                    code = "SERVICE_RUNNING"
                else:
                    code = "INITIALIZER_FAILED" if name in INITIALIZERS else "SERVICE_FAILED"
            checks.append(check(code, name))
        ports = snapshot.get("ports", {})
        for key, service_name in (("http", "frontend"), ("identity", "keycloak")):
            port_state = ports.get(key) if isinstance(ports, dict) else None
            port_code = {"busy": "PORT_OCCUPIED", "free": "PORT_AVAILABLE", "expected": "PORT_EXPECTED"}
            checks.append(
                check(
                    port_code.get(port_state, "PORT_UNKNOWN") if isinstance(port_state, str) else "PORT_UNKNOWN",
                    service_name,
                )
            )
        release = snapshot.get("release", {})
        images = release.get("images", {}) if isinstance(release, dict) else {}
        for name in ("api", "worker", "setup-secrets", "setup-identity", "frontend"):
            expected = images.get("frontend" if name == "frontend" else "backend") if isinstance(images, dict) else None
            code = "IMAGE_UNKNOWN"
            if isinstance(expected, str) and re.fullmatch(r"[\w./:-]+@sha256:[a-f0-9]{64}", expected) and name in known:
                code = "IMAGE_MATCH" if known[name].get("image") == expected else "IMAGE_MISMATCH"
            checks.append(check(code, name))
    checks.append(sample_check(data_dir, snapshot.get("sample_manifest")))
    for name, directory in (("storage", storage_dir), ("models", models_dir)):
        if directory is not None:
            try:
                code = (
                    "STORAGE_MISSING"
                    if not directory.is_dir()
                    else ("STORAGE_ACCESSIBLE" if os.access(directory, os.W_OK | os.X_OK) else "STORAGE_PERMISSIONS")
                )
            except OSError:
                code = "STORAGE_PERMISSIONS"
            checks.append(check(code, name))
    return {"format": 1, "checks": checks}


def export_report(report: Mapping[str, Any], destination: Path) -> None:
    """Crea un reporte privado exclusivo, sin seguir enlaces ni reemplazar archivos existentes."""
    # Reconstruir por lista permitida protege también a consumidores externos de esta función.
    safe = {"format": 1, "checks": [check(item["code"], item["service"]) for item in report["checks"]]}
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(safe, output, ensure_ascii=True)
        output.write("\n")


def main(argv: Sequence[str] | None = None) -> int:
    """CLI sin dependencias de Docker/Python adicionales en el host; nunca consulta la red."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-stdin", action="store_true")
    parser.add_argument("--data-dir", type=Path, default=Path(os.environ.get("CERBERUS_DATA_DIR", "/app/Data")))
    parser.add_argument(
        "--storage-dir", type=Path, default=Path(os.environ.get("CERBERUS_STORAGE_DIR", "/app/storage"))
    )
    parser.add_argument("--models-dir", type=Path, default=Path(os.environ.get("CERBERUS_MODELS_DIR", "/app/models")))
    parser.add_argument("--export", type=Path)
    args = parser.parse_args(argv)
    try:
        raw = sys.stdin.read(5_000_001) if args.snapshot_stdin else "{}"
        if len(raw) > 5_000_000:
            raise ValueError("Snapshot demasiado grande")
        snapshot = json.loads(raw)
        if not isinstance(snapshot, dict):
            raise ValueError("Snapshot inválido")
        if "sample_manifest" not in snapshot:
            manifest_path = Path(__file__).resolve().parents[2] / "tools/release/sample-manifest.json"
            if manifest_path.is_file():
                snapshot["sample_manifest"] = json.loads(manifest_path.read_text())
        report = build_report(
            snapshot, data_dir=args.data_dir, storage_dir=args.storage_dir, models_dir=args.models_dir
        )
    except (OSError, ValueError, TypeError, RecursionError):
        report = {"format": 1, "checks": [check("SNAPSHOT_INVALID", "report")]}
    if args.export:
        try:
            export_report(report, args.export)
        except (OSError, ValueError, TypeError, KeyError):
            report["checks"].append(check("EXPORT_FAILED", "report"))
    print(json.dumps(report, ensure_ascii=True))
    return int(any(item["status"] == "error" for item in report["checks"]))


if __name__ == "__main__":
    raise SystemExit(main())
