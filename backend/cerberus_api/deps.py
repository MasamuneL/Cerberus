"""Dependencias de FastAPI compartidas por los routers.

En los tests se sustituyen con `app.dependency_overrides[settings_dep] = ...`.
"""

from typing import Annotated

from fastapi import Depends

from cerberus_api.config import Settings, get_settings


def settings_dep() -> Settings:
    """Ajustes de la app; dependencia separada de `get_settings` para poder sobreescribirla en tests."""
    return get_settings()


# Alias para anotar parámetros de los endpoints: `settings: SettingsDep`
SettingsDep = Annotated[Settings, Depends(settings_dep)]

# B6: aquí va `get_redis()` (pool arq creado de forma lazy, una sola vez). No implementado en B4.
