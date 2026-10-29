"""Tests de la API de lectura (ticket B4) con `TestClient` y settings apuntando a `tmp_path`."""

import os
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from cerberus_api.config import Settings
from cerberus_api.deps import settings_dep
from cerberus_api.main import app
from conftest import MakeNifti, MakeStudy


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "Data", storage_dir=tmp_path / "storage", models_dir=tmp_path / "models")


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    app.dependency_overrides[settings_dep] = lambda: settings
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_health(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_list_studies(client: TestClient, settings: Settings, make_study: MakeStudy) -> None:
    make_study(settings.data_dir, patient="002", timepoint="t0", seqs=("t1gd",))
    make_study(settings.data_dir, patient="001", timepoint="t0")
    r = client.get("/api/studies")
    assert r.status_code == 200
    body = r.json()
    assert [(s["patient"], s["timepoint"]) for s in body] == [("001", "t0"), ("002", "t0")]
    assert body[0]["sequences"] == ["brain_mask", "flair", "gtv", "t1gd"]
    assert body[0]["has_gtv"] is True
    assert body[1]["has_gtv"] is False


def test_study_detail(client: TestClient, settings: Settings, make_study: MakeStudy) -> None:
    make_study(settings.data_dir)
    r = client.get("/api/studies/001/t0")
    assert r.status_code == 200
    vols = {v["sequence"]: v for v in r.json()["volumes"]}
    assert vols["t1gd"]["shape"] == [40, 40, 20]
    assert vols["t1gd"]["spacing_mm"] == [0.5, 0.5, 1.0]
    assert vols["gtv"]["label"] == "GTV de radioterapia (etiqueta)"


@pytest.mark.parametrize("url", ["/api/studies/001/t9", "/api/studies/1/t0", "/api/studies/001/x"])
def test_study_detail_404(client: TestClient, settings: Settings, make_study: MakeStudy, url: str) -> None:
    make_study(settings.data_dir)
    r = client.get(url)
    assert r.status_code == 404
    assert r.json()["detail"] == "Estudio no encontrado"


def test_file_download(client: TestClient, settings: Settings, make_study: MakeStudy) -> None:
    study_dir = make_study(settings.data_dir)
    r = client.get("/api/studies/001/t0/files/t1gd.nii.gz")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/gzip"
    assert r.content == (study_dir / "1_t0_t1gd.nii.gz").read_bytes()
    head = client.head("/api/studies/001/t0/files/t1gd.nii.gz")
    assert head.status_code == 200
    assert int(head.headers["content-length"]) == len(r.content)


def test_monai_seg_served_only_when_present(client: TestClient, settings: Settings, make_study: MakeStudy) -> None:
    make_study(settings.data_dir)
    url = "/api/studies/001/t0/files/monai_seg.nii.gz"
    assert client.get(url).status_code == 404
    seg = settings.results_dir / "001" / "t0" / "monai_seg.nii.gz"
    seg.parent.mkdir(parents=True)
    seg.write_bytes(b"\x1f\x8bfake")
    r = client.get(url)
    assert r.status_code == 200
    assert r.content == b"\x1f\x8bfake"


# --- §16 · Caché HTTP (ETag / Last-Modified → 304) ----------------------------------------------------

FILE_URL = "/api/studies/001/t0/files/t1gd.nii.gz"


def test_file_cache_headers(client: TestClient, settings: Settings, make_study: MakeStudy) -> None:
    make_study(settings.data_dir)
    for r in (client.get(FILE_URL), client.head(FILE_URL)):
        assert r.status_code == 200
        assert r.headers["cache-control"] == "no-cache"
        assert r.headers["etag"].startswith('"')
        assert "last-modified" in r.headers
        assert r.headers["accept-ranges"] == "bytes"


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_file_304_if_none_match(client: TestClient, settings: Settings, make_study: MakeStudy, method: str) -> None:
    make_study(settings.data_dir)
    etag = client.head(FILE_URL).headers["etag"]
    for inm in (etag, f"W/{etag}", f'"otro", {etag}', "*"):
        r = client.request(method, FILE_URL, headers={"If-None-Match": inm})
        assert r.status_code == 304, inm
        assert r.content == b""
        assert r.headers["etag"] == etag
        assert r.headers["cache-control"] == "no-cache"


def test_file_200_on_etag_mismatch(client: TestClient, settings: Settings, make_study: MakeStudy) -> None:
    study_dir = make_study(settings.data_dir)
    r = client.get(FILE_URL, headers={"If-None-Match": '"no-coincide"'})
    assert r.status_code == 200
    assert r.content == (study_dir / "1_t0_t1gd.nii.gz").read_bytes()


def test_file_etag_changes_when_file_changes(client: TestClient, settings: Settings, make_study: MakeStudy) -> None:
    study_dir = make_study(settings.data_dir)
    etag = client.head(FILE_URL).headers["etag"]
    path = study_dir / "1_t0_t1gd.nii.gz"
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    r = client.get(FILE_URL, headers={"If-None-Match": etag})
    assert r.status_code == 200
    assert r.headers["etag"] != etag


def test_file_if_modified_since(client: TestClient, settings: Settings, make_study: MakeStudy) -> None:
    make_study(settings.data_dir)
    last_modified = client.head(FILE_URL).headers["last-modified"]
    r = client.get(FILE_URL, headers={"If-Modified-Since": last_modified})
    assert r.status_code == 304
    assert r.content == b""
    assert client.get(FILE_URL, headers={"If-Modified-Since": "Thu, 01 Jan 2004 00:00:00 GMT"}).status_code == 200
    assert client.get(FILE_URL, headers={"If-Modified-Since": "no es fecha"}).status_code == 200
    # If-None-Match manda sobre If-Modified-Since
    both = {"If-None-Match": '"no-coincide"', "If-Modified-Since": last_modified}
    assert client.get(FILE_URL, headers=both).status_code == 200


def test_file_range_still_works(client: TestClient, settings: Settings, make_study: MakeStudy) -> None:
    study_dir = make_study(settings.data_dir)
    data = (study_dir / "1_t0_t1gd.nii.gz").read_bytes()
    r = client.get(FILE_URL, headers={"Range": "bytes=0-99"})
    assert r.status_code == 206
    assert r.content == data[:100]
    assert r.headers["content-range"] == f"bytes 0-99/{len(data)}"
    etag = r.headers["etag"]
    assert client.get(FILE_URL, headers={"Range": "bytes=0-99", "If-Range": etag}).status_code == 206
    assert client.get(FILE_URL, headers={"Range": "bytes=0-99", "If-Range": '"viejo"'}).status_code == 200


@pytest.mark.parametrize(
    "url",
    [
        "/api/studies/001/t0/files/..%2F..%2Fetc%2Fpasswd",
        "/api/studies/001/t0/files/..%2F..%2Fetc%2Fpasswd.nii.gz",
        "/api/studies/001/t0/files/passwd.nii.gz",  # nombre no servible
        "/api/studies/001/t0/files/t2tse.nii.gz",  # secuencia válida pero ausente
        "/api/studies/1/t0/files/t1gd.nii.gz",  # paciente inválido
        "/api/studies/001/t0/files/t1gd",  # sin .nii.gz
        "/api/studies/001/t0/files/t1gd.nii",
    ],
)
def test_file_404(client: TestClient, settings: Settings, make_study: MakeStudy, url: str) -> None:
    make_study(settings.data_dir)
    assert client.get(url).status_code == 404


def test_volumetry(client: TestClient, settings: Settings, make_study: MakeStudy) -> None:
    make_study(settings.data_dir)
    r = client.get("/api/studies/001/t0/volumetry")
    assert r.status_code == 200
    body = r.json()
    # 1000 vóxeles × 0.5 × 0.5 × 1 mm³ = 250 mm³ = 0.25 cm³
    assert body["gtv_cm3"] == 0.25
    assert (body["lr_mm"], body["ap_mm"], body["si_mm"]) == (5.0, 5.0, 10.0)
    assert body["components"] == 1


def test_volumetry_404_without_gtv(client: TestClient, settings: Settings, make_study: MakeStudy) -> None:
    make_study(settings.data_dir, seqs=("t1gd", "brain_mask"))
    r = client.get("/api/studies/001/t0/volumetry")
    assert r.status_code == 404
    assert r.json()["detail"] == "El estudio no tiene GTV o máscara cerebral"


def test_volumetry_422_empty_gtv(
    client: TestClient, settings: Settings, make_study: MakeStudy, make_nifti: MakeNifti
) -> None:
    study_dir = make_study(settings.data_dir)
    make_nifti(study_dir / "1_t0_gtv.nii.gz", np.zeros((40, 40, 20), np.uint8))
    assert client.get("/api/studies/001/t0/volumetry").status_code == 422


def test_longitudinal(client: TestClient, settings: Settings, make_study: MakeStudy, make_nifti: MakeNifti) -> None:
    make_study(settings.data_dir, timepoint="t0")
    t1_dir = make_study(settings.data_dir, timepoint="t1", seqs=("gtv", "brain_mask"))
    # GTV de t1 a la mitad: 500 vóxeles → 0.125 cm³, redondeado a 0.12 → -52 % vs t0 (MR)
    gtv = np.zeros((40, 40, 20), np.uint8)
    gtv[10:20, 10:20, 5:10] = 1
    make_nifti(t1_dir / "1_t1_gtv.nii.gz", gtv)
    r = client.get("/api/patients/001/longitudinal")
    assert r.status_code == 200
    assert r.json() == [
        {"timepoint": "t0", "gtv_cm3": 0.25, "change_vs_t0_pct": 0.0, "rano": None},
        {"timepoint": "t1", "gtv_cm3": 0.12, "change_vs_t0_pct": -52.0, "rano": "MR"},
    ]


def test_longitudinal_invalid_patient(client: TestClient) -> None:
    r = client.get("/api/patients/1/longitudinal")
    assert r.status_code == 404
    assert r.json()["detail"] == "Paciente no encontrado"
