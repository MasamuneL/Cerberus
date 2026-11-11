"""Sincroniza presentación, idioma y «Recordarme»; crea la cuenta demo solo si falta."""

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import httpx2 as httpx

SETTING_NAMES = (
    "CERBERUS_KEYCLOAK_ADMIN_USERNAME",
    "CERBERUS_KEYCLOAK_ADMIN_PASSWORD",
    "CERBERUS_KEYCLOAK_HTTP_PORT",
)
DESIRED_FIELDS: dict[str, object] = {
    "displayName": "Cerberus · Demo académica",
    "loginTheme": "cerberus",
    "rememberMe": True,
    "internationalizationEnabled": True,
    "defaultLocale": "es",
}


def read_settings(path: Path, environment: Mapping[str, str]) -> dict[str, str]:
    """Lee valores literales del bootstrap; el entorno gana y no se evalúa código ni interpolación."""
    settings: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            name, separator, value = line.strip().partition("=")
            if not separator or name not in SETTING_NAMES:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            settings[name] = value
    settings.update({name: environment[name] for name in SETTING_NAMES if name in environment})
    return settings


def build_realm_patch(current: Mapping[str, Any]) -> dict[str, object]:
    """PUT parcial: conserva cuentas, clientes, roles, atributos y todos los límites de sesión."""
    desired = DESIRED_FIELDS.copy()
    locales = current.get("supportedLocales", [])
    if not isinstance(locales, list) or not all(isinstance(locale, str) for locale in locales):
        raise ValueError("El proveedor devolvió una lista de idiomas inválida.")
    desired["supportedLocales"] = sorted(set(locales) | {"es", "en"})
    patch = {key: value for key, value in desired.items() if current.get(key) != value}
    # Keycloak devuelve conjuntos de idiomas sin garantizar el orden.
    if set(locales) == set(desired["supportedLocales"]):
        patch.pop("supportedLocales", None)
    return patch


def sync_realm(client: httpx.Client, username: str, password: str) -> list[str]:
    """Actualiza cerberus e importa la cuenta de demo con SKIP, conservando cualquier cuenta existente."""
    response = client.post(
        "/realms/master/protocol/openid-connect/token",
        data={"grant_type": "password", "client_id": "admin-cli", "username": username, "password": password},
    )
    response.raise_for_status()
    token_data = response.json()
    token = token_data.get("access_token") if isinstance(token_data, dict) else None
    if not isinstance(token, str) or not token:
        raise ValueError("El proveedor no entregó una sesión administrativa válida.")
    headers = {"Authorization": f"Bearer {token}"}
    response = client.get("/admin/realms/cerberus", headers=headers)
    response.raise_for_status()
    current = response.json()
    if not isinstance(current, dict) or current.get("realm") != "cerberus":
        raise ValueError("No se pudo verificar el realm cerberus existente.")
    patch = build_realm_patch(current)
    if patch:
        response = client.put("/admin/realms/cerberus", headers=headers, json=patch)
        response.raise_for_status()
    # Se reutiliza la cuenta del seed. SKIP conserva contraseña, roles y estado si ya existe,
    # incluso cuando el administrador deshabilitó la cuenta o cambió sus permisos.
    seed_path = Path(__file__).resolve().parents[2] / "docker/keycloak/realm.json"
    users = json.loads(seed_path.read_text())["users"]
    response = client.post(
        "/admin/realms/cerberus/partialImport",
        headers=headers,
        json={"ifResourceExists": "SKIP", "users": users},
    )
    response.raise_for_status()
    imported = response.json()
    if not isinstance(imported, dict) or type(imported.get("added")) is not int or imported["added"] not in (0, 1):
        raise ValueError("El proveedor devolvió un resultado de importación inválido.")
    return sorted([*patch, *(["demo"] if imported["added"] else [])])


def main(
    argv: Sequence[str] | None = None,
    environment: Mapping[str, str] | None = None,
    transport: httpx.BaseTransport | None = None,
) -> int:
    """CLI local sin secretos en argv o salida; timeout y transporte inyectable para pruebas sin red."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=Path(".env.auth"))
    args = parser.parse_args(argv)
    try:
        settings = read_settings(args.env_file, os.environ if environment is None else environment)
        username = settings.get("CERBERUS_KEYCLOAK_ADMIN_USERNAME", "cerberus-admin")
        password = settings.get("CERBERUS_KEYCLOAK_ADMIN_PASSWORD", "")
        port = int(settings.get("CERBERUS_KEYCLOAK_HTTP_PORT", "8081"))
        if not username.strip() or not password.strip() or not 1 <= port <= 65535:
            raise ValueError("Configuración administrativa incompleta o puerto inválido.")
        # Loopback fijo; ni proxies del entorno ni redirecciones reciben la contraseña administrativa.
        with httpx.Client(
            base_url=f"http://localhost:{port}",
            timeout=10,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        ) as client:
            changed = sync_realm(client, username, password)
    except (OSError, ValueError, httpx.HTTPError, json.JSONDecodeError):
        # No interpolar excepciones HTTP: pueden contener cuerpos, tokens o credenciales del proveedor.
        print(
            "No se pudo sincronizar el realm. Comprueba .env.auth, el administrador y que Keycloak esté listo; "
            "después repite el comando.",
            file=sys.stderr,
        )
        return 1
    print("Realm actualizado: " + ", ".join(changed) + "." if changed else "Realm verificado: sin cambios.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
