"""Tests de atlas.py: hemisferios con un atlas sintético y `map_atlas` con transformación identidad.

Los rápidos no usan red ni corren el registro ANTs (se reemplaza `_register` por una afín identidad); el `slow`
registra de verdad Data/001/t0.
"""

import json
import time
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest
from scipy.ndimage import distance_transform_edt

from cerberus_api import atlas
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
from cerberus_api.config import REPO_ROOT
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
        study_files: dict[str, Path], moving_seq: str, mni_dir: Path, models_dir: Path, tmp: Path
    ) -> list[str]:
        calls.append(1)
        mni_dir.mkdir(parents=True, exist_ok=True)
        tx = mni_dir / "pat2mni_0GenericAffine.mat"
        ants.write_transform(ants.create_ants_transform(transform_type="AffineTransform", dimension=3), str(tx))
        meta = {"key": atlas._cache_key(study_files, moving_seq), "invtransforms": [tx.name]}
        (mni_dir / atlas.CACHE_FILE).write_text(json.dumps(meta), encoding="utf-8")
        return [str(tx)]

    monkeypatch.setattr(atlas, "fetch_atlas", lambda models_dir: (_synthetic_atlas(), LABELS))
    monkeypatch.setattr(atlas, "_register", register)
    return calls


def test_map_atlas_identity(tmp_path: Path, fake_register: list[int]) -> None:
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
