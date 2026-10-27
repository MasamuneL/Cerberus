"""Worker arq: jobs pesados fuera del proceso de la API (docs/PLAN_MVP.md §7 "Jobs de arq", ticket B6).

Arranque: `uv run arq cerberus_api.worker.WorkerSettings` (necesita `redis-server` corriendo).
El trabajo bloqueante (MONAI, dcm2niix) se corre con `asyncio.to_thread` para no congelar el event loop.
"""

import asyncio
from pathlib import Path
from typing import Any

from arq.connections import RedisSettings

from cerberus_api import catalog
from cerberus_api.config import get_settings
from cerberus_api.segmentation import run_segmentation
from cerberus_api.sequences import validate_patient, validate_timepoint


async def segment_study(ctx: dict[str, Any], patient: str, timepoint: str) -> dict[str, Any]:
    """Segmenta un estudio con MONAI y devuelve el `SegmentationResult` serializado a JSON.

    Escribe `storage/results/<patient>/<timepoint>/monai_seg.{nii.gz,json}`. Lanza `ValueError` si los IDs
    son inválidos, el estudio no existe o no tiene ninguna secuencia de canal del modelo.
    """
    settings = get_settings()
    validate_patient(patient)
    validate_timepoint(timepoint)
    study = catalog.get_study(settings.data_dir, settings.results_dir, patient, timepoint)
    if study is None:
        raise ValueError(f"Estudio no encontrado: {patient}/{timepoint}")

    # Todas las secuencias del estudio: run_segmentation usa también gtv (Dice) y brain_mask (skull-strip)
    study_files: dict[str, Path] = {}
    for seq in study.sequences:
        path = catalog.sequence_path(settings.data_dir, patient, timepoint, seq)
        if path is not None:
            study_files[seq] = path

    out_dir = settings.results_dir / patient / timepoint
    result = await asyncio.to_thread(run_segmentation, study_files, out_dir, settings.models_dir)
    return result.model_dump(mode="json")


async def ingest_dicom(ctx: dict[str, Any], upload_id: str, zip_path: str) -> dict[str, Any]:
    """Ingesta de un ZIP DICOM (ticket B8). Registrado ya en el worker; aún no implementado."""
    raise NotImplementedError("B8")


class WorkerSettings:
    """Configuración del worker que lee `arq` (atributos de clase)."""

    functions = [segment_study, ingest_dicom]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    job_timeout = 1800
    # Un solo job a la vez: un modelo en GPU/MPS
    max_jobs = 1
    keep_result = 3600
