"""Tests de las máscaras suavizadas para el visor (`cerberus_api.display`) y de `?smooth=true`."""

import gzip
import os
from collections.abc import Iterator
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest
from fastapi.testclient import TestClient

from cerberus_api.atlas import affine_of
from cerberus_api.config import Settings
from cerberus_api.deps import settings_dep
from cerberus_api.display import display_path, ensure_smoothed, smooth_labels
from cerberus_api.main import app
from cerberus_api.nifti import load_nifti
from conftest import GTV_SLICE, MakeNifti, MakeStudy

AFF = np.diag([0.5, 0.5, 1.0, 1.0])


def test_cube_corners_are_rounded_and_volume_kept() -> None:
    data = np.zeros((40, 40, 20), np.uint8)
    data[GTV_SLICE] = 1
    out = smooth_labels(data, AFF, (40, 40, 20), AFF)
    assert out[15, 15, 10] == 1  # centro intacto
    assert out[10, 10, 5] == 0  # la esquina del cubo se redondea
    assert set(np.unique(out)) == {0, 1}
    assert abs(int(out.sum()) - int(data.sum())) / data.sum() < 0.25


def test_single_voxel_focus_is_kept() -> None:
    data = np.zeros((20, 20, 10), np.uint8)
    data[5, 5, 5] = 1
    out = smooth_labels(data, AFF, (20, 20, 10), AFF)
    assert out[5, 5, 5] == 1


def test_resamples_to_finer_reference_grid() -> None:
    src_aff = np.diag([1.0, 1.0, 1.0, 1.0])
    data = np.zeros((20, 20, 20), np.uint8)
    data[5:15, 5:15, 5:15] = 2  # etiqueta 2 de MONAI
    out = smooth_labels(data, src_aff, (40, 40, 20), AFF)
    assert out.shape == (40, 40, 20)
    assert out[20, 20, 10] == 2  # centro (10 mm) → vóxel (20, 20, 10)
    assert out[2, 2, 2] == 0
    # ~1000 mm³ en vóxeles de 0.25 mm³
    assert 2500 < int((out > 0).sum()) < 4500


def test_adjacent_labels_leave_no_gap() -> None:
    data = np.zeros((40, 40, 20), np.uint8)
    data[5:20, 5:35, 3:17] = 3
    data[20:35, 5:35, 3:17] = 7
    out = smooth_labels(data, AFF, (40, 40, 20), AFF)
    # La frontera entre ambas áreas sigue ocupada: sin huecos donde ninguna llega a 0.5
    assert np.all(out[15:25, 20, 10] > 0)
    assert out[10, 20, 10] == 3 and out[30, 20, 10] == 7


def test_tiny_label_between_large_ones_survives() -> None:
    data = np.zeros((40, 40, 20), np.uint8)
    data[5:35, 5:35, 3:17] = 1
    data[20, 20, 10] = 9
    out = smooth_labels(data, AFF, (40, 40, 20), AFF)
    assert 9 in np.unique(out)


def test_empty_mask() -> None:
    out = smooth_labels(np.zeros((8, 8, 4)), AFF, (8, 8, 4), AFF)
    assert not out.any()


def test_ensure_smoothed_caches_and_regenerates(tmp_path: Path, make_nifti: MakeNifti) -> None:
    data = np.zeros((40, 40, 20), np.uint8)
    data[GTV_SLICE] = 1
    src = make_nifti(tmp_path / "gtv.nii.gz", data)
    target = tmp_path / "display" / "gtv.nii.gz"
    ensure_smoothed(src, None, target)
    first = target.stat().st_mtime_ns
    ensure_smoothed(src, None, target)
    assert target.stat().st_mtime_ns == first  # reutiliza la caché
    stat = src.stat()
    os.utime(src, ns=(stat.st_atime_ns, first + 10**9))
    ensure_smoothed(src, None, target)
    assert target.stat().st_mtime_ns != first  # origen más nuevo → regenera
    img = load_nifti(target)
    assert img.shape == (40, 40, 20)
    assert np.allclose(affine_of(img), AFF)
    assert sorted(p.name for p in target.parent.iterdir()) == ["gtv.nii.gz"]  # sin temporales huérfanos


# --- API: /files/{name}.nii.gz?smooth=true --------------------------------------------------------------


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "Data", storage_dir=tmp_path / "storage", models_dir=tmp_path / "models")


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    app.dependency_overrides[settings_dep] = lambda: settings
    try:
        yield TestClient(app, base_url="http://localhost", headers={"X-Cerberus": "1"})
    finally:
        app.dependency_overrides.clear()


def _decode(content: bytes) -> nib.Nifti1Image:
    return nib.Nifti1Image.from_bytes(gzip.decompress(content))


def test_api_smooth_gtv(client: TestClient, settings: Settings, make_study: MakeStudy) -> None:
    make_study(settings.data_dir)
    r = client.get("/api/studies/001/t0/files/gtv.nii.gz", params={"smooth": "true"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/gzip"
    assert _decode(r.content).shape == (40, 40, 20)
    assert display_path(settings.results_dir, "001", "t0", "gtv").is_file()
    # Sin `smooth` se sirve el original, que sigue siendo el que usan las métricas
    raw = client.get("/api/studies/001/t0/files/gtv.nii.gz")
    assert raw.content != r.content


def test_api_smooth_monai_seg_on_reference_grid(
    client: TestClient, settings: Settings, make_study: MakeStudy, make_nifti: MakeNifti
) -> None:
    make_study(settings.data_dir)
    seg = np.zeros((20, 20, 20), np.uint8)
    seg[5:15, 5:15, 5:15] = 1
    make_nifti(settings.results_dir / "001" / "t0" / "monai_seg.nii.gz", seg, zooms=(1.0, 1.0, 1.0))
    r = client.get("/api/studies/001/t0/files/monai_seg.nii.gz?smooth=1")
    assert r.status_code == 200
    img = _decode(r.content)
    assert img.shape == (40, 40, 20)  # rejilla del GTV, no la de 1 mm del modelo
    assert np.allclose(affine_of(img), AFF)


def test_api_smooth_rejects_other_sequences(client: TestClient, settings: Settings, make_study: MakeStudy) -> None:
    make_study(settings.data_dir)
    assert client.get("/api/studies/001/t0/files/t1gd.nii.gz?smooth=true").status_code == 400


@pytest.mark.parametrize(
    "url",
    [
        "/api/studies/001/t0/files/brodmann.nii.gz?smooth=true",  # sin áreas calculadas
        "/api/studies/abc/t0/files/gtv.nii.gz?smooth=true",
        "/api/studies/001/t0x/files/gtv.nii.gz?smooth=true",
    ],
)
def test_api_smooth_404(client: TestClient, settings: Settings, make_study: MakeStudy, url: str) -> None:
    make_study(settings.data_dir)
    assert client.get(url).status_code == 404
