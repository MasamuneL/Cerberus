"""Tests de volumetría, RANO volumétrico y serie longitudinal (ticket B3)."""

from pathlib import Path

import numpy as np
import pytest

from cerberus_api.volumetry import gtv_volumetry, longitudinal, rano_category
from conftest import BRAIN_SLICE, GTV_SLICE, MakeNifti, MakeStudy

SHAPE = (40, 40, 20)
ISO = (1.0, 1.0, 1.0)
BRAIN_VOXELS = 36 * 36 * 18  # caja BRAIN_SLICE


def _mask(*slices: tuple[slice, slice, slice]) -> np.ndarray:
    data = np.zeros(SHAPE, np.uint8)
    for s in slices:
        data[s] = 1
    return data


def _write_pair(
    make_nifti: MakeNifti, root: Path, gtv: np.ndarray, zooms: tuple[float, float, float] = ISO
) -> tuple[Path, Path]:
    gtv_path = make_nifti(root / "gtv.nii.gz", gtv, zooms)
    brain_path = make_nifti(root / "brain.nii.gz", _mask(BRAIN_SLICE), zooms)
    return gtv_path, brain_path


def test_cube_at_1mm(tmp_path: Path, make_nifti: MakeNifti) -> None:
    vol = gtv_volumetry(*_write_pair(make_nifti, tmp_path, _mask(GTV_SLICE)))
    assert vol.gtv_cm3 == 1.0
    assert vol.abc2_cm3 == 0.5
    assert vol.abc2_error_pct == -50.0
    assert (vol.lr_mm, vol.ap_mm, vol.si_mm) == (10.0, 10.0, 10.0)
    assert vol.components == 1
    assert vol.rano_measurable is True
    assert vol.spacing_ok is False  # (1, 1, 1) se marca como spacing sospechoso
    assert vol.brain_cm3 == round(BRAIN_VOXELS / 1000, 1)
    assert vol.fraction_pct == round(100 * 1000 / BRAIN_VOXELS, 2)


def test_cube_anisotropic(tmp_path: Path, make_nifti: MakeNifti) -> None:
    vol = gtv_volumetry(*_write_pair(make_nifti, tmp_path, _mask(GTV_SLICE), (0.5, 0.5, 1.0)))
    assert vol.gtv_cm3 == 0.25
    assert (vol.lr_mm, vol.ap_mm, vol.si_mm) == (5.0, 5.0, 10.0)
    assert vol.rano_measurable is False  # extensiones < 10 mm
    assert vol.spacing_ok is True
    # La fracción no depende del spacing
    assert vol.fraction_pct == round(100 * 1000 / BRAIN_VOXELS, 2)


def test_two_components(tmp_path: Path, make_nifti: MakeNifti) -> None:
    gtv = _mask((slice(5, 8), slice(5, 8), slice(5, 8)), (slice(20, 23), slice(20, 23), slice(10, 13)))
    vol = gtv_volumetry(*_write_pair(make_nifti, tmp_path, gtv))
    assert vol.components == 2
    assert vol.gtv_cm3 == round(54 / 1000, 2)


def test_small_extent_not_measurable(tmp_path: Path, make_nifti: MakeNifti) -> None:
    gtv = _mask((slice(10, 15), slice(10, 25), slice(5, 17)))
    vol = gtv_volumetry(*_write_pair(make_nifti, tmp_path, gtv))
    assert (vol.lr_mm, vol.ap_mm, vol.si_mm) == (5.0, 15.0, 12.0)
    assert vol.rano_measurable is False


def test_empty_gtv_raises(tmp_path: Path, make_nifti: MakeNifti) -> None:
    with pytest.raises(ValueError, match="GTV vacío"):
        gtv_volumetry(*_write_pair(make_nifti, tmp_path, _mask()))


@pytest.mark.parametrize(
    ("pct", "expected"),
    [(40, "PD"), (39.9, "SD"), (0, "SD"), (-39.9, "SD"), (-40, "MR"), (-64.9, "MR"), (-65, "PR"), (-90, "PR")],
)
def test_rano_category_edges(pct: float, expected: str) -> None:
    assert rano_category(pct) == expected


def _write_tp(make_nifti: MakeNifti, data_dir: Path, tp: str, gtv: np.ndarray) -> None:
    study = data_dir / "001" / tp
    make_nifti(study / f"1_{tp}_gtv.nii.gz", gtv, ISO)
    make_nifti(study / f"1_{tp}_brain_mask.nii.gz", _mask(BRAIN_SLICE), ISO)


def test_longitudinal(tmp_path: Path, make_nifti: MakeNifti) -> None:
    _write_tp(make_nifti, tmp_path, "t0", _mask(GTV_SLICE))  # 1.0 cm³
    _write_tp(make_nifti, tmp_path, "t1", _mask((slice(10, 25), slice(10, 20), slice(5, 15))))  # 1.5 cm³
    _write_tp(make_nifti, tmp_path, "t2", _mask((slice(10, 13), slice(10, 20), slice(5, 15))))  # 0.3 cm³
    _write_tp(make_nifti, tmp_path, "t10", _mask((slice(10, 16), slice(10, 20), slice(5, 15))))  # 0.6 cm³
    # Tiempo sin brain_mask y carpeta con nombre inválido: se ignoran
    make_nifti(tmp_path / "001" / "t3" / "1_t3_gtv.nii.gz", _mask(GTV_SLICE), ISO)
    (tmp_path / "001" / "notes").mkdir()

    points = longitudinal(tmp_path, "001")
    assert [(p.timepoint, p.gtv_cm3, p.change_vs_t0_pct, p.rano) for p in points] == [
        ("t0", 1.0, 0.0, None),
        ("t1", 1.5, 50.0, "PD"),
        ("t2", 0.3, -70.0, "PR"),
        ("t10", 0.6, -40.0, "MR"),
    ]


def test_longitudinal_with_make_study(tmp_path: Path, make_study: MakeStudy) -> None:
    make_study(tmp_path, timepoint="t0")
    make_study(tmp_path, timepoint="t1")
    points = longitudinal(tmp_path, "001")
    assert [(p.timepoint, p.gtv_cm3, p.change_vs_t0_pct, p.rano) for p in points] == [
        ("t0", 0.25, 0.0, None),
        ("t1", 0.25, 0.0, "SD"),
    ]


def test_longitudinal_without_t0(tmp_path: Path, make_study: MakeStudy) -> None:
    make_study(tmp_path, timepoint="t1")
    make_study(tmp_path, timepoint="t2")
    assert longitudinal(tmp_path, "001") == []


def test_longitudinal_missing_patient(tmp_path: Path) -> None:
    assert longitudinal(tmp_path, "999") == []


def test_longitudinal_invalid_patient(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        longitudinal(tmp_path, "../etc")
