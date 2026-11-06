"""Tests de areas.py, `worker.map_areas` y las rutas `/areas` (§13, ticket B11).

Los rápidos usan un mapa de etiquetas sintético y un `map_atlas` falso (sin red ni ANTs); el `slow` mapea de verdad
Data/001/t0.
"""

import asyncio
import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np
import pytest
from fastapi.testclient import TestClient

from cerberus_api import atlas, worker
from cerberus_api.areas import (
    AREAS_JSON,
    ATLAS_NAME,
    MARGIN_MM,
    WARN_NO_WT,
    compute_area_report,
    run_area_mapping,
)
from cerberus_api.atlas import AtlasMapping
from cerberus_api.config import REPO_ROOT, Settings
from cerberus_api.deps import get_redis, settings_dep
from cerberus_api.main import app
from cerberus_api.schemas import AreaLabel, AreasResult, Hemisphere
from conftest import MakeStudy

# --- Mapa sintético ---------------------------------------------------------------------------------------
#
# 30×10×10 a (1, 1, 2) mm → 2 mm³ por vóxel. GTV: x 10–14, z 0–4 (todo y) = 250 vóxeles.
#   40  BA40 izq.     x 5–11            → 700 vóx, 100 en el GTV
#   144 BA44 der.     x 12–15, z 0–6    → 280 vóx, 150 en el GTV
#   7   BA7 izq.      x 12–15, z 7–9    → sobre el GTV en x, 3 cortes arriba en z: (7 - 4) × 2 mm = 6 mm
#   9   desconocida   x 18–19           → 4 mm en x
#   10  BA99 (desc.)  x 27–29           → 13 mm: fuera del margen
#   11  en entries pero ausente del mapa

ZOOMS = (1.0, 1.0, 2.0)
SHAPE = (30, 10, 10)
ENTRIES: list[tuple[int, str, Hemisphere]] = [
    (7, "Brodmann area 7", "izquierdo"),
    (9, "Mystery structure", "derecho"),
    (10, "Brodmann area 99", "izquierdo"),
    (11, "Brodmann area 17", "izquierdo"),
    (40, "Brodmann area 40", "izquierdo"),
    (144, "Brodmann area 44", "derecho"),
]


def _labels() -> np.ndarray:
    lab = np.zeros(SHAPE, np.uint8)
    lab[5:12] = 40
    lab[12:16, :, :7] = 144
    lab[12:16, :, 7:] = 7
    lab[18:20] = 9
    lab[27:30] = 10
    return lab


def _gtv() -> np.ndarray:
    gtv = np.zeros(SHAPE, np.uint8)
    gtv[10:15, :, :5] = 1
    return gtv


def _save(path: Path, data: np.ndarray, zooms: tuple[float, float, float] = ZOOMS) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(data, np.diag([*zooms, 1.0])), path)
    return path


@pytest.fixture
def synthetic(tmp_path: Path) -> tuple[Path, Path]:
    return _save(tmp_path / "brodmann.nii.gz", _labels()), _save(tmp_path / "gtv.nii.gz", _gtv())


def test_report_overlaps_distances_and_order(synthetic: tuple[Path, Path]) -> None:
    label_path, gtv_path = synthetic
    areas, lut = compute_area_report(label_path, ENTRIES, gtv_path, None)

    assert [a.label for a in areas] == [144, 40, 9, 7]  # solapadas por cm³ desc, luego cercanas por distancia
    by = {a.label: a for a in areas}

    ba44 = by[144]
    assert (ba44.area_cm3, ba44.overlap_gtv_cm3, ba44.overlap_gtv_pct, ba44.distance_mm) == (0.56, 0.3, 53.6, 0.0)
    assert ba44.hemisphere == "derecho" and ba44.kind == "cortical"
    ba40 = by[40]
    assert (ba40.area_cm3, ba40.overlap_gtv_cm3, ba40.overlap_gtv_pct, ba40.distance_mm) == (1.4, 0.2, 14.3, 0.0)
    assert ba40.eloquent is True
    assert "Procesamiento fonológico del lenguaje" in ba40.functions  # función del lado izquierdo
    assert ba40.domains == ["lenguaje", "sensitivo"]  # dominios: lado izquierdo + generales (§14)
    assert "lenguaje" not in ba44.domains and "motor" in ba44.domains  # BA44 derecho

    # Distancia en z con spacing anisotrópico (2 mm) y en x (1 mm)
    assert by[7].distance_mm == 6.0 and by[7].overlap_gtv_cm3 == 0.0 and by[7].overlap_gtv_pct == 0.0
    assert by[9].distance_mm == 4.0

    # Nombre desconocido: se conserva el del atlas, sin funciones
    assert (by[9].name_es, by[9].kind, by[9].functions, by[9].eloquent) == (
        "Mystery structure",
        "subcortical",
        [],
        False,
    )
    assert by[9].domains == []

    # Sin WT: campos None
    assert all(a.overlap_wt_cm3 is None and a.overlap_wt_pct is None for a in areas)

    # LUT: todas las etiquetas presentes (la 10 aunque esté lejos), sin la 11 ausente
    assert [entry.label for entry in lut] == [7, 9, 10, 40, 144]
    ba99 = next(entry for entry in lut if entry.label == 10)
    assert (ba99.name_es, ba99.kind) == ("Brodmann area 99", "cortical")


