"""Guardas de actualización: paquetes íntegros y compatibilidad de identidad explícita."""

import hashlib
import json
import os
import re
import shutil
import tarfile
import tempfile
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

IDENTITY_SERVICES = ("auth-db", "keycloak", "redis")
VOLUME_NAMES = (
    "redis-data",
    "auth-db-data",
    "keycloak-data",
    "auth-db-secret",
    "keycloak-admin-secret",
    "oidc-client-secret",
)
IMAGE_RE = re.compile(r"[a-z0-9./:_-]+@sha256:[a-f0-9]{64}")


def package_names(root: Path) -> list[str]:
    """Devuelve solo recursos del paquete; los checksums no pueden designar datos ni configuración privada."""
    names = []
    for line in (root / "SHA256SUMS").read_text().splitlines():
        match = re.fullmatch(r"[a-f0-9]{64}  (.+)", line)
        if match is None:
            raise ValueError("Lista de integridad inválida")
        name = match[1]
        path = PurePosixPath(name)
        allowed = name in {
            "compose.yaml",
            "release.json",
            "LEEME.md",
            "LICENSE",
            "NOTICE",
            "start.sh",
            "start.command",
            "start.ps1",
        }
        allowed = allowed or name.startswith(("tools/setup/", "tools/release/", "docker/keycloak/", "docs/"))
        if not allowed or path.is_absolute() or any(part in {"..", "."} or part.startswith(".") for part in path.parts):
            raise ValueError("Recurso fuera del contrato de paquete")
        names.append(name)
    return [*names, "SHA256SUMS"]


def verify_package(root: Path) -> dict[str, Any]:
    """Verifica checksums locales antes de tocar la instalación; nunca acepta enlaces ni rutas externas."""
    root = root.resolve()
    package_names(root)
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
        if any(parent.is_symlink() for parent in (path, *path.parents) if parent != root.parent) or not path.is_file():
            raise ValueError("Archivo de paquete ausente o enlazado")
        with path.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != digest:
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
        if IMAGE_RE.fullmatch(image) is None:
            raise ValueError("Imagen sin digest")
        if any(compose["services"][service]["image"] != image for service in services):
            raise ValueError("Imágenes mezcladas")
    if (
        "setup-sample" in compose["services"]
        and compose["services"]["setup-sample"]["image"] != manifest["images"]["backend"]
    ):
        raise ValueError("Imágenes mezcladas")
    return compose


def check_update(current: Mapping[str, Any], candidate: Mapping[str, Any], active_jobs: int) -> None:
    """No mezcla upgrades de identidad ni actualiza con trabajos activos."""
    if active_jobs != 0:
        raise ValueError("Hay trabajos activos o no se pudo comprobar la cola; posponer actualización")
    for service in IDENTITY_SERVICES:
        if current["services"][service] != candidate["services"][service]:
            raise ValueError("Cambio de identidad requiere backup y restauración validados por separado")
    if current.get("name") != candidate.get("name") or current.get("volumes") != candidate.get("volumes"):
        raise ValueError("Identidad del proyecto o volúmenes incompatibles")
    for name in current["services"].keys() & candidate["services"].keys():
        if current["services"][name].get("volumes") != candidate["services"][name].get("volumes"):
            raise ValueError("Montajes persistentes incompatibles")


def validate_release_pair(current: Path, candidate: Path) -> None:
    """Exige integridad y versión explícita del estado; volver de imagen no revierte una migración."""
    check_update(verify_package(current), verify_package(candidate), 0)
    manifests = [json.loads((root / "release.json").read_text()) for root in (current, candidate)]
    if any(type(manifest.get("state_format")) is not int or manifest["state_format"] != 1 for manifest in manifests):
        raise ValueError("Formato de estado incompatible; requiere restauración validada por separado")


