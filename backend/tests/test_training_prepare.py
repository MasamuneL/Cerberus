"""Tests de FT2: preprocesamiento, parches/augmentations, caché, preflight y CLI (docs/PLAN_PIPELINE_FINETUNING.md §5).

Fantomas sintéticos diminutos (8-40 vóxeles por eje) definidos en coordenadas de mundo: cada archivo se genera
evaluando la misma función física en su propio grid, así que tras preparar deben coincidir en espacio físico.
Sin red, sin GPU y sin `Data/001`.
"""

import json
import subprocess
import sys
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np
import pytest

import cerberus_training.cache as cache_mod
from cerberus_api.segmentation import normalize_nonzero
from cerberus_training.__main__ import EXIT_DATA_ERROR, EXIT_RESOURCES, EXIT_STUDY_ERRORS, main
from cerberus_training.cache import (
    CacheEntryError,
    CacheError,
    StudyCache,
    cache_key_payload,
    prepare_all,
    preprocess_hash,
)
from cerberus_training.config import REPO_ROOT, PreprocessConfig, TrainConfig, load_config, resolve_config
from cerberus_training.inventory import inspect_study, write_inventory
from cerberus_training.preflight import (
    CACHE_BYTES_PER_VOXEL,
    SOURCE_NATIVE_BYTES_BOUND,
    run_preflight,
    study_estimate,
)
from cerberus_training.transforms import (
    GEOMETRY_TOL_MM,
    Geometry,
    PreparedStudy,
    StudyError,
    augment,
    corner_distance,
    eval_sample,
    make_rng,
    prepare_study,
    resample,
    restore_to_reference,
    sample_patch,
    study_sources,
    target_grid,
    train_sample,
)

EXAMPLE = REPO_ROOT / "configs" / "training" / "gtv_binary.json"
EXTENT = (20.0, 20.0, 16.0)  # mm por eje de mundo; el fantoma está centrado en el origen
SEQS = ("t1gd", "t1eg", "t2tse", "flair")
GTV_CENTER = np.array([1.0, 1.0, 0.0])
BACKGROUND = 5.0  # valor de fondo fuera del cerebro en las imágenes fuente
PRE = PreprocessConfig(patch_size=(8, 8, 8))

Grid = tuple[tuple[int, int, int], np.ndarray]
Edit = Callable[[str, np.ndarray], np.ndarray]


def grid(
    spacing: tuple[float, float, float] = (1.0, 1.0, 1.0),
    perm: tuple[int, int, int] = (0, 1, 2),
    flips: tuple[bool, bool, bool] = (False, False, False),
    rot_deg: float = 0.0,
    shift: tuple[float, float, float] = (0.0, 0.0, 0.0),
    extent: tuple[float, float, float] = EXTENT,
) -> Grid:
    """Grid que cubre la caja `extent` centrada en el origen; el eje de vóxel i apunta al eje de mundo `perm[i]`.

    `spacing` es por eje de mundo; `flips` invierte ejes de vóxel; `rot_deg` rota alrededor de z (oblicuo).
    """
    t = np.deg2rad(rot_deg)
    rot = np.array([[np.cos(t), -np.sin(t), 0], [np.sin(t), np.cos(t), 0], [0, 0, 1]])
    cols, shape = [], []
    for i, axis in enumerate(perm):
        shape.append(round(extent[axis] / spacing[axis]))
        cols.append(rot[:, axis] * spacing[axis] * (-1.0 if flips[i] else 1.0))
    m = np.stack(cols, axis=1)
    affine = np.eye(4)
    affine[:3, :3] = m
    affine[:3, 3] = -m @ ((np.array(shape) - 1) / 2) + np.array(shift)
    return (shape[0], shape[1], shape[2]), affine


def world(g: Grid) -> np.ndarray:
    """Coordenadas de mundo (mm) del centro de cada vóxel, `[X, Y, Z, 3]`."""
    shape, affine = g
    idx = np.stack(np.meshgrid(*[np.arange(n) for n in shape], indexing="ij"), axis=-1).astype(np.float64)
    return idx @ affine[:3, :3].T + affine[:3, 3]


def brain_fn(w: np.ndarray) -> np.ndarray:
    return ((w[..., 0] / 7.5) ** 2 + (w[..., 1] / 7.5) ** 2 + (w[..., 2] / 6.0) ** 2) <= 1.0


def interior_fn(w: np.ndarray) -> np.ndarray:
    """Interior del cerebro a más de ~2 mm del borde: ahí la interpolación lineal no mezcla con el fondo."""
    return ((w[..., 0] / 5.5) ** 2 + (w[..., 1] / 5.5) ** 2 + (w[..., 2] / 4.0) ** 2) <= 1.0


def gtv_fn(w: np.ndarray) -> np.ndarray:
    return np.linalg.norm(w - GTV_CENTER, axis=-1) <= 2.6


def no_gtv(w: np.ndarray) -> np.ndarray:
    return np.zeros(w.shape[:3], dtype=bool)


def image_fn(seq: str, w: np.ndarray) -> np.ndarray:
    """Patrón distinto por canal: T1c rampa x, T1 rampa y, T2 rampa z, FLAIR rampa -x."""
    ramp = {"t1gd": w[..., 0], "t1eg": w[..., 1], "t2tse": w[..., 2], "flair": -w[..., 0]}[seq]
    return np.where(brain_fn(w), 50.0 + 3.0 * ramp, BACKGROUND)


