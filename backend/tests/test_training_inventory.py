"""Tests del inventario FT1 y de la CLI `inventory`/`split` (docs/PLAN_PIPELINE_FINETUNING.md §4).

NIfTI sintéticos diminutos en `tmp_path`; sin red, sin GPU y sin depender de `Data/001`.
"""

import gzip
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np
import pytest

import cerberus_training.inventory as inventory_mod
from cerberus_training.__main__ import EXIT_CONFIG_ERROR, EXIT_DATA_ERROR, main
from cerberus_training.config import REPO_ROOT
from cerberus_training.inventory import (
    EXCLUSION_CODES,
    INVENTORY_SCHEMA_VERSION,
    InventoryError,
    build_inventory,
    ensure_outside_root,
    inspect_study,
    name_digest,
    read_inventory,
    resolve_under_root,
    sha256_file,
    study_dir,
    summarize,
    write_inventory,
)

FULL = ("t1gd", "t1eg", "t2tse", "flair", "gtv")
SHAPE = (6, 5, 4)
EXAMPLE = REPO_ROOT / "configs" / "training" / "gtv_binary.json"


def _rotated_affine(spacing: Sequence[float]) -> np.ndarray:
    """Affine con rotación de 30° en z, spacing anisótropo y origen desplazado."""
    c, s = np.cos(np.pi / 6), np.sin(np.pi / 6)
    rot = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
    affine = np.eye(4)
    affine[:3, :3] = rot @ np.diag(spacing)
    affine[:3, 3] = [-10.0, 5.0, 2.5]
    return affine


def _data(name: str, shape: Sequence[int]) -> np.ndarray:
    """Contenido distinto por archivo (semilla derivada del nombre) para que los hashes no coincidan."""
    seed = int(hashlib.sha256(name.encode()).hexdigest()[:8], 16)
    return np.random.default_rng(seed).integers(1, 100, size=tuple(shape)).astype(np.int16)


def save_nifti(path: Path, data: np.ndarray, affine: np.ndarray | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(data, np.eye(4) if affine is None else affine), str(path))
    return path


def save_raw_nifti(
    path: Path,
    shape: Sequence[int] = SHAPE,
    pixdim: Sequence[float] = (1.0, 1.0, 1.0),
    srow: np.ndarray | None = None,
) -> Path:
    """Escribe la cabecera a mano: `nib.save` no permite spacing no positivo ni affines singulares."""
    hdr = nib.Nifti1Header()
    hdr.set_data_dtype(np.uint8)
    hdr.set_data_shape(tuple(shape))
    pd = np.ones(8, dtype=np.float32)
    pd[1 : 1 + len(pixdim)] = pixdim
    hdr["pixdim"] = pd
    hdr["vox_offset"] = 352
    hdr["qform_code"] = 0
    hdr["sform_code"] = 1
    rows = np.eye(4)[:3] if srow is None else srow
    hdr["srow_x"], hdr["srow_y"], hdr["srow_z"] = rows[0], rows[1], rows[2]
    payload = hdr.binaryblock + b"\0" * 4 + np.ones(tuple(shape), dtype=np.uint8).tobytes(order="F")
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb") as handle:
        handle.write(payload)
    return path


def file_path(root: Path, patient: str, timepoint: str, seq: str) -> Path:
    return root / patient / timepoint / f"{int(patient)}_{timepoint}_{seq}.nii.gz"


def make_study(
    root: Path,
    patient: str,
    timepoint: str = "t0",
    seqs: Sequence[str] = FULL,
    affine: np.ndarray | None = None,
    empty_gtv: bool = False,
) -> Path:
    """Crea un estudio con la convención `<pac>/<t>/<int(pac)>_<t>_<seq>.nii.gz`."""
    for seq in seqs:
        data = _data(f"{patient}{timepoint}{seq}", SHAPE)
        if seq in ("gtv", "brain_mask"):
            data = np.zeros(SHAPE, dtype=np.uint8) if (seq == "gtv" and empty_gtv) else (data > 50).astype(np.uint8)
        save_nifti(file_path(root, patient, timepoint, seq), data, affine)
    return root / patient / timepoint


def codes(record: dict[str, Any]) -> list[str]:
    return [e["code"] for e in record["exclusions"]]


