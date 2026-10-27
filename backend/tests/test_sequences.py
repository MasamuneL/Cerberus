"""Tests de validación de identificadores (docs/PLAN_MVP.md §6)."""

import pytest

from cerberus_api.sequences import (
    MRI_SEQS,
    SEQ_INFO,
    validate_file_name,
    validate_patient,
    validate_sequence,
    validate_timepoint,
)

# Intentos de path traversal y basura que nunca deben pasar
HOSTILE = ["", "../x", "../../etc/passwd", "/etc/passwd", "001/..", "t0\n", "001\n"]


def test_seq_info_matches_notebook() -> None:
    assert len(SEQ_INFO) == 11
    assert set(MRI_SEQS) <= set(SEQ_INFO)


@pytest.mark.parametrize("value", ["001", "042", "999"])
def test_patient_accepts(value: str) -> None:
    assert validate_patient(value) == value


@pytest.mark.parametrize("value", ["1", "01", "0001", "abc", "٠٠١", *HOSTILE])
def test_patient_rejects(value: str) -> None:
    with pytest.raises(ValueError):
        validate_patient(value)


@pytest.mark.parametrize("value", ["t0", "t1", "t10", "t99"])
def test_timepoint_accepts(value: str) -> None:
    assert validate_timepoint(value) == value


@pytest.mark.parametrize("value", ["t100", "tx", "T0", "t", "0", "t-1", *HOSTILE])
def test_timepoint_rejects(value: str) -> None:
    with pytest.raises(ValueError):
        validate_timepoint(value)


@pytest.mark.parametrize("value", sorted(SEQ_INFO))
def test_sequence_accepts(value: str) -> None:
    assert validate_sequence(value) == value


@pytest.mark.parametrize("value", ["T1GD", "t1", "monai_seg", "gtv.nii.gz", *HOSTILE])
def test_sequence_rejects(value: str) -> None:
    with pytest.raises(ValueError):
        validate_sequence(value)


@pytest.mark.parametrize("value", ["t1gd", "gtv", "brain_mask", "monai_seg"])
def test_file_name_accepts(value: str) -> None:
    assert validate_file_name(value) == value


@pytest.mark.parametrize("value", ["monai_seg.json", "MONAI_SEG", "manifest", *HOSTILE])
def test_file_name_rejects(value: str) -> None:
    with pytest.raises(ValueError):
        validate_file_name(value)
