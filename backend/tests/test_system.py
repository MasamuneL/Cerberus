"""Tests de `GET /api/system` y del hook de arranque del worker (§16, D2e-back)."""

import asyncio
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from redis.exceptions import RedisError

from cerberus_api import runtime, worker
from cerberus_api.main import app
from cerberus_api.routers.system import WORKER_NOT_REPORTED, optional_redis
from cerberus_api.schemas import SystemInfo


class FakeRedis:
    """Sustituto mínimo de `ArqRedis` con get/set/delete en memoria; `fail=True` simula Redis caído."""

    def __init__(self, fail: bool = False) -> None:
        self.data: dict[str, bytes] = {}
        self.fail = fail

    async def get(self, key: str) -> bytes | None:
        if self.fail:
            raise RedisError("caído")
        return self.data.get(key)

    async def set(self, key: str, value: str) -> None:
        self.data[key] = value.encode()

    async def delete(self, key: str) -> None:
        self.data.pop(key, None)


MakeClient = Callable[[FakeRedis | None], TestClient]


def _worker_info() -> SystemInfo:
    return SystemInfo(
        source="worker",
        reported_at=datetime(2026, 10, 29, tzinfo=UTC),
        in_container=True,
        platform="linux/x86_64 (emulado en arm64)",
        cpus_available=14.0,
        threads=8,
        threads_source="auto",
        memory_gb=6.0,
        device="cpu",
        warnings=["Plataforma emulada: el cálculo será más lento"],
    )


@pytest.fixture
def make_client() -> Iterator[MakeClient]:
    def _make(redis: FakeRedis | None) -> TestClient:
        app.dependency_overrides[optional_redis] = lambda: redis
        return TestClient(app)

    try:
        yield _make
    finally:
        app.dependency_overrides.clear()


def test_system_from_worker(make_client: MakeClient) -> None:
    redis = FakeRedis()
    redis.data[runtime.SYSTEM_INFO_KEY] = _worker_info().model_dump_json().encode()
    r = make_client(redis).get("/api/system")
    assert r.status_code == 200
    assert SystemInfo.model_validate(r.json()) == _worker_info()


@pytest.mark.parametrize("redis", [FakeRedis(), FakeRedis(fail=True), None], ids=["missing", "error", "down"])
def test_system_fallback_to_api(make_client: MakeClient, redis: FakeRedis | None) -> None:
    r = make_client(redis).get("/api/system")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "api"
    assert body["warnings"][0] == WORKER_NOT_REPORTED
    assert body["threads"] >= 1


def test_system_corrupt_key_falls_back(make_client: MakeClient) -> None:
    redis = FakeRedis()
    redis.data[runtime.SYSTEM_INFO_KEY] = b"{no json"
    assert make_client(redis).get("/api/system").json()["source"] == "api"


def test_worker_startup_publishes_and_shutdown_clears(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_configure() -> tuple[int, str]:
        calls.append("configure")
        return 3, "auto"

    def fake_build(source: str) -> SystemInfo:
        calls.append(f"build {source}")
        return _worker_info()

    monkeypatch.setattr(runtime, "configure_threads", fake_configure)
    monkeypatch.setattr(runtime, "apply_threads", lambda n: calls.append(f"apply {n}"))
    monkeypatch.setattr(runtime, "build_system_info", fake_build)
    redis = FakeRedis()
    ctx: dict[str, Any] = {"redis": redis}
    asyncio.run(worker.startup(ctx))
    # Los hilos se aplican antes de construir el SystemInfo (que importa torch) y de nuevo después
    assert calls == ["configure", "build worker", "apply 3"]
    assert ctx["cerberus_threads"] == 3
    assert SystemInfo.model_validate_json(redis.data[runtime.SYSTEM_INFO_KEY]) == _worker_info()
    asyncio.run(worker.shutdown(ctx))
    assert runtime.SYSTEM_INFO_KEY not in redis.data


def test_run_blocking_reapplies_threads(monkeypatch: pytest.MonkeyPatch) -> None:
    applied: list[int] = []
    monkeypatch.setattr(runtime, "apply_threads", applied.append)
    assert asyncio.run(worker._run_blocking({"cerberus_threads": 4}, lambda a, b: a + b, 1, 2)) == 3
    assert applied == [4]
    assert asyncio.run(worker._run_blocking({}, lambda: "ok")) == "ok"
    assert applied == [4]


def test_worker_settings_hooks() -> None:
    assert worker.WorkerSettings.on_startup is worker.startup
    assert worker.WorkerSettings.on_shutdown is worker.shutdown