@pytest.fixture
def root(tmp_path: Path) -> Path:
    data_root = tmp_path / "cfb"
    data_root.mkdir()
    return data_root.resolve()


# --- estudio válido y selección de canales ---


def test_valid_study_record(root: Path) -> None:
    affine = _rotated_affine((0.9, 1.1, 3.0))
    make_study(root, "001", "t0", (*FULL, "t1tse", "brain_mask", "adc"), affine=affine)
    rec = inspect_study(root, "001", "t0")
    assert rec["eligible"] and rec["exclusions"] == []
    assert rec["schema_version"] == INVENTORY_SCHEMA_VERSION
    assert rec["study_id"] == "001_t0" and rec["patient"] == "001" and rec["stratum"] == "baseline"
    assert rec["selected_sequences"] == {"T1c": "t1gd", "T1": "t1eg", "T2": "t2tse", "FLAIR": "flair"}
    t1c = rec["channels"]["T1c"]
    assert t1c["path"] == "001/t0/1_t0_t1gd.nii.gz" and not Path(t1c["path"]).is_absolute()
    assert t1c["shape"] == list(SHAPE)
    assert t1c["spacing_mm"] == pytest.approx([0.9, 1.1, 3.0], abs=1e-5)
    assert np.allclose(t1c["affine"], affine, atol=1e-5)
    assert t1c["sha256"] == sha256_file(root / t1c["path"])
    assert rec["label"]["name"] == "gtv" and rec["label"]["nonzero_voxels"] > 0 and not rec["label"]["empty"]
    assert rec["brain_mask"]["path"] == "001/t0/1_t0_brain_mask.nii.gz"
    assert rec["review_flags"] == []
    assert str(root) not in json.dumps(rec)  # nada absoluto en el registro


def test_t1_falls_back_to_t1tse(root: Path) -> None:
    make_study(root, "002", "t1", ("t1gd", "t1tse", "t2tse", "flair", "gtv"))
    rec = inspect_study(root, "002", "t1")
    assert rec["eligible"] and rec["selected_sequences"]["T1"] == "t1tse" and rec["stratum"] == "follow_up"
    assert rec["brain_mask"] is None


def test_missing_channel_excludes(root: Path) -> None:
    make_study(root, "001", "t0", ("t1gd", "t1eg", "t2tse", "gtv"))
    rec = inspect_study(root, "001", "t0")
    assert not rec["eligible"] and codes(rec) == ["missing_channel"]
    assert rec["exclusions"][0]["channel"] == "FLAIR" and rec["channels"]["FLAIR"] is None


def test_t2star_never_replaces_t2(root: Path) -> None:
    make_study(root, "001", "t0", ("t1gd", "t1eg", "t2star", "flair", "gtv"))
    rec = inspect_study(root, "001", "t0")
    assert not rec["eligible"] and codes(rec) == ["missing_channel"]
    assert rec["exclusions"][0]["channel"] == "T2" and "T2*" in rec["exclusions"][0]["message"]
    assert rec["selected_sequences"]["T2"] is None


def test_missing_gtv_is_excluded_not_empty_mask(root: Path) -> None:
    make_study(root, "001", "t0", ("t1gd", "t1eg", "t2tse", "flair"))
    rec = inspect_study(root, "001", "t0")
    assert not rec["eligible"] and codes(rec) == ["missing_label"] and rec["label"] is None


def test_empty_gtv_kept_and_flagged(root: Path) -> None:
    make_study(root, "001", "t0", empty_gtv=True)
    rec = inspect_study(root, "001", "t0")
    assert rec["eligible"]
    assert rec["label"]["empty"] is True and rec["label"]["nonzero_voxels"] == 0
    assert [f["code"] for f in rec["review_flags"]] == ["empty_label"]


# --- validación de cabeceras ---


def test_4d_volume_excluded(root: Path) -> None:
    make_study(root, "001", "t0")
    save_nifti(file_path(root, "001", "t0", "flair"), np.ones((*SHAPE, 2), dtype=np.int16))
    rec = inspect_study(root, "001", "t0")
    assert codes(rec) == ["not_3d"] and rec["exclusions"][0]["channel"] == "FLAIR"


