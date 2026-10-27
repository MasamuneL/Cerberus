"""Tests de la subida de NIfTI (ticket B7) con `TestClient` y settings apuntando a `tmp_path`."""

import gzip
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cerberus_api.config import Settings
from cerberus_api.deps import settings_dep
from cerberus_api.main import create_app
from cerberus_api.nifti import load_nifti
from cerberus_api.routers import uploads
from conftest import MakeNifti

# Starlette tipa la respuesta con httpx o httpx2 según lo instalado: se deja como `Any`
Upload = Callable[..., Any]
NiftiBytes = Callable[..., bytes]


def _make_app(settings: Settings) -> FastAPI:
    """App de test con settings apuntando a `tmp_path` (main.py ya monta `uploads`)."""
    app = create_app()
    app.dependency_overrides[settings_dep] = lambda: settings
    return app


def _tmp_is_empty(settings: Settings) -> bool:
    tmp = settings.tmp_dir
    return not tmp.exists() or not any(tmp.iterdir())


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "Data", storage_dir=tmp_path / "storage", models_dir=tmp_path / "models")


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(_make_app(settings))


@pytest.fixture
def nifti_bytes(tmp_path: Path, make_nifti: MakeNifti) -> NiftiBytes:
    """`nifti_bytes(shape=(8, 8, 4), suffix=".nii.gz")` → bytes de un NIfTI sintético."""

    def _make(shape: tuple[int, ...] = (8, 8, 4), suffix: str = ".nii.gz") -> bytes:
        data = np.arange(int(np.prod(shape)), dtype=np.float32).reshape(shape)
        return make_nifti(tmp_path / "src" / f"vol{suffix}", data).read_bytes()

    return _make


@pytest.fixture
def upload(client: TestClient, settings: Settings) -> Iterator[Upload]:
    """POST a /api/uploads; tras cada petición comprueba que `storage/tmp` quede vacío."""

    def _post(
        content: bytes,
        filename: str = "vol.nii.gz",
        patient: str = "001",
        timepoint: str = "t0",
        sequence: str | None = "flair",
    ) -> Any:
        form = {"patient": patient, "timepoint": timepoint}
        if sequence is not None:
            form["sequence"] = sequence
        r = client.post("/api/uploads", data=form, files={"file": (filename, content, "application/octet-stream")})
        assert _tmp_is_empty(settings), "storage/tmp debe quedar vacío"
        return r

    yield _post


def test_upload_nii_gz(upload: Upload, client: TestClient, settings: Settings, nifti_bytes: NiftiBytes) -> None:
    r = upload(nifti_bytes())
    assert r.status_code == 201
    assert r.json() == {
        "patient": "001",
        "timepoint": "t0",
        "sequences": ["flair"],
        "has_gtv": False,
        "has_brain_mask": False,
        "has_segmentation": False,
    }
    assert (settings.data_dir / "001" / "t0" / "1_t0_flair.nii.gz").is_file()
    studies = client.get("/api/studies").json()
    assert [(s["patient"], s["timepoint"], s["sequences"]) for s in studies] == [("001", "t0", ["flair"])]


def test_upload_uncompressed_nii_stored_as_gz(upload: Upload, settings: Settings, nifti_bytes: NiftiBytes) -> None:
    r = upload(nifti_bytes(suffix=".nii"), filename="SCAN.NII", sequence="t1gd", timepoint="t2")
    assert r.status_code == 201
    assert r.json()["sequences"] == ["t1gd"]
    target = settings.data_dir / "001" / "t2" / "1_t2_t1gd.nii.gz"
    with target.open("rb") as f:
        assert f.read(2) == b"\x1f\x8b"  # cabecera gzip
    assert load_nifti(target).shape == (8, 8, 4)


def test_upload_4d_singleton_squeezed(upload: Upload, settings: Settings, nifti_bytes: NiftiBytes) -> None:
    r = upload(nifti_bytes(shape=(8, 8, 4, 1)))
    assert r.status_code == 201
    assert load_nifti(settings.data_dir / "001" / "t0" / "1_t0_flair.nii.gz").shape == (8, 8, 4)


@pytest.mark.parametrize(
    ("kwargs", "status"),
    [
        ({"sequence": None}, 422),
        ({"sequence": "tumor"}, 422),
        ({"sequence": "../etc"}, 422),
        ({"patient": "1"}, 422),
        ({"patient": "../001"}, 422),
        ({"timepoint": "x0"}, 422),
        ({"filename": "notas.txt"}, 415),
        ({"filename": "estudio.zip"}, 501),
    ],
)
def test_upload_rejected(
    upload: Upload, settings: Settings, nifti_bytes: NiftiBytes, kwargs: dict[str, str | None], status: int
) -> None:
    r = upload(nifti_bytes(), **kwargs)
    assert r.status_code == status
    assert isinstance(r.json()["detail"], str)
    assert not settings.data_dir.exists() or not any(settings.data_dir.rglob("*.nii.gz"))


def test_upload_duplicate_409(upload: Upload, nifti_bytes: NiftiBytes) -> None:
    assert upload(nifti_bytes()).status_code == 201
    r = upload(nifti_bytes())
    assert r.status_code == 409
    assert r.json()["detail"] == "Ese volumen ya existe en el estudio"


@pytest.mark.parametrize("content", [b"esto no es un NIfTI", gzip.compress(b"tampoco" * 100)])
def test_upload_not_nifti_422(upload: Upload, settings: Settings, content: bytes) -> None:
    r = upload(content)
    assert r.status_code == 422
    assert r.json()["detail"] == "Archivo NIfTI inválido"
    assert not (settings.data_dir / "001" / "t0" / "1_t0_flair.nii.gz").exists()


def test_upload_4d_422(upload: Upload, nifti_bytes: NiftiBytes) -> None:
    r = upload(nifti_bytes(shape=(8, 8, 4, 3)))
    assert r.status_code == 422
    assert "3D" in r.json()["detail"]


def test_upload_too_large_413(tmp_path: Path) -> None:
    small = Settings(
        data_dir=tmp_path / "Data", storage_dir=tmp_path / "storage", models_dir=tmp_path / "models", max_upload_mb=1
    )
    client = TestClient(_make_app(small))
    content = b"\0" * (uploads.CHUNK_SIZE + 1)
    r = client.post(
        "/api/uploads",
        data={"patient": "001", "timepoint": "t0", "sequence": "flair"},
        files={"file": ("big.nii.gz", content, "application/octet-stream")},
    )
    assert r.status_code == 413
    assert _tmp_is_empty(small)
    assert not (small.data_dir / "001").exists()
