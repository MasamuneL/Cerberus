"""Permisos antes del body/I/O y propiedad en Redis; todas las identidades son sintéticas."""

import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fakeredis import FakeAsyncRedis, FakeServer
from fastapi import Request
from fastapi.testclient import TestClient
from pydantic import SecretStr

from cerberus_api.config import Settings
from cerberus_api.identity import Principal
from cerberus_api.main import create_app
from cerberus_api.sessions import SessionStore

READ_PATHS = [
    "/api/studies",
    "/api/studies/001/t0",
    "/api/studies/001/t0/volumetry",
    "/api/studies/001/t0/segmentation",
    "/api/studies/001/t0/areas",
    "/api/patients/001/longitudinal",
    "/api/system",
    "/api/studies/001/t0/files/gtv.nii.gz",
]
OWN_ID = "a" * 32
OWN_PATHS = [f"/api/jobs/{OWN_ID}", f"/api/uploads/{OWN_ID}", f"/api/uploads/{OWN_ID}/series/0.nii.gz"]
MUTATIONS = [
    ("POST", "/api/uploads"),
    ("POST", "/api/studies/001/t0/segmentation"),
    ("POST", "/api/studies/001/t0/areas"),
    ("POST", f"/api/uploads/{OWN_ID}/confirm"),
    ("DELETE", f"/api/uploads/{OWN_ID}"),
]


@pytest.fixture
def guarded(tmp_path: Path) -> Iterator[tuple[TestClient, SessionStore, FakeServer]]:
    settings = Settings(
        auth_mode="oidc",
        app_origin="http://localhost:8080",
        oidc_issuer_url="https://id.example",
        oidc_client_secret=SecretStr("synthetic"),
        auth_cookie_secure=False,
        data_dir=tmp_path / "Data",
        storage_dir=tmp_path / "storage",
    )
    server = FakeServer()
    store = SessionStore(FakeAsyncRedis(server=server), settings)

    async def factory() -> SessionStore:
        return store

    app = create_app(settings, session_factory=factory)

    # Estas rutas sentinela solo corren si la guarda dejó pasar la petición.
    @app.api_route("/api/probe", methods=["GET", "POST"])
    async def probe(request: Request) -> dict[str, str]:
        await request.body()
        return {"ok": "yes"}

    with TestClient(app, base_url="http://localhost:8080") as client:
        yield client, store, server


def sign_in(
    client: TestClient,
    store: SessionStore,
    role: str = "analyst",
    *,
    sub: str = "one",
    issuer: str = "https://id.example",
) -> dict[str, str]:
    async def scenario() -> tuple[str, str]:
        principal = Principal(issuer=issuer, sub=sub, roles=frozenset({role}))  # type: ignore[arg-type]
        token, session = await store.create_session(principal)
        return token, session.csrf_token

    token, csrf = client.portal.call(scenario)  # type: ignore[union-attr]
    client.cookies.set("cerberus_session", token)
    return {"Origin": "http://localhost:8080", "X-CSRF-Token": csrf}


@pytest.mark.parametrize("path", READ_PATHS + OWN_PATHS)
@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_anonymous_cannot_read_even_conditional(guarded: Any, path: str, method: str) -> None:
    client, _, _ = guarded
    result = client.request(method, path, headers={"If-None-Match": "*"})
    assert result.status_code == 401
    assert result.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("method,path", MUTATIONS)
@pytest.mark.parametrize("role,status", [(None, 401), ("reader", 403)])
def test_mutations_denied_before_multipart_or_json(
    guarded: Any, method: str, path: str, role: str | None, status: int
) -> None:
    client, store, _ = guarded
    headers = sign_in(client, store, role) if role else {}
    result = client.request(
        method, path, headers={**headers, "Content-Type": "multipart/form-data; boundary=broken"}, content=b"invalid"
    )
    assert result.status_code == status


@pytest.mark.parametrize("path", OWN_PATHS)
def test_reader_cannot_read_ingestion_or_jobs(guarded: Any, path: str) -> None:
    client, store, _ = guarded
    sign_in(client, store, "reader")
    assert client.get(path).status_code == 403


def test_analyst_requires_csrf_and_origin(guarded: Any) -> None:
    client, store, _ = guarded
    headers = sign_in(client, store)
    for bad in (
        {},
        {"Origin": headers["Origin"]},
        {"X-CSRF-Token": headers["X-CSRF-Token"]},
        {**headers, "Origin": "https://evil.example"},
    ):
        assert client.post("/api/probe", headers=bad).status_code == 403
    response = client.post("/api/probe", headers=headers)
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"