@pytest.mark.parametrize("bad", ["zero_column", "nan"])
def test_invalid_affine_excluded(root: Path, bad: str) -> None:
    make_study(root, "001", "t0")
    srow = np.eye(4)[:3].copy()
    srow[0, 0] = 0.0 if bad == "zero_column" else np.nan
    save_raw_nifti(file_path(root, "001", "t0", "t1gd"), srow=srow)
    rec = inspect_study(root, "001", "t0")
    assert codes(rec) == ["invalid_affine"]


@pytest.mark.parametrize("pixdim", [(0.0, 1.0, 1.0), (1.0, -2.0, 1.0), (1.0, 1.0, float("nan"))])
def test_non_positive_spacing_excluded(root: Path, pixdim: tuple[float, float, float]) -> None:
    # nib.load "repara" estos valores en silencio; el inventario debe verlos tal como están en el archivo.
    make_study(root, "001", "t0")
    save_raw_nifti(file_path(root, "001", "t0", "t2tse"), pixdim=pixdim)
    rec = inspect_study(root, "001", "t0")
    assert codes(rec) == ["invalid_spacing"]


def test_corrupt_file_excluded(root: Path) -> None:
    make_study(root, "001", "t0")
    file_path(root, "001", "t0", "t1eg").write_bytes(b"esto no es un NIfTI")
    rec = inspect_study(root, "001", "t0")
    assert codes(rec) == ["unreadable"] and rec["exclusions"][0]["channel"] == "T1"


def test_corrupt_gtv_voxels_excluded(root: Path) -> None:
    make_study(root, "001", "t0")
    gtv = file_path(root, "001", "t0", "gtv")
    gtv.write_bytes(gzip.compress(gzip.decompress(gtv.read_bytes())[:360]))  # cabecera íntegra, vóxeles truncados
    rec = inspect_study(root, "001", "t0")
    assert codes(rec) == ["unreadable"] and rec["label"] is None


def test_images_are_read_header_only(root: Path) -> None:
    """Una imagen con vóxeles truncados pasa el inventario: solo se lee la cabecera (el contenido es de FT2)."""
    make_study(root, "001", "t0")
    flair = file_path(root, "001", "t0", "flair")
    flair.write_bytes(gzip.compress(gzip.decompress(flair.read_bytes())[:360]))
    assert inspect_study(root, "001", "t0")["eligible"]


def test_invalid_brain_mask_is_review_only(root: Path) -> None:
    make_study(root, "001", "t0")
    file_path(root, "001", "t0", "brain_mask").write_bytes(b"roto")
    rec = inspect_study(root, "001", "t0")
    assert rec["eligible"] and rec["brain_mask"] is None
    assert [f["code"] for f in rec["review_flags"]] == ["invalid_brain_mask"]


def test_duplicate_within_study_flagged(root: Path) -> None:
    make_study(root, "001", "t0")
    file_path(root, "001", "t0", "t1eg").write_bytes(file_path(root, "001", "t0", "t1gd").read_bytes())
    rec = inspect_study(root, "001", "t0")
    assert rec["eligible"] and "duplicate_within_study" in [f["code"] for f in rec["review_flags"]]


# --- seguridad de rutas e identificadores ---


@pytest.mark.parametrize("parts", [("..", "x"), ("001", ".."), ("a/b",), ("",), (".",), ("x\0",)])
def test_resolve_under_root_rejects_traversal(root: Path, parts: tuple[str, ...]) -> None:
    with pytest.raises(ValueError):
        resolve_under_root(root, *parts)


@pytest.mark.parametrize(
    ("patient", "timepoint"), [("../001", "t0"), ("001", "../t0"), ("1", "t0"), ("001", "t100"), ("٠٠١", "t0")]
)
def test_invalid_identifiers_rejected_before_path(root: Path, patient: str, timepoint: str) -> None:
    with pytest.raises(ValueError):
        study_dir(root, patient, timepoint)
    with pytest.raises(ValueError):
        inspect_study(root, patient, timepoint)