def write_study(
    root: Path,
    patient: str = "001",
    timepoint: str = "t0",
    grids: dict[str, Grid] | None = None,
    default: Grid | None = None,
    brain_mask: bool = True,
    label: Callable[[np.ndarray], np.ndarray] = gtv_fn,
    edit: Edit | None = None,
) -> dict[str, Any]:
    """Escribe un estudio sintético y devuelve su registro de inventario (debe ser elegible)."""
    grids = grids or {}
    base = default or grid()
    seqs = (*SEQS, "gtv", *(("brain_mask",) if brain_mask else ()))
    for seq in seqs:
        g = grids.get(seq, base)
        w = world(g)
        if seq == "gtv":
            data: np.ndarray = label(w).astype(np.uint8)
        elif seq == "brain_mask":
            data = brain_fn(w).astype(np.uint8)
        else:
            data = image_fn(seq, w).astype(np.float32)
        if edit is not None:
            data = edit(seq, data)
        path = root / patient / timepoint / f"{int(patient)}_{timepoint}_{seq}.nii.gz"
        path.parent.mkdir(parents=True, exist_ok=True)
        nib.save(nib.Nifti1Image(data, g[1]), str(path))
    record = inspect_study(root.resolve(), patient, timepoint)
    assert record["eligible"], record["exclusions"]
    return record


@pytest.fixture
def root(tmp_path: Path) -> Path:
    data_root = tmp_path / "cfb"
    data_root.mkdir()
    return data_root.resolve()


def prepared_world(study: PreparedStudy) -> np.ndarray:
    return world((study.geometry.prepared_shape, study.geometry.prepared_affine))


def dice(a: np.ndarray, b: np.ndarray) -> float:
    a, b = a.astype(bool), b.astype(bool)
    return float(2 * (a & b).sum() / (a.sum() + b.sum()))


def centroid(mask: np.ndarray, w: np.ndarray) -> np.ndarray:
    return w[mask.astype(bool)].mean(axis=0)


def ramps(w: np.ndarray) -> list[np.ndarray]:
    return [w[..., 0], w[..., 1], w[..., 2], -w[..., 0]]


# ---------------------------------------------------------------------------------------------------------------
# Preparación: canales y geometría
# ---------------------------------------------------------------------------------------------------------------


def test_channel_order_and_dtypes(root: Path) -> None:
    study = prepare_study(write_study(root), root, PRE)
    assert study.image.dtype == np.float32 and study.image.shape[0] == 4
    assert study.label.dtype == np.uint8 and study.brain.dtype == np.uint8
    assert study.meta()["channel_order"] == ["T1c", "T1", "T2", "FLAIR"]
    w = prepared_world(study)
    inside = study.brain.astype(bool)
    for c, ramp in enumerate(ramps(w)):
        assert np.corrcoef(study.image[c][inside], ramp[inside])[0, 1] > 0.95, c


def test_prepared_grid_is_ras_1mm_and_contains_reference(root: Path) -> None:
    ref = grid(spacing=(2.0, 1.0, 2.0), perm=(2, 0, 1), flips=(True, False, True))
    study = prepare_study(write_study(root, default=ref), root, PRE)
    assert np.allclose(study.geometry.prepared_affine[:3, :3], np.eye(3))
    assert study.geometry.reference_shape == ref[0]
    assert np.allclose(study.geometry.reference_affine, ref[1])
    full_shape, _ = target_grid(ref[0], ref[1], 1.0)
    assert all(p <= f for p, f in zip(study.geometry.prepared_shape, full_shape, strict=True))


@pytest.mark.parametrize(
    "grids",
    [
        # cada archivo con spacing, permutación de ejes y flips distintos que cubren la misma caja
        {
            "t1eg": grid(spacing=(2.0, 1.0, 2.0)),
            "t2tse": grid(perm=(2, 1, 0), flips=(True, False, True)),
            "flair": grid(spacing=(0.5, 1.0, 1.0)),
            "gtv": grid(perm=(1, 0, 2), flips=(False, True, False)),
            "brain_mask": grid(spacing=(1.0, 2.0, 1.0), flips=(True, True, True)),
        },
        # todos oblicuos (30° en z); la GTV, además, con ejes invertidos
        {
            "t1gd": grid(rot_deg=30),
            "t1eg": grid(rot_deg=30),
            "t2tse": grid(rot_deg=30),
            "flair": grid(rot_deg=30),
            "gtv": grid(rot_deg=30, flips=(True, True, False)),
            "brain_mask": grid(rot_deg=30),
        },
    ],
    ids=["spacing-perm-flip", "oblique"],
)
def test_images_and_label_coincide_in_physical_space(root: Path, grids: dict[str, Grid]) -> None:
    study = prepare_study(write_study(root, grids=grids), root, PRE)
    w = prepared_world(study)
    assert set(np.unique(study.label).tolist()) <= {0, 1}
    # GTV en el lugar físico correcto: Dice con la esfera evaluada en el grid preparado y centroide < 0.5 mm.
    assert dice(study.label, gtv_fn(w)) > 0.8
    assert np.linalg.norm(centroid(study.label, w) - GTV_CENTER) < 0.5
    # Máscara cerebral y canales alineados con el mismo espacio físico.
    assert dice(study.brain, brain_fn(w)) > 0.9
    inside = study.brain.astype(bool) & interior_fn(w)
    for c, ramp in enumerate(ramps(w)):
        assert np.corrcoef(study.image[c][inside], ramp[inside])[0, 1] > 0.99, c


