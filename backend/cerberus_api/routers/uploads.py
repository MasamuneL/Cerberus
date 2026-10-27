"""Subida de volúmenes al dataset (docs/PLAN_MVP.md §7 `/api/uploads`, tickets B7 y B8).

- `.nii` / `.nii.gz`: se escribe en streaming a `storage/tmp/<uuid>/`, se valida que sea un NIfTI 3D y se
  guarda como `.nii.gz` en la ruta de §6 (`Data/<patient>/<timepoint>/<int(patient)>_<timepoint>_<seq>.nii.gz`).
- `.zip` (DICOM): se escribe en streaming a `storage/tmp/<upload_id>.zip`, se crea el staging con el manifest
  `processing` y se encola `ingest_dicom` (202). El worker convierte las series a `storage/staging/<id>/series/`;
  luego `POST /uploads/{id}/confirm` las mueve a `Data/` con el mapeo serie → secuencia que eligió el usuario.

Los identificadores se validan con `cerberus_api.sequences` / `cerberus_api.staging` **antes** de construir
cualquier `Path` (AGENTS.md, regla 9). El nombre del archivo subido nunca se usa para construir rutas: solo su
extensión. El DICOM crudo nunca sale de `storage/tmp/` (AGENTS.md, regla 4).
"""

import inspect
import re
import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Annotated, Any, BinaryIO

import nibabel as nib
import numpy as np
from arq.connections import ArqRedis
from fastapi import APIRouter, File, Form, HTTPException, Request, Response, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse

from cerberus_api import catalog, staging
from cerberus_api.config import Settings
from cerberus_api.deps import SettingsDep, get_redis
from cerberus_api.nifti import load_nifti
from cerberus_api.schemas import ConfirmUpload, Study, UploadCreated, UploadManifest
from cerberus_api.sequences import validate_patient, validate_sequence, validate_timepoint

router = APIRouter(tags=["uploads"])

# Tamaño de bloque al copiar la subida a disco (1 MiB)
CHUNK_SIZE = 1024 * 1024

# Índice de serie en la URL / en el mapping de confirm (texto de dígitos, sin signo)
INDEX_RE = re.compile(r"^\d{1,5}$", re.ASCII)

UPLOAD_NOT_FOUND = "Subida no encontrada"


def _find_study(settings: Settings, patient: str, timepoint: str) -> Study | None:
    """El `Study` de (paciente, tiempo) según el catálogo, o `None` si no aparece."""
    for study in catalog.list_studies(settings.data_dir, settings.results_dir):
        if study.patient == patient and study.timepoint == timepoint:
            return study
    return None


def _study_or_500(settings: Settings, patient: str, timepoint: str) -> Study:
    study = _find_study(settings, patient, timepoint)
    if study is None:  # pragma: no cover - el archivo recién guardado siempre cumple la convención
        raise HTTPException(status_code=500, detail="El volumen se guardó pero no aparece en el catálogo")
    return study


def _target_path(settings: Settings, patient: str, timepoint: str, sequence: str) -> Path:
    """Ruta de §6 de un volumen; los tres IDs deben venir ya validados."""
    return settings.data_dir / patient / timepoint / f"{int(patient)}_{timepoint}_{sequence}.nii.gz"


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


def _save_nifti(
    settings: Settings, src: BinaryIO, patient: str, timepoint: str, sequence: str, compressed: bool
) -> Study:
    """Rama NIfTI (B7, bloqueante): guarda el volumen en `Data/` y devuelve el `Study` actualizado."""
    target = _target_path(settings, patient, timepoint, sequence)
    if target.exists():
        raise HTTPException(status_code=409, detail="Ese volumen ya existe en el estudio")

    tmp_dir = settings.tmp_dir / uuid.uuid4().hex
    try:
        tmp_dir.mkdir(parents=True)
        tmp_path = tmp_dir / ("upload.nii.gz" if compressed else "upload.nii")
        _stream_to_disk(src, tmp_path, settings.max_upload_mb * CHUNK_SIZE)
        # Otra subida pudo crear el archivo mientras se recibía esta
        if target.exists():
            raise HTTPException(status_code=409, detail="Ese volumen ya existe en el estudio")
        _store_nifti(tmp_path, target, compressed)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return _study_or_500(settings, patient, timepoint)