def test_invalid_directory_names_are_not_studies(root: Path) -> None:
    make_study(root, "001", "t0")
    (root / "abc" / "t0").mkdir(parents=True)
    (root / "1" / "t0").mkdir(parents=True)
    (root / "001" / "x0").mkdir()
    (root / "001" / "t0" / "notas.txt").write_text("x")
    (root / "001" / "t0" / "2_t0_flair.nii.gz").write_bytes(b"de otro paciente")
    (root / "README.txt").write_text("x")
    (root / ".DS_Store").write_text("x")
    result = build_inventory(root)
    assert [r["study_id"] for r in result.records] == ["001_t0"]
    assert result.records[0]["unrecognized_files"] == 2 and result.records[0]["eligible"]
    rejected = sorted((r.level, r.patient or "", r.code, r.name_sha8) for r in result.rejected)
    assert rejected == sorted(
        [
            ("patient", "", "invalid_identifier", name_digest("1")),
            ("patient", "", "invalid_identifier", name_digest("abc")),
            ("timepoint", "001", "invalid_identifier", name_digest("x0")),
        ]
    )
    assert result.ignored_entries == 1


def test_symlinked_dir_escaping_root_rejected(root: Path, tmp_path: Path) -> None:
    make_study(root, "001", "t0")
    outside = tmp_path / "fuera"
    make_study(outside, "002", "t0")
    os.symlink(outside / "002", root / "002")
    os.symlink(outside / "002" / "t0", root / "001" / "t1")
    result = build_inventory(root)
    assert [r["study_id"] for r in result.records] == ["001_t0"]
    assert sorted(r.code for r in result.rejected) == ["path_outside_root", "path_outside_root"]


def test_symlinked_file_escaping_root_excluded(root: Path, tmp_path: Path) -> None:
    make_study(root, "001", "t0", ("t1gd", "t1eg", "t2tse", "gtv"))
    secret = save_nifti(tmp_path / "fuera.nii.gz", _data("fuera", SHAPE))
    os.symlink(secret, file_path(root, "001", "t0", "flair"))
    rec = inspect_study(root, "001", "t0")
    assert codes(rec) == ["path_outside_root"] and rec["channels"]["FLAIR"] is None


def test_symlink_inside_root_is_allowed(root: Path) -> None:
    make_study(root, "001", "t0", ("t1gd", "t1eg", "t2tse", "gtv"))
    store = save_nifti(root / "001" / "almacen" / "flair.nii.gz", _data("flair-interno", SHAPE))
    os.symlink(store, file_path(root, "001", "t0", "flair"))
    rec = inspect_study(root, "001", "t0")
    assert rec["eligible"] and rec["channels"]["FLAIR"]["path"] == "001/t0/1_t0_flair.nii.gz"


def test_missing_root_and_output_inside_root(root: Path) -> None:
    with pytest.raises(InventoryError):
        build_inventory(root / "no-existe")
    with pytest.raises(InventoryError):
        ensure_outside_root(root / "sub" / "inventory.jsonl", root)
    ensure_outside_root(root.parent / "work" / "inventory.jsonl", root)


# --- recorrido, escritura y resumen ---


def test_build_inventory_order_and_summary(root: Path) -> None:
    make_study(root, "002", "t0")
    make_study(root, "001", "t10")
    make_study(root, "001", "t2", affine=_rotated_affine((2.0, 2.0, 2.0)))
    make_study(root, "001", "t0", ("t1gd", "t1eg", "t2star", "flair", "gtv"))
    make_study(root, "003", "t0", ("t1gd", "t1eg", "t2tse", "flair"))
    result = build_inventory(root)
    assert [r["study_id"] for r in result.records] == ["001_t0", "001_t2", "001_t10", "002_t0", "003_t0"]
    summary = summarize(result)
    assert summary["studies"] == 5 and summary["eligible_studies"] == 3 and summary["eligible_patients"] == 2
    assert summary["exclusion_counts"] == {"missing_channel": 1, "missing_label": 1}
    assert set(summary["exclusion_counts"]) <= set(EXCLUSION_CODES)
    assert summary["strata"] == {"baseline": {"eligible": 1, "excluded": 2}, "follow_up": {"eligible": 2}}
    assert summary["per_patient"]["001"]["timepoints"]["t0"] == {"eligible": False, "exclusions": ["missing_channel"]}
    assert summary["duplicates"] == []


def test_cross_study_duplicates_in_summary(root: Path) -> None:
    make_study(root, "001", "t0")
    make_study(root, "002", "t0")
    src, dst = file_path(root, "001", "t0", "flair"), file_path(root, "002", "t0", "flair")
    dst.write_bytes(src.read_bytes())
    dups = summarize(build_inventory(root))["duplicates"]
    assert dups == [{"sha256": sha256_file(src), "studies": ["001_t0", "002_t0"]}]