def test_corner_distance_ignores_axis_order_but_not_shift() -> None:
    a, b = grid(), grid(perm=(2, 1, 0), flips=(True, True, False), spacing=(0.5, 2.0, 1.0))
    assert corner_distance(a[0], a[1], b[0], b[1]) < 1e-9
    c = grid(shift=(0.0, 2.0, 0.0))
    assert corner_distance(a[0], a[1], c[0], c[1]) == pytest.approx(2.0)


@pytest.mark.parametrize(
    ("grids", "channel"),
    [
        ({"t2tse": grid(shift=(3.0, 0.0, 0.0))}, "T2"),  # desplazamiento (desregistro de cabecera)
        ({"gtv": grid(extent=(20.0, 20.0, 12.0))}, "label"),  # FOV distinto
        ({"flair": grid(rot_deg=10)}, "FLAIR"),  # rotación: affine incompatible
        ({"brain_mask": grid(shift=(0.0, 0.0, 1.0))}, "brain_mask"),
    ],
)
def test_misregistration_is_rejected(root: Path, grids: dict[str, Grid], channel: str) -> None:
    with pytest.raises(StudyError) as exc_info:
        prepare_study(write_study(root, grids=grids), root, PRE)
    assert exc_info.value.code == "geometry_mismatch" and exc_info.value.channel == channel


# ---------------------------------------------------------------------------------------------------------------
# Preparación: validaciones de contenido
# ---------------------------------------------------------------------------------------------------------------


def _edit(target: str, fn: Callable[[np.ndarray], np.ndarray]) -> Edit:
    return lambda seq, data: fn(data) if seq == target else data


@pytest.mark.parametrize(
    ("edit", "code", "channel"),
    [
        (_edit("gtv", lambda d: d * 2), "non_binary_label", "label"),
        (_edit("gtv", lambda d: d.astype(np.float32) * 0.5), "non_binary_label", "label"),
        (_edit("gtv", lambda d: np.where(d > 0, np.nan, 0).astype(np.float32)), "non_finite", "label"),
        (_edit("t1eg", lambda d: np.where(d > 40, np.inf, d).astype(np.float32)), "non_finite", "T1"),
        (_edit("t1gd", lambda d: np.full_like(d, np.nan)), "non_finite", "T1c"),
        (_edit("brain_mask", lambda d: d * 3), "non_binary_mask", "brain_mask"),
        (_edit("brain_mask", np.zeros_like), "empty_brain_mask", "brain_mask"),
        # T2 solo con fondo: dentro de la máscara cerebral no queda ningún vóxel no nulo
        (_edit("t2tse", lambda d: np.where(d == BACKGROUND, BACKGROUND, 0).astype(np.float32)), "empty_image", "T2"),
    ],
)
def test_invalid_content_is_rejected(root: Path, edit: Edit, code: str, channel: str) -> None:
    with pytest.raises(StudyError) as exc_info:
        prepare_study(write_study(root, edit=edit), root, PRE)
    assert exc_info.value.code == code and exc_info.value.channel == channel


def flags(study: PreparedStudy) -> dict[str, Any]:
    return {f["code"]: f.get("voxels") for f in study.review_flags}


def test_label_outside_support_is_flagged_not_excluded(root: Path) -> None:
    def far(w: np.ndarray) -> np.ndarray:  # GTV dentro del cerebro + una parte en una esquina, fuera del soporte
        return gtv_fn(w) | (np.linalg.norm(w - np.array([9.0, 9.0, 7.0]), axis=-1) <= 1.0)

    study = prepare_study(write_study(root, label=far), root, PRE)
    w = world(grid())
    corner = int((far(w) & ~gtv_fn(w)).sum())
    assert flags(study)["label_outside_support"] == corner == study.label_lost_voxels
    assert flags(study)["label_outside_brain_mask"] == corner  # la esquina también está fuera de la máscara
    assert int(study.label.sum()) == int(gtv_fn(w).sum())  # se conserva la GTV dentro del recorte


def test_label_vanished_is_flagged(root: Path) -> None:
    fine = grid(spacing=(0.25, 0.25, 0.25))  # 4 vóxeles fuente por vóxel destino

    def one_voxel(data: np.ndarray) -> np.ndarray:
        out = np.zeros_like(data)
        out[40, 40, 32] = 1  # índice 4k: ningún centro del grid destino de 1 mm lo muestrea por NN
        return out

    study = prepare_study(write_study(root, grids={"gtv": fine}, edit=_edit("gtv", one_voxel)), root, PRE)
    assert flags(study) == {"label_vanished": 1} and study.label_empty


def test_empty_gtv_is_preserved_and_flagged(root: Path) -> None:
    study = prepare_study(write_study(root, label=no_gtv), root, PRE)
    assert study.label_empty and not study.label.any()
    assert [f["code"] for f in study.review_flags] == ["empty_label"]


def test_source_changed_after_inventory(root: Path) -> None:
    record = write_study(root)
    path = root / "001" / "t0" / "1_t0_flair.nii.gz"
    nib.save(nib.Nifti1Image(np.ones((20, 20, 16), np.float32), grid()[1]), str(path))
    with pytest.raises(StudyError) as exc_info:
        prepare_study(record, root, PRE)
    assert exc_info.value.code == "source_changed" and exc_info.value.channel == "FLAIR"


