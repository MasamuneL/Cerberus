"""Crea secretos locales de la demo sin sobrescribir archivos ni imprimir credenciales."""

import argparse
import os
import re
import secrets
from collections.abc import Mapping
from pathlib import Path

SECRET_NAMES = (
    "CERBERUS_AUTH_DB_PASSWORD",
    "CERBERUS_KEYCLOAK_ADMIN_PASSWORD",
    "CERBERUS_OIDC_CLIENT_SECRET",
)


def create_env_file(path: Path, environment: Mapping[str, str]) -> bool:
    """Archivo nuevo 0600; secretos del entorno o aleatorios, compatibles con Compose sin interpolación."""
    if path.exists() or path.is_symlink():
        return False
    values = {name: environment.get(name, secrets.token_urlsafe(48)) for name in SECRET_NAMES}
    for name, value in values.items():
        if re.fullmatch(r"[A-Za-z0-9_-]{32,}", value) is None:
            raise ValueError(f"{name} requiere al menos 32 caracteres URL-safe (letras, números, _ y -)")
    content = "# Secretos locales; no versionar ni compartir este archivo.\n"
    content += "".join(f"{name}={value}\n" for name, value in values.items())
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(descriptor, "w") as output:
        output.write(content)
    return True


def main() -> int:
    """Entrada de CLI; no instala servicios ni modifica cuentas o contraseñas existentes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=Path(".env.auth"))
    args = parser.parse_args()
    try:
        created = create_env_file(args.env_file, os.environ)
    except (ValueError, OSError) as error:
        parser.exit(1, f"No se pudo preparar la configuración: {error}\n")
    print("Archivo de secretos creado con permisos 0600." if created else "Archivo existente conservado sin cambios.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
