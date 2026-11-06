"""Tests de la ingesta DICOM (ticket B8): ZIP seguro, agrupación, sugerencia, worker y endpoints de staging.

Los DICOM son sintéticos (pydicom) con datos personales falsos ("Doe^Jane", "PHI123") para comprobar que
nunca llegan al manifest. La conversión real con dcm2niix va marcada `slow`.
"""

import asyncio
import io
import json
import stat
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, MRImageStorage, generate_uid

from cerberus_api import dicom, staging, worker
from cerberus_api.config import Settings
from cerberus_api.deps import get_redis, settings_dep
from cerberus_api.main import create_app
from cerberus_api.schemas import SeriesInfo, UploadManifest
from conftest import MakeNifti

PHI_STRINGS = ("Doe", "Jane", "PHI123", "19700101", "Hospital", "ACC999", "20240101")


# --------------------------------------------------------------------------- DICOM sintético


@dataclass
class SyntheticSeries:
    files: list[Path]
    uids: list[str]  # todos los UIDs escritos (para comprobar que no se filtran)


def write_mr_series(
    folder: Path,
    n_slices: int = 6,
    size: int = 16,
    description: str = "AX FLAIR",
    protocol: str = "flair_ax",
    series_number: int = 3,
    contrast_agent: str | None = None,
) -> SyntheticSeries:
    """Serie MR axial con `n_slices` cortes uint16 de `size`×`size` (1×1 mm, 2 mm entre cortes) y PHI falsa."""
    folder.mkdir(parents=True, exist_ok=True)
    study_uid, series_uid, frame_uid = generate_uid(), generate_uid(), generate_uid()
    uids = [str(study_uid), str(series_uid), str(frame_uid)]
    files: list[Path] = []
    rng = np.random.default_rng(series_number)
    for i in range(n_slices):
        sop_uid = generate_uid()
        uids.append(str(sop_uid))
        meta = FileMetaDataset()
        meta.MediaStorageSOPClassUID = MRImageStorage
        meta.MediaStorageSOPInstanceUID = sop_uid
        meta.TransferSyntaxUID = ExplicitVRLittleEndian

        ds = Dataset()
        ds.file_meta = meta
        ds.SOPClassUID = MRImageStorage
        ds.SOPInstanceUID = sop_uid
        ds.StudyInstanceUID = study_uid
        ds.SeriesInstanceUID = series_uid
        ds.FrameOfReferenceUID = frame_uid
        # Datos personales falsos: no deben llegar nunca al manifest
        ds.PatientName = "Doe^Jane"
        ds.PatientID = "PHI123"
        ds.PatientBirthDate = "19700101"
        ds.InstitutionName = "Hospital Secreto"
        ds.AccessionNumber = "ACC999"
        ds.StudyDate = "20240101"
        ds.SeriesDate = "20240101"
        ds.StudyTime = "120000"
        ds.Modality = "MR"
        ds.SeriesDescription = description
        ds.ProtocolName = protocol
        ds.SeriesNumber = series_number
        ds.InstanceNumber = i + 1
        if contrast_agent is not None:
            ds.ContrastBolusAgent = contrast_agent
        ds.ImageType = ["ORIGINAL", "PRIMARY", "M", "ND"]
        ds.ImagePositionPatient = [0.0, 0.0, float(i * 2)]
        ds.ImageOrientationPatient = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
        ds.PixelSpacing = [1.0, 1.0]
        ds.SliceThickness = 2.0
        ds.SpacingBetweenSlices = 2.0
        ds.EchoTime = 90.0
        ds.RepetitionTime = 9000.0
        ds.Rows = size
        ds.Columns = size
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = "MONOCHROME2"
        ds.BitsAllocated = 16
        ds.BitsStored = 16
        ds.HighBit = 15
        ds.PixelRepresentation = 0
        ds.PixelData = rng.integers(0, 1000, (size, size), dtype=np.uint16).tobytes()

        path = folder / f"IM{i:04d}"
        ds.save_as(path, enforce_file_format=True)
        files.append(path)
    return SyntheticSeries(files=files, uids=uids)