def test_ineligible_and_tampered_records(root: Path) -> None:
    record = write_study(root)
    with pytest.raises(StudyError, match="excluye") as exc_info:
        prepare_study({**record, "eligible": False}, root, PRE)
    assert exc_info.value.code == "not_eligible"
    bad = json.loads(json.dumps(record))
    bad["channels"]["T1"]["path"] = "001/t0/../../../etc/passwd"
    with pytest.raises(StudyError) as exc_info:
        prepare_study(bad, root, PRE)
    assert exc_info.value.code == "invalid_source"
    for broken in ({k: v for k, v in record.items() if k != "label"}, {**record, "channels": {}}):
        with pytest.raises(StudyError) as exc_info:  # nunca un KeyError
            prepare_study(broken, root, PRE)
        assert exc_info.value.code == "invalid_source"


def test_normalization_over_nonzero_voxels(root: Path) -> None:
    study = prepare_study(write_study(root), root, PRE)
    inside = study.brain.astype(bool)
    for c in range(4):
        ch = study.image[c]
        nz = ch != 0
        assert abs(float(ch[nz].mean())) < 1e-4 and abs(float(ch[nz].std()) - 1.0) < 1e-4
        assert not ch[~inside].any()  # con máscara cerebral, el fondo (5 en la fuente) queda a 0


def test_brain_mask_policy_without_mask(root: Path) -> None:
    study = prepare_study(write_study(root, brain_mask=False), root, PRE)
    assert study.brain_mask_source == "nonzero_support"
    assert [f["code"] for f in study.review_flags] == ["no_brain_mask"]
    # Sin máscara, el fondo no nulo forma parte del soporte: no hay skull-strip silencioso.
    assert study.brain.all()
    with_mask = prepare_study(write_study(root, patient="002"), root, PRE)
    assert with_mask.brain_mask_source == "brain_mask" and not with_mask.review_flags
    assert with_mask.brain.sum() < study.brain.sum()


def test_gtv_does_not_influence_image(tmp_path: Path) -> None:
    def shifted(w: np.ndarray) -> np.ndarray:
        return np.linalg.norm(w - np.array([-3.0, 0.0, 1.0]), axis=-1) <= 3.5

    studies = []
    for name, label in (("a", gtv_fn), ("b", shifted), ("c", no_gtv)):
        data_root = tmp_path / name
        studies.append(prepare_study(write_study(data_root, label=label), data_root, PRE))
    a, b, c = studies
    assert not np.array_equal(a.label, b.label)
    for other in (b, c):
        assert np.array_equal(a.image, other.image)
        assert np.array_equal(a.geometry.prepared_affine, other.geometry.prepared_affine)


def test_prepare_is_deterministic(root: Path) -> None:
    record = write_study(root, grids={"t1eg": grid(spacing=(2.0, 1.0, 2.0))})
    a, b = prepare_study(record, root, PRE), prepare_study(record, root, PRE)
    assert np.array_equal(a.image, b.image) and np.array_equal(a.label, b.label)


def test_normalize_nonzero_regression() -> None:
    """Fija la salida de la función compartida con la API: un cambio en `cerberus_api` debe notarse aquí."""
    x = np.array([[[0.0, 1.0, 2.0], [3.0, 0.0, 5.0]], [[0.0, 4.0, 0.0], [4.0, 0.0, 0.0]], [[0.0] * 3] * 2])
    expected = np.array(
        [
            [[0.0, -1.18321596, -0.50709255], [0.16903085, 0.0, 1.52127766]],
            [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
            [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]],
        ]
    )
    out = normalize_nonzero(x)
    assert out.dtype == np.float32 and np.allclose(out, expected, atol=1e-6)


@pytest.mark.parametrize("flips", [(True, False, False), (True, True, False)], ids=["flip-x", "flip-xy"])
@pytest.mark.parametrize("order", [0, 1])
def test_resample_leaves_no_zeros_inside_hull(flips: tuple[bool, bool, bool], order: int) -> None:
    """Grid no centrado, origen no entero, spacing 0.9375: un volumen de unos no deja ceros dentro del casco."""
    src = grid(spacing=(0.9375, 0.9375, 0.9375), flips=flips, shift=(3.37, -1.61, 0.29), extent=(15.0, 15.0, 11.25))
    out_shape, out_affine = target_grid(src[0], src[1], 1.0)
    ones = np.ones(src[0], dtype=np.float32 if order else np.uint8)
    res = resample(ones, src[1], out_shape, out_affine, order=order)
    coords = world((out_shape, out_affine)) @ np.linalg.inv(src[1])[:3, :3].T + np.linalg.inv(src[1])[:3, 3]
    hull = np.all((coords > -0.5 + 1e-6) & (coords < np.array(src[0]) - 0.5 - 1e-6), axis=-1)
    assert hull.sum() > 0.5 * hull.size
    assert bool(np.all(res[hull] > 0))
    if order == 0:
        assert bool(np.all(res[hull] == 1)) and not res[~hull].any()


