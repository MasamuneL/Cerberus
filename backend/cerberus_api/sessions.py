"""Transacciones OIDC y sesiones opacas en Redis, separadas de arq (PLAN_MVP §17)."""

import hashlib
import json
import re
import secrets
import time
from collections.abc import Awaitable, Callable
from typing import cast

from pydantic import BaseModel
from redis.asyncio import Redis
from redis.exceptions import RedisError

from cerberus_api.config import Settings
from cerberus_api.identity import Principal

TRANSACTION_TTL = 300
_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{43}", re.ASCII)

# La lectura/comprobación/borrado es atómica: dos callbacks no consumen la misma transacción.
_CONSUME_TRANSACTION = """
local raw = redis.call('GET', KEYS[1])
if not raw then return nil end
local data = cjson.decode(raw)
if tonumber(ARGV[2]) - data.created_at >= 300 then
    redis.call('DEL', KEYS[1]); return nil
end
if data.browser_hash ~= ARGV[1] then return nil end
redis.call('DEL', KEYS[1])
return raw
"""

# Renovar inactividad nunca extiende el máximo absoluto ni revive una sesión ya caducada.
_READ_SESSION = """
local raw = redis.call('GET', KEYS[1])
if not raw then return nil end
local data = cjson.decode(raw)
local now, idle, absolute = tonumber(ARGV[1]), tonumber(ARGV[2]), tonumber(ARGV[3])
if now - data.last_seen >= idle or now - data.created_at >= absolute then
    redis.call('DEL', KEYS[1]); return nil
end
data.last_seen = now
data.expires_at = math.min(now + idle, data.created_at + absolute)
local result = cjson.encode(data)
redis.call('SET', KEYS[1], result, 'EX', math.max(1, math.ceil(data.expires_at - now)))
return result
"""


class SessionUnavailable(RuntimeError):
    """El almacén de identidad no está disponible; se debe denegar acceso con 503."""


class LoginTransaction(BaseModel):
    state: str
    nonce: str
    code_verifier: str
    browser_token: str
    created_at: float


class SessionData(BaseModel):
    principal: Principal
    csrf_token: str
    created_at: float
    last_seen: float
    expires_at: float


def _key(kind: str, token: str) -> str:
    """Redis guarda hashes de identificadores opacos; nunca la cookie utilizable."""
    return f"cerberus:auth:{kind}:{hashlib.sha256(token.encode()).hexdigest()}"


class SessionStore:
    def __init__(self, redis: Redis, settings: Settings, *, clock: Callable[[], float] = time.time) -> None:
        self.redis = redis
        self.settings = settings
        self.clock = clock

    async def _evaluate(self, script: str, key: str, *values: str | float | int) -> bytes | str | None:
        """Ejecuta las operaciones atómicas sin dejar escapar errores de transporte o claves internas."""
        try:
            # Redis comparte anotaciones síncronas de eval; el cliente async devuelve un awaitable.
            operation = self.redis.eval(script, 1, key, *(str(value) for value in values))
            return await cast(Awaitable[bytes | str | None], operation)
        except (RedisError, OSError) as error:
            raise SessionUnavailable("Sesiones no disponibles") from error

    async def create_transaction(self) -> LoginTransaction:
        """Genera state/nonce/PKCE y una cookie temporal independiente del contenido OIDC."""
        transaction = LoginTransaction(
            state=secrets.token_urlsafe(32),
            nonce=secrets.token_urlsafe(32),
            code_verifier=secrets.token_urlsafe(48),
            browser_token=secrets.token_urlsafe(32),
            created_at=self.clock(),
        )
        data = transaction.model_dump(exclude={"browser_token"})
        data["browser_hash"] = hashlib.sha256(transaction.browser_token.encode()).hexdigest()
        try:
            stored = await self.redis.set(
                _key("transactions", transaction.state), json.dumps(data), ex=TRANSACTION_TTL, nx=True
            )
            if not stored:
                raise SessionUnavailable("No se pudo iniciar la transacción")
        except (RedisError, OSError) as error:
            raise SessionUnavailable("Sesiones no disponibles") from error
        return transaction

    async def consume_transaction(self, state: str, browser_token: str) -> LoginTransaction | None:
        """Otro navegador no consume la transacción válida; el callback repetido queda denegado."""
        if not _TOKEN_RE.fullmatch(state) or not _TOKEN_RE.fullmatch(browser_token):
            return None
        raw = await self._evaluate(
            _CONSUME_TRANSACTION,
            _key("transactions", state),
            hashlib.sha256(browser_token.encode()).hexdigest(),
            self.clock(),
        )
        if raw is None:
            return None
        return LoginTransaction.model_validate(json.loads(raw) | {"browser_token": browser_token})

    async def create_session(
        self, principal: Principal, *, previous_token: str | None = None
    ) -> tuple[str, SessionData]:
        """Renueva el identificador al autenticar y elimina la sesión previa antes de devolver éxito."""
        now = self.clock()
        session = SessionData(
            principal=principal,
            csrf_token=secrets.token_urlsafe(32),
            created_at=now,
            last_seen=now,
            expires_at=now + min(self.settings.auth_idle_timeout_seconds, self.settings.auth_absolute_timeout_seconds),
        )
        token = secrets.token_urlsafe(32)
        try:
            stored = await self.redis.set(
                _key("sessions", token),
                session.model_dump_json(),
                ex=min(self.settings.auth_idle_timeout_seconds, self.settings.auth_absolute_timeout_seconds),
                nx=True,
            )
            if not stored:
                raise SessionUnavailable("No se pudo crear la sesión")
        except (RedisError, OSError) as error:
            raise SessionUnavailable("Sesiones no disponibles") from error
        if previous_token is not None:
            await self.delete_session(previous_token)
        return token, session

    async def read_session(self, token: str) -> SessionData | None:
        """Consulta y renueva la inactividad dentro del plazo absoluto original."""
        if not _TOKEN_RE.fullmatch(token):
            return None
        raw = await self._evaluate(
            _READ_SESSION,
            _key("sessions", token),
            self.clock(),
            self.settings.auth_idle_timeout_seconds,
            self.settings.auth_absolute_timeout_seconds,
        )
        return SessionData.model_validate_json(raw) if raw is not None else None

    async def delete_session(self, token: str) -> None:
        """Logout idempotente; un fallo de Redis no se interpreta como una invalidación correcta."""
        if not _TOKEN_RE.fullmatch(token):
            return
        try:
            await self.redis.delete(_key("sessions", token))
        except (RedisError, OSError) as error:
            raise SessionUnavailable("Sesiones no disponibles") from error