def zip_dir(folder: Path, zip_path: Path) -> Path:
    """Comprime todo `folder` en `zip_path` (rutas relativas)."""
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w") as zf:
        for f in sorted(folder.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(folder).as_posix())
    return zip_path


# --------------------------------------------------------------------------- suggest_sequence


@pytest.mark.parametrize(
    ("modality", "description", "protocol", "agent", "expected"),
    [
        ("CT", "Head 2.5mm", "", False, "ct"),
        ("RTDOSE", "Dose", "", False, None),
        ("RTSTRUCT", "GTV contours", "", False, None),
        ("SR", "t1 report", "", False, None),
        ("MR", "AX FLAIR", "", False, "flair"),
        ("MR", "T2 FLAIR post gad", "", False, "flair"),
        ("MR", "dWIP ADC", "", False, "adc"),
        ("MR", "Apparent Diffusion Coefficient", "", False, "adc"),
        ("MR", "AX T2*", "", False, "t2star"),
        ("MR", "SWI_Images", "", False, "t2star"),
        ("MR", "ax gre hemo", "", False, "t2star"),
        ("MR", "T2 TSE AX", "", False, "t2tse"),
        ("MR", "T1 AX post", "", False, "t1gd"),
        ("MR", "T1 +C", "", False, "t1gd"),
        ("MR", "t1_mprage_sag", "", False, "t1eg"),
        ("MR", "T1 3D", "", True, "t1gd"),
        ("MR", "T1W_3D_TFE", "", False, "t1eg"),
        ("MR", "T1 GRE", "", False, "t1eg"),
        ("MR", "T1 SE AX", "", False, "t1tse"),
        ("MR", "", "t1_tse_tra", False, "t1tse"),
        ("MR", "T1 space sag", "", False, "t1tse"),  # "ce" dentro de "space" no cuenta como contraste
        ("MR", "Localizer", "", False, None),
        ("MR", "", "", False, None),
    ],
)
def test_suggest_sequence(modality: str, description: str, protocol: str, agent: bool, expected: str | None) -> None:
    assert dicom.suggest_sequence(modality, description, protocol, agent) == expected


# --------------------------------------------------------------------------- safe_extract


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_safe_extract_ok(tmp_path: Path) -> None:
    zp = tmp_path / "ok.zip"
    zp.write_bytes(_zip_bytes({"a/b.dcm": b"x" * 10, "c.dcm": b"y"}))
    out = dicom.safe_extract(zp, tmp_path / "out")
    assert sorted(p.relative_to(tmp_path / "out").as_posix() for p in out) == ["a/b.dcm", "c.dcm"]
    assert (tmp_path / "out" / "a" / "b.dcm").read_bytes() == b"x" * 10


@pytest.mark.parametrize("name", ["../evil", "a/../../evil", "/etc/evil", "C:/evil", "..\\evil"])
def test_safe_extract_rejects_bad_paths(tmp_path: Path, name: str) -> None:
    zp = tmp_path / "bad.zip"
    zp.write_bytes(_zip_bytes({"ok.dcm": b"1", name: b"2"}))
    with pytest.raises(ValueError):
        dicom.safe_extract(zp, tmp_path / "out")
    # Se valida todo antes de extraer: no se escribió nada
    assert not (tmp_path / "out").exists()
    assert not (tmp_path / "evil").exists()