def test_redis_failure_denies_access(guarded: Any) -> None:
    client, store, server = guarded
    sign_in(client, store)
    server.connected = False
    assert client.get("/api/studies").status_code == 503
    server.connected = True


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_docs_disabled_in_oidc(guarded: Any, path: str) -> None:
    assert guarded[0].get(path).status_code == 404


def test_public_health_and_auth_config(guarded: Any) -> None:
    client, _, _ = guarded
    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.get("/api/auth/config").json() == {"mode": "oidc"}


@pytest.mark.parametrize("mode", ["off", "oidc"])
def test_host_guard(guarded: Any, mode: str) -> None:
    client = guarded[0] if mode == "oidc" else TestClient(create_app(), base_url="http://localhost")
    assert client.get("/api/health", headers={"Host": "attacker.example"}).status_code == 400
    for host in ("localhost:8080", "127.0.0.1:8000", "[::1]:8000"):
        assert client.get("/api/health", headers={"Host": host}).status_code == 200


def test_local_mutations_require_custom_header_and_valid_origin() -> None:
    with TestClient(create_app(), base_url="http://localhost") as client:
        assert client.post("/api/uploads").status_code == 403
        assert (
            client.post("/api/uploads", headers={"X-Cerberus": "1", "Origin": "https://evil.example"}).status_code
            == 403
        )
        assert client.post("/api/uploads", headers={"X-Cerberus": "1"}).status_code == 422
        assert (
            client.post("/api/uploads", headers={"X-Cerberus": "1", "Origin": "http://localhost:5173"}).status_code
            == 422
        )


def test_denied_body_never_consumed(guarded: Any) -> None:
    client, _, _ = guarded

    async def scenario() -> None:
        async def receive() -> Any:
            raise AssertionError("No se debe leer el body antes de autenticar")

        messages: list[Any] = []

        async def send(message: Any) -> None:
            messages.append(message)

        await client.app(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "POST",
                "path": "/api/uploads",
                "raw_path": b"/api/uploads",
                "query_string": b"",
                "headers": [(b"host", b"localhost")],
                "scheme": "http",
                "server": ("localhost", 8080),
                "client": ("127.0.0.1", 1),
                "root_path": "",
            },
            receive,
            send,
        )
        assert messages[0]["status"] == 401

    asyncio.run(scenario())


def test_owners_use_issuer_and_subject_across_sessions() -> None:
    from cerberus_api.access import OwnerStore

    async def scenario() -> None:
        redis: Any = FakeAsyncRedis()
        owners = OwnerStore(redis)
        first = Principal(issuer="https://one", sub="same", roles=frozenset({"analyst"}))
        for kind in ("jobs", "uploads"):
            assert not await owners.owns(kind, OWN_ID, first)
            await owners.register(kind, OWN_ID, first)
            assert await owners.owns(kind, OWN_ID, first.model_copy(update={"roles": frozenset({"reader"})}))
            assert not await owners.owns(kind, OWN_ID, first.model_copy(update={"issuer": "https://two"}))
            assert not await owners.owns(kind, OWN_ID, first.model_copy(update={"sub": "other"}))
            assert not await owners.owns(kind, "../invalid", first)
            await owners.delete(kind, OWN_ID)
            assert not await owners.owns(kind, OWN_ID, first)
        await redis.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("path", OWN_PATHS)
def test_foreign_and_unowned_resources_hidden(guarded: Any, path: str) -> None:
    from cerberus_api.access import OwnerStore

    client, store, _ = guarded
    sign_in(client, store, sub="owner")
    principal = Principal(issuer="https://id.example", sub="owner", roles=frozenset({"analyst"}))
    owners = OwnerStore(store.redis)
    kind = "jobs" if "/jobs/" in path else "uploads"
    assert client.get(path).status_code == 404
    client.portal.call(owners.register, kind, OWN_ID, principal)
    sign_in(client, store, sub="stranger")
    assert client.get(path).status_code == 404
    sign_in(client, store, sub="owner", issuer="https://other.example")
    assert client.get(path).status_code == 404