def _receive_zip(settings: Settings, src: BinaryIO, upload_id: str) -> Path:
    """Rama ZIP (bloqueante): escribe `storage/tmp/<upload_id>.zip` (413 / 422 si no es ZIP) y crea el staging."""
    settings.tmp_dir.mkdir(parents=True, exist_ok=True)
    zip_path = settings.tmp_dir / f"{staging.validate_upload_id(upload_id)}.zip"
    try:
        _stream_to_disk(src, zip_path, settings.max_upload_mb * CHUNK_SIZE)
        if not zipfile.is_zipfile(zip_path):
            raise HTTPException(status_code=422, detail="El archivo no es un ZIP válido")
        staging.write_manifest(
            settings.staging_dir, UploadManifest(upload_id=upload_id, status="processing", series=[])
        )
    except BaseException:
        zip_path.unlink(missing_ok=True)
        raise
    return zip_path


async def _resolve_redis(request: Request, settings: Settings) -> ArqRedis:
    """Pool arq solo para la rama `.zip`, para que subir un NIfTI no dependa de Redis.

    No se declara como `RedisDep` en el endpoint (eso exigiría Redis también para NIfTI); por eso se respeta a
    mano `app.dependency_overrides[get_redis]`, que es lo que usan los tests.
    """
    override = request.app.dependency_overrides.get(get_redis)
    if override is None:
        return await get_redis(settings)
    result: Any = override()
    return await result if inspect.isawaitable(result) else result


def _cleanup_upload(settings: Settings, upload_id: str, zip_path: Path) -> None:
    zip_path.unlink(missing_ok=True)
    shutil.rmtree(staging.upload_dir(settings.staging_dir, upload_id), ignore_errors=True)


@router.post(
    "/uploads",
    status_code=status.HTTP_201_CREATED,
    response_model=Study,
    responses={202: {"model": UploadCreated, "description": "ZIP DICOM recibido; ingesta encolada"}},
)
async def post_upload(
    request: Request,
    settings: SettingsDep,
    file: Annotated[UploadFile, File()],
    patient: Annotated[str, Form()],
    timepoint: Annotated[str, Form()],
    sequence: Annotated[str | None, Form()] = None,
) -> Study | JSONResponse:
    """Sube un volumen `.nii`/`.nii.gz` (`sequence` obligatoria) → 201 `Study`, o un `.zip` DICOM → 202
    `UploadCreated` con la ingesta encolada en el worker.

    422 si algún ID es inválido, el NIfTI no es 3D o el ZIP no es un ZIP; 409 si el volumen ya existe; 413 si
    excede `MAX_UPLOAD_MB`; 415 con otra extensión; 503 si Redis no responde (solo `.zip`). En un `.zip`,
    `patient`/`timepoint` se validan aquí pero se vuelven a pedir en `confirm`.
    """
    try:
        validate_patient(patient)
        validate_timepoint(timepoint)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    name = (file.filename or "").lower()
    if name.endswith(".zip"):
        upload_id = staging.new_upload_id()
        zip_path = await run_in_threadpool(_receive_zip, settings, file.file, upload_id)
        try:
            redis = await _resolve_redis(request, settings)
            job = await redis.enqueue_job("ingest_dicom", upload_id, str(zip_path))
        except BaseException:
            _cleanup_upload(settings, upload_id, zip_path)
            raise
        if job is None:  # pragma: no cover - arq solo devuelve None si el job_id ya existe
            _cleanup_upload(settings, upload_id, zip_path)
            raise HTTPException(status_code=500, detail="No se pudo encolar la ingesta DICOM")
        created = UploadCreated(upload_id=upload_id, job_id=job.job_id)
        return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=created.model_dump())

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

    return await run_in_threadpool(_save_nifti, settings, file.file, patient, timepoint, sequence, compressed)


def _manifest_or_404(settings: Settings, upload_id: str) -> UploadManifest:
    """Manifest de la subida; 404 si el id es inválido o no existe."""
    try:
        manifest = staging.read_manifest(settings.staging_dir, upload_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=UPLOAD_NOT_FOUND) from exc
    if manifest is None:
        raise HTTPException(status_code=404, detail=UPLOAD_NOT_FOUND)
    return manifest


