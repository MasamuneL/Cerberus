"""Tests de segmentation.py con un predictor falso (sin red ni torch)."""

from pathlib import Path

import numpy as np
import pytest
from nibabel.processing import resample_from_to, resample_to_output

from cerberus_api.config import REPO_ROOT
from cerberus_api.nifti import load_nifti
from cerberus_api.schemas import SegmentationResult
from cerberus_api.segmentation import normalize_nonzero, run_segmentation
from conftest import MakeStudy


def _files(study_dir: Path) -> dict[str, Path]:
    return {p.name.split("_", 2)[2].removesuffix(".nii.gz"): p for p in study_dir.glob("*.nii.gz")}


def _cube_predictor(x: np.ndarray) -> np.ndarray:
    """WT = [2:12]^3, TC = [4:10]^3, ET = [5:8]^3 (1000, 216, 27 vóxeles)."""
    assert x.ndim == 4 and x.shape[0] == 4 and x.dtype == np.float32
    p = np.zeros((3, *x.shape[1:]), np.float32)
    p[1, 2:12, 2:12, 2:12] = 0.9
    p[0, 4:10, 4:10, 4:10] = 0.9
    p[2, 5:8, 5:8, 5:8] = 0.9
    return p


def test_labels_volumes_and_outputs(tmp_path: Path, make_study: MakeStudy) -> None:
    study = make_study(tmp_path / "Data", seqs=("t1gd", "flair", "gtv"))
    out = tmp_path / "out"
    res = run_segmentation(_files(study), out, tmp_path / "models", predictor=_cube_predictor)

    img = load_nifti(out / "monai_seg.nii.gz")
    assert np.allclose(img.header.get_zooms()[:3], (1, 1, 1))
    ref = resample_to_output(load_nifti(_files(study)["t1gd"]), voxel_sizes=(1, 1, 1), order=1)
    assert img.shape == ref.shape and abs(img.shape[0] - 20) <= 1
    lab = np.asarray(img.dataobj)
    assert lab.dtype == np.uint8
    counts = {v: int((lab == v).sum()) for v in (1, 2, 3)}
    assert counts == {1: 1000 - 216, 2: 216 - 27, 3: 27}
    assert (res.volumes_cm3.wt, res.volumes_cm3.tc, res.volumes_cm3.et) == (1.0, 0.22, 0.03)
    assert res.device == "custom"
    assert res.warnings == [
        "Sin brain_mask: no hay skull-strip",
        "Canal T1 faltante: se usaron ceros",
        "Canal T2 faltante: se usaron ceros",
    ]
    assert [c.sequence for c in res.channels] == ["t1gd", None, None, "flair"]
    assert res.dice_vs_gtv is not None and 0 < res.dice_vs_gtv.wt <= 1
    loaded = SegmentationResult.model_validate_json((out / "monai_seg.json").read_text())
    assert loaded == res


def test_brain_mask_clips_labels(tmp_path: Path, make_study: MakeStudy) -> None:
    study = make_study(tmp_path / "Data", seqs=("flair", "brain_mask"))

    def everywhere(x: np.ndarray) -> np.ndarray:
        return np.ones((3, *x.shape[1:]), np.float32)

    res = run_segmentation(_files(study), tmp_path / "o", tmp_path / "m", predictor=everywhere)
    lab = np.asarray(load_nifti(tmp_path / "o" / "monai_seg.nii.gz").dataobj)
    assert lab[0, 0, 0] == 0 and (lab == 3).any() and not (lab == 1).any()
    assert "Sin brain_mask: no hay skull-strip" not in res.warnings
    assert "Canal T1c faltante: se usaron ceros" in res.warnings
    assert res.dice_vs_gtv is None


def test_perfect_dice(tmp_path: Path, make_study: MakeStudy) -> None:
    files = make_study(tmp_path / "Data", seqs=("t1gd", "gtv"))
    files = _files(files)

    def from_gtv(x: np.ndarray) -> np.ndarray:
        ref = resample_to_output(load_nifti(files["t1gd"]), voxel_sizes=(1, 1, 1), order=1)
        g = np.asarray(resample_from_to(load_nifti(files["gtv"]), ref, order=0).dataobj) > 0.5
        return np.stack([g, g, g]).astype(np.float32)

    res = run_segmentation(files, tmp_path / "o", tmp_path / "m", predictor=from_gtv)
    assert res.dice_vs_gtv is not None
    assert (res.dice_vs_gtv.tc, res.dice_vs_gtv.wt) == (1.0, 1.0)


def test_no_channels_raises(tmp_path: Path, make_study: MakeStudy) -> None:
    study = make_study(tmp_path / "Data", seqs=("gtv", "brain_mask"))
    with pytest.raises(ValueError):
        run_segmentation(_files(study), tmp_path / "o", tmp_path / "m", predictor=_cube_predictor)


def test_normalize_nonzero() -> None:
    x = np.zeros((2, 4, 1, 1), np.float32)
    x[0, :2, 0, 0] = [1, 3]
    x[1, :2, 0, 0] = [5, 5]
    y = normalize_nonzero(x)
    assert np.allclose(y[0, :, 0, 0], [-1, 1, 0, 0])
    assert np.allclose(y[1, :, 0, 0], [0, 0, 0, 0])


@pytest.mark.slow
def test_real_model_on_data(tmp_path: Path) -> None:
    study = REPO_ROOT / "Data" / "001" / "t0"
    if not study.is_dir():
        pytest.skip("Sin Data/001/t0")
    pytest.importorskip("monai")
    res = run_segmentation(_files(study), tmp_path, REPO_ROOT / "models")
    assert res.volumes_cm3.wt > 0
    assert res.dice_vs_gtv is not None and res.dice_vs_gtv.tc > 0.3