def test_report_margin(synthetic: tuple[Path, Path]) -> None:
    label_path, gtv_path = synthetic
    narrow, _ = compute_area_report(label_path, ENTRIES, gtv_path, None, margin_mm=5.0)
    assert [a.label for a in narrow] == [144, 40, 9]
    wide, _ = compute_area_report(label_path, ENTRIES, gtv_path, None, margin_mm=15.0)
    assert [a.label for a in wide] == [144, 40, 9, 7, 10]
    assert wide[-1].distance_mm == 13.0


def test_report_with_wt(synthetic: tuple[Path, Path]) -> None:
    label_path, gtv_path = synthetic
    wt = _gtv().astype(bool)
    wt[16:19] = True  # edema hacia la etiqueta 9 (incluye x = 18)
    areas, _ = compute_area_report(label_path, ENTRIES, gtv_path, wt)
    by = {a.label: a for a in areas}
    assert (by[9].overlap_wt_cm3, by[9].overlap_wt_pct) == (0.2, 50.0)
    assert (by[40].overlap_wt_cm3, by[40].overlap_wt_pct) == (0.2, 14.3)
    assert by[7].overlap_wt_cm3 == 0.0


def test_report_wt_wrong_shape_raises(synthetic: tuple[Path, Path]) -> None:
    label_path, gtv_path = synthetic
    with pytest.raises(ValueError):
        compute_area_report(label_path, ENTRIES, gtv_path, np.zeros((2, 2, 2), bool))


def test_report_resamples_gtv(tmp_path: Path, synthetic: tuple[Path, Path]) -> None:
    """GTV en otro grid (x a 0.5 mm): se remuestrea con orden 0 y da lo mismo."""
    label_path, gtv_path = synthetic
    fine = np.repeat(_gtv(), 2, axis=0)
    fine_path = _save(tmp_path / "gtv_fine.nii.gz", fine, (0.5, 1.0, 2.0))
    expected, _ = compute_area_report(label_path, ENTRIES, gtv_path, None)
    got, _ = compute_area_report(label_path, ENTRIES, fine_path, None)
    assert got == expected


def test_report_trace_overlap_stays_affected(tmp_path: Path, synthetic: tuple[Path, Path]) -> None:
    """Un solapamiento de 1 vóxel (0.002 cm³) no se redondea a 0: la UI lo separa con `overlap_gtv_cm3 > 0`."""
    _, gtv_path = synthetic
    lab = _labels()
    lab[14, 0, 0] = 12  # dentro del GTV
    label_path = _save(tmp_path / "trace.nii.gz", lab)
    areas, _ = compute_area_report(label_path, [*ENTRIES, (12, "Brodmann area 3", "izquierdo")], gtv_path, None)
    trace = next(a for a in areas if a.label == 12)
    assert (trace.overlap_gtv_cm3, trace.distance_mm, trace.area_cm3) == (0.002, 0.0, 0.0)
    assert [a.label for a in areas][:3] == [144, 40, 12]


def test_report_empty_gtv(tmp_path: Path, synthetic: tuple[Path, Path]) -> None:
    label_path, _ = synthetic
    empty = _save(tmp_path / "empty.nii.gz", np.zeros(SHAPE, np.uint8))
    areas, lut = compute_area_report(label_path, ENTRIES, empty, None)
    assert areas == [] and len(lut) == 5


# --- run_area_mapping con map_atlas falso -----------------------------------------------------------------


def _fake_study(tmp: Path) -> dict[str, Path]:
    return {
        "t1gd": _save(tmp / "study" / "t1gd.nii.gz", np.ones(SHAPE, np.float32)),
        "gtv": _save(tmp / "study" / "gtv.nii.gz", _gtv()),
    }