def test_write_and_read_inventory_atomic(root: Path, tmp_path: Path) -> None:
    make_study(root, "001", "t0")
    records = build_inventory(root).records
    out = tmp_path / "work" / "inventory.jsonl"
    write_inventory(records, out)
    write_inventory(records, out)  # reescribir es atómico y no deja temporales
    assert [p.name for p in out.parent.iterdir()] == ["inventory.jsonl"]
    assert read_inventory(out) == records
    out.write_text(json.dumps({"schema_version": 99}) + "\n", encoding="utf-8")
    with pytest.raises(InventoryError):
        read_inventory(out)
    out.write_text("{no json\n", encoding="utf-8")
    with pytest.raises(InventoryError):
        read_inventory(out)


def test_inventory_does_not_modify_data_root(root: Path) -> None:
    make_study(root, "001", "t0")
    before = sorted((p.relative_to(root), p.stat().st_mtime_ns) for p in root.rglob("*"))
    build_inventory(root)
    assert sorted((p.relative_to(root), p.stat().st_mtime_ns) for p in root.rglob("*")) == before


# --- CLI de extremo a extremo ---


def _config(tmp_path: Path, data_root: Path, name: str = "config.json", **split: Any) -> Path:
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    data["paths"] = {"data_root": str(data_root), "work_dir": str(tmp_path / "work")}
    data["split"].update(split)
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _dataset(root: Path) -> None:
    """7 pacientes elegibles (impares con seguimiento t1) y uno solo con T2* (excluido)."""
    for i in range(1, 8):
        make_study(root, f"{i:03d}", "t0")
        if i % 2:
            make_study(root, f"{i:03d}", "t1")
    make_study(root, "008", "t0", ("t1gd", "t1eg", "t2star", "flair", "gtv"))


