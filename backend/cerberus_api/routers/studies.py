"""Endpoints de estudios (docs/PLAN_MVP.md §7): lectura (B4), segmentación MONAI (B6) y áreas de Brodmann (§13, B11).

Todo identificador que llega en la URL se valida con `cerberus_api.sequences` (directamente o a través de
`catalog`) **antes** de construir un `Path` (AGENTS.md, regla 9).
"""

import os
from email.utils import parsedate_to_datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import ValidationError
from redis.exceptions import RedisError

from cerberus_api import catalog
from cerberus_api.access import enqueue_owned_job
from cerberus_api.areas import AREAS_JSON
from cerberus_api.atlas import MOVING_PRIORITY
from cerberus_api.config import Settings
from cerberus_api.deps import REDIS_UNAVAILABLE, PrincipalDep, RedisDep, SettingsDep
from cerberus_api.schemas import (
    AreasResult,
    JobCreated,
    LongitudinalPoint,
    SegmentationResult,
    Study,
    StudyDetail,
    Volumetry,
)
from cerberus_api.segmentation import CHANNEL_MAP
from cerberus_api.sequences import SERVABLE_DERIVED, validate_file_name, validate_patient, validate_timepoint
from cerberus_api.volumetry import gtv_volumetry, longitudinal

router = APIRouter(tags=["studies"])


@router.get("/studies")
def get_studies(settings: SettingsDep) -> list[Study]:
    """Lista de estudios de `Data/`, ordenada por (paciente, tiempo)."""
    return catalog.list_studies(settings.data_dir, settings.results_dir)


@router.get("/studies/{patient}/{timepoint}")
def get_study_detail(patient: str, timepoint: str, settings: SettingsDep) -> StudyDetail:
    """Detalle de un estudio con el header de cada volumen; 404 si no existe o los IDs son inválidos."""
    study = catalog.get_study(settings.data_dir, settings.results_dir, patient, timepoint)
    if study is None:
        raise HTTPException(status_code=404, detail="Estudio no encontrado")
    return study


def _resolve_file(settings: Settings, patient: str, timepoint: str, name: str) -> Path | None:
    """Ruta en disco de `<name>.nii.gz` del estudio, o `None` si algún ID es inválido o no existe."""
    try:
        validate_file_name(name)
        validate_patient(patient)
        validate_timepoint(timepoint)
    except ValueError:
        return None
    if name in SERVABLE_DERIVED:
        path = settings.results_dir / patient / timepoint / f"{name}.nii.gz"
        return path if path.is_file() else None
    return catalog.sequence_path(settings.data_dir, patient, timepoint, name)


# Los NIfTI pesan ~75 MB: el navegador los guarda y revalida en cada uso (`no-cache` ≠ `no-store`) para no servir
# nunca una versión vieja; si no cambiaron, la API responde 304 sin cuerpo (§16, D2e).
FILE_CACHE_CONTROL = "no-cache"


def _etag_matches(if_none_match: str, etag: str) -> bool:
    """Comparación débil de `If-None-Match` (RFC 9110 §13.1.2): lista separada por comas o `*`."""
    if if_none_match.strip() == "*":
        return True
    target = etag.removeprefix("W/")
    return any(tag.strip().removeprefix("W/") == target for tag in if_none_match.split(","))


def _not_modified(request: Request, response: FileResponse, stat_result: os.stat_result) -> bool:
    """`True` si la petición condicional permite un 304. `If-Modified-Since` solo cuenta sin `If-None-Match`."""
    if_none_match = request.headers.get("if-none-match")
    if if_none_match is not None:
        return _etag_matches(if_none_match, response.headers["etag"])
    if_modified_since = request.headers.get("if-modified-since")
    if if_modified_since is None:
        return False
    try:
        since = parsedate_to_datetime(if_modified_since)
    except (TypeError, ValueError):
        return False
    # Last-Modified tiene resolución de segundos
    return int(stat_result.st_mtime) <= since.timestamp()


# Starlette compila `{name}` como `[^/]+` y escapa el literal `.nii.gz`: sin esa extensión la ruta no casa
# (404), y un `%2F` llega ya decodificado como `/`, así que tampoco casa. HEAD permite consultar el tamaño
# (Content-Length) sin descargar el volumen.
@router.api_route(
    "/studies/{patient}/{timepoint}/files/{name}.nii.gz",
    methods=["GET", "HEAD"],
    response_class=FileResponse,
    responses={200: {"content": {"application/gzip": {}}}, 304: {"description": "No modificado (ETag)"}},
)
def get_study_file(patient: str, timepoint: str, name: str, request: Request, settings: SettingsDep) -> Response:
    """Descarga un volumen NIfTI (`name` = secuencia o `monai_seg`) como `application/gzip`.

    Lleva `ETag` / `Last-Modified` (los de Starlette) y `Cache-Control: no-cache`; responde 304 si
    `If-None-Match` (o, sin él, `If-Modified-Since`) coincide. `Range` sigue funcionando (206).
    """
    path = _resolve_file(settings, patient, timepoint, name)
    if path is None:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    try:
        stat_result = path.stat()
    except OSError as exc:
        raise HTTPException(status_code=404, detail="Archivo no encontrado") from exc
    response = FileResponse(
        path,
        media_type="application/gzip",
        filename=f"{name}.nii.gz",
        stat_result=stat_result,
        headers={"Cache-Control": FILE_CACHE_CONTROL},
    )
    if _not_modified(request, response, stat_result):
        headers = {k: response.headers[k] for k in ("etag", "last-modified", "cache-control")}
        return Response(status_code=304, headers=headers)
    return response


