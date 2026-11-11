"""Prepara configuración pública de migración; no inicia ni detiene contenedores."""

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any


def migration_environment(config: dict[str, Any], checkout: Path) -> dict[str, str]:
    """Conserva identidad y montajes efectivos del Compose anterior, incluidos espacios."""
    project = config.get("name")
    if not isinstance(project, str) or not project:
        raise ValueError("No se pudo identificar el proyecto anterior")
    result = {"COMPOSE_PROJECT_NAME": project}
    api = config["services"]["api"]
    for key, target in (("DATA", "/app/Data"), ("STORAGE", "/app/storage"), ("MODELS", "/app/models")):
        mounts = [m for m in api["volumes"] if m["target"] == target and m["type"] == "bind"]
        if len(mounts) != 1:
            raise ValueError("Montajes anteriores incompatibles")
        source = Path(mounts[0]["source"])
        result[f"CERBERUS_{key}_PATH"] = str((checkout / source).resolve())
    expected = {
        name: project + "_" + name
        for name in (
            "redis-data",
            "auth-db-data",
            "keycloak-data",
            "auth-db-secret",
            "keycloak-admin-secret",
            "oidc-client-secret",
        )
    }
    for name, physical in expected.items():
        if config["volumes"][name].get("name", physical) != physical:
            raise ValueError("Volúmenes personalizados requieren adopción explícita; no crear otros")
    for service, variable in (("frontend", "CERBERUS_HTTP_PORT"), ("keycloak", "CERBERUS_KEYCLOAK_HTTP_PORT")):
        ports = config["services"][service]["ports"]
        if len(ports) != 1 or ports[0].get("host_ip") != "127.0.0.1":
            raise ValueError("Puertos anteriores no son de loopback")
        result[variable] = str(ports[0]["published"])
    result["CERBERUS_APP_ORIGIN"] = api["environment"]["CERBERUS_APP_ORIGIN"]
    uid, gid = api["user"].split(":")
    if not uid.isdecimal() or not gid.isdecimal():
        raise ValueError("UID/GID anteriores inválidos")
    result.update(CERBERUS_UID=uid, CERBERUS_GID=gid)
    legacy = checkout / ".env.auth"
    if legacy.is_file():
        result["CERBERUS_LEGACY_AUTH_ENV_FILE"] = str(legacy.resolve())
    return result


def write_environment(destination: Path, values: dict[str, str]) -> None:
    """Escribe sin reemplazar configuración; valores literales, nunca código shell."""
    lines = []
    for key, value in values.items():
        if any(char in value for char in ("\n", "\r", "'", "\x00")):
            raise ValueError("Configuración contiene caracteres no admitidos")
        lines.append(f"{key}='{value}'\n")
    with destination.open("x") as output:
        os.chmod(destination, 0o600)
        output.writelines(lines)


def main() -> None:
    """Adopción explícita desde checkout; salida solo con estado, sin rutas ni claves."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", type=Path)
    parser.add_argument("installation", type=Path)
    args = parser.parse_args()
    checkout = args.checkout.resolve()
    config = subprocess.run(
        [
            "docker",
            "compose",
            "--project-directory",
            str(checkout),
            "-f",
            str(checkout / "compose.yaml"),
            "config",
            "--format",
            "json",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    values = migration_environment(json.loads(config.stdout), checkout)
    write_environment(args.installation.resolve() / ".env", values)
    print("Configuración de migración preparada. Detén explícitamente la instancia anterior antes de iniciar.")


if __name__ == "__main__":
    main()
