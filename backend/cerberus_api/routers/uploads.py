"""Subida de volúmenes al dataset (docs/PLAN_MVP.md §7 `POST /api/uploads`, ticket B7).

- `.nii` / `.nii.gz`: se escribe en streaming a `storage/tmp/<uuid>/`, se valida que sea un NIfTI 3D y se
  guarda como `.nii.gz` en la ruta de §6 (`Data/<patient>/<timepoint>/<int(patient)>_<timepoint>_<seq>.nii.gz`).
- `.zip` (DICOM): pendiente del ticket B8 (501 por ahora).

Los identificadores se validan con `cerberus_api.sequences` **antes** de construir cualquier `Path`
(AGENTS.md, regla 9). El nombre del archivo subido nunca se usa para construir rutas: solo su extensión.
"""

import shutil
import uuid
from pathlib import Path
from typing import Annotated, BinaryIO

import nibabel as nib
import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from cerberus_api import catalog
from cerberus_api.config import Settings
from cerberus_api.deps import SettingsDep
from cerberus_api.nifti import load_nifti
from cerberus_api.schemas import Study
from cerberus_api.sequences import validate_patient, validate_sequence, validate_timepoint

router = APIRouter(tags=["uploads"])

# Tamaño de bloque al copiar la subida a disco (1 MiB)
CHUNK_SIZE = 1024 * 1024


def _find_study(settings: Settings, patient: str, timepoint: str) -> Study | None:
    """El `Study` de (paciente, tiempo) según el catálogo, o `None` si no aparece."""
    for study in catalog.list_studies(settings.data_dir, settings.results_dir):
        if study.patient == patient and study.timepoint == timepoint:
            return study
    return None


def _stream_to_disk(src: BinaryIO, dest: Path, max_bytes: int) -> None:
    """Copia `src` a `dest` por bloques; lanza 413 en cuanto se superan `max_bytes`."""
    written = 0
    with dest.open("wb") as out:
        while chunk := src.read(CHUNK_SIZE):
            written += len(chunk)
            if written > max_bytes:
                raise HTTPException(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    detail=f"El archivo excede el tamaño máximo ({max_bytes // CHUNK_SIZE} MB)",
                )
            out.write(chunk)


def _store_nifti(tmp_path: Path, target: Path, compressed: bool) -> None:
    """Valida que `tmp_path` sea un NIfTI 3D y lo guarda en `target` como `.nii.gz`.

    Un 4D con la última dimensión 1 se aplana a 3D. Cualquier otro caso → 422.
    """
    try:
        img = load_nifti(tmp_path)
        shape = img.shape
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Archivo NIfTI inválido") from exc

    squeeze = len(shape) == 4 and shape[3] == 1
    if len(shape) != 3 and not squeeze:
        raise HTTPException(status_code=422, detail=f"El volumen debe ser 3D (forma recibida: {list(shape)})")

    target.parent.mkdir(parents=True, exist_ok=True)
    if compressed and not squeeze:
        # Ya es .nii.gz 3D: basta con moverlo
        shutil.move(tmp_path, target)
        return
    try:
        data = np.asanyarray(img.dataobj)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Archivo NIfTI inválido") from exc
    if squeeze:
        data = data[..., 0]
    header = img.header.copy()
    header.set_data_shape(data.shape)
    nib.save(nib.Nifti1Image(data, img.affine, header), target)


@router.post("/uploads", status_code=status.HTTP_201_CREATED)
def post_upload(
    settings: SettingsDep,
    file: Annotated[UploadFile, File()],
    patient: Annotated[str, Form()],
    timepoint: Annotated[str, Form()],
    sequence: Annotated[str | None, Form()] = None,
) -> Study:
    """Sube un volumen `.nii`/`.nii.gz` (`sequence` obligatoria) y devuelve el `Study` actualizado.

    422 si algún ID es inválido o el archivo no es un NIfTI 3D; 409 si ya existe; 413 si excede
    `MAX_UPLOAD_MB`; 415 con otra extensión; 501 para `.zip` (DICOM, ticket B8).
    """
    try:
        validate_patient(patient)
        validate_timepoint(timepoint)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    name = (file.filename or "").lower()
    if name.endswith(".zip"):
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Ingesta DICOM pendiente (B8)")
    if name.endswith(".nii.gz"):
        compressed = True
    elif name.endswith(".nii"):
        compressed = False
    else:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Formato no soportado: usa .nii, .nii.gz o .zip",
        )

    if sequence is None:
        raise HTTPException(status_code=422, detail="La secuencia es obligatoria para subir un NIfTI")
    try:
        validate_sequence(sequence)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    target = settings.data_dir / patient / timepoint / f"{int(patient)}_{timepoint}_{sequence}.nii.gz"
    if target.exists():
        raise HTTPException(status_code=409, detail="Ese volumen ya existe en el estudio")

    tmp_dir = settings.tmp_dir / uuid.uuid4().hex
    try:
        tmp_dir.mkdir(parents=True)
        tmp_path = tmp_dir / ("upload.nii.gz" if compressed else "upload.nii")
        _stream_to_disk(file.file, tmp_path, settings.max_upload_mb * CHUNK_SIZE)
        # Otra subida pudo crear el archivo mientras se recibía esta
        if target.exists():
            raise HTTPException(status_code=409, detail="Ese volumen ya existe en el estudio")
        _store_nifti(tmp_path, target, compressed)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    study = _find_study(settings, patient, timepoint)
    if study is None:  # pragma: no cover - el archivo recién guardado siempre cumple la convención
        raise HTTPException(status_code=500, detail="El volumen se guardó pero no aparece en el catálogo")
    return study
