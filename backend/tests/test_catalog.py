"""Tests del catálogo de estudios (docs/PLAN_MVP.md §6, ticket B2)."""

from pathlib import Path

import pytest

from cerberus_api.catalog import get_study, list_studies, sequence_path
from conftest import MakeStudy


@pytest.fixture
def dirs(tmp_path: Path) -> tuple[Path, Path]:
    """(data_dir, results_dir) vacíos dentro de `tmp_path`."""
    data_dir = tmp_path / "Data"
    results_dir = tmp_path / "results"
    data_dir.mkdir()
    return data_dir, results_dir


def test_list_studies_sorted(dirs: tuple[Path, Path], make_study: MakeStudy) -> None:
    data_dir, results_dir = dirs
    # Se crean en desorden para comprobar el orden por (paciente, tiempo)
    make_study(data_dir, patient="002", timepoint="t0", seqs=("t1gd",))
    make_study(data_dir, patient="001", timepoint="t1", seqs=("flair",))
    make_study(data_dir, patient="001", timepoint="t0")

    studies = list_studies(data_dir, results_dir)

    assert [(s.patient, s.timepoint) for s in studies] == [("001", "t0"), ("001", "t1"), ("002", "t0")]
    first = studies[0]
    assert first.sequences == ["brain_mask", "flair", "gtv", "t1gd"]
    assert first.has_gtv and first.has_brain_mask
    assert not first.has_segmentation
    assert not studies[2].has_gtv and not studies[2].has_brain_mask


def test_list_studies_empty(dirs: tuple[Path, Path]) -> None:
    data_dir, results_dir = dirs
    assert list_studies(data_dir, results_dir) == []
    assert list_studies(data_dir / "missing", results_dir) == []


def test_junk_files_ignored(dirs: tuple[Path, Path], make_study: MakeStudy) -> None:
    data_dir, results_dir = dirs
    study_dir = make_study(data_dir, seqs=("t1gd",))
    # Basura que no cumple la convención: no debe aparecer ni romper el escaneo
    (study_dir / "notes.nii.gz").write_bytes(b"junk")  # no casa con la regex
    (study_dir / "1_t0_unknown.nii.gz").write_bytes(b"junk")  # secuencia desconocida
    (study_dir / "2_t0_flair.nii.gz").write_bytes(b"junk")  # prefijo distinto al paciente
    (study_dir / "1_t1_flair.nii.gz").write_bytes(b"junk")  # tiempo distinto a la carpeta
    (study_dir / "1_t0_adc.nii").write_bytes(b"junk")  # extensión distinta
    bad_patient = data_dir / "abc" / "t0"
    bad_patient.mkdir(parents=True)
    (bad_patient / "1_t0_flair.nii.gz").write_bytes(b"junk")  # carpeta de paciente inválida

    studies = list_studies(data_dir, results_dir)

    assert len(studies) == 1
    assert studies[0].sequences == ["t1gd"]
    detail = get_study(data_dir, results_dir, "001", "t0")
    assert detail is not None
    assert [v.sequence for v in detail.volumes] == ["t1gd"]


def test_get_study_volumes(dirs: tuple[Path, Path], make_study: MakeStudy) -> None:
    data_dir, results_dir = dirs
    make_study(data_dir)

    detail = get_study(data_dir, results_dir, "001", "t0")

    assert detail is not None
    assert detail.sequences == ["brain_mask", "flair", "gtv", "t1gd"]
    assert [v.sequence for v in detail.volumes] == detail.sequences
    for vol in detail.volumes:
        assert vol.shape == [40, 40, 20]
        assert vol.spacing_mm == [0.5, 0.5, 1.0]
        assert vol.label
    by_seq = {v.sequence: v for v in detail.volumes}
    assert by_seq["gtv"].dtype == "uint8"
    assert by_seq["t1gd"].dtype == "float32"


def test_get_study_missing_or_invalid(dirs: tuple[Path, Path], make_study: MakeStudy) -> None:
    data_dir, results_dir = dirs
    make_study(data_dir)
    assert get_study(data_dir, results_dir, "002", "t0") is None
    assert get_study(data_dir, results_dir, "001", "t5") is None
    assert get_study(data_dir, results_dir, "../x", "t0") is None
    assert get_study(data_dir, results_dir, "001", "../t0") is None


def test_has_segmentation(dirs: tuple[Path, Path], make_study: MakeStudy) -> None:
    data_dir, results_dir = dirs
    make_study(data_dir)
    seg = results_dir / "001" / "t0" / "monai_seg.nii.gz"
    seg.parent.mkdir(parents=True)
    seg.write_bytes(b"seg")

    assert list_studies(data_dir, results_dir)[0].has_segmentation
    detail = get_study(data_dir, results_dir, "001", "t0")
    assert detail is not None and detail.has_segmentation


def test_sequence_path(dirs: tuple[Path, Path], make_study: MakeStudy) -> None:
    data_dir, _ = dirs
    study_dir = make_study(data_dir)

    assert sequence_path(data_dir, "001", "t0", "flair") == study_dir / "1_t0_flair.nii.gz"
    assert sequence_path(data_dir, "001", "t0", "adc") is None  # válida pero no existe
    assert sequence_path(data_dir, "002", "t0", "flair") is None


@pytest.mark.parametrize(
    ("patient", "timepoint", "sequence"),
    [
        ("../x", "t0", "flair"),
        ("001", "../x", "flair"),
        ("001", "t0", "../x"),
        ("001", "t0", "../../etc/passwd"),
        ("/etc", "t0", "flair"),
    ],
)
def test_sequence_path_rejects_traversal(
    dirs: tuple[Path, Path], make_study: MakeStudy, patient: str, timepoint: str, sequence: str
) -> None:
    data_dir, _ = dirs
    make_study(data_dir)
    assert sequence_path(data_dir, patient, timepoint, sequence) is None