def test_gtv_on_border_plane_is_preserved(root: Path) -> None:
    ref = grid(spacing=(0.9375, 0.9375, 0.9375), flips=(True, True, False), shift=(3.37, -1.61, 0.29))

    def border(data: np.ndarray) -> np.ndarray:
        out = np.zeros_like(data)
        out[0, 5:15, 4:12] = 1  # plano de borde del eje 0
        return out

    study = prepare_study(write_study(root, default=ref, brain_mask=False, edit=_edit("gtv", border)), root, PRE)
    assert "label_vanished" not in flags(study) and study.label.any()
    restored = restore_to_reference(study.label, study.geometry)
    assert restored[0].any() and dice(restored, border(np.zeros(ref[0], np.uint8))) > 0.8


# ---------------------------------------------------------------------------------------------------------------
# Restauración geométrica
# ---------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ref",
    [
        grid(perm=(1, 2, 0), flips=(True, False, True)),
        grid(spacing=(1.0, 1.0, 2.0), flips=(False, True, False)),
    ],
    ids=["perm-flip", "anisotropic"],
)
def test_restore_roundtrip_is_exact_on_aligned_grids(root: Path, ref: Grid) -> None:
    study = prepare_study(write_study(root, default=ref), root, PRE)
    restored = restore_to_reference(study.label, study.geometry)
    original = gtv_fn(world(ref)).astype(np.uint8)
    assert restored.shape == ref[0] and np.array_equal(restored, original)


def test_restore_roundtrip_oblique(root: Path) -> None:
    ref = grid(rot_deg=30)
    study = prepare_study(write_study(root, default=ref), root, PRE)
    restored = restore_to_reference(study.label, study.geometry)
    assert restored.shape == ref[0] and dice(restored, gtv_fn(world(ref))) > 0.85
    with pytest.raises(ValueError, match="forma preparada"):
        restore_to_reference(study.label[1:], study.geometry)


# ---------------------------------------------------------------------------------------------------------------
# Parches y augmentations
# ---------------------------------------------------------------------------------------------------------------


@pytest.fixture
def study(root: Path) -> PreparedStudy:
    return prepare_study(write_study(root), root, PRE)


def test_patch_sampling_is_seeded_and_balanced(study: PreparedStudy) -> None:
    patches = [sample_patch(study, (8, 8, 8), (1, 1), make_rng(7, 0, i)) for i in range(200)]
    again = [sample_patch(study, (8, 8, 8), (1, 1), make_rng(7, 0, i)) for i in range(200)]
    assert [p.start for p in patches] == [p.start for p in again]
    assert all(p.image.shape == (4, 8, 8, 8) and p.label.shape == (8, 8, 8) for p in patches)
    positives = [p for p in patches if p.positive]
    assert 0.4 < len(positives) / len(patches) < 0.6
    assert all(p.label.any() for p in positives)
    other_seed = [sample_patch(study, (8, 8, 8), (1, 1), make_rng(8, 0, i)).start for i in range(200)]
    assert other_seed != [p.start for p in patches]


def test_patch_sampling_empty_gtv_only_negatives(root: Path) -> None:
    empty = prepare_study(write_study(root, label=no_gtv), root, PRE)
    patches = [sample_patch(empty, (8, 8, 8), (1, 1), make_rng(1, 0, i)) for i in range(50)]
    assert not any(p.positive for p in patches) and not any(p.label.any() for p in patches)


def test_patch_padding_when_volume_is_smaller(study: PreparedStudy) -> None:
    patch = sample_patch(study, (32, 32, 32), (1, 1), make_rng(0, 0, 0))
    assert patch.image.shape == (4, 32, 32, 32) and patch.start == (0, 0, 0)


def test_augmentations_are_seeded_and_train_only(study: PreparedStudy) -> None:
    a = train_sample(study, PRE, make_rng(3, 1, 5))
    b = train_sample(study, PRE, make_rng(3, 1, 5))
    assert np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1])
    assert a[0].shape == (4, 8, 8, 8) and a[0].dtype == np.float32
    assert set(np.unique(a[1]).tolist()) <= {0, 1}
    # Las augmentations cambian el parche respecto al recorte sin aumentar con la misma semilla.
    patch = sample_patch(study, PRE.patch_size, PRE.pos_neg_ratio, make_rng(3, 1, 5))
    assert not np.array_equal(a[0], patch.image)
    assert int(a[1].sum()) == int(patch.label.sum())  # la GTV solo se mueve, no cambia de tamaño
    # Validación/prueba: volumen completo sin augmentations.
    image, label, geometry = eval_sample(study)
    assert image is study.image and label is study.label and geometry is study.geometry


def test_augment_moves_image_and_label_together() -> None:
    rng = np.random.default_rng(0)
    label = (rng.random((8, 8, 8)) > 0.8).astype(np.uint8)
    image = np.stack([label.astype(np.float32) * 10 + 1] * 4)
    for seed in range(20):
        img, lab = augment(image, label, np.random.default_rng(seed))
        # Dentro de la GTV el valor era 11 y fuera 1: tras ±10 % de escala y ±0.1 de desplazamiento siguen separados.
        assert np.array_equal(img[0] > 5, lab.astype(bool))


