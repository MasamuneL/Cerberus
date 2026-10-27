"""Dependencias de FastAPI compartidas por los routers.

En los tests se sustituyen con `app.dependency_overrides[settings_dep] = ...` (y `get_redis`).
"""

import asyncio
import dataclasses
from typing import Annotated

from arq.connections import ArqRedis, RedisSettings, create_pool
from fastapi import Depends, HTTPException
from redis.exceptions import RedisError

from cerberus_api.config import Settings, get_settings


def settings_dep() -> Settings:
    """Ajustes de la app; dependencia separada de `get_settings` para poder sobreescribirla en tests."""
    return get_settings()


# Alias para anotar parámetros de los endpoints: `settings: SettingsDep`
SettingsDep = Annotated[Settings, Depends(settings_dep)]

# Pool arq único, creado de forma lazy en la primera petición que lo necesita: así la app arranca aunque
# Redis esté apagado. El lock evita que dos peticiones concurrentes creen dos pools.
_redis_pool: ArqRedis | None = None
_redis_lock = asyncio.Lock()

REDIS_UNAVAILABLE = "Redis no disponible: inicia redis-server y el worker"


async def get_redis(settings: SettingsDep) -> ArqRedis:
    """Pool arq compartido; 503 si Redis no responde (sin reintentos largos para no colgar la petición)."""
    global _redis_pool
    if _redis_pool is not None:
        return _redis_pool
    async with _redis_lock:
        if _redis_pool is None:
            # arq reintenta 5 veces con 1 s de espera por defecto: en la API basta un reintento
            redis_settings = dataclasses.replace(RedisSettings.from_dsn(settings.redis_url), conn_retries=1)
            try:
                _redis_pool = await create_pool(redis_settings)
            except (RedisError, OSError, TimeoutError) as exc:
                raise HTTPException(status_code=503, detail=REDIS_UNAVAILABLE) from exc
        return _redis_pool


async def close_redis() -> None:
    """Cierra el pool si llegó a crearse (se llama al apagar la app)."""
    global _redis_pool
    if _redis_pool is not None:
        await _redis_pool.aclose()
        _redis_pool = None


# Alias para anotar parámetros de los endpoints: `redis: RedisDep`
RedisDep = Annotated[ArqRedis, Depends(get_redis)]