def test_safe_extract_rejects_symlink(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        info = zipfile.ZipInfo("link")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(info, "/etc/passwd")
    zp = tmp_path / "link.zip"
    zp.write_bytes(buf.getvalue())
    with pytest.raises(ValueError, match="enlace"):
        dicom.safe_extract(zp, tmp_path / "out")


def test_safe_extract_rejects_over_limit(tmp_path: Path) -> None:
    zp = tmp_path / "big.zip"
    zp.write_bytes(_zip_bytes({"a.dcm": b"\0" * 600, "b.dcm": b"\0" * 600}))
    with pytest.raises(ValueError, match="excede"):
        dicom.safe_extract(zp, tmp_path / "out", max_bytes=1000)
    assert not (tmp_path / "out").exists()


def test_safe_extract_rejects_too_many_members(tmp_path: Path) -> None:
    zp = tmp_path / "many.zip"
    zp.write_bytes(_zip_bytes({f"{i}.dcm": b"1" for i in range(5)}))
    with pytest.raises(ValueError, match="demasiados"):
        dicom.safe_extract(zp, tmp_path / "out", max_members=4)


def test_safe_extract_not_a_zip(tmp_path: Path) -> None:
    zp = tmp_path / "x.zip"
    zp.write_bytes(b"no soy un zip")
    with pytest.raises(ValueError, match="ZIP"):
        dicom.safe_extract(zp, tmp_path / "out")


# --------------------------------------------------------------------------- group_series y manifest


def test_group_series_and_manifest_without_phi(tmp_path: Path) -> None:
    root = tmp_path / "dicom"
    flair = write_mr_series(root / "s1", description="AX FLAIR", series_number=5)
    t1 = write_mr_series(
        root / "s2", n_slices=4, description="T1 AX", protocol="t1_se", series_number=2, contrast_agent="Gadovist"
    )
    (root / "DICOMDIR_notes.txt").write_text("no soy DICOM")

    groups = dicom.group_series(root)
    assert [(g.series_number, g.description, len(g.files)) for g in groups] == [(2, "T1 AX", 4), (5, "AX FLAIR", 6)]
    assert groups[0].has_contrast_agent and not groups[1].has_contrast_agent
    assert groups[0].modality == "MR"
    # El SeriesGroup solo expone los campos permitidos
    assert set(vars(groups[0])) == {
        "modality",
        "description",
        "protocol",
        "series_number",
        "has_contrast_agent",
        "files",
    }

    series = [
        SeriesInfo(
            index=i,
            modality=g.modality,
            description=g.description,
            n_files=len(g.files),
            shape=None,
            spacing_mm=None,
            converted=False,
            suggested_sequence=dicom.suggest_sequence(g.modality, g.description, g.protocol, g.has_contrast_agent),
        )
        for i, g in enumerate(groups)
    ]
    assert [s.suggested_sequence for s in series] == ["t1gd", "flair"]
    upload_id = staging.new_upload_id()
    path = staging.write_manifest(
        tmp_path / "staging", UploadManifest(upload_id=upload_id, status="ready", series=series)
    )
    text = path.read_text()
    for phi in PHI_STRINGS:
        assert phi not in text
    for uid in flair.uids + t1.uids:
        assert uid not in text
    assert staging.read_manifest(tmp_path / "staging", upload_id) == UploadManifest.model_validate_json(text)


# --------------------------------------------------------------------------- staging


@pytest.mark.parametrize("bad", ["", "../x", "0" * 31, "g" * 32, "A" * 32, "0" * 32 + "/..", "0" * 33])
def test_validate_upload_id_rejects(bad: str) -> None:
    with pytest.raises(ValueError):
        staging.validate_upload_id(bad)
    with pytest.raises(ValueError):
        staging.manifest_path(Path("/tmp"), bad)


def test_staging_roundtrip(tmp_path: Path) -> None:
    uid = staging.new_upload_id()
    assert staging.validate_upload_id(uid) == uid
    assert staging.read_manifest(tmp_path, uid) is None
    staging.write_manifest(tmp_path, UploadManifest(upload_id=uid, status="processing", series=[]))
    manifest = staging.read_manifest(tmp_path, uid)
    assert manifest is not None and manifest.status == "processing"
    # Sin restos del archivo temporal de la escritura atómica
    assert [p.name for p in (tmp_path / uid).iterdir()] == ["manifest.json"]
    staging.manifest_path(tmp_path, uid).write_text("{roto")
    assert staging.read_manifest(tmp_path, uid) is None


# --------------------------------------------------------------------------- worker ingest_dicom


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "Data", storage_dir=tmp_path / "storage", models_dir=tmp_path / "models")


