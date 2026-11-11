"""Inicialización persistente de la demo Docker; nunca imprime secretos ni restablece cuentas."""

import argparse
import os
import re
import runpy
import secrets
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

import httpx2 as httpx

SECRET_FILES = {
    "CERBERUS_AUTH_DB_PASSWORD": "db/secret",
    "CERBERUS_KEYCLOAK_ADMIN_PASSWORD": "admin/secret",
    "CERBERUS_OIDC_CLIENT_SECRET": "client/secret",
}


def read_secret(path: Path) -> str:
    """Lee un archivo regular de secreto; sin enlaces ni valores interpolables en el proveedor."""
    if path.is_symlink() or not path.is_file():
        raise ValueError("Archivo de secreto ausente o inválido")
    value = path.read_text().removesuffix("\n")
    if re.fullmatch(r"[A-Za-z0-9_-]{32,}", value) is None:
        raise ValueError("Secreto inválido; se requieren al menos 32 caracteres URL-safe")
    return value


def _persist_secret(path: Path, value: str) -> None:
    """Publica un archivo completo con enlace exclusivo; no reemplaza un secreto existente."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".prepare-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as output:
            output.write(value)
            output.flush()
            os.fsync(output.fileno())
            # Cada volumen se monta solo en sus consumidores, todos en modo lectura.
            # PostgreSQL y Keycloak usan UID distintos: el archivo debe ser legible por ambos.
            os.fchmod(output.fileno(), 0o444)
        try:
            os.link(temporary, path)
        except FileExistsError:
            pass
    finally:
        Path(temporary).unlink(missing_ok=True)


def prepare_secrets(root: Path, database_dir: Path, environment: Mapping[str, str]) -> None:
    """Genera una vez o adopta .env.auth; una base previa sin secretos recuperables bloquea el arranque."""
    existing_database = any(database_dir.iterdir())
    username_file = root / "admin/username"
    existing_username = (
        username_file.read_text() if username_file.is_file() and not username_file.is_symlink() else None
    )
    username = (
        environment.get("CERBERUS_SEED_ADMIN_USERNAME")
        or environment.get("CERBERUS_KEYCLOAK_ADMIN_USERNAME")
        or existing_username
        or environment.get("CERBERUS_DEFAULT_ADMIN_USERNAME", "cerberus-admin")
    )
    if not username.strip() or any(ord(char) < 32 for char in username) or username_file.is_symlink():
        raise ValueError("Usuario administrativo inválido")
    if existing_username is not None and username != existing_username:
        raise ValueError("El usuario administrativo difiere del persistente")
    values: dict[str, str] = {}
    supplied_values: dict[str, str] = {}
    # Validar todo antes de escribir evita una migración parcial por configuración incompleta.
    for name, relative in SECRET_FILES.items():
        path = root / relative
        supplied = environment.get("CERBERUS_SEED_" + name.removeprefix("CERBERUS_")) or environment.get(name)
        if supplied is not None:
            supplied_values[name] = supplied
        if supplied is not None and re.fullmatch(r"[A-Za-z0-9_-]{32,}", supplied) is None:
            raise ValueError(f"{name}: secreto inválido")
        if path.exists() or path.is_symlink():
            values[name] = read_secret(path)
            if supplied is not None and supplied != values[name]:
                raise ValueError(f"{name}: difiere del secreto persistente; no se sobrescribe")
        elif supplied is not None:
            values[name] = supplied
        elif existing_database:
            raise ValueError(f"Base existente sin {name}; conserva y proporciona la .env.auth anterior")
        else:
            values[name] = secrets.token_urlsafe(48)
    for name, relative in SECRET_FILES.items():
        path = root / relative
        if not path.exists():
            _persist_secret(path, values[name])
        actual = read_secret(path)
        if name in supplied_values and actual != supplied_values[name]:
            raise ValueError(f"{name}: difiere del secreto persistente; no se sobrescribe")
    if not username_file.exists():
        _persist_secret(username_file, username)


def backend_environment(environment: Mapping[str, str]) -> dict[str, str]:
    """Solo la API recibe el secreto OIDC; el worker mantiene su entorno sin identidad administrativa."""
    result = dict(environment)
    if filename := environment.get("CERBERUS_OIDC_CLIENT_SECRET_FILE"):
        secret = read_secret(Path(filename))
        if result.get("CERBERUS_OIDC_CLIENT_SECRET", secret) != secret:
            raise ValueError("El secreto OIDC del entorno difiere del archivo persistente")
        result["CERBERUS_OIDC_CLIENT_SECRET"] = secret
    return result


def prepare_writable_directory(path: Path, uid: int, gid: int) -> None:
    """Ajusta solo directorios nuevos vacíos; no cambia propietarios ni contenido de resultados existentes."""
    if uid < 0 or gid < 0:
        raise ValueError("UID/GID del contenedor deben ser no negativos")
    if not any(path.iterdir()):
        os.chown(path, uid, gid)


def synchronize_identity(
    root: Path, environment: Mapping[str, str], transport: httpx.BaseTransport | None = None
) -> list[str]:
    """Aprovisiona por la red privada fija; el administrador nunca se envía a URLs o proxies del entorno."""
    script = Path(__file__).resolve().parents[2] / "tools/auth/sync_realm.py"
    sync_realm = runpy.run_path(str(script))["sync_realm"]

    with httpx.Client(
        base_url="http://keycloak:8080", timeout=10, follow_redirects=False, trust_env=False, transport=transport
    ) as client:
        return sync_realm(
            client,
            (root / "admin/username").read_text(),
            read_secret(root / "admin/secret"),
            app_origin=environment["CERBERUS_APP_ORIGIN"],
        )


def main(argv: Sequence[str] | None = None, environment: Mapping[str, str] | None = None) -> int:
    """Modos prepare/sync/exec para Compose; errores públicos sin cuerpos HTTP ni credenciales."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "sync", "exec"))
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    environment = os.environ if environment is None else environment
    root = Path(environment.get("CERBERUS_CONTAINER_SECRET_ROOT", "/run/cerberus"))
    try:
        if args.mode == "prepare":
            prepare_secrets(root, Path("/run/cerberus-existing-db"), environment)
            uid = int(environment.get("CERBERUS_CONTAINER_UID", "1000"))
            gid = int(environment.get("CERBERUS_CONTAINER_GID", "1000"))
            for directory in (Path("/app/storage"), Path("/app/models")):
                prepare_writable_directory(directory, uid, gid)
            print("Secretos persistentes preparados; valores existentes conservados.")
        elif args.mode == "sync":
            changed = synchronize_identity(root, environment)
            print("Identidad preparada: " + (", ".join(changed) if changed else "sin cambios") + ".")
        else:
            if not args.arguments:
                raise ValueError("Falta el comando del contenedor")
            os.execvpe(args.arguments[0], args.arguments, backend_environment(environment))
    except (OSError, ValueError, KeyError, httpx.HTTPError):
        print(
            "No se pudo preparar la demo. Comprueba secretos persistentes, .env.auth anterior y Keycloak; "
            "no borres los volúmenes para reintentar.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
