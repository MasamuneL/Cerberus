"""Tests de jobs (ticket B6): encolado de la segmentación, estado de jobs y worker, sin Redis ni torch."""

import asyncio
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from arq.jobs import JobStatus as ArqJobStatus
from fastapi.testclient import TestClient

from cerberus_api import worker
from cerberus_api.config import Settings
from cerberus_api.deps import get_redis, settings_dep
from cerberus_api.main import app
from cerberus_api.routers import jobs as jobs_router
from cerberus_api.schemas import ChannelUsed, DiceVsGtv, SegmentationResult, SegmentationVolumes
from conftest import MakeStudy


@dataclass
class FakeJob:
    job_id: str


class FakeRedis:
    """Sustituto de `ArqRedis`: registra las llamadas a `enqueue_job`."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    async def enqueue_job(self, function: str, *args: Any, **kwargs: Any) -> FakeJob:
        self.calls.append((function, *args))
        return FakeJob(job_id=f"job-{len(self.calls)}")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "Data", storage_dir=tmp_path / "storage", models_dir=tmp_path / "models")


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def client(settings: Settings, fake_redis: FakeRedis) -> Iterator[TestClient]:
    app.dependency_overrides[settings_dep] = lambda: settings
    app.dependency_overrides[get_redis] = lambda: fake_redis
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _sample_result() -> SegmentationResult:
    return SegmentationResult(
        device="custom",
        created_at=datetime(2026, 10, 27, 18, 0, tzinfo=UTC),
        channels=[
            ChannelUsed(model_channel="T1c", sequence="t1gd"),
            ChannelUsed(model_channel="T1", sequence=None),
            ChannelUsed(model_channel="T2", sequence=None),
            ChannelUsed(model_channel="FLAIR", sequence="flair"),
        ],
        volumes_cm3=SegmentationVolumes(wt=1.5, tc=0.25, et=0.1),
        dice_vs_gtv=DiceVsGtv(tc=0.857, wt=0.5),
        warnings=["Canal T1 faltante: se usaron ceros"],
    )


# --- POST /segmentation -------------------------------------------------------------------------------


def test_post_segmentation_enqueues(
    client: TestClient, settings: Settings, fake_redis: FakeRedis, make_study: MakeStudy
) -> None:
    make_study(settings.data_dir)
    r = client.post("/api/studies/001/t0/segmentation")
    assert r.status_code == 202
    assert r.json() == {"job_id": "job-1"}
    assert fake_redis.calls == [("segment_study", "001", "t0")]


@pytest.mark.parametrize("url", ["/api/studies/001/t9/segmentation", "/api/studies/1/t0/segmentation"])
def test_post_segmentation_404(
    client: TestClient, settings: Settings, fake_redis: FakeRedis, make_study: MakeStudy, url: str
) -> None:
    make_study(settings.data_dir)
    assert client.post(url).status_code == 404
    assert fake_redis.calls == []


def test_post_segmentation_422_without_channels(
    client: TestClient, settings: Settings, fake_redis: FakeRedis, make_study: MakeStudy
) -> None:
    make_study(settings.data_dir, seqs=("gtv", "brain_mask"))
    assert client.post("/api/studies/001/t0/segmentation").status_code == 422
    assert fake_redis.calls == []


# --- GET /segmentation --------------------------------------------------------------------------------


def test_get_segmentation_reads_json(client: TestClient, settings: Settings) -> None:
    out = settings.results_dir / "001" / "t0" / "monai_seg.json"
    out.parent.mkdir(parents=True)
    expected = _sample_result()
    out.write_text(expected.model_dump_json(), encoding="utf-8")
    r = client.get("/api/studies/001/t0/segmentation")
    assert r.status_code == 200
    assert SegmentationResult.model_validate(r.json()) == expected


@pytest.mark.parametrize("url", ["/api/studies/001/t0/segmentation", "/api/studies/..%2F/t0/segmentation"])
def test_get_segmentation_404(client: TestClient, url: str) -> None:
    assert client.get(url).status_code == 404


# --- GET /jobs/{job_id} -------------------------------------------------------------------------------


@dataclass
class FakeResultInfo:
    success: bool
    result: Any


def _fake_job_class(status: ArqJobStatus, info: FakeResultInfo | None = None) -> type:
    class FakeArqJob:
        def __init__(self, job_id: str, redis: Any) -> None:
            self.job_id = job_id

        async def status(self) -> ArqJobStatus:
            return status

        async def result_info(self) -> FakeResultInfo | None:
            return info

    return FakeArqJob


@pytest.mark.parametrize(
    ("arq_status", "expected"),
    [
        (ArqJobStatus.deferred, "queued"),
        (ArqJobStatus.queued, "queued"),
        (ArqJobStatus.in_progress, "in_progress"),
        (ArqJobStatus.not_found, "not_found"),
    ],
)
def test_job_status_pending(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, arq_status: ArqJobStatus, expected: str
) -> None:
    monkeypatch.setattr(jobs_router, "Job", _fake_job_class(arq_status))
    r = client.get("/api/jobs/abc")
    assert r.status_code == 200
    assert r.json() == {"job_id": "abc", "status": expected, "result": None, "error": None}


def test_job_status_complete(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    result = {"device": "mps", "volumes_cm3": {"wt": 1.0, "tc": 0.5, "et": 0.2}}
    monkeypatch.setattr(jobs_router, "Job", _fake_job_class(ArqJobStatus.complete, FakeResultInfo(True, result)))
    r = client.get("/api/jobs/abc")
    assert r.json() == {"job_id": "abc", "status": "complete", "result": result, "error": None}


def test_job_status_failed(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    info = FakeResultInfo(False, ValueError("No hay ninguna secuencia utilizable"))
    monkeypatch.setattr(jobs_router, "Job", _fake_job_class(ArqJobStatus.complete, info))
    r = client.get("/api/jobs/abc")
    assert r.json() == {
        "job_id": "abc",
        "status": "failed",
        "result": None,
        "error": "No hay ninguna secuencia utilizable",
    }


def test_job_status_result_expired(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jobs_router, "Job", _fake_job_class(ArqJobStatus.complete, None))
    assert client.get("/api/jobs/abc").json()["status"] == "not_found"


# --- Arranque sin Redis -------------------------------------------------------------------------------


def test_app_starts_without_redis(settings: Settings) -> None:
    """La app arranca (lifespan incluido) y /api/health responde aunque Redis no esté corriendo."""
    with TestClient(app) as c:
        assert c.get("/api/health").json() == {"status": "ok"}


def test_redis_down_returns_503(settings: Settings, make_study: MakeStudy, monkeypatch: pytest.MonkeyPatch) -> None:
    # Puerto 1: nadie escucha → error de conexión inmediato
    down = settings.model_copy(update={"redis_url": "redis://127.0.0.1:1"})
    make_study(settings.data_dir)
    app.dependency_overrides[settings_dep] = lambda: down
    try:
        with TestClient(app) as c:
            r = c.post("/api/studies/001/t0/segmentation")
            assert r.status_code == 503
            assert r.json()["detail"] == "Redis no disponible: inicia redis-server y el worker"
    finally:
        app.dependency_overrides.clear()


# --- Worker -------------------------------------------------------------------------------------------


def test_worker_segment_study(settings: Settings, make_study: MakeStudy, monkeypatch: pytest.MonkeyPatch) -> None:
    make_study(settings.data_dir, seqs=("t1gd", "flair", "gtv", "brain_mask"))
    calls: list[tuple[dict[str, Path], Path, Path]] = []

    def fake_run(study_files: dict[str, Path], out_dir: Path, models_dir: Path) -> SegmentationResult:
        calls.append((study_files, out_dir, models_dir))
        return _sample_result()

    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    monkeypatch.setattr(worker, "run_segmentation", fake_run)
    out = asyncio.run(worker.segment_study({}, "001", "t0"))

    assert out == _sample_result().model_dump(mode="json")
    assert out["created_at"] == "2026-10-27T18:00:00Z"
    (files, out_dir, models_dir) = calls[0]
    assert sorted(files) == ["brain_mask", "flair", "gtv", "t1gd"]
    assert files["t1gd"] == settings.data_dir / "001" / "t0" / "1_t0_t1gd.nii.gz"
    assert out_dir == settings.results_dir / "001" / "t0"
    assert models_dir == settings.models_dir


@pytest.mark.parametrize(("patient", "timepoint"), [("001", "t9"), ("../x", "t0")])
def test_worker_segment_study_invalid(
    settings: Settings, make_study: MakeStudy, monkeypatch: pytest.MonkeyPatch, patient: str, timepoint: str
) -> None:
    make_study(settings.data_dir)
    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    with pytest.raises(ValueError):
        asyncio.run(worker.segment_study({}, patient, timepoint))


def test_worker_ingest_dicom_invalid_upload_id() -> None:
    # B8 ya implementó ingest_dicom (tests completos en test_dicom.py): un id inválido se rechaza antes del disco
    with pytest.raises(ValueError):
        asyncio.run(worker.ingest_dicom({}, "u1", "/tmp/x.zip"))


def test_worker_settings() -> None:
    assert worker.WorkerSettings.functions == [worker.segment_study, worker.ingest_dicom]
    assert worker.WorkerSettings.job_timeout == 1800
    assert worker.WorkerSettings.max_jobs == 1
