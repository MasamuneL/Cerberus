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


def runtime_config(containers: list[dict[str, Any]], checkout: Path) -> dict[str, Any]:
    """Reconstruye solo identidad pública y montajes reales; nunca usa defaults de otra shell."""
    selected: dict[str, dict[str, Any]] = {}
    projects: set[str] = set()
    for container in containers:
        labels = container.get("Config", {}).get("Labels", {})
        directory = labels.get("com.docker.compose.project.working_dir")
        if not directory or Path(directory).resolve() != checkout.resolve():
            continue
        if str(labels.get("com.docker.compose.oneoff", "false")).lower() == "true":
            continue
        project = labels.get("com.docker.compose.project")
        service = labels.get("com.docker.compose.service")
        if not project or not service or service in selected:
            raise ValueError("Instalación anterior ambigua; conserva el proyecto explícito antes de migrar")
        projects.add(project)
        selected[service] = container
    if len(projects) != 1 or not {"api", "frontend", "keycloak", "redis", "auth-db"} <= selected.keys():
        raise ValueError("No se identifica una instalación completa; conserva sus contenedores detenidos para migrar")
    project = projects.pop()
    api = selected["api"]
    environment = dict(item.split("=", 1) for item in api["Config"]["Env"] if "=" in item)
    result: dict[str, Any] = {
        "name": project,
        "volumes": {},
        "services": {
            "api": {
                "user": api["Config"]["User"],
                "environment": {"CERBERUS_APP_ORIGIN": environment["CERBERUS_APP_ORIGIN"]},
                "volumes": [
                    {"type": mount["Type"], "source": mount["Source"], "target": mount["Destination"]}
                    for mount in api["Mounts"]
                    if mount["Destination"] in ("/app/Data", "/app/storage", "/app/models")
                ],
            }
        },
    }
    for name in ("frontend", "keycloak"):
        bindings = selected[name]["HostConfig"]["PortBindings"].get("8080/tcp", [])
        result["services"][name] = {
            "ports": [{"host_ip": binding["HostIp"], "published": binding["HostPort"]} for binding in bindings]
        }
    for volume, service, target in (
        ("redis-data", "redis", "/data"),
        ("auth-db-data", "auth-db", "/var/lib/postgresql"),
        ("keycloak-data", "keycloak", "/opt/keycloak/data"),
        ("auth-db-secret", "auth-db", "/run/cerberus/db"),
        ("keycloak-admin-secret", "keycloak", "/run/cerberus/admin"),
        ("oidc-client-secret", "api", "/run/cerberus/client"),
    ):
        mounts = [m for m in selected[service]["Mounts"] if m["Destination"] == target and m["Type"] == "volume"]
        if len(mounts) != 1:
            raise ValueError("Volumen anterior no identificado; no crear una identidad nueva")
        result["volumes"][volume] = {"name": mounts[0]["Name"]}
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
    found = subprocess.run(
        ["docker", "ps", "-aq", "--filter", "label=com.docker.compose.project.working_dir"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.split()
    if not found:
        parser.error("No hay contenedores anteriores identificables; no se adoptan defaults de Compose")
    inspected = subprocess.run(["docker", "inspect", *found], check=True, capture_output=True, text=True, timeout=30)
    values = migration_environment(runtime_config(json.loads(inspected.stdout), checkout), checkout)
    write_environment(args.installation.resolve() / ".env", values)
    print(
        "Configuración preparada. Termina trabajos y retira contenedores antiguos conservando volúmenes antes de iniciar."
    )


if __name__ == "__main__":
    main()