def test_cli_inventory_and_split_end_to_end(root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _dataset(root)
    cfg = _config(tmp_path, root)
    work = tmp_path / "work"
    assert main(["inventory", "--config", str(cfg)]) == 0
    out = capsys.readouterr().out
    assert "11 elegibles" in out and "missing_channel" in out and "008: t0 excluido" in out
    records = read_inventory(work / "inventory.jsonl")
    assert len(records) == 12 and sum(r["eligible"] for r in records) == 11

    assert main(["split", "--config", str(cfg)]) == 0
    assert "Split escrito" in capsys.readouterr().out
    splits = json.loads((work / "splits.json").read_text(encoding="utf-8"))
    patients = [p for name in ("train", "val", "test") for p in splits["partitions"][name]["patients"]]
    assert sorted(patients) == [f"{i:03d}" for i in range(1, 8)]
    assert all(splits["partitions"][name]["patients"] for name in ("train", "val", "test"))
    assert splits["pretraining_overlap"] == "unknown"

    first = (work / "splits.json").read_bytes()
    assert main(["split", "--config", str(cfg)]) == 0
    assert "reutilizado" in capsys.readouterr().out
    assert (work / "splits.json").read_bytes() == first

    # Mismo inventario, otra semilla: el split existente no se redistribuye.
    assert main(["split", "--config", str(_config(tmp_path, root, "seed7.json", seed=7))]) == EXIT_DATA_ERROR
    assert "no se redistribuye" in capsys.readouterr().err
    assert (work / "splits.json").read_bytes() == first


def test_cli_inventory_explicit_paths_and_summary(root: Path, tmp_path: Path) -> None:
    _dataset(root)
    out, summary = tmp_path / "o" / "inv.jsonl", tmp_path / "o" / "summary.json"
    argv = ["inventory", "--data-root", str(root), "--output", str(out), "--summary", str(summary)]
    assert main(argv) == 0
    assert json.loads(summary.read_text(encoding="utf-8"))["eligible_studies"] == 11
    assert len(read_inventory(out)) == 12


def test_cli_inventory_errors(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["inventory", "--data-root", str(root)]) == EXIT_CONFIG_ERROR
    inside = ["inventory", "--data-root", str(root), "--output", str(root / "inv.jsonl")]
    assert main(inside) == EXIT_DATA_ERROR
    assert "solo lectura" in capsys.readouterr().err
    assert not (root / "inv.jsonl").exists()
    missing = ["inventory", "--data-root", str(root / "nada"), "--output", str(root.parent / "x.jsonl")]
    assert main(missing) == EXIT_DATA_ERROR


def test_cli_split_too_few_patients(root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_study(root, "001", "t0")
    make_study(root, "002", "t0")
    cfg = _config(tmp_path, root)
    assert main(["inventory", "--config", str(cfg)]) == 0
    assert main(["split", "--config", str(cfg)]) == EXIT_DATA_ERROR
    assert "al menos 3" in capsys.readouterr().err
    assert not (tmp_path / "work" / "splits.json").exists()


# --- revisión FT1: privacidad, permisos, geometría, manifest manipulado, TOCTOU ---


def test_rejected_folder_names_never_emitted(root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    secret = "Juan_Perez_1980"
    make_study(root, "001", "t0")
    make_study(root, "002", "t0")
    make_study(root, "003", "t0")
    (root / secret / "t0").mkdir(parents=True)
    (root / "001" / secret).mkdir()
    out, summary = tmp_path / "o" / "inv.jsonl", tmp_path / "o" / "summary.json"
    argv = ["inventory", "--data-root", str(root), "--output", str(out), "--summary", str(summary)]
    assert main(argv) == 0
    captured = capsys.readouterr()
    for text in (captured.out, captured.err, out.read_text("utf-8"), summary.read_text("utf-8")):
        assert secret not in text and "Juan" not in text
    rejected = json.loads(summary.read_text("utf-8"))["rejected"]
    assert sorted(r["level"] for r in rejected) == ["patient", "timepoint"]
    assert {r["name_sha8"] for r in rejected} == {name_digest(secret)}
    assert name_digest(secret) in captured.out


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignora los permisos")
def test_unreadable_dirs_do_not_abort(root: Path) -> None:
    make_study(root, "001", "t0")
    make_study(root, "002", "t0")
    make_study(root, "003", "t0")
    study, patient = root / "002" / "t0", root / "003"
    study.chmod(0)
    patient.chmod(0)
    try:
        result = build_inventory(root)
    finally:
        study.chmod(0o755)
        patient.chmod(0o755)
    by_id = {r["study_id"]: r for r in result.records}
    assert by_id["001_t0"]["eligible"]
    assert codes(by_id["002_t0"]) == ["unreadable"] and not by_id["002_t0"]["eligible"]
    assert [(r.level, r.code, r.patient) for r in result.rejected] == [("patient", "unreadable", "003")]


def test_spacing_affine_mismatch_excluded(root: Path) -> None:
    make_study(root, "001", "t0")
    save_raw_nifti(file_path(root, "001", "t0", "flair"), pixdim=(2.0, 1.0, 1.0))  # affine identidad: normas 1
    rec = inspect_study(root, "001", "t0")
    assert codes(rec) == ["spacing_affine_mismatch"]


def test_4d_with_trailing_singleton_excluded(root: Path) -> None:
    make_study(root, "001", "t0")
    save_nifti(file_path(root, "001", "t0", "t1gd"), np.ones((*SHAPE, 1), dtype=np.int16))
    assert codes(inspect_study(root, "001", "t0")) == ["not_3d"]


def test_nifti2_is_unreadable(root: Path) -> None:
    make_study(root, "001", "t0")
    nib.save(nib.Nifti2Image(_data("n2", SHAPE), np.eye(4)), str(file_path(root, "001", "t0", "t2tse")))
    rec = inspect_study(root, "001", "t0")
    assert codes(rec) == ["unreadable"] and "NIfTI-2" in rec["exclusions"][0]["message"]


def test_directory_named_like_sequence_is_ignored(root: Path) -> None:
    make_study(root, "001", "t0", ("t1gd", "t1eg", "t2tse", "gtv"))
    file_path(root, "001", "t0", "flair").mkdir()
    rec = inspect_study(root, "001", "t0")
    assert codes(rec) == ["missing_channel"] and rec["unrecognized_files"] == 1
    assert "flair" not in rec["available_sequences"]


def test_file_changed_during_inventory_excluded(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_study(root, "001", "t0")
    real = inventory_mod.sha256_file

    def mutating_hash(path: Path) -> str:
        digest = real(path)
        if path.name.endswith("_flair.nii.gz"):
            with path.open("ab") as handle:
                handle.write(b"x")
        return digest

    monkeypatch.setattr(inventory_mod, "sha256_file", mutating_hash)
    rec = inspect_study(root, "001", "t0")
    assert codes(rec) == ["unreadable"] and "cambió" in rec["exclusions"][0]["message"]


def test_label_changed_before_voxel_read_excluded(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_study(root, "001", "t0")
    real = inventory_mod.load_nifti
    gtv = file_path(root, "001", "t0", "gtv").resolve()
    calls = {"n": 0}

    def touching_load(path: str | Path) -> Any:
        if Path(path) == gtv:
            calls["n"] += 1
            if calls["n"] == 2:  # segunda apertura (lectura de vóxeles): el archivo cambia entre medias
                os.utime(gtv, ns=(1, 1))
        return real(path)

    monkeypatch.setattr(inventory_mod, "load_nifti", touching_load)
    rec = inspect_study(root, "001", "t0")
    assert codes(rec) == ["unreadable"] and rec["label"] is None


def _tamper(path: Path, change: Any) -> None:
    rec = json.loads(path.read_text("utf-8").splitlines()[0])
    change(rec)
    path.write_text(json.dumps(rec) + "\n", encoding="utf-8")


@pytest.mark.parametrize(
    ("change", "match"),
    [
        (lambda r: r.update(patient="../x"), "identificador"),
        (lambda r: r.update(timepoint="t0/.."), "identificador"),
        (lambda r: r.update(study_id="002_t0"), "study_id"),
        (lambda r: r.pop("channels"), "faltan claves"),
        (lambda r: r["channels"]["T1c"].update(path="../../etc/passwd"), "relativa"),
        (lambda r: r["channels"]["T1c"].update(path="/abs/001/t0/x.nii.gz"), "relativa"),
        (lambda r: r["channels"]["T1c"].update(path="002/t0/2_t0_t1gd.nii.gz"), "no corresponde"),
        (lambda r: r["label"].update(sha256="zz"), "sha256"),
        (lambda r: r.update(eligible="yes"), "booleano"),
        (lambda r: r["channels"].update(T2=None), "elegible sin"),
        (lambda r: r.update(exclusions=[{"code": "x", "message": "y"}]), "incoherente"),
    ],
)
def test_read_inventory_rejects_tampering(root: Path, tmp_path: Path, change: Any, match: str) -> None:
    make_study(root, "001", "t0")
    out = tmp_path / "inv.jsonl"
    write_inventory(build_inventory(root).records, out)
    _tamper(out, change)
    with pytest.raises(InventoryError, match=match):
        read_inventory(out)


def test_read_inventory_rejects_duplicate_study(root: Path, tmp_path: Path) -> None:
    make_study(root, "001", "t0")
    out = tmp_path / "inv.jsonl"
    write_inventory(build_inventory(root).records * 2, out)
    with pytest.raises(InventoryError, match="repetido"):
        read_inventory(out)


def test_cli_output_collisions_and_split_inside_root(
    root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _dataset(root)
    same = tmp_path / "x.jsonl"
    argv = ["inventory", "--data-root", str(root), "--output", str(same), "--summary", str(same)]
    assert main(argv) == EXIT_DATA_ERROR and not same.exists()
    cfg = _config(tmp_path, root)
    assert main(["inventory", "--config", str(cfg)]) == 0
    inv = tmp_path / "work" / "inventory.jsonl"
    capsys.readouterr()
    assert main(["split", "--config", str(cfg), "--output", str(inv)]) == EXIT_DATA_ERROR
    assert "mismo archivo" in capsys.readouterr().err
    assert main(["split", "--config", str(cfg), "--output", str(root / "splits.json")]) == EXIT_DATA_ERROR
    assert "solo lectura" in capsys.readouterr().err and not (root / "splits.json").exists()


def test_split_and_manifest_import_without_nibabel_or_numpy() -> None:
    code = (
        "import sys\n"
        "import cerberus_training.manifest, cerberus_training.splits\n"
        "heavy = sorted(m for m in sys.modules if m.split('.')[0] in {'torch', 'monai', 'nibabel', 'numpy'})\n"
        "assert not heavy, heavy\n"
    )
    result = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