@pytest.fixture
def fake_map_atlas(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    calls: list[Path] = []

    def fake(study_files: dict[str, Path], out_dir: Path, models_dir: Path) -> AtlasMapping:
        calls.append(out_dir)
        label_path = _save(out_dir / "brodmann.nii.gz", _labels())
        return AtlasMapping(
            label_path=label_path,
            entries=ENTRIES,
            reference_sequence="t1gd",
            registration="falso",
            warnings=["Sin brain_mask: el registro es menos preciso"],
        )

    monkeypatch.setattr(atlas, "map_atlas", fake)
    return calls


def test_run_area_mapping_without_wt(tmp_path: Path, fake_map_atlas: list[Path]) -> None:
    out_dir = tmp_path / "results" / "001" / "t0"
    res = run_area_mapping(_fake_study(tmp_path), out_dir, tmp_path / "models")
    assert fake_map_atlas == [out_dir]
    assert (res.atlas, res.registration, res.reference_sequence, res.margin_mm) == (
        ATLAS_NAME,
        "falso",
        "t1gd",
        MARGIN_MM,
    )
    assert res.created_at.tzinfo is not None
    assert res.warnings == ["Sin brain_mask: el registro es menos preciso", WARN_NO_WT]
    assert [a.label for a in res.areas] == [144, 40, 9, 7]
    assert res.areas[0].overlap_wt_cm3 is None
    on_disk = AreasResult.model_validate_json((out_dir / AREAS_JSON).read_text(encoding="utf-8"))
    assert on_disk == res


def test_run_area_mapping_with_wt(tmp_path: Path, fake_map_atlas: list[Path]) -> None:
    """`monai_seg` en otro grid (0.5 mm en x): WT = etiquetas >= 1, remuestreado con orden 0."""
    out_dir = tmp_path / "results" / "001" / "t0"
    seg = np.zeros((60, 10, 10), np.uint8)
    seg[20:28, :, :5] = 2  # x 10–13 en el grid del atlas
    seg[28:32, :, :5] = 3  # x 14–15
    _save(out_dir / "monai_seg.nii.gz", seg, (0.5, 1.0, 2.0))
    res = run_area_mapping(_fake_study(tmp_path), out_dir, tmp_path / "models")
    assert WARN_NO_WT not in res.warnings
    by = {a.label: a for a in res.areas}
    assert by[144].overlap_wt_cm3 == round(4 * 10 * 5 * 2 / 1000, 2)
    assert by[40].overlap_wt_cm3 == 0.2


def test_run_area_mapping_requires_gtv(tmp_path: Path, fake_map_atlas: list[Path]) -> None:
    files = _fake_study(tmp_path)
    del files["gtv"]
    with pytest.raises(ValueError, match="GTV"):
        run_area_mapping(files, tmp_path / "out", tmp_path / "models")
    assert fake_map_atlas == []


# --- Worker y API -----------------------------------------------------------------------------------------


@dataclass
class FakeJob:
    job_id: str


class FakeRedis:
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
        yield TestClient(app, base_url="http://localhost", headers={"X-Cerberus": "1"})
    finally:
        app.dependency_overrides.clear()


def _sample_result() -> AreasResult:
    return AreasResult(
        atlas=ATLAS_NAME,
        registration="falso",
        reference_sequence="t1gd",
        margin_mm=MARGIN_MM,
        created_at=datetime(2026, 10, 29, 12, 0, tzinfo=UTC),
        areas=[],
        lut=[AreaLabel(label=4, name="Brodmann area 4", name_es="BA4", hemisphere="izquierdo", kind="cortical")],
        warnings=[WARN_NO_WT],
    )


def test_worker_map_areas(settings: Settings, make_study: MakeStudy, monkeypatch: pytest.MonkeyPatch) -> None:
    make_study(settings.data_dir, seqs=("t1gd", "gtv", "brain_mask"))
    calls: list[tuple[dict[str, Path], Path, Path]] = []

    def fake_run(study_files: dict[str, Path], out_dir: Path, models_dir: Path) -> AreasResult:
        calls.append((study_files, out_dir, models_dir))
        return _sample_result()

    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    monkeypatch.setattr(worker, "run_area_mapping", fake_run)
    out = asyncio.run(worker.map_areas({}, "001", "t0"))
    assert out == _sample_result().model_dump(mode="json")
    files, out_dir, models_dir = calls[0]
    assert sorted(files) == ["brain_mask", "gtv", "t1gd"]
    assert out_dir == settings.results_dir / "001" / "t0"
    assert models_dir == settings.models_dir


@pytest.mark.parametrize(("patient", "timepoint"), [("001", "t9"), ("../x", "t0")])
def test_worker_map_areas_invalid(
    settings: Settings, make_study: MakeStudy, monkeypatch: pytest.MonkeyPatch, patient: str, timepoint: str
) -> None:
    make_study(settings.data_dir)
    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    with pytest.raises(ValueError):
        asyncio.run(worker.map_areas({}, patient, timepoint))


def test_post_areas_enqueues(
    client: TestClient, settings: Settings, fake_redis: FakeRedis, make_study: MakeStudy
) -> None:
    make_study(settings.data_dir)
    r = client.post("/api/studies/001/t0/areas")
    assert r.status_code == 202
    assert r.json() == {"job_id": "job-1"}
    assert fake_redis.calls == [("map_areas", "001", "t0")]


@pytest.mark.parametrize("url", ["/api/studies/001/t9/areas", "/api/studies/1/t0/areas"])
def test_post_areas_404(
    client: TestClient, settings: Settings, fake_redis: FakeRedis, make_study: MakeStudy, url: str
) -> None:
    make_study(settings.data_dir)
    assert client.post(url).status_code == 404
    assert fake_redis.calls == []


@pytest.mark.parametrize(
    ("seqs", "word"), [(("t1gd", "flair", "brain_mask"), "GTV"), (("flair", "gtv", "brain_mask"), "T1")]
)
def test_post_areas_422(
    client: TestClient,
    settings: Settings,
    fake_redis: FakeRedis,
    make_study: MakeStudy,
    seqs: tuple[str, ...],
    word: str,
) -> None:
    make_study(settings.data_dir, seqs=seqs)
    r = client.post("/api/studies/001/t0/areas")
    assert r.status_code == 422
    assert word in r.json()["detail"]
    assert fake_redis.calls == []


def test_get_areas(client: TestClient, settings: Settings) -> None:
    url = "/api/studies/001/t0/areas"
    assert client.get(url).status_code == 404
    out = settings.results_dir / "001" / "t0" / AREAS_JSON
    out.parent.mkdir(parents=True)
    out.write_text(_sample_result().model_dump_json(), encoding="utf-8")
    r = client.get(url)
    assert r.status_code == 200
    assert AreasResult.model_validate(r.json()) == _sample_result()
    out.write_text("{}", encoding="utf-8")
    assert client.get(url).status_code == 500
    assert client.get("/api/studies/..%2F/t0/areas").status_code == 404


def test_has_areas_and_file_served(client: TestClient, settings: Settings, make_study: MakeStudy) -> None:
    make_study(settings.data_dir)
    url = "/api/studies/001/t0/files/brodmann.nii.gz"
    assert client.get("/api/studies/001/t0").json()["has_areas"] is False
    assert client.get(url).status_code == 404
    label_path = _save(settings.results_dir / "001" / "t0" / "brodmann.nii.gz", _labels())
    assert client.get("/api/studies/001/t0").json()["has_areas"] is True
    r = client.get(url)
    assert r.status_code == 200
    assert r.content == label_path.read_bytes()


# --- Real: 001/t0 -----------------------------------------------------------------------------------------


@pytest.mark.slow
def test_real_area_mapping_on_data(tmp_path: Path) -> None:
    study = REPO_ROOT / "Data" / "001" / "t0"
    if not study.is_dir():
        pytest.skip("Sin Data/001/t0")
    pytest.importorskip("ants")
    files = {p.name.split("_", 2)[2].removesuffix(".nii.gz"): p for p in study.glob("*.nii.gz")}

    res = run_area_mapping(files, tmp_path, REPO_ROOT / "models")
    AreasResult.model_validate(json.loads((tmp_path / AREAS_JSON).read_text(encoding="utf-8")))

    affected = [a for a in res.areas if a.overlap_gtv_cm3 > 0]
    nearby = [a for a in res.areas if a.overlap_gtv_cm3 == 0]
    assert affected and all(0 <= a.overlap_gtv_pct <= 100 for a in res.areas)
    assert all(0 < a.distance_mm <= MARGIN_MM for a in nearby)
    assert all(a.distance_mm == 0 for a in affected)
    assert [a.distance_mm for a in nearby] == sorted(a.distance_mm for a in nearby)
    top = [(a.name, a.hemisphere) for a in affected[:5]]
    assert ("Brodmann area 40", "izquierdo") in top
    ba40 = next(a for a in affected if a.name == "Brodmann area 40" and a.hemisphere == "izquierdo")
    assert ba40.functions and ba40.eloquent

    print(f"\n{res.registration} · warnings: {res.warnings} · lut: {len(res.lut)} etiquetas")
    for title, rows in (("Afectadas", affected[:8]), ("Cercanas", nearby[:8])):
        print(title)
        for a in rows:
            print(
                f"  {a.label:3d} {a.name_es} ({a.hemisphere}): {a.overlap_gtv_pct}%"
                f" · {a.overlap_gtv_cm3}/{a.area_cm3} cm³ · {a.distance_mm} mm"
                f" · WT {a.overlap_wt_cm3} · {'elocuente' if a.eloquent else '-'}"
            )
