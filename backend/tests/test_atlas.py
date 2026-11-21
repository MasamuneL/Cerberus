"""Tests de atlas.py: hemisferios con un atlas sintético y `map_atlas` con transformación identidad.

Los rápidos no usan red ni corren el registro ANTs. Los `slow` registran estudios reales.
"""

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import ants
import nibabel as nib
import numpy as np
import pytest
from scipy.ndimage import distance_transform_edt

from cerberus_api import areas, atlas, linear_reg
from cerberus_api.atlas import (
    WARN_LARGE_GTV,
    WARN_NO_BRAIN,
    WARN_ONLY_T1GD,
    affine_of,
    map_atlas,
    select_sequences,
    split_hemispheres,
    which_to_invert,
)
from cerberus_api.config import REPO_ROOT, RegistrationMode, Settings
from cerberus_api.nifti import load_nifti

LABELS = ["Background", "Brodmann area 4", "Putamen"]


def _synthetic_atlas() -> nib.Nifti1Image:
    """10×4×4 a 2 mm con x del mundo de -10 a +8: índice 1 en z>=1, índice 2 en x<=-6 (j=0, z=1), fondo en z=0."""
    data = np.zeros((10, 4, 4), np.int16)
    data[:, :, 1:] = 1
    data[:3, 0, 1] = 2
    affine = np.diag([2.0, 2.0, 2.0, 1.0])
    affine[:3, 3] = (-10, -4, -4)
    return nib.Nifti1Image(data, affine)


def test_split_hemispheres_encoding() -> None:
    img, entries = split_hemispheres(_synthetic_atlas(), LABELS)
    out = np.asarray(img.dataobj)
    assert out.dtype == np.uint8 and np.allclose(affine_of(img), affine_of(_synthetic_atlas()))
    # i=0..4 → x=-10..-2 (izquierdo); i=5..9 → x=0..8 (derecho; x=0 cuenta como derecho)
    assert (out[:, :, 0] == 0).all()
    assert (out[3:5, :, 1:] == 1).all() and (out[5:, :, 1:] == 101).all()
    assert (out[:3, 0, 1] == 2).all() and (out[:3, 1:, 1:] == 1).all()
    assert set(np.unique(out).tolist()) == {0, 1, 2, 101}
    assert entries == [
        (1, "Brodmann area 4", "izquierdo"),
        (2, "Putamen", "izquierdo"),
        (101, "Brodmann area 4", "derecho"),
    ]


def test_split_hemispheres_flipped_affine_without_labels() -> None:
    src = _synthetic_atlas()
    flipped = affine_of(src).copy()
    flipped[0, 0], flipped[0, 3] = -2.0, 8.0  # i=0 → x=8 (derecho), i=9 → x=-10 (izquierdo)
    img, entries = split_hemispheres(nib.Nifti1Image(np.asarray(src.dataobj), flipped))
    out = np.asarray(img.dataobj)
    assert (out[:5, :, 1:] >= 100).all() and (out[5:, :, 1:] < 100).all()
    assert (102, "2", "derecho") in entries and (2, "2", "izquierdo") not in entries


def test_split_hemispheres_rejects_large_indices() -> None:
    with pytest.raises(ValueError):
        split_hemispheres(nib.Nifti1Image(np.full((2, 2, 2), 120, np.int16), np.eye(4)))


@pytest.mark.parametrize(
    ("seqs", "expected"),
    [
        (("t1gd", "t1eg", "flair"), ("t1gd", "t1eg")),
        (("t1gd", "t1tse"), ("t1gd", "t1tse")),
        (("t1gd", "flair"), ("t1gd", "t1gd")),
        (("t1tse", "flair"), ("t1tse", "t1tse")),
        (("flair", "t1eg"), ("t1eg", "t1eg")),
    ],
)
def test_select_sequences(seqs: tuple[str, ...], expected: tuple[str, str]) -> None:
    assert select_sequences({s: Path(f"{s}.nii.gz") for s in seqs}) == expected


def test_select_sequences_without_t1_raises() -> None:
    with pytest.raises(ValueError):
        select_sequences({"flair": Path("f.nii.gz"), "gtv": Path("g.nii.gz")})


def test_which_to_invert() -> None:
    assert which_to_invert(["a/pat2mni_0GenericAffine.mat", "a/pat2mni_1InverseWarp.nii.gz"]) == [True, False]


# --- map_atlas con un registro falso (afín identidad) ----------------------------------------------------

# Grid del "paciente" alineado con el atlas sintético pero con x invertido: x del mundo = 8 - 2i
REF_AFFINE = np.array([[-2.0, 0, 0, 8.0], [0, 2.0, 0, -4.0], [0, 0, 2.0, -4.0], [0, 0, 0, 1]])