@router.get("/studies/{patient}/{timepoint}/volumetry")
def get_volumetry(patient: str, timepoint: str, settings: SettingsDep) -> Volumetry:
    """Volumetría del GTV; 404 si falta `gtv` o `brain_mask`, 422 si el GTV está vacío."""
    gtv_path = catalog.sequence_path(settings.data_dir, patient, timepoint, "gtv")
    brain_path = catalog.sequence_path(settings.data_dir, patient, timepoint, "brain_mask")
    if gtv_path is None or brain_path is None:
        raise HTTPException(status_code=404, detail="El estudio no tiene GTV o máscara cerebral")
    try:
        return gtv_volumetry(gtv_path, brain_path)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="El GTV está vacío: no se puede calcular la volumetría") from exc


@router.get("/patients/{patient}/longitudinal")
def get_longitudinal(patient: str, settings: SettingsDep) -> list[LongitudinalPoint]:
    """Serie longitudinal del GTV (solo tiempos con gtv + brain_mask); 404 si el paciente es inválido."""
    try:
        validate_patient(patient)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Paciente no encontrado") from exc
    try:
        return longitudinal(settings.data_dir, patient)
    except ValueError as exc:
        # Algún tiempo tiene el GTV vacío
        raise HTTPException(status_code=422, detail="Algún GTV del paciente está vacío") from exc


# Secuencias que alimentan algún canal del modelo (t1gd, t1eg, t1tse, t2tse, t2star, flair)
_CHANNEL_SEQS = frozenset(seq for cands in CHANNEL_MAP.values() for seq in cands)


@router.post("/studies/{patient}/{timepoint}/segmentation", status_code=202)
async def start_segmentation(
    patient: str, timepoint: str, settings: SettingsDep, redis: RedisDep, principal: PrincipalDep
) -> JobCreated:
    """Encola `segment_study` en el worker; 404 si no existe el estudio, 422 sin secuencias de canal."""
    study = catalog.get_study(settings.data_dir, settings.results_dir, patient, timepoint)
    if study is None:
        raise HTTPException(status_code=404, detail="Estudio no encontrado")
    if not _CHANNEL_SEQS.intersection(study.sequences):
        raise HTTPException(
            status_code=422,
            detail="El estudio no tiene ninguna secuencia MRI para el modelo (t1gd/t1eg/t1tse/t2tse/t2star/flair)",
        )
    try:
        job = await enqueue_owned_job(redis, principal, "segment_study", patient, timepoint)
    except (RedisError, OSError) as exc:
        raise HTTPException(status_code=503, detail=REDIS_UNAVAILABLE) from exc
    if job is None:
        # arq devuelve None si ya existe un job con ese id (no pasa con ids aleatorios)
        raise HTTPException(status_code=409, detail="La segmentación ya está en cola")
    return JobCreated(job_id=job.job_id)


@router.get("/studies/{patient}/{timepoint}/segmentation")
def get_segmentation(patient: str, timepoint: str, settings: SettingsDep) -> SegmentationResult:
    """Resultado de la última segmentación (`monai_seg.json`); 404 si no hay o los IDs son inválidos."""
    try:
        validate_patient(patient)
        validate_timepoint(timepoint)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Segmentación no encontrada") from exc
    path = settings.results_dir / patient / timepoint / "monai_seg.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Segmentación no encontrada")
    try:
        return SegmentationResult.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as exc:
        raise HTTPException(status_code=500, detail="monai_seg.json corrupto") from exc


# --- §13 · Áreas de Brodmann (ticket B11) ---------------------------------------------------------------


@router.post("/studies/{patient}/{timepoint}/areas", status_code=202)
async def start_area_mapping(
    patient: str, timepoint: str, settings: SettingsDep, redis: RedisDep, principal: PrincipalDep
) -> JobCreated:
    """Encola `map_areas` en el worker; 404 si no existe el estudio, 422 sin GTV o sin secuencia T1."""
    study = catalog.get_study(settings.data_dir, settings.results_dir, patient, timepoint)
    if study is None:
        raise HTTPException(status_code=404, detail="Estudio no encontrado")
    if not study.has_gtv:
        raise HTTPException(status_code=422, detail="El estudio no tiene GTV: no se pueden reportar áreas afectadas")
    if not set(MOVING_PRIORITY).intersection(study.sequences):
        raise HTTPException(
            status_code=422, detail="El estudio no tiene secuencia T1 (t1gd/t1eg/t1tse) para registrar al MNI"
        )
    try:
        job = await enqueue_owned_job(redis, principal, "map_areas", patient, timepoint)
    except (RedisError, OSError) as exc:
        raise HTTPException(status_code=503, detail=REDIS_UNAVAILABLE) from exc
    if job is None:
        raise HTTPException(status_code=409, detail="El mapeo de áreas ya está en cola")
    return JobCreated(job_id=job.job_id)


@router.get("/studies/{patient}/{timepoint}/areas")
def get_areas(patient: str, timepoint: str, settings: SettingsDep) -> AreasResult:
    """Último reporte de áreas (`brodmann.json`); 404 si no hay o los IDs son inválidos, 500 si está corrupto."""
    try:
        validate_patient(patient)
        validate_timepoint(timepoint)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Reporte de áreas no encontrado") from exc
    path = settings.results_dir / patient / timepoint / AREAS_JSON
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Reporte de áreas no encontrado")
    try:
        return AreasResult.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as exc:
        raise HTTPException(status_code=500, detail="brodmann.json corrupto") from exc