def test_patch_larger_than_volume_in_one_axis_with_border_gtv() -> None:
    shape = (12, 12, 6)
    label = np.zeros(shape, np.uint8)
    label[10:12, 10:12, 5] = 1  # GTV en la esquina y en el último plano z
    image = np.stack([np.arange(np.prod(shape), dtype=np.float32).reshape(shape) + 1] * 4)
    geometry = Geometry(shape, np.eye(4), shape, np.eye(4), 1.0)
    study = PreparedStudy("001_t0", image, label, np.ones(shape, np.uint8), geometry, "brain_mask", False, {})
    patches = [sample_patch(study, (8, 8, 16), (1, 1), make_rng(5, 0, i)) for i in range(40)]
    assert all(p.image.shape == (4, 8, 8, 16) and p.start[2] == 0 for p in patches)
    positives = [p for p in patches if p.positive]
    assert positives and all(int(p.label.sum()) == 4 for p in positives)
    assert all(not p.image[:, :, :, 6:].any() for p in patches)  # relleno con ceros solo en z


def test_train_sample_augments_eval_sample_does_not(study: PreparedStudy) -> None:
    for seed in range(5):
        patch = sample_patch(study, PRE.patch_size, PRE.pos_neg_ratio, make_rng(seed, 0, 0))
        image, _label = train_sample(study, PRE, make_rng(seed, 0, 0))
        assert not np.array_equal(image, patch.image)  # mismo recorte, con augmentations
    before = study.image.copy()
    first, second = eval_sample(study), eval_sample(study)
    assert np.array_equal(first[0], before) and np.array_equal(second[0], before)
    assert first[2] is study.geometry


# ---------------------------------------------------------------------------------------------------------------
# Caché
# ---------------------------------------------------------------------------------------------------------------


def write_config(tmp_path: Path, data_root: Path, **preprocess: Any) -> Path:
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    data["paths"] = {"data_root": str(data_root), "work_dir": str(tmp_path / "work")}
    data["weights"]["path"] = str(tmp_path / "model.pt")
    data["training"].update({"device": "cpu", "amp": False})
    data["preprocess"].update({"patch_size": [8, 8, 8], "cache_limit_gb": 1.0, "min_free_disk_gb": 1e-6})
    data["preprocess"].update(preprocess)
    path = tmp_path / f"config_{len(list(tmp_path.glob('config_*.json')))}.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def config_for(tmp_path: Path, data_root: Path, **preprocess: Any) -> TrainConfig:
    return resolve_config(load_config(write_config(tmp_path, data_root, **preprocess)))


def test_cache_hit_and_roundtrip(root: Path, tmp_path: Path) -> None:
    records = [write_study(root, "001"), write_study(root, "002", label=no_gtv)]
    config = config_for(tmp_path, root)
    first = prepare_all(config, records)
    assert [s["status"] for s in first.studies] == ["prepared", "prepared"]
    second = prepare_all(config, records)
    assert [s["status"] for s in second.studies] == ["cached", "cached"]
    cache = StudyCache.from_config(config)
    loaded = cache.load("002_t0")
    direct = prepare_study(records[1], root, config.preprocess)
    assert loaded.label_empty
    assert np.array_equal(loaded.image, direct.image) and np.array_equal(loaded.label, direct.label)
    assert np.allclose(loaded.geometry.prepared_affine, direct.geometry.prepared_affine)
    report = json.loads((tmp_path / "work" / "prepare_report.json").read_text(encoding="utf-8"))
    assert report["counts"] == {"cached": 2} and report["completed"] is True
    assert report["review_totals"]["empty_label"] == {"studies": 1, "voxels": 0}
    key = json.loads((cache.directory / "key.json").read_text(encoding="utf-8"))
    assert key["transforms_version"] == cache_mod.TRANSFORMS_VERSION and "inventory_sha256" not in key
    assert set(key["libraries"]) == {"numpy", "scipy", "nibabel"} and key["geometry_tol_mm"] == GEOMETRY_TOL_MM
    assert not [p for p in cache.directory.iterdir() if p.name.startswith(".")]


