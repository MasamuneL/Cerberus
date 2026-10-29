"""Catálogo de estudios: escaneo de `Data/` → `Study` (docs/PLAN_MVP.md §6, ticket B2).

Portado del inventario de `cerberus_eda.py:100-120`, con dos cambios:

- La regex acepta tiempos de 1-2 dígitos (`t\\d+`, no `t\\d`) y se aplica con `fullmatch`.
- Todo archivo que no cumpla la convención (`<int(paciente)>_<tiempo>_<secuencia>.nii.gz` dentro de
  `<paciente>/<tiempo>/`, con secuencia de `SEQ_INFO`) se ignora en silencio, sin fallar.

Solo se lee el header de cada NIfTI (`load_nifti(path).header`), nunca los vóxeles.
"""

import re
from pathlib import Path

from cerberus_api.nifti import load_nifti
from cerberus_api.schemas import Study, StudyDetail, VolumeInfo
from cerberus_api.sequences import (
    SEQ_INFO,
    validate_patient,
    validate_sequence,
    validate_timepoint,
)

# Convención de nombres del dataset: "1_t0_flair.nii.gz" (prefijo sin ceros a la izquierda)
FILE_RE = re.compile(r"(\d+)_(t\d+)_(.+)\.nii\.gz", re.ASCII)

# Segmentación MONAI ya calculada: storage/results/<patient>/<timepoint>/monai_seg.nii.gz
SEGMENTATION_FILE = "monai_seg.nii.gz"
AREAS_FILE = "brodmann.nii.gz"  # §13


def _parse_file(path: Path) -> str | None:
    """Devuelve la secuencia de `path` si cumple la convención de su carpeta; si no, `None`.

    Exige que el paciente y el tiempo de las carpetas sean válidos, que el prefijo numérico y el tiempo del
    nombre coincidan con ellas y que la secuencia sea una clave de `SEQ_INFO`.
    """
    m = FILE_RE.fullmatch(path.name)
    if not m:
        return None
    timepoint_dir = path.parent.name
    patient_dir = path.parent.parent.name
    try:
        validate_patient(patient_dir)
        validate_timepoint(timepoint_dir)
        validate_sequence(m.group(3))
    except ValueError:
        return None
    if int(m.group(1)) != int(patient_dir) or m.group(2) != timepoint_dir:
        return None
    return m.group(3)


def _scan(data_dir: Path, pattern: str) -> dict[tuple[str, str], dict[str, Path]]:
    """Agrupa los archivos válidos que casan con `pattern` en {(paciente, tiempo): {secuencia: ruta}}.

    Portado de `cerberus_eda.py:102-106` (glob + regex por archivo).
    """
    studies: dict[tuple[str, str], dict[str, Path]] = {}
    for f in sorted(data_dir.glob(pattern)):
        seq = _parse_file(f)
        if seq is None or not f.is_file():
            continue
        key = (f.parent.parent.name, f.parent.name)
        studies.setdefault(key, {})[seq] = f
    return studies


def _make_study(patient: str, timepoint: str, files: dict[str, Path], results_dir: Path) -> Study:
    """Construye un `Study` a partir de las secuencias encontradas en disco."""
    return Study(
        patient=patient,
        timepoint=timepoint,
        sequences=sorted(files),
        has_gtv="gtv" in files,
        has_brain_mask="brain_mask" in files,
        has_segmentation=(results_dir / patient / timepoint / SEGMENTATION_FILE).is_file(),
        has_areas=(results_dir / patient / timepoint / AREAS_FILE).is_file(),
    )


def list_studies(data_dir: Path, results_dir: Path) -> list[Study]:
    """Lista todos los estudios de `data_dir`, ordenados por (paciente, tiempo).

    Portado de `cerberus_eda.py:100-120` (inventario). `results_dir` se usa solo para `has_segmentation`.
    """
    scanned = _scan(data_dir, "*/t*/*.nii.gz")
    return [_make_study(p, t, files, results_dir) for (p, t), files in sorted(scanned.items())]


def get_study(data_dir: Path, results_dir: Path, patient: str, timepoint: str) -> StudyDetail | None:
    """Detalle de un estudio con el header de cada volumen; `None` si los IDs son inválidos o no existe.

    Lectura del header portada de `cerberus_eda.py:107-117` (shape, spacing redondeado a 3 decimales, dtype).
    """
    try:
        validate_patient(patient)
        validate_timepoint(timepoint)
    except ValueError:
        return None
    files = _scan(data_dir, f"{patient}/{timepoint}/*.nii.gz").get((patient, timepoint))
    if not files:
        return None

    volumes: list[VolumeInfo] = []
    for seq in sorted(files):
        hdr = load_nifti(files[seq]).header
        volumes.append(
            VolumeInfo(
                sequence=seq,
                label=SEQ_INFO[seq],
                shape=[int(s) for s in hdr.get_data_shape()],
                spacing_mm=[round(float(z), 3) for z in hdr.get_zooms()[:3]],
                dtype=str(hdr.get_data_dtype()),
            )
        )
    study = _make_study(patient, timepoint, files, results_dir)
    return StudyDetail(**study.model_dump(), volumes=volumes)


def sequence_path(data_dir: Path, patient: str, timepoint: str, sequence: str) -> Path | None:
    """Ruta del NIfTI de una secuencia, o `None` si algún ID es inválido o el archivo no existe.

    Valida los tres identificadores **antes** de construir el `Path` (AGENTS.md, regla 9).
    """
    try:
        validate_patient(patient)
        validate_timepoint(timepoint)
        validate_sequence(sequence)
    except ValueError:
        return None
    path = data_dir / patient / timepoint / f"{int(patient)}_{timepoint}_{sequence}.nii.gz"
    return path if path.is_file() else None