def _fake_convert(make_nifti: MakeNifti) -> Any:
    """`convert_series` falso: escribe un NIfTI 16×16×n con spacing (1, 1, 2) sin llamar a dcm2niix."""

    def _convert(files: list[Path], work_dir: Path, out_path: Path) -> bool:
        # Las copias de trabajo deben vivir dentro de storage/tmp
        work_dir.mkdir(parents=True, exist_ok=True)
        make_nifti(out_path, np.zeros((16, 16, len(files)), np.int16), (1.0, 1.0, 2.0))
        return True

    return _convert


def _prepare_zip(settings: Settings, tmp_path: Path) -> tuple[str, Path, list[str]]:
    src = tmp_path / "src"
    a = write_mr_series(src / "flair", description="AX FLAIR", series_number=4)
    b = write_mr_series(src / "t1", n_slices=5, description="T1 AX post", protocol="t1_se", series_number=1)
    upload_id = staging.new_upload_id()
    zip_path = zip_dir(src, settings.tmp_dir / f"{upload_id}.zip")
    return upload_id, zip_path, a.uids + b.uids


def _assert_no_phi(settings: Settings, upload_id: str, uids: list[str]) -> None:
    text = staging.manifest_path(settings.staging_dir, upload_id).read_text()
    for phi in PHI_STRINGS:
        assert phi not in text
    for uid in uids:
        assert uid not in text


def test_worker_ingest_dicom(
    settings: Settings, tmp_path: Path, make_nifti: MakeNifti, monkeypatch: pytest.MonkeyPatch
) -> None:
    upload_id, zip_path, uids = _prepare_zip(settings, tmp_path)
    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    monkeypatch.setattr(worker, "convert_series", _fake_convert(make_nifti))

    result = asyncio.run(worker.ingest_dicom({}, upload_id, str(zip_path)))

    assert result["status"] == "ready"
    assert [(s["index"], s["description"], s["n_files"], s["suggested_sequence"]) for s in result["series"]] == [
        (0, "T1 AX post", 5, "t1gd"),
        (1, "AX FLAIR", 6, "flair"),
    ]
    assert result["series"][1]["shape"] == [16, 16, 6]
    assert result["series"][1]["spacing_mm"] == [1.0, 1.0, 2.0]
    assert staging.series_path(settings.staging_dir, upload_id, 0).is_file()
    # El DICOM crudo y el ZIP se borraron
    assert not zip_path.exists()
    assert not any(settings.tmp_dir.iterdir())
    _assert_no_phi(settings, upload_id, uids)