def test_files_revalidated_only_while_session_valid(guarded: Any) -> None:
    client, store, _ = guarded
    file = store.settings.storage_dir / "sample.nii.gz"
    file.parent.mkdir(parents=True)
    file.write_bytes(b"synthetic")
    # Usar la ruta real y su validador con un volumen del catálogo.
    data = store.settings.data_dir / "001" / "t0"
    data.mkdir(parents=True)
    (data / "1_t0_gtv.nii.gz").write_bytes(file.read_bytes())
    sign_in(client, store, "reader")
    path = "/api/studies/001/t0/files/gtv.nii.gz"
    first = client.get(path)
    assert first.status_code == 200 and first.headers["cache-control"] == "private, no-cache"
    etag = first.headers["etag"]
    for method in ("GET", "HEAD"):
        response = client.request(method, path, headers={"If-None-Match": etag})
        assert response.status_code == 304 and response.headers["cache-control"] == "private, no-cache"
    token = client.cookies.get("cerberus_session")
    client.portal.call(store.delete_session, token)
    for method in ("GET", "HEAD"):
        assert client.request(method, path, headers={"If-None-Match": etag}).status_code == 401


def test_owned_enqueue_registers_before_queue_and_cleans_failures() -> None:
    from types import SimpleNamespace

    from cerberus_api.access import OwnerStore, enqueue_owned_job

    async def scenario() -> None:
        redis: Any = FakeAsyncRedis()
        principal = Principal(issuer="https://id", sub="owner", roles=frozenset({"analyst"}))
        seen: list[str] = []

        async def enqueue(function: str, *args: Any, **kwargs: Any) -> Any:
            job_id = kwargs["_job_id"]
            assert await OwnerStore(redis).owns("jobs", job_id, principal)
            seen.append(job_id)
            if function == "fail":
                raise OSError("synthetic")
            if function == "collision":
                return None
            return SimpleNamespace(job_id=job_id)

        redis.enqueue_job = enqueue
        job = await enqueue_owned_job(redis, principal, "ok", "001", "t0")
        assert job and job.job_id == seen[-1]
        with pytest.raises(OSError):
            await enqueue_owned_job(redis, principal, "fail")
        assert not await OwnerStore(redis).owns("jobs", seen[-1], principal)
        assert await enqueue_owned_job(redis, principal, "collision") is None
        assert not await OwnerStore(redis).owns("jobs", seen[-1], principal)
        await redis.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("result_ttl,pending", [(5000, False), (-1, False), (None, False), (None, True)])
def test_worker_owner_lifetime_follows_arq_result(result_ttl: int | None, pending: bool) -> None:
    from cerberus_api.access import OwnerStore
    from cerberus_api.worker import finish_owner

    async def scenario() -> None:
        redis: Any = FakeAsyncRedis()
        principal = Principal(issuer="https://id", sub="owner", roles=frozenset({"analyst"}))
        owners = OwnerStore(redis)
        await owners.register("jobs", OWN_ID, principal)
        if result_ttl is not None:
            await redis.set(f"arq:result:{OWN_ID}", b"result")
            if result_ttl > 0:
                await redis.pexpire(f"arq:result:{OWN_ID}", result_ttl)
        if pending:
            await redis.set(f"arq:job:{OWN_ID}", b"retry")
        await finish_owner({"redis": redis, "job_id": OWN_ID})
        ttl = await redis.pttl(owners.key("jobs", OWN_ID))
        if result_ttl and result_ttl > 0:
            assert 0 < ttl <= result_ttl
        elif result_ttl == -1 or pending:
            assert ttl == -1
        else:
            assert ttl == -2
        # Los jobs de modo off carecen de propietario; el hook no inventa metadata.
        await finish_owner({"redis": redis, "job_id": "legacy-job"})
        await redis.aclose()

    asyncio.run(scenario())


