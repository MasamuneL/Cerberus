from pathlib import Path

import cerberus_api
from cerberus_api.nifti import load_nifti
from conftest import GTV_SLICE, MakeStudy


def test_package_importable() -> None:
    assert cerberus_api.__version__


def test_make_study_follows_data_convention(tmp_path: Path, make_study: MakeStudy) -> None:
    study_dir = make_study(tmp_path, patient="002", timepoint="t1", seqs=("t1gd", "gtv"))
    assert sorted(p.name for p in study_dir.iterdir()) == ["2_t1_gtv.nii.gz", "2_t1_t1gd.nii.gz"]
    gtv = load_nifti(study_dir / "2_t1_gtv.nii.gz")
    assert gtv.header.get_zooms()[:3] == (0.5, 0.5, 1.0)
    assert int(gtv.get_fdata()[GTV_SLICE].sum()) == 1000
