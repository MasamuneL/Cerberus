"""Endpoints de lectura de estudios (docs/PLAN_MVP.md §7, ticket B4).

Todo identificador que llega en la URL se valida con `cerberus_api.sequences` (directamente o a través de
`catalog`) **antes** de construir un `Path` (AGENTS.md, regla 9).
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from cerberus_api import catalog
from cerberus_api.config import Settings
from cerberus_api.deps import SettingsDep
from cerberus_api.schemas import LongitudinalPoint, Study, StudyDetail, Volumetry
from cerberus_api.sequences import validate_file_name, validate_patient, validate_timepoint
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
    if name == "monai_seg":
        path = settings.results_dir / patient / timepoint / catalog.SEGMENTATION_FILE
        return path if path.is_file() else None
    return catalog.sequence_path(settings.data_dir, patient, timepoint, name)


# Starlette compila `{name}` como `[^/]+` y escapa el literal `.nii.gz`: sin esa extensión la ruta no casa
# (404), y un `%2F` llega ya decodificado como `/`, así que tampoco casa. HEAD permite consultar el tamaño
# (Content-Length) sin descargar el volumen.
@router.api_route(
    "/studies/{patient}/{timepoint}/files/{name}.nii.gz",
    methods=["GET", "HEAD"],
    response_class=FileResponse,
    responses={200: {"content": {"application/gzip": {}}}},
)
def get_study_file(patient: str, timepoint: str, name: str, settings: SettingsDep) -> FileResponse:
    """Descarga un volumen NIfTI (`name` = secuencia o `monai_seg`) como `application/gzip`."""
    path = _resolve_file(settings, patient, timepoint, name)
    if path is None:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return FileResponse(path, media_type="application/gzip", filename=f"{name}.nii.gz")


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