def test_job_producers_store_owner_before_enqueue(
    guarded: Any, make_study: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from cerberus_api.access import OwnerStore
    from cerberus_api.deps import get_redis

    client, store, _ = guarded
    make_study(store.settings.data_dir)
    headers = sign_in(client, store)
    calls: list[str] = []
    principal = Principal(issuer="https://id.example", sub="one", roles=frozenset({"analyst"}))

    async def enqueue(function: str, *args: Any, **kwargs: Any) -> Any:
        job_id = kwargs["_job_id"]
        assert await OwnerStore(store.redis).owns("jobs", job_id, principal)
        calls.append(function)
        return SimpleNamespace(job_id=job_id)

    monkeypatch.setattr(store.redis, "enqueue_job", enqueue, raising=False)
    client.app.dependency_overrides[get_redis] = lambda: store.redis
    for operation in ("segmentation", "areas"):
        response = client.post(f"/api/studies/001/t0/{operation}", headers=headers)
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        assert client.portal.call(OwnerStore(store.redis).owns, "jobs", job_id, principal)
    assert calls == ["segment_study", "map_areas"]


def test_upload_owner_registered_before_queue_and_removed_on_delete(
    guarded: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import io
    import zipfile
    from types import SimpleNamespace

    from cerberus_api.access import OwnerStore
    from cerberus_api.deps import get_redis

    client, store, _ = guarded
    headers = sign_in(client, store)
    principal = Principal(issuer="https://id.example", sub="one", roles=frozenset({"analyst"}))
    owners = OwnerStore(store.redis)

    async def enqueue(function: str, *args: Any, **kwargs: Any) -> Any:
        assert await owners.owns("uploads", args[0], principal)
        assert await owners.owns("jobs", kwargs["_job_id"], principal)
        return SimpleNamespace(job_id=kwargs["_job_id"])

    monkeypatch.setattr(store.redis, "enqueue_job", enqueue, raising=False)
    client.app.dependency_overrides[get_redis] = lambda: store.redis
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("synthetic.txt", "sin datos personales")
    response = client.post(
        "/api/uploads",
        headers=headers,
        data={"patient": "999", "timepoint": "t0"},
        files={"file": ("synthetic.zip", archive.getvalue())},
    )
    assert response.status_code == 202
    upload_id = response.json()["upload_id"]
    path = f"/api/uploads/{upload_id}"
    assert client.get(path).status_code == 200
    sign_in(client, store, sub="two")
    assert client.get(path).status_code == 404
    assert client.delete(path, headers=sign_in(client, store, sub="two")).status_code == 404
    headers = sign_in(client, store, sub="one")
    assert client.delete(path, headers=headers).status_code == 204
    assert not client.portal.call(owners.owns, "uploads", upload_id, principal)
    assert client.get(path).status_code == 404


def test_upload_failure_cleans_both_owners_and_files(guarded: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    import io
    import zipfile

    from cerberus_api.deps import get_redis

    client, store, _ = guarded
    headers = sign_in(client, store)

    async def enqueue(*args: Any, **kwargs: Any) -> None:
        raise OSError("synthetic queue failure")

    monkeypatch.setattr(store.redis, "enqueue_job", enqueue, raising=False)
    client.app.dependency_overrides[get_redis] = lambda: store.redis
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("synthetic.txt", "sin datos personales")
    with pytest.raises(OSError):
        client.post(
            "/api/uploads",
            headers=headers,
            data={"patient": "999", "timepoint": "t0"},
            files={"file": ("synthetic.zip", archive.getvalue())},
        )
    assert not client.portal.call(store.redis.keys, "cerberus:auth:owners:*")
    assert not list(store.settings.tmp_dir.iterdir())
    assert not list(store.settings.staging_dir.iterdir())


def test_reader_can_read_shared_catalogue_and_reports(guarded: Any, make_study: Any) -> None:
    client, store, _ = guarded
    make_study(store.settings.data_dir)
    sign_in(client, store, "reader")
    for path in READ_PATHS:
        response = client.get(path)
        assert response.status_code not in {401, 403, 500, 503}
        assert response.headers["cache-control"] == ("private, no-cache" if path.endswith(".nii.gz") else "no-store")


def test_owner_store_fails_closed_and_refuses_collisions() -> None:
    from cerberus_api.access import OwnerStore
    from cerberus_api.sessions import SessionUnavailable

    async def scenario() -> None:
        server = FakeServer()
        redis = FakeAsyncRedis(server=server)
        owners = OwnerStore(redis)
        principal = Principal(issuer="https://id", sub="one", roles=frozenset({"analyst"}))
        with pytest.raises(ValueError):
            owners.key("jobs", "invalid")
        await owners.register("jobs", OWN_ID, principal)
        with pytest.raises(SessionUnavailable):
            await owners.register("jobs", OWN_ID, principal)
        server.connected = False
        for operation in (
            owners.register("uploads", OWN_ID, principal),
            owners.owns("jobs", OWN_ID, principal),
            owners.delete("jobs", OWN_ID),
        ):
            with pytest.raises(SessionUnavailable):
                await operation
        server.connected = True
        await redis.aclose()

    asyncio.run(scenario())


def test_preview_and_confirm_owned_upload(guarded: Any) -> None:
    from cerberus_api import staging
    from cerberus_api.access import OwnerStore
    from cerberus_api.deps import get_redis
    from cerberus_api.schemas import SeriesInfo, UploadManifest

    client, store, _ = guarded
    principal = Principal(issuer="https://id.example", sub="one", roles=frozenset({"analyst"}))
    owners = OwnerStore(store.redis)
    client.portal.call(owners.register, "uploads", OWN_ID, principal)
    staging.write_manifest(
        store.settings.staging_dir,
        UploadManifest(
            upload_id=OWN_ID,
            status="ready",
            series=[
                SeriesInfo(
                    index=0,
                    modality="MR",
                    description="Serie sintética",
                    n_files=1,
                    converted=True,
                    shape=None,
                    spacing_mm=None,
                    suggested_sequence=None,
                )
            ],
        ),
    )
    path = staging.series_path(store.settings.staging_dir, OWN_ID, 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"synthetic")
    client.app.dependency_overrides[get_redis] = lambda: store.redis
    headers = sign_in(client, store)
    for method in ("GET", "HEAD"):
        response = client.request(method, f"/api/uploads/{OWN_ID}/series/0.nii.gz")
        assert response.status_code == 200 and response.headers["cache-control"] == "private, no-cache"
    body = {"patient": "999", "timepoint": "t0", "mapping": {"0": "t1gd"}}
    other = sign_in(client, store, sub="two")
    assert client.post(f"/api/uploads/{OWN_ID}/confirm", headers=other, json=body).status_code == 404
    assert path.exists()
    headers = sign_in(client, store)
    response = client.post(f"/api/uploads/{OWN_ID}/confirm", headers=headers, json=body)
    assert response.status_code == 201 and response.json()["patient"] == "999"
    assert not client.portal.call(owners.owns, "uploads", OWN_ID, principal)
    assert not path.exists()


@pytest.mark.parametrize("mode", ["off", "oidc"])
def test_root_path_cannot_bypass_access_or_csrf(guarded: Any, mode: str) -> None:
    app = guarded[0].app if mode == "oidc" else create_app()
    with TestClient(app, root_path="/prefix", base_url="http://localhost:8080") as client:
        if mode == "oidc":
            for path in READ_PATHS + OWN_PATHS:
                assert client.get("/prefix" + path).status_code == 401
        assert client.post("/prefix/api/uploads").status_code == (401 if mode == "oidc" else 403)


@pytest.mark.parametrize("failure", ["expired", "corrupt", "missing_function", "max_tries", "abort"])
def test_real_arq_early_failures_expire_owner(failure: str) -> None:
    from arq.connections import ArqRedis
    from arq.utils import timestamp_ms

    from cerberus_api.access import OwnerStore
    from cerberus_api.worker import OwnedWorker

    async def noop(ctx: dict[str, Any]) -> None:
        pass

    async def scenario() -> None:
        fake = FakeAsyncRedis()
        redis = ArqRedis(connection_pool=fake.connection_pool)
        principal = Principal(issuer="https://id", sub="one", roles=frozenset({"analyst"}))
        owners = OwnerStore(redis)
        await owners.register("jobs", OWN_ID, principal)
        await redis.enqueue_job(
            "missing" if failure == "missing_function" else "noop",
            _job_id=OWN_ID,
            _job_try=2 if failure == "max_tries" else 1,
        )
        if failure == "expired":
            await redis.delete("arq:job:" + OWN_ID)
        elif failure == "corrupt":
            await redis.set("arq:job:" + OWN_ID, b"invalid")
        elif failure == "abort":
            await redis.zadd("arq:abort", {OWN_ID: timestamp_ms()})
        worker = OwnedWorker(
            [noop], redis_pool=redis, max_tries=1, keep_result=1, handle_signals=False, allow_abort_jobs=True
        )
        await worker.run_job(OWN_ID, timestamp_ms())
        assert 0 < await redis.pttl("arq:result:" + OWN_ID) <= 1000
        assert 0 < await redis.pttl(owners.key("jobs", OWN_ID)) <= 1000
        await redis.aclose()

    asyncio.run(scenario())


def test_worker_launcher_uses_settings_and_owned_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    from cerberus_api import worker

    calls: list[dict[str, Any]] = []

    class Runner:
        def __init__(self, **kwargs: Any) -> None:
            calls.append(kwargs)

        def run(self) -> None:
            calls[0]["ran"] = True

    monkeypatch.setattr(worker, "OwnedWorker", Runner)
    worker.run_worker()
    assert calls[0]["ran"]
    assert calls[0]["functions"] == worker.WorkerSettings.functions
    assert callable(calls[0]["after_job_end"])