def test_cache_key_invalidation(root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = config_for(tmp_path, root)
    base = preprocess_hash(cache_key_payload(config))
    other = config_for(tmp_path, root, spacing_mm=1.5)
    assert preprocess_hash(cache_key_payload(other)) != base  # configuración de preprocesamiento
    patched = config_for(tmp_path, root, patch_size=[16, 16, 16], cache_limit_gb=2.0)
    assert preprocess_hash(cache_key_payload(patched)) == base  # parche y límites no cambian volúmenes
    with monkeypatch.context() as m:
        m.setattr(cache_mod, "TRANSFORMS_VERSION", "ft2-test")
        assert preprocess_hash(cache_key_payload(config)) != base  # versión de transformaciones
    with monkeypatch.context() as m:
        m.setattr(cache_mod, "GEOMETRY_TOL_MM", 0.25)
        assert preprocess_hash(cache_key_payload(config)) != base  # tolerancia geométrica
    with monkeypatch.context() as m:
        m.setattr(cache_mod, "library_versions", lambda: {"numpy": "0", "scipy": "0", "nibabel": "0"})
        assert preprocess_hash(cache_key_payload(config)) != base  # bibliotecas


def test_cache_miss_on_source_or_version_change(root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    record = write_study(root)
    config = config_for(tmp_path, root)
    prepare_all(config, [record])
    cache = StudyCache.from_config(config)
    sources = cache.load("001_t0").sources
    assert cache.is_hit("001_t0", sources) is not None
    assert cache.is_hit("001_t0", {**sources, "T1": "f" * 64}) is None
    with pytest.raises(CacheEntryError, match="fuentes cambiaron"):
        cache.load("001_t0", {**sources, "T1": "f" * 64})
    # Otra fuente en el inventario (misma carpeta de clave): solo ese estudio se reprepara.
    changed = json.loads(json.dumps(record))
    changed["channels"]["T1"]["sha256"] = "f" * 64
    assert prepare_all(config, [changed]).studies[0]["error"]["code"] == "source_changed"
    monkeypatch.setattr(cache_mod, "TRANSFORMS_VERSION", "ft2-test")
    assert [s["status"] for s in prepare_all(config, [record]).studies] == ["prepared"]
    assert len(list((tmp_path / "work" / "cache").iterdir())) == 2


def test_missing_or_corrupt_entry_raises_and_is_rebuilt(root: Path, tmp_path: Path) -> None:
    record = write_study(root)
    config = config_for(tmp_path, root)
    cache = StudyCache.from_config(config)
    with pytest.raises(CacheEntryError, match="no hay entrada"):
        cache.load("001_t0")
    prepare_all(config, [record])
    cache.path("001_t0").write_bytes(b"no es un npz")
    with pytest.raises(CacheEntryError, match="ilegible"):
        cache.load("001_t0")
    assert [s["status"] for s in prepare_all(config, [record]).studies] == ["prepared"]
    cache.load("001_t0")


def test_altered_byte_is_detected_and_rewritten(root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    record = write_study(root)
    config = config_for(tmp_path, root)
    prepare_all(config, [record])
    cache = StudyCache.from_config(config)
    path = cache.path("001_t0")
    raw = bytearray(path.read_bytes())
    with np.load(path) as npz:
        target = np.asarray(npz["image"]).tobytes()[200:216]  # 16 bytes del interior de `image`
    offset = raw.index(target)
    raw[offset] ^= 0xFF
    path.write_bytes(bytes(raw))
    sources = study_sources(record)
    assert cache.is_hit("001_t0", sources) is None
    with pytest.raises(CacheEntryError):
        cache.load("001_t0", sources)
    assert [s["status"] for s in prepare_all(config, [record]).studies] == ["prepared"]
    assert cache.is_hit("001_t0", sources) is not None


def test_array_hash_mismatch_is_detected(root: Path, tmp_path: Path) -> None:
    record = write_study(root)
    config = config_for(tmp_path, root)
    prepare_all(config, [record])
    cache = StudyCache.from_config(config)
    path = cache.path("001_t0")
    with np.load(path) as npz:
        arrays = {name: np.asarray(npz[name]) for name in npz.files}
    image = arrays["image"].copy()
    image.flat[0] += 1.0  # zip íntegro (CRC nuevo) pero contenido distinto del que se preparó
    np.savez(path, image=image, label=arrays["label"], brain=arrays["brain"], meta=arrays["meta"])
    with pytest.raises(CacheEntryError, match="SHA-256 del array image"):
        cache.load("001_t0")
    assert cache.is_hit("001_t0", study_sources(record)) is None


def test_atomic_write_leaves_no_partial_files(root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    record = write_study(root)
    config = config_for(tmp_path, root)
    real_savez = np.savez

    def failing_savez(file: Any, **arrays: Any) -> None:
        real_savez(file, image=arrays["image"])  # escribe una parte y falla
        raise OSError("disco lleno simulado")

    monkeypatch.setattr(cache_mod.np, "savez", failing_savez)
    with pytest.raises(OSError, match="simulado"):
        prepare_all(config, [record])
    directory = StudyCache.from_config(config).directory
    assert sorted(p.name for p in directory.iterdir()) == ["key.json"]
    # El informe se persiste aunque falle el primer `store`.
    report = json.loads((tmp_path / "work" / "prepare_report.json").read_text(encoding="utf-8"))
    assert report["completed"] is False and report["studies"][0]["status"] == "aborted"
    assert "simulado" in report["aborted"]


def test_orphan_temporaries_are_removed(root: Path, tmp_path: Path) -> None:
    record = write_study(root)
    config = config_for(tmp_path, root)
    directory = StudyCache.from_config(config).directory
    directory.mkdir(parents=True)
    orphan = directory / ".001_t0.npz.abc123.tmp"
    orphan.write_bytes(b"x" * 1000)
    prepare_all(config, [record])
    assert not orphan.exists()


def test_cache_size_limit(root: Path, tmp_path: Path) -> None:
    record = write_study(root)
    config = config_for(tmp_path, root, cache_limit_gb=1e-6)  # ~1 KB
    with pytest.raises(CacheError, match="límite"):
        prepare_all(config, [record])
    assert not StudyCache.from_config(config).path("001_t0").exists()
    report = json.loads((tmp_path / "work" / "prepare_report.json").read_text(encoding="utf-8"))
    assert report["completed"] is False


def test_cache_free_space_check(root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    record = write_study(root)
    config = config_for(tmp_path, root, min_free_disk_gb=5.0)
    fake = types.SimpleNamespace(total=10 * 1024**3, used=6 * 1024**3, free=4 * 1024**3)
    monkeypatch.setattr(cache_mod.shutil, "disk_usage", lambda _path: fake)
    with pytest.raises(CacheError, match="Espacio libre insuficiente"):
        prepare_all(config, [record])
    assert not StudyCache.from_config(config).path("001_t0").exists()


def test_cache_disabled_only_validates_but_writes_report(root: Path, tmp_path: Path) -> None:
    config = config_for(tmp_path, root, cache_enabled=False)
    report = prepare_all(config, [write_study(root)])
    assert [s["status"] for s in report.studies] == ["validated"] and report.cache_key is None
    assert not (tmp_path / "work" / "cache").exists()
    saved = json.loads((tmp_path / "work" / "prepare_report.json").read_text(encoding="utf-8"))
    assert saved["counts"] == {"validated": 1} and saved["cache_key"] is None


# ---------------------------------------------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------------------------------------------


def test_preflight_estimates_from_shapes(root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ref = grid(spacing=(2.0, 1.0, 2.0))
    record = write_study(root, default=ref)
    config = config_for(tmp_path, root)
    voxels, shape, source = study_estimate(record, 1.0, config.channels.reference)
    full_shape, _ = target_grid(ref[0], ref[1], 1.0)
    assert shape == full_shape and voxels == int(np.prod(full_shape))
    assert source == int(np.prod(ref[0]))
    report = run_preflight(config, [record])
    assert report.ok and report.studies == 1
    assert report.cache_bytes == voxels * CACHE_BYTES_PER_VOXEL + cache_mod.ENTRY_OVERHEAD_BYTES
    assert report.prepare_ram_bytes == voxels * 39 + source * (SOURCE_NATIVE_BYTES_BOUND + 4)
    assert report.train_ram_bytes > report.cache_bytes and "no encontrados" in report.weights
    # El tamaño real de una entrada (con recorte) nunca supera la cota superior.
    assert cache_mod.entry_bytes(prepare_study(record, root, config.preprocess)) <= report.cache_bytes
    fake = types.SimpleNamespace(total=1, used=1, free=0)
    monkeypatch.setattr(cache_mod.shutil, "disk_usage", lambda _path: fake)
    assert any("Espacio libre" in p for p in run_preflight(config, [record]).problems)


def test_preflight_cache_limit_problem(root: Path, tmp_path: Path) -> None:
    config = config_for(tmp_path, root, cache_limit_gb=1e-6)
    report = run_preflight(config, [write_study(root)])
    assert not report.ok and "cache_limit_gb" in report.problems[0]


# ---------------------------------------------------------------------------------------------------------------
# CLI end-to-end
# ---------------------------------------------------------------------------------------------------------------


def test_cli_prepare_and_preflight_end_to_end(root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_study(root, "001")
    write_study(root, "002", label=no_gtv, brain_mask=False)
    write_study(root, "003", edit=_edit("gtv", lambda d: d * 2))  # elegible en el inventario, falla en prepare
    cfg = write_config(tmp_path, root)
    assert main(["inventory", "--config", str(cfg)]) == 0
    assert main(["preflight", "--config", str(cfg)]) == 0
    out = capsys.readouterr().out
    assert "no se usa el tamaño de los .nii.gz" in out and "Recursos suficientes" in out

    assert main(["prepare", "--config", str(cfg)]) == EXIT_STUDY_ERRORS
    captured = capsys.readouterr()
    assert "ERROR 003_t0: non_binary_label" in captured.out and "error non_binary_label: 1" in captured.out
    assert "revisión empty_label: 1" in captured.out and "revisión no_brain_mask: 1" in captured.out
    cache_dirs = list((tmp_path / "work" / "cache").iterdir())
    assert len(cache_dirs) == 1
    assert sorted(p.name for p in cache_dirs[0].glob("*.npz")) == ["001_t0.npz", "002_t0.npz"]

    assert main(["prepare", "--config", str(cfg)]) == EXIT_STUDY_ERRORS  # el estudio 003 vuelve a fallar
    assert "001_t0: en caché" in capsys.readouterr().out

    tiny = write_config(tmp_path, root, cache_limit_gb=1e-6)
    inventory = str(tmp_path / "work" / "inventory.jsonl")
    assert main(["preflight", "--config", str(tiny), "--inventory", inventory]) == EXIT_RESOURCES
    assert "PROBLEMA" in capsys.readouterr().out


def test_cli_prepare_resource_and_data_errors(root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = write_config(tmp_path, root, cache_limit_gb=1e-6)
    assert main(["prepare", "--config", str(cfg)]) == EXIT_DATA_ERROR  # sin inventario
    assert "No se pudo leer el inventario" in capsys.readouterr().err
    write_inventory([write_study(root)], tmp_path / "work" / "inventory.jsonl")
    assert main(["prepare", "--config", str(cfg)]) == EXIT_RESOURCES
    assert "Error de recursos" in capsys.readouterr().err


def test_cli_without_eligible_studies_is_data_error(
    root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = write_config(tmp_path, root)
    record = write_study(root)
    excluded = {**record, "eligible": False, "exclusions": [{"code": "missing_label", "message": "x"}]}
    write_inventory([excluded], tmp_path / "work" / "inventory.jsonl")
    for command in ("prepare", "preflight"):
        assert main([command, "--config", str(cfg)]) == EXIT_DATA_ERROR
        assert "no tiene estudios elegibles" in capsys.readouterr().err


def test_cli_startup_does_not_import_heavy_modules() -> None:
    code = (
        "import sys\n"
        "import cerberus_training.__main__\n"
        "heavy = sorted(m for m in sys.modules if m.split('.')[0] in {'torch', 'monai', 'nibabel', 'numpy', 'scipy'})\n"
        "assert not heavy, heavy\n"
    )
    result = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