@router.get("/uploads/{upload_id}")
def get_upload(upload_id: str, settings: SettingsDep) -> UploadManifest:
    """Estado de una ingesta DICOM (`UploadManifest`); 404 si no existe o el id es inválido."""
    return _manifest_or_404(settings, upload_id)


# Igual que en studies.py: `{index}` casa con `[^/]+` y el literal `.nii.gz` es obligatorio
@router.api_route(
    "/uploads/{upload_id}/series/{index}.nii.gz",
    methods=["GET", "HEAD"],
    response_class=FileResponse,
    responses={200: {"content": {"application/gzip": {}}}},
)
def get_upload_series(upload_id: str, index: str, settings: SettingsDep) -> FileResponse:
    """Vista previa de una serie convertida (`staging/<id>/series/<index>.nii.gz`); 404 si no existe."""
    if not INDEX_RE.fullmatch(index):
        raise HTTPException(status_code=404, detail="Serie no encontrada")
    try:
        path = staging.series_path(settings.staging_dir, upload_id, int(index))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Serie no encontrada") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Serie no encontrada")
    return FileResponse(path, media_type="application/gzip", filename=f"serie_{int(index)}.nii.gz")


def _confirm_sync(settings: Settings, upload_id: str, body: ConfirmUpload) -> Study:
    """Valida el mapping, comprueba **todos** los destinos y solo entonces mueve las series a `Data/`."""
    try:
        validate_patient(body.patient)
        validate_timepoint(body.timepoint)
        mapping: dict[int, str] = {}
        for key, seq in body.mapping.items():
            if not INDEX_RE.fullmatch(key):
                raise ValueError(f"Índice de serie inválido: {key!r}")
            mapping[int(key)] = validate_sequence(seq)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not mapping:
        raise HTTPException(status_code=422, detail="El mapping está vacío: asigna al menos una serie")

    manifest = _manifest_or_404(settings, upload_id)
    if manifest.status != "ready":
        raise HTTPException(status_code=409, detail="La subida aún no está lista o falló")

    seqs = list(mapping.values())
    if len(set(seqs)) != len(seqs):
        raise HTTPException(status_code=409, detail="Hay secuencias repetidas en el mapping")

    by_index = {s.index: s for s in manifest.series}
    moves: list[tuple[Path, Path]] = []
    for index, seq in sorted(mapping.items()):
        info = by_index.get(index)
        src = staging.series_path(settings.staging_dir, upload_id, index)
        if info is None or not info.converted or not src.is_file():
            raise HTTPException(status_code=422, detail=f"La serie {index} no existe o no se pudo convertir")
        moves.append((src, _target_path(settings, body.patient, body.timepoint, seq)))

    existing = [dest.name for _, dest in moves if dest.exists()]
    if existing:
        raise HTTPException(status_code=409, detail=f"Ya existen en el estudio: {', '.join(existing)}")

    for src, dest in moves:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(src, dest)
    shutil.rmtree(staging.upload_dir(settings.staging_dir, upload_id), ignore_errors=True)
    return _study_or_500(settings, body.patient, body.timepoint)


@router.post("/uploads/{upload_id}/confirm", status_code=status.HTTP_201_CREATED)
def confirm_upload(upload_id: str, body: ConfirmUpload, settings: SettingsDep) -> Study:
    """Mueve las series elegidas (`mapping`: índice → secuencia) a `Data/` y borra el staging → 201 `Study`.

    404 si la subida no existe; 409 si no está `ready`, hay secuencias repetidas o algún destino ya existe
    (en ese caso no se mueve nada); 422 si algún ID, índice o secuencia es inválido.
    """
    return _confirm_sync(settings, upload_id, body)


@router.delete("/uploads/{upload_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_upload(upload_id: str, settings: SettingsDep) -> Response:
    """Descarta una subida (borra su staging). Idempotente: 204 aunque ya no exista; 404 si el id es inválido."""
    try:
        path = staging.upload_dir(settings.staging_dir, upload_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=UPLOAD_NOT_FOUND) from exc
    shutil.rmtree(path, ignore_errors=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