def _write(path: Path, data: np.ndarray) -> Path:
    nib.save(nib.Nifti1Image(data, REF_AFFINE), path)
    return path


def _study(tmp: Path, seqs: tuple[str, ...]) -> dict[str, Path]:
    tmp.mkdir(parents=True, exist_ok=True)
    files: dict[str, Path] = {}
    for s in seqs:
        if s == "brain_mask":
            data = np.ones((10, 4, 4), np.uint8)
            data[:, 3, :] = 0
        elif s == "gtv":
            data = np.zeros((10, 4, 4), np.uint8)
            data[4:6, 1:3, 1:3] = 1
        else:
            data = np.random.default_rng(0).normal(100, 10, (10, 4, 4)).astype(np.float32)
        files[s] = _write(tmp / f"{s}.nii.gz", data)
    return files


@pytest.fixture
def fake_register(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Sustituye el atlas por el sintético y `_register` por una afín identidad; cuenta los registros."""
    import ants

    calls: list[int] = []

    def register(
        study_files: dict[str, Path],
        moving_seq: str,
        mni_dir: Path,
        models_dir: Path,
        tmp: Path,
        mode: RegistrationMode = "full",
    ) -> list[str]:
        calls.append(1)
        mni_dir.mkdir(parents=True, exist_ok=True)
        tx = mni_dir / "pat2mni_0GenericAffine.mat"
        ants.write_transform(ants.create_ants_transform(transform_type="AffineTransform", dimension=3), str(tx))
        meta = {"key": atlas._cache_key(study_files, moving_seq, mode), "invtransforms": [tx.name]}
        (mni_dir / atlas.CACHE_FILE).write_text(json.dumps(meta), encoding="utf-8")
        return [str(tx)]

    monkeypatch.setattr(atlas, "fetch_atlas", lambda models_dir: (_synthetic_atlas(), LABELS))
    monkeypatch.setattr(atlas, "_register", register)
    return calls


def test_map_atlas_identity(tmp_path: Path, fake_register: list[int], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(atlas, "ICBM_OTHER2TAL_RAS", np.eye(4))
    files = _study(tmp_path / "s", ("t1gd", "t1eg", "brain_mask", "gtv"))
    res = map_atlas(files, tmp_path / "out", tmp_path / "models")

    assert res.label_path == tmp_path / "out" / "brodmann.nii.gz"
    assert res.reference_sequence == "t1gd"
    assert res.warnings == []
    assert "t1eg→MNI152 (GTV excluido del costo)" in res.registration
    img = load_nifti(res.label_path)
    assert np.allclose(affine_of(img), REF_AFFINE) and img.shape == (10, 4, 4)
    lab = np.asarray(img.dataobj)
    assert lab.dtype == np.uint8
    # Fondo del atlas (z=0) y fuera de brain_mask (j=3) en cero
    assert (lab[:, :, 0] == 0).all() and (lab[:, 3, :] == 0).all()
    # i=0..4 → x=8..0 (derecho); i=5..9 → x=-2..-10 (izquierdo); el índice 2 cae en x<=-6 → i=7..9
    assert (lab[:5, :3, 1:] == 101).all() and (lab[5:7, :3, 1:] == 1).all()
    assert (lab[7:, 0, 1] == 2).all() and (lab[7:, 1:3, 1:] == 1).all()
    assert res.entries == [
        (1, "Brodmann area 4", "izquierdo"),
        (2, "Putamen", "izquierdo"),
        (101, "Brodmann area 4", "derecho"),
    ]

    # Segunda corrida: reutiliza las transformaciones de out/mni
    map_atlas(files, tmp_path / "out", tmp_path / "models")
    assert len(fake_register) == 1
    # Si cambia la imagen móvil, se registra de nuevo
    _write(files["t1eg"], np.zeros((10, 4, 4), np.float32))
    map_atlas(files, tmp_path / "out", tmp_path / "models")
    assert len(fake_register) == 2


def test_lancaster_ras_and_lps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    create_transform = Mock()
    write_transform = Mock()
    monkeypatch.setattr(ants, "create_ants_transform", create_transform)
    monkeypatch.setattr(ants, "write_transform", write_transform)
    np.testing.assert_array_equal(
        atlas.ICBM_OTHER2TAL_RAS,
        [
            [0.9357, 0.0029, -0.0072, -1.0423],
            [-0.0065, 0.9396, -0.0726, -1.3940],
            [0.0103, 0.0752, 0.8967, 3.6475],
            [0.0, 0.0, 0.0, 1.0],
        ],
    )

    path = tmp_path / "icbm_other2tal.mat"
    atlas._write_lancaster_transform(path)
    create_transform.assert_called_once_with(transform_type="AffineTransform", dimension=3)
    transform = create_transform.return_value
    transform.set_parameters.assert_called_once()
    np.testing.assert_array_equal(
        transform.set_parameters.call_args.args[0],
        [0.9357, 0.0029, 0.0072, -0.0065, 0.9396, 0.0726, -0.0103, -0.0752, 0.8967, 1.0423, 1.3940, 3.6475],
    )
    write_transform.assert_called_once_with(transform, str(path))


def test_map_atlas_lancaster_reuses_reg1_and_replaces_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    files = _study(tmp_path / "s", ("t1eg", "brain_mask", "gtv"))
    out = tmp_path / "out"
    mni = out / "mni"
    mni.mkdir(parents=True)
    inverse = [mni / "pat2mni_0GenericAffine.mat", mni / "pat2mni_1InverseWarp.nii.gz"]
    for path in inverse:
        path.touch()
    metadata = mni / atlas.CACHE_FILE
    cached = json.dumps({"key": atlas._cache_key(files, "t1eg"), "invtransforms": [p.name for p in inverse]})
    metadata.write_text(cached, encoding="utf-8")
    old_map = _write(out / "brodmann.nii.gz", np.zeros((10, 4, 4), np.uint8))
    old_report = out / areas.AREAS_JSON
    old_report.write_text('{"atlas":"Talairach-Brodmann (nilearn)"}', encoding="utf-8")

    register = Mock(side_effect=AssertionError("REG1 debe reutilizarse"))
    write_transform = Mock()
    projected = np.zeros((10, 4, 4), np.uint8)
    projected[4:6, 1:3, 1:3] = 1
    apply = Mock(return_value=Mock(numpy=Mock(return_value=projected)))
    monkeypatch.setattr(atlas, "_register", register)
    monkeypatch.setattr(atlas, "_write_lancaster_transform", write_transform)
    monkeypatch.setattr(atlas, "fetch_atlas", lambda models_dir: (_synthetic_atlas(), LABELS))
    monkeypatch.setattr(ants, "image_read", Mock())
    monkeypatch.setattr(ants, "apply_transforms", apply)

    mapping = map_atlas(files, out, tmp_path / "models")
    assert not old_report.exists()
    register.assert_not_called()
    assert metadata.read_text(encoding="utf-8") == cached
    write_transform.assert_called_once()
    apply.assert_called_once()
    lancaster = write_transform.call_args.args[0]
    assert lancaster.name == "icbm_other2tal.mat"
    assert apply.call_args.kwargs["transformlist"] == [str(p) for p in (*inverse, lancaster)]
    assert apply.call_args.kwargs["whichtoinvert"] == [True, False, False]
    assert apply.call_args.kwargs["interpolator"] == "genericLabel"
    assert "proyectado a MNI152 con Lancaster 2007" in mapping.registration
    assert "afín global, estimación determinista" in mapping.registration
    img = load_nifti(old_map)
    np.testing.assert_array_equal(np.asarray(img.dataobj), projected)
    assert img.header["descrip"].item() == atlas.ATLAS_NAME.encode("ascii")

    result = areas.run_area_mapping(files, out, tmp_path / "models")
    assert result.atlas == atlas.ATLAS_NAME
    assert json.loads(old_report.read_text(encoding="utf-8"))["registration"] == mapping.registration


def test_map_atlas_registration_mode(tmp_path: Path, fake_register: list[int]) -> None:
    """El modo `fast` se anota en el texto, no reutiliza las transformaciones de `full` y viceversa."""
    files = _study(tmp_path / "s", ("t1gd", "t1eg", "brain_mask", "gtv"))
    out = tmp_path / "out"
    full = map_atlas(files, out, tmp_path / "m")
    assert "(rápido)" not in full.registration and full.registration.startswith("ANTs SyN t1eg→MNI152")

    fast = map_atlas(files, out, tmp_path / "m", "fast")
    assert fast.registration == full.registration + " (rápido)"
    assert len(fake_register) == 2  # la caché de `full` no sirve para `fast`

    map_atlas(files, out, tmp_path / "m", "fast")
    assert len(fake_register) == 2  # misma huella: se reutiliza
    map_atlas(files, out, tmp_path / "m", "full")
    assert len(fake_register) == 2  # cada modo tiene su directorio: `full` reutiliza mni/
    assert (out / "mni").is_dir() and (out / "mni_fast").is_dir()


@pytest.mark.parametrize("mode", ["full", "fast"])
def test_cache_key_invalidates_pre_reg1_transforms(tmp_path: Path, mode: RegistrationMode) -> None:
    files = _study(tmp_path / "s", ("t1eg", "brain_mask", "gtv"))
    assert atlas._cache_key(files, "t1eg", "full") != atlas._cache_key(files, "t1eg", "fast")
    assert atlas._cache_key(files, "t1eg") == atlas._cache_key(files, "t1eg", "full")

    # Ambas huellas de HW3 dejan de servir aunque los archivos de transformación sigan en disco.
    h = hashlib.sha256()
    for seq in ("t1eg", "brain_mask", "gtv"):
        st = files[seq].stat()
        h.update(f"{seq}:{files[seq].resolve()}:{st.st_size}:{st.st_mtime_ns};".encode())
    h.update(b"SyN:1.5:5.0:42" if mode == "full" else b"SyN:2.0:5.0:42:fast:2.0:[('reg_iterations', (20, 10, 0))]")
    tx = tmp_path / "pat2mni_0GenericAffine.mat"
    tx.touch()
    (tmp_path / atlas.CACHE_FILE).write_text(json.dumps({"key": h.hexdigest(), "invtransforms": [tx.name]}))
    assert atlas._load_cached(tmp_path, atlas._cache_key(files, "t1eg", mode)) is None


def _capture_registration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: RegistrationMode
) -> list[dict[str, Any]]:
    """Ejecuta ambas etapas con ANTs y el subproceso simulados."""
    calls: list[dict[str, Any]] = []

    def fake_registration(**kwargs: object) -> dict[str, list[str]]:
        calls.append(kwargs)
        out = Path(str(kwargs["outprefix"]))
        affine = out.parent / (out.name + "0GenericAffine.mat")
        affine.write_bytes(b"")
        return {"fwdtransforms": [str(affine)], "invtransforms": [str(affine)]}

    template = nib.Nifti1Image(np.ones((6, 6, 6), np.float32), np.eye(4))
    mask = nib.Nifti1Image(np.ones((6, 6, 6), np.uint8), np.eye(4))
    monkeypatch.setattr(atlas, "fetch_template", lambda models_dir: (template, mask))
    monkeypatch.setattr(ants, "registration", fake_registration)
    monkeypatch.setenv("ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS", "8")

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert command == [sys.executable, "-m", "cerberus_api.linear_reg"]
        assert kwargs["env"]["ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS"] == "1"
        assert os.environ["ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS"] == "8"
        payload = json.loads(kwargs["input"])
        return subprocess.CompletedProcess(command, 0, json.dumps(linear_reg.run_affine(payload)), "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    study = tmp_path / "study"
    files = _study(study, ("t1eg", "brain_mask", "gtv"))
    work = tmp_path / "work"
    work.mkdir()
    atlas._register(files, "t1eg", tmp_path / "mni", tmp_path / "models", work, mode)
    return calls


@pytest.mark.parametrize(("mode", "spacing", "iterations"), [("full", 1.5, None), ("fast", 2.0, (20, 10, 0))])
def test_register_fixes_affine_threads_and_seeds(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mode: RegistrationMode,
    spacing: float,
    iterations: tuple[int, int, int] | None,
) -> None:
    affine, syn = _capture_registration(monkeypatch, tmp_path, mode)
    assert affine["type_of_transform"] == "Affine"
    assert affine["aff_iterations"] == (2100, 1200, 1200, 0)
    assert affine["aff_shrink_factors"] == (4, 2, 2, 1)
    assert syn["type_of_transform"] == "SyNOnly"
    assert syn["initial_transform"] == [affine["outprefix"] + "0GenericAffine.mat"]
    assert syn.get("reg_iterations") == iterations
    for stage in (affine, syn):
        assert stage["random_seed"] == 42 and stage["mask_all_stages"] is True
        assert np.allclose(stage["moving"].spacing, (spacing,) * 3)
    assert np.allclose(syn["fixed"].spacing, (1 if mode == "full" else 2,) * 3)
    meta = json.loads((tmp_path / "mni" / atlas.CACHE_FILE).read_text(encoding="utf-8"))
    assert meta["registration_mode"] == mode and meta["type_of_transform"] == "SyN"
    assert meta["registration_version"] == atlas.REGISTRATION_VERSION


def test_register_affine_reports_child_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fail(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, "", "error de prueba")

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(RuntimeError, match=r"código 1.*error de prueba"):
        atlas._register_affine(tmp_path)


def test_map_atlas_warnings(tmp_path: Path, fake_register: list[int]) -> None:
    files = _study(tmp_path / "s", ("t1gd", "flair"))
    res = map_atlas(files, tmp_path / "o1", tmp_path / "m")
    assert res.warnings == [WARN_NO_BRAIN, WARN_ONLY_T1GD]
    assert "excluido" not in res.registration

    files = _study(tmp_path / "s2", ("t1tse", "brain_mask", "gtv"))
    _write(files["gtv"], np.ones((10, 4, 4), np.uint8))
    res = map_atlas(files, tmp_path / "o2", tmp_path / "m")
    assert res.reference_sequence == "t1tse"
    assert res.warnings == [WARN_LARGE_GTV]


def test_map_atlas_without_t1_raises(tmp_path: Path, fake_register: list[int]) -> None:
    with pytest.raises(ValueError):
        map_atlas(_study(tmp_path / "s", ("flair", "gtv")), tmp_path / "o", tmp_path / "m")
    assert fake_register == []


# --- Real: 001/t0 ----------------------------------------------------------------------------------------


def _files(study_dir: Path) -> dict[str, Path]:
    return {p.name.split("_", 2)[2].removesuffix(".nii.gz"): p for p in study_dir.glob("*.nii.gz")}


@pytest.mark.slow
def test_real_mapping_on_data(tmp_path: Path) -> None:
    study = REPO_ROOT / "Data" / "001" / "t0"
    if not study.is_dir():
        pytest.skip("Sin Data/001/t0")
    pytest.importorskip("ants")
    files = _files(study)

    start = time.perf_counter()
    res = map_atlas(files, tmp_path, REPO_ROOT / "models")
    elapsed = time.perf_counter() - start

    ref = load_nifti(files["t1gd"])
    img = load_nifti(res.label_path)
    assert res.reference_sequence == "t1gd"
    assert np.allclose(affine_of(img), affine_of(ref)) and img.shape == ref.shape
    lab = np.asarray(img.dataobj)
    values = set(np.unique(lab).tolist()) - {0}
    assert values <= {v for v, _, _ in res.entries} and len(values) >= 30
    assert (tmp_path / "mni" / atlas.CACHE_FILE).is_file()

    # Etiqueta en el centroide del GTV o la más cercana a <= 15 mm
    gtv = np.asarray(load_nifti(files["gtv"]).dataobj) > 0.5
    centroid = np.round(np.argwhere(gtv).mean(axis=0)).astype(int)
    zooms = np.asarray(ref.header.get_zooms()[:3], dtype=float)
    reach = np.ceil(15 / zooms).astype(int)
    lo = np.maximum(centroid - reach, 0)
    hi = centroid + reach + 1
    win = lab[lo[0] : hi[0], lo[1] : hi[1], lo[2] : hi[2]]
    assert (win > 0).any()
    dist = np.asarray(distance_transform_edt(win == 0, sampling=zooms))
    c = centroid - lo
    assert float(dist[c[0], c[1], c[2]]) <= 15

    names = {v: (n, h) for v, n, h in res.entries}
    vals, counts = np.unique(lab[gtv], return_counts=True)
    top = sorted(((int(n), int(v)) for v, n in zip(vals, counts, strict=True) if v != 0), reverse=True)[:5]
    print(f"\nmap_atlas 001/t0: {elapsed:.1f} s · {len(values)} etiquetas · {res.registration} · {res.warnings}")
    for n, v in top:
        print(f"  {v:3d} {names[v][0]} ({names[v][1]}): {n} vóxeles GTV")


@pytest.mark.slow
@pytest.mark.parametrize("mode", ["full", "fast"])
def test_real_registration_is_reproducible(tmp_path: Path, mode: RegistrationMode) -> None:
    settings = Settings()
    files = _files(settings.data_dir / "004" / "t0")
    if not {"t1eg", "t1gd", "brain_mask", "gtv"} <= files.keys():
        pytest.skip("Sin los NIfTI de registro de 004/t0")
    atlas_dir = settings.models_dir / "atlas" / "talairach_atlas"
    if not all((atlas_dir / name).is_file() for name in ("ba.nii.gz", "ba-labels.json")):
        pytest.skip("Sin el atlas Talairach-Brodmann en caché")

    first = map_atlas(files, tmp_path / "first", settings.models_dir, mode)
    second = map_atlas(files, tmp_path / "second", settings.models_dir, mode)
    first_labels = np.asarray(load_nifti(first.label_path).dataobj)
    assert np.any(first_labels)
    np.testing.assert_array_equal(first_labels, np.asarray(load_nifti(second.label_path).dataobj))