def validate_image_labels(candidate: Path, labels: Mapping[str, Any]) -> None:
    """Comprueba metadatos OCI de imágenes descargadas sin ejecutar código del candidato."""
    verify_package(candidate)
    manifest = json.loads((candidate / "release.json").read_text())
    for component in ("backend", "frontend"):
        actual = labels.get(component)
        expected = {
            "version": manifest["version"],
            "revision": manifest["revision"],
            "architecture": "amd64",
            "os": "linux",
        }
        if not isinstance(actual, dict) or any(actual.get(key) != value for key, value in expected.items()):
            raise ValueError("Etiquetas o plataforma de imagen difieren de release")


def digest_file(path: Path) -> str:
    """Calcula SHA-256 sin cargar archivos de datos/modelos en memoria."""
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def backup_filter(member: tarfile.TarInfo) -> tarfile.TarInfo | None:
    """Excluye temporales DICOM y logs; no sigue enlaces ni dispositivos del host."""
    parts = PurePosixPath(member.name).parts
    if parts[:2] == ("storage", "tmp") or "logs" in parts or member.name.endswith(".log"):
        return None
    if not member.isfile() and not member.isdir():
        raise ValueError("El backup no acepta enlaces ni archivos especiales; origen intacto")
    return member


def create_backup(current: Path, destination: Path, sources: Mapping[str, Path], *, helper_image: str) -> None:
    """Archiva estado en frío y pg_dump previo; el wrapper debe detener todos los escritores antes.

    Incluye seis volúmenes completos: PostgreSQL físico detenido y dump lógico. Este backup
    es privado, incluye credenciales y datos propios; nunca se utiliza como diagnóstico.
    """
    verify_package(current)
    if IMAGE_RE.fullmatch(helper_image) is None or set(sources) != {"Data", "storage", "models", *VOLUME_NAMES}:
        raise ValueError("Fuentes o imagen de backup incompatibles")
    if destination.is_symlink() or not destination.is_dir() or (destination / "backup.json").exists():
        raise ValueError("Destino de backup inválido o ya completo")
    os.chmod(destination, 0o700)
    owner = destination.stat()
    dump = destination / "database.dump"
    if dump.is_symlink() or not dump.is_file():
        raise ValueError("Falta pg_dump consistente")
    with dump.open("rb") as source:
        if source.read(5) != b"PGDMP":
            raise ValueError("pg_dump inválido")
    os.chmod(dump, 0o600)
    entries: list[tuple[Path, str]] = [(current / name, "package/" + name) for name in package_names(current)]
    entries.extend((current / name, "package/" + name) for name in (".env", ".env.auth") if (current / name).exists())
    for name, source in sources.items():
        if source.is_symlink() or not source.is_dir():
            raise ValueError("Directorio persistente ausente o enlazado")
        entries.append((source, name if name in {"Data", "storage", "models"} else "volumes/" + name))
    estimated = 0
    for source, _ in entries:
        paths = source.rglob("*") if source.is_dir() else (source,)
        for path in paths:
            if path.is_symlink():
                raise ValueError("El backup no acepta enlaces; origen intacto")
            if path.is_file():
                estimated += path.stat().st_size + 1024
    if shutil.disk_usage(destination).free < estimated + 1024 * 1024:
        raise ValueError("Espacio insuficiente para backup completo; versión actual conservada")
    archive = destination / "state.tar"
    temporary = destination / ".state.tar.partial"
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as output, tarfile.open(fileobj=output, mode="w", dereference=False) as tar:
            for source, name in entries:
                tar.add(source, arcname=name, filter=backup_filter)
        os.replace(temporary, archive)
        os.chown(archive, owner.st_uid, owner.st_gid)
        manifest = {
            "format": 1,
            "state_format": 1,
            "revision": json.loads((current / "release.json").read_text())["revision"],
            "archive_sha256": digest_file(archive),
            "database_sha256": digest_file(dump),
            "helper_image": helper_image,
            "volumes": list(VOLUME_NAMES),
        }
        for name, content in (("backup.json", json.dumps(manifest) + "\n"), ("helper-image.txt", helper_image + "\n")):
            with os.fdopen(os.open(destination / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as output:
                output.write(content)
            os.chown(destination / name, owner.st_uid, owner.st_gid)
    finally:
        temporary.unlink(missing_ok=True)


def verify_backup(backup: Path) -> dict[str, Any]:
    """Valida integridad y todas las rutas antes de crear destinos de restauración."""
    for name in ("backup.json", "state.tar", "database.dump", "helper-image.txt"):
        if (backup / name).is_symlink() or not (backup / name).is_file():
            raise ValueError("Backup incompleto o enlazado")
    manifest = json.loads((backup / "backup.json").read_text())
    if (
        manifest.get("format") != 1
        or manifest.get("state_format") != 1
        or manifest.get("volumes") != list(VOLUME_NAMES)
        or not isinstance(manifest.get("helper_image"), str)
        or IMAGE_RE.fullmatch(manifest["helper_image"]) is None
    ):
        raise ValueError("Backup incompatible")
    if digest_file(backup / "state.tar") != manifest.get("archive_sha256") or digest_file(
        backup / "database.dump"
    ) != manifest.get("database_sha256"):
        raise ValueError("Backup corrupto; destinos intactos")
    if (backup / "helper-image.txt").read_text().strip() != manifest["helper_image"]:
        raise ValueError("Imagen de recuperación difiere del backup")
    seen: set[str] = set()
    directories: set[str] = set()
    with tarfile.open(backup / "state.tar", "r") as tar:
        for member in tar:
            path = PurePosixPath(member.name)
            if (
                path.is_absolute()
                or ".." in path.parts
                or "\\" in member.name
                or str(path) != member.name
                or member.name in seen
                or not (member.isfile() or member.isdir())
                or not path.parts
                or path.parts[0] not in {"package", "Data", "storage", "models", "volumes"}
                or (path.parts[0] == "volumes" and (len(path.parts) < 2 or path.parts[1] not in VOLUME_NAMES))
            ):
                raise ValueError("Ruta o entrada insegura en backup")
            seen.add(member.name)
            if member.isdir():
                directories.add(member.name)
    required_directories = {"Data", "storage", "models", *("volumes/" + name for name in VOLUME_NAMES)}
    required_files = {"package/compose.yaml", "package/release.json", "package/SHA256SUMS"}
    if not required_directories.issubset(directories) or not required_files.issubset(seen - directories):
        raise ValueError("Backup incompleto; destinos intactos")
    return manifest


def restore_backup(backup: Path, destination: Path, volumes: Mapping[str, Path], *, project: str) -> None:
    """Restaura exclusivamente destinos vacíos de proyecto nuevo/QA; no inicia servicios ni sobrescribe."""
    if re.fullmatch(r"cerberus-(restore|qa)-[a-z0-9][a-z0-9_-]{0,49}", project) is None:
        raise ValueError("Restauración requiere proyecto nuevo cerberus-restore-* o cerberus-qa-*")
    verify_backup(backup)
    if destination.is_symlink() or any(root.is_symlink() for root in volumes.values()):
        raise ValueError("Destino enlazado; restauración detenida")
    destination = destination.resolve()
    volumes = {name: root.resolve() for name, root in volumes.items()}
    if set(volumes) != set(VOLUME_NAMES):
        raise ValueError("Faltan volúmenes nuevos de restauración")
    for root in (destination, *volumes.values()):
        occupied = root.exists() and (
            not root.is_dir()
            or any(child.name != ".cerberus-setup.lock" or root != destination for child in root.iterdir())
        )
        if root.is_symlink() or occupied:
            raise ValueError("Destino debe estar vacío; no se sobrescriben datos")
    roots = {
        "package": destination,
        "Data": destination / "Data",
        "storage": destination / "storage",
        "models": destination / "models",
    }
    for root in (destination, *volumes.values()):
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
    owner = destination.stat()
    directories = []
    with tarfile.open(backup / "state.tar", "r") as tar:
        for member in tar:
            parts = PurePosixPath(member.name).parts
            root = volumes[parts[1]] if parts[0] == "volumes" else roots[parts[0]]
            relative = parts[2:] if parts[0] == "volumes" else parts[1:]
            path = root.joinpath(*relative)
            if any(parent.is_symlink() for parent in (path, *path.parents)):
                raise ValueError("Destino enlazado; restauración detenida")
            if member.isdir():
                path.mkdir(parents=True, exist_ok=True)
                directories.append((path, member, parts[0] == "package"))
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                source = tar.extractfile(member)
                if source is None:
                    raise ValueError("Entrada de backup ausente")
                with source, path.open("xb") as output:
                    shutil.copyfileobj(source, output)
                os.chmod(path, member.mode & 0o777)
                uid, gid = (owner.st_uid, owner.st_gid) if parts[0] == "package" else (member.uid, member.gid)
                os.chown(path, uid, gid)
                os.utime(path, (member.mtime, member.mtime))
    for path, member, package_directory in reversed(directories):
        os.chmod(path, member.mode & 0o777)
        uid, gid = (owner.st_uid, owner.st_gid) if package_directory else (member.uid, member.gid)
        os.chown(path, uid, gid)
        os.utime(path, (member.mtime, member.mtime))
    # El proyecto y rutas anteriores nunca se reutilizan al iniciar la restauración.
    env = destination / ".env"
    existing = env.read_text() if env.is_file() else ""
    replaced = {
        "COMPOSE_PROJECT_NAME",
        "CERBERUS_DATA_PATH",
        "CERBERUS_STORAGE_PATH",
        "CERBERUS_MODELS_PATH",
        "CERBERUS_LEGACY_AUTH_ENV_FILE",
    }
    lines = [line for line in existing.splitlines() if line.partition("=")[0].strip() not in replaced]
    lines.extend(
        [
            f"COMPOSE_PROJECT_NAME='{project}'",
            "CERBERUS_DATA_PATH='./Data'",
            "CERBERUS_STORAGE_PATH='./storage'",
            "CERBERUS_MODELS_PATH='./models'",
            "CERBERUS_LEGACY_AUTH_ENV_FILE='.env.auth'",
        ]
    )
    env.write_text("\n".join(lines) + "\n")
    os.chmod(env, 0o600)
    if (destination / ".env.auth").is_file():
        os.chmod(destination / ".env.auth", 0o600)
    verify_package(destination)


def copy_package(source: Path, destination: Path) -> None:
    """Publica archivos completos con reemplazo atómico por archivo; no modifica datos/configuración."""
    source, destination = source.resolve(), destination.resolve()
    for name in sorted(package_names(source), key=lambda name: name == "release.json"):
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if any(parent.is_symlink() for parent in (target, *target.parents)):
            raise ValueError("Destino de paquete enlazado")
        descriptor, temporary = tempfile.mkstemp(prefix=".cerberus-copy-", dir=target.parent)
        try:
            with os.fdopen(descriptor, "wb") as output, (source / name).open("rb") as content:
                shutil.copyfileobj(content, output)
                output.flush()
                os.fsync(output.fileno())
            shutil.copymode(source / name, temporary)
            owner = destination.stat()
            os.chown(temporary, owner.st_uid, owner.st_gid)
            os.replace(temporary, target)
        finally:
            Path(temporary).unlink(missing_ok=True)


def activate_package(current: Path, candidate: Path) -> None:
    """Conserva paquete anterior y revierte archivos si falla la publicación; nunca revierte datos."""
    current, candidate = current.resolve(), candidate.resolve()
    validate_release_pair(current, candidate)
    revision = json.loads((current / "release.json").read_text())["revision"]
    previous = current / ".cerberus-versions" / revision
    if previous.exists():
        if verify_package(previous) != verify_package(current):
            raise ValueError("Paquete anterior retenido difiere; no se sobrescribe")
    else:
        previous.mkdir(parents=True, mode=0o700)
        owner = current.stat()
        os.chown(previous.parent, owner.st_uid, owner.st_gid)
        os.chown(previous, owner.st_uid, owner.st_gid)
        copy_package(current, previous)
    try:
        copy_package(candidate, current)
        verify_package(current)
    except Exception:
        copy_package(previous, current)
        raise


async def active_job_count(client: Any) -> int:
    """Cuenta cola y trabajos en ejecución según constantes de arq instalado; falla cerrado."""
    from arq.constants import default_queue_name, in_progress_key_prefix

    count = int(await client.zcard(default_queue_name))
    async for _ in client.scan_iter(match=in_progress_key_prefix + "*"):
        count += 1
    return count


def main() -> int:
    """Guardas y operaciones locales para wrappers Docker; fallos públicos sin rutas ni secretos."""
    import argparse
    import asyncio
    import os

    from redis.asyncio import Redis

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--operation",
        choices=("guard", "verify", "verify-images", "backup", "activate", "verify-backup", "restore"),
        default="guard",
    )
    parser.add_argument("--current", type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--project")
    parser.add_argument("--helper-image")
    parser.add_argument("--quiesced", action="store_true")
    parser.add_argument("--labels", type=Path)
    args = parser.parse_args()

    async def validate() -> None:
        client = Redis.from_url(os.environ.get("CERBERUS_REDIS_URL", "redis://redis:6379/0"))
        try:
            count = await active_job_count(client)
            if count != 0:
                raise ValueError("Hay trabajos activos; posponer")
            validate_release_pair(args.current, args.candidate)
        finally:
            await client.aclose()

    try:
        if args.operation in {"guard", "verify", "verify-images", "activate"}:
            if args.current is None or args.candidate is None:
                raise ValueError("Faltan paquetes")
            if args.operation == "guard":
                asyncio.run(validate())
            elif args.operation == "verify":
                validate_release_pair(args.current, args.candidate)
            elif args.operation == "verify-images":
                validate_release_pair(args.current, args.candidate)
                if args.labels is None:
                    raise ValueError("Faltan etiquetas OCI")
                validate_image_labels(args.candidate, json.loads(args.labels.read_text()))
            else:
                if args.backup is None or not args.quiesced:
                    raise ValueError("Falta backup en frío")
                metadata = verify_backup(args.backup)
                if metadata["revision"] != json.loads((args.current / "release.json").read_text())["revision"]:
                    raise ValueError("Backup de otra versión")
                activate_package(args.current, args.candidate)
        elif args.operation == "backup":
            if args.current is None or args.backup is None or not args.quiesced or args.helper_image is None:
                raise ValueError("Falta parada consistente o destino")
            manifest = json.loads((args.current / "release.json").read_text())
            if manifest.get("state_format") != 1 or manifest["images"]["backend"] != args.helper_image:
                raise ValueError("Imagen de backup no coincide con instalación")
            sources = {name: Path("/app") / name for name in ("Data", "storage", "models")}
            sources.update({name: Path("/run/cerberus-backup") / name for name in VOLUME_NAMES})
            create_backup(args.current, args.backup, sources, helper_image=args.helper_image)
        elif args.operation == "verify-backup":
            if args.backup is None:
                raise ValueError("Falta backup")
            verify_backup(args.backup)
        else:
            if args.backup is None or args.destination is None or args.project is None:
                raise ValueError("Faltan destinos nuevos")
            volumes = {name: Path("/run/cerberus-backup") / name for name in VOLUME_NAMES}
            restore_backup(args.backup, args.destination, volumes, project=args.project)
    except Exception:
        print(
            "Operación bloqueada: comprueba integridad, estado compatible, trabajos, permisos y espacio; "
            "conserva datos y backups."
        )
        return 1
    print("Operación completada; los datos y credenciales no se restablecen automáticamente.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