def test_worker_ingest_dicom_failed_cleans_up(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    upload_id = staging.new_upload_id()
    zip_path = settings.tmp_dir / f"{upload_id}.zip"
    zip_path.parent.mkdir(parents=True)
    zip_path.write_bytes(_zip_bytes({"../evil": b"x"}))

    result = asyncio.run(worker.ingest_dicom({}, upload_id, str(zip_path)))

    assert result["status"] == "failed"
    assert "'..'" in result["error"]
    manifest = staging.read_manifest(settings.staging_dir, upload_id)
    assert manifest is not None and manifest.status == "failed"
    assert not zip_path.exists()
    assert not any(settings.tmp_dir.iterdir())


def test_worker_ingest_dicom_no_series(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    upload_id = staging.new_upload_id()
    zip_path = settings.tmp_dir / f"{upload_id}.zip"
    zip_path.parent.mkdir(parents=True)
    zip_path.write_bytes(_zip_bytes({"notas.txt": b"hola"}))
    result = asyncio.run(worker.ingest_dicom({}, upload_id, str(zip_path)))
    assert result == {
        "upload_id": upload_id,
        "status": "failed",
        "error": "No se encontraron series DICOM en el ZIP",
        "series": [],
    }
    assert not zip_path.exists()


def test_worker_ingest_dicom_zip_outside_tmp(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    outside = tmp_path / "fuera.zip"
    outside.write_bytes(_zip_bytes({"a": b"1"}))
    result = asyncio.run(worker.ingest_dicom({}, staging.new_upload_id(), str(outside)))
    assert result["status"] == "failed"
    assert outside.exists()  # nunca se borra nada fuera de storage/tmp


def test_worker_ingest_dicom_invalid_id(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    with pytest.raises(ValueError):
        asyncio.run(worker.ingest_dicom({}, "../x", "/tmp/x.zip"))


@pytest.mark.slow
def test_convert_series_real_dcm2niix(tmp_path: Path) -> None:
    """Conversión real con dcm2niix de la serie sintética."""
    from cerberus_api.nifti import load_nifti

    series = write_mr_series(tmp_path / "dicom", n_slices=6, size=16)
    out = tmp_path / "out" / "0.nii.gz"
    assert dicom.convert_series(series.files, tmp_path / "work", out)
    img = load_nifti(out)
    assert img.shape == (16, 16, 6)
    assert [round(float(z), 3) for z in img.header.get_zooms()[:3]] == [1.0, 1.0, 2.0]
    # El header NIfTI tampoco lleva PHI
    raw = bytes(img.header.binaryblock)
    assert b"Doe" not in raw and b"PHI123" not in raw
    # Sin sidecar JSON (-b n)
    assert not list((tmp_path / "work").rglob("*.json"))


@pytest.mark.slow
def test_worker_ingest_dicom_real(settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ingesta completa con dcm2niix real."""
    upload_id, zip_path, uids = _prepare_zip(settings, tmp_path)
    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    result = asyncio.run(worker.ingest_dicom({}, upload_id, str(zip_path)))
    assert result["status"] == "ready", result
    assert [s["converted"] for s in result["series"]] == [True, True]
    assert [s["shape"] for s in result["series"]] == [[16, 16, 5], [16, 16, 6]]
    assert not zip_path.exists()
    assert not any(settings.tmp_dir.iterdir())
    _assert_no_phi(settings, upload_id, uids)


# --------------------------------------------------------------------------- endpoints


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
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def client(settings: Settings, fake_redis: FakeRedis) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[settings_dep] = lambda: settings
    app.dependency_overrides[get_redis] = lambda: fake_redis
    yield TestClient(app, base_url="http://localhost", headers={"X-Cerberus": "1"})


def _ready_upload(settings: Settings, make_nifti: MakeNifti, n: int = 3, converted: tuple[bool, ...] = ()) -> str:
    """Staging `ready` con `n` series convertidas (NIfTI 8×8×4)."""
    upload_id = staging.new_upload_id()
    series = []
    for i in range(n):
        ok = converted[i] if i < len(converted) else True
        if ok:
            make_nifti(staging.series_path(settings.staging_dir, upload_id, i), np.ones((8, 8, 4), np.float32))
        series.append(
            SeriesInfo(
                index=i,
                modality="MR",
                description=f"serie {i}",
                n_files=4,
                shape=[8, 8, 4] if ok else None,
                spacing_mm=[0.5, 0.5, 1.0] if ok else None,
                converted=ok,
                suggested_sequence=None,
            )
        )
    staging.write_manifest(settings.staging_dir, UploadManifest(upload_id=upload_id, status="ready", series=series))
    return upload_id


def test_post_zip_enqueues(client: TestClient, settings: Settings, fake_redis: FakeRedis, tmp_path: Path) -> None:
    src = tmp_path / "src"
    write_mr_series(src)
    content = zip_dir(src, tmp_path / "estudio.zip").read_bytes()
    r = client.post(
        "/api/uploads",
        data={"patient": "001", "timepoint": "t0"},
        files={"file": ("Estudio.ZIP", content, "application/zip")},
    )
    assert r.status_code == 202, r.text
    body = r.json()
    upload_id = body["upload_id"]
    staging.validate_upload_id(upload_id)
    assert body["job_id"] == "job-1"
    zip_path = settings.tmp_dir / f"{upload_id}.zip"
    assert fake_redis.calls == [("ingest_dicom", upload_id, str(zip_path))]
    assert zip_path.read_bytes() == content
    r = client.get(f"/api/uploads/{upload_id}")
    assert r.status_code == 200
    assert r.json() == {"upload_id": upload_id, "status": "processing", "error": None, "series": []}


def test_post_zip_invalid_ids_422(client: TestClient, settings: Settings, fake_redis: FakeRedis) -> None:
    r = client.post(
        "/api/uploads",
        data={"patient": "../1", "timepoint": "t0"},
        files={"file": ("e.zip", _zip_bytes({"a": b"1"}), "application/zip")},
    )
    assert r.status_code == 422
    assert fake_redis.calls == []


def test_post_zip_too_large_413(tmp_path: Path, fake_redis: FakeRedis) -> None:
    small = Settings(
        data_dir=tmp_path / "Data", storage_dir=tmp_path / "storage", models_dir=tmp_path / "models", max_upload_mb=1
    )
    app = create_app()
    app.dependency_overrides[settings_dep] = lambda: small
    app.dependency_overrides[get_redis] = lambda: fake_redis
    r = TestClient(app, base_url="http://localhost", headers={"X-Cerberus": "1"}).post(
        "/api/uploads",
        data={"patient": "001", "timepoint": "t0"},
        files={"file": ("big.zip", b"\0" * (1024 * 1024 + 1), "application/zip")},
    )
    assert r.status_code == 413
    assert fake_redis.calls == []
    assert not any(small.tmp_dir.iterdir())
    assert not small.staging_dir.exists() or not any(small.staging_dir.iterdir())


@pytest.mark.parametrize("bad", ["../x", "x", "0" * 31, "ZZ" * 16])
def test_get_manifest_404_bad_id(client: TestClient, bad: str) -> None:
    assert client.get(f"/api/uploads/{bad}").status_code == 404


def test_get_manifest_404_missing(client: TestClient) -> None:
    assert client.get(f"/api/uploads/{staging.new_upload_id()}").status_code == 404


def test_get_series_preview(client: TestClient, settings: Settings, make_nifti: MakeNifti) -> None:
    upload_id = _ready_upload(settings, make_nifti, n=1)
    r = client.get(f"/api/uploads/{upload_id}/series/0.nii.gz")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/gzip"
    assert r.content[:2] == b"\x1f\x8b"
    for bad in ("5", "-1", "abc", "0x1"):
        assert client.get(f"/api/uploads/{upload_id}/series/{bad}.nii.gz").status_code == 404
    assert client.get(f"/api/uploads/{'0' * 31}/series/0.nii.gz").status_code == 404


def test_confirm_moves_and_deletes_staging(client: TestClient, settings: Settings, make_nifti: MakeNifti) -> None:
    upload_id = _ready_upload(settings, make_nifti, n=3)
    r = client.post(
        f"/api/uploads/{upload_id}/confirm",
        json={"patient": "007", "timepoint": "t1", "mapping": {"0": "t1gd", "2": "flair"}},
    )
    assert r.status_code == 201, r.text
    assert r.json()["sequences"] == ["flair", "t1gd"]
    assert (settings.data_dir / "007" / "t1" / "7_t1_t1gd.nii.gz").is_file()
    assert (settings.data_dir / "007" / "t1" / "7_t1_flair.nii.gz").is_file()
    assert not (settings.staging_dir / upload_id).exists()
    assert client.get(f"/api/uploads/{upload_id}").status_code == 404


def test_confirm_duplicate_sequences_409(client: TestClient, settings: Settings, make_nifti: MakeNifti) -> None:
    upload_id = _ready_upload(settings, make_nifti, n=2)
    r = client.post(
        f"/api/uploads/{upload_id}/confirm",
        json={"patient": "001", "timepoint": "t0", "mapping": {"0": "flair", "1": "flair"}},
    )
    assert r.status_code == 409
    assert not settings.data_dir.exists()
    assert staging.series_path(settings.staging_dir, upload_id, 0).is_file()


def test_confirm_existing_target_409_moves_nothing(
    client: TestClient, settings: Settings, make_nifti: MakeNifti
) -> None:
    upload_id = _ready_upload(settings, make_nifti, n=2)
    existing = make_nifti(settings.data_dir / "001" / "t0" / "1_t0_flair.nii.gz", np.zeros((4, 4, 4), np.uint8))
    r = client.post(
        f"/api/uploads/{upload_id}/confirm",
        json={"patient": "001", "timepoint": "t0", "mapping": {"0": "t1gd", "1": "flair"}},
    )
    assert r.status_code == 409
    assert "1_t0_flair.nii.gz" in r.json()["detail"]
    # Nada se movió: ni siquiera el t1gd que no chocaba
    assert not (settings.data_dir / "001" / "t0" / "1_t0_t1gd.nii.gz").exists()
    assert staging.series_path(settings.staging_dir, upload_id, 0).is_file()
    assert existing.is_file()


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"patient": "1", "timepoint": "t0", "mapping": {"0": "flair"}}, 422),
        ({"patient": "001", "timepoint": "../t0", "mapping": {"0": "flair"}}, 422),
        ({"patient": "001", "timepoint": "t0", "mapping": {"0": "tumor"}}, 422),
        ({"patient": "001", "timepoint": "t0", "mapping": {"../0": "flair"}}, 422),
        ({"patient": "001", "timepoint": "t0", "mapping": {"9": "flair"}}, 422),
        ({"patient": "001", "timepoint": "t0", "mapping": {"1": "flair"}}, 422),  # serie no convertida
        ({"patient": "001", "timepoint": "t0", "mapping": {}}, 422),
    ],
)
def test_confirm_rejected(
    client: TestClient, settings: Settings, make_nifti: MakeNifti, body: dict[str, Any], status: int
) -> None:
    upload_id = _ready_upload(settings, make_nifti, n=2, converted=(True, False))
    r = client.post(f"/api/uploads/{upload_id}/confirm", json=body)
    assert r.status_code == status, r.text
    assert not settings.data_dir.exists()


def test_confirm_not_ready_409(client: TestClient, settings: Settings) -> None:
    upload_id = staging.new_upload_id()
    staging.write_manifest(settings.staging_dir, UploadManifest(upload_id=upload_id, status="processing", series=[]))
    r = client.post(
        f"/api/uploads/{upload_id}/confirm", json={"patient": "001", "timepoint": "t0", "mapping": {"0": "flair"}}
    )
    assert r.status_code == 409


def test_confirm_unknown_upload_404(client: TestClient) -> None:
    body = {"patient": "001", "timepoint": "t0", "mapping": {"0": "flair"}}
    assert client.post(f"/api/uploads/{staging.new_upload_id()}/confirm", json=body).status_code == 404
    assert client.post("/api/uploads/xyz/confirm", json=body).status_code == 404


def test_delete_upload(client: TestClient, settings: Settings, make_nifti: MakeNifti) -> None:
    upload_id = _ready_upload(settings, make_nifti, n=1)
    assert client.delete(f"/api/uploads/{upload_id}").status_code == 204
    assert not (settings.staging_dir / upload_id).exists()
    assert client.delete(f"/api/uploads/{upload_id}").status_code == 204
    assert client.delete("/api/uploads/..").status_code in (404, 405)
    assert client.delete("/api/uploads/abc").status_code == 404


def test_manifest_json_has_only_contract_keys(settings: Settings, make_nifti: MakeNifti) -> None:
    upload_id = _ready_upload(settings, make_nifti, n=1)
    data = json.loads(staging.manifest_path(settings.staging_dir, upload_id).read_text())
    assert set(data) == {"upload_id", "status", "error", "series"}
    assert set(data["series"][0]) == set(SeriesInfo.model_fields)
