"""`GET /api/system`: recursos detectados por el worker (docs/PLAN_MVP.md §16, ticket D2e-back)."""

from typing import Annotated

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from redis.exceptions import RedisError

from cerberus_api import runtime
from cerberus_api.deps import SettingsDep, get_redis
from cerberus_api.schemas import SystemInfo

router = APIRouter(tags=["system"])

WORKER_NOT_REPORTED = "El worker no ha reportado sus recursos"


async def optional_redis(settings: SettingsDep) -> ArqRedis | None:
    """Pool de Redis o `None` si no responde: `/system` no debe dar 503 cuando Redis está apagado."""
    try:
        return await get_redis(settings)
    except HTTPException:
        return None


OptionalRedisDep = Annotated[ArqRedis | None, Depends(optional_redis)]


@router.get("/system")
async def get_system(redis: OptionalRedisDep) -> SystemInfo:
    """`SystemInfo` publicado por el worker; si no hay (o Redis falla), el de la API con un warning."""
    if redis is not None:
        try:
            raw = await redis.get(runtime.SYSTEM_INFO_KEY)
            if raw is not None:
                return SystemInfo.model_validate_json(raw)
        except (RedisError, OSError, ValidationError):
            pass
    info = runtime.build_system_info("api")
    info.warnings.insert(0, WORKER_NOT_REPORTED)
    return info
