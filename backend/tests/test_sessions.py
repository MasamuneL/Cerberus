"""Sesiones y transacciones Redis: reloj inyectado y Lua real de fakeredis, sin red."""

import asyncio

import pytest
from fakeredis import FakeAsyncRedis, FakeServer

from cerberus_api.config import Settings
from cerberus_api.identity import Principal


class Clock:
    now: float = 1_800_000_000

    def __call__(self) -> float:
        return self.now


def test_login_transaction_is_bound_to_browser_and_single_use() -> None:
    from cerberus_api.sessions import SessionStore

    async def scenario() -> None:
        redis = FakeAsyncRedis()
        store = SessionStore(redis, Settings(), clock=Clock())
        transaction = await store.create_transaction()
        assert len(transaction.state) == len(transaction.nonce) == len(transaction.browser_token) == 43
        assert len(transaction.code_verifier) >= 43
        assert await store.consume_transaction(transaction.state, "x" * 43) is None
        consumed = await store.consume_transaction(transaction.state, transaction.browser_token)
        assert consumed is not None
        assert consumed.code_verifier == transaction.code_verifier
        assert consumed.nonce == transaction.nonce
        assert await store.consume_transaction(transaction.state, transaction.browser_token) is None
        assert not await redis.keys("cerberus:auth:transactions:*")
        await redis.aclose()

    asyncio.run(scenario())


def test_transaction_expiry_and_invalid_identifiers() -> None:
    from cerberus_api.sessions import SessionStore

    async def scenario() -> None:
        clock = Clock()
        redis = FakeAsyncRedis()
        store = SessionStore(redis, Settings(), clock=clock)
        transaction = await store.create_transaction()
        assert await store.consume_transaction("invalid", transaction.browser_token) is None
        clock.now += 300
        assert await store.consume_transaction(transaction.state, transaction.browser_token) is None
        assert not await redis.keys("cerberus:auth:transactions:*")
        await redis.aclose()

    asyncio.run(scenario())


def test_session_rotation_logout_and_no_raw_cookie_in_redis() -> None:
    from cerberus_api.sessions import SessionStore

    async def scenario() -> None:
        redis = FakeAsyncRedis()
        store = SessionStore(redis, Settings(), clock=Clock())
        principal = Principal(issuer="https://identity.example", sub="subject", roles=frozenset({"reader"}))
        old_token, _ = await store.create_session(principal)
        token, created = await store.create_session(principal, previous_token=old_token)
        assert token != old_token
        assert len(token) == len(created.csrf_token) == 43
        assert await store.read_session(old_token) is None
        current = await store.read_session(token)
        assert current is not None and current.principal == principal
        keys = await redis.keys("cerberus:auth:sessions:*")
        assert len(keys) == 1 and token.encode() not in keys[0]
        raw = await redis.get(keys[0])
        assert raw is not None and token.encode() not in raw
        await store.delete_session(token)
        assert await store.read_session(token) is None
        assert await store.read_session("arq:job:invalid") is None
        await store.delete_session("invalid")
        await redis.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("idle_expiry", [True, False])
def test_session_enforces_idle_and_absolute_deadlines(idle_expiry: bool) -> None:
    from cerberus_api.sessions import SessionStore

    async def scenario() -> None:
        clock = Clock()
        redis = FakeAsyncRedis()
        store = SessionStore(
            redis, Settings(auth_idle_timeout_seconds=5, auth_absolute_timeout_seconds=12), clock=clock
        )
        principal = Principal(issuer="https://identity.example", sub="subject", roles=frozenset({"analyst"}))
        token, session = await store.create_session(principal)
        assert session.expires_at == clock.now + 5
        if idle_expiry:
            clock.now += 5
        else:
            start = clock.now
            current = None
            for _ in range(2):
                clock.now += 4
                current = await store.read_session(token)
                assert current is not None
            assert current is not None and current.expires_at == start + 12
            clock.now += 4
        assert await store.read_session(token) is None
        assert not await redis.keys("cerberus:auth:sessions:*")
        await redis.aclose()

    asyncio.run(scenario())


def test_redis_unavailable_never_creates_anonymous_session() -> None:
    from cerberus_api.sessions import SessionStore, SessionUnavailable

    async def scenario() -> None:
        server = FakeServer()
        redis = FakeAsyncRedis(server=server)
        store = SessionStore(redis, Settings(), clock=Clock())
        transaction = await store.create_transaction()
        principal = Principal(issuer="https://identity.example", sub="subject", roles=frozenset({"reader"}))
        token, _ = await store.create_session(principal)
        server.connected = False
        for operation in (
            store.create_transaction(),
            store.consume_transaction(transaction.state, transaction.browser_token),
            store.create_session(principal),
            store.read_session(token),
            store.delete_session(token),
        ):
            with pytest.raises(SessionUnavailable):
                await operation
        await redis.aclose()

    asyncio.run(scenario())
