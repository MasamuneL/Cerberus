"""Worker arq: jobs pesados fuera del proceso de la API (docs/PLAN_MVP.md §7 "Jobs de arq", ticket B6).

Arranque: `uv run arq cerberus_api.worker.WorkerSettings` (necesita `redis-server` corriendo).
El trabajo bloqueante (MONAI, dcm2niix) se corre con `asyncio.to_thread` para no congelar el event loop.
"""

import asyncio
import logging
import shutil
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from arq.connections import RedisSettings
from redis.exceptions import RedisError

from cerberus_api import catalog, runtime
from cerberus_api.areas import run_area_mapping
from cerberus_api.config import get_settings
from cerberus_api.dicom import convert_series, group_series, safe_extract, suggest_sequence
from cerberus_api.nifti import load_nifti
from cerberus_api.schemas import SeriesInfo, UploadManifest
from cerberus_api.segmentation import run_segmentation
from cerberus_api.sequences import validate_patient, validate_timepoint
from cerberus_api.staging import series_path, upload_dir, validate_upload_id, write_manifest

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


async def startup(ctx: dict[str, Any]) -> None:
    """Hook `on_startup` de arq: aplica los hilos **antes** de importar torch/ANTs y publica el `SystemInfo`.

    Ningún módulo importado por el worker carga torch ni ANTs al importarse (`segmentation` y `atlas` los
    importan dentro de las funciones), así que aquí OpenMP/MKL/ITK aún no se han inicializado.
    """
    threads, source = runtime.configure_threads()
    ctx["cerberus_threads"] = threads
    # detect_device importa torch (ya con OMP_NUM_THREADS fijado); en un hilo para no congelar el event loop
    info = await asyncio.to_thread(runtime.build_system_info, "worker")
    runtime.apply_threads(threads)  # torch ya está importado: fija también torch.set_num_threads
    logger.info(
        "Recursos: %s CPU, %s hilos (%s), %s GB, %s, %s",
        info.cpus_available,
        threads,
        source,
        info.memory_gb,
        info.device,
        info.platform,
    )
    try:
        await ctx["redis"].set(runtime.SYSTEM_INFO_KEY, info.model_dump_json())
    except (RedisError, OSError):
        logger.warning("No se pudo publicar el SystemInfo en Redis", exc_info=True)


async def shutdown(ctx: dict[str, Any]) -> None:
    """Hook `on_shutdown`: borra el `SystemInfo` para que la API no muestre los recursos de un worker apagado."""
    try:
        await ctx["redis"].delete(runtime.SYSTEM_INFO_KEY)
    except (RedisError, OSError):
        pass


async def _run_blocking(ctx: dict[str, Any], fn: Callable[..., _T], *args: Any) -> _T:
    """Corre `fn(*args)` en un hilo tras reaplicar los hilos ahí (OpenMP guarda el ajuste por hilo).

    También cubre el caso de que torch se importe por primera vez dentro de un job.
    """
    threads: int | None = ctx.get("cerberus_threads")  # None si el job corre sin el hook (tests)

    def _call() -> _T:
        if threads is not None:
            runtime.apply_threads(threads)
        return fn(*args)

    return await asyncio.to_thread(_call)


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
    result = await _run_blocking(ctx, run_segmentation, study_files, out_dir, settings.models_dir)
    return result.model_dump(mode="json")


async def map_areas(ctx: dict[str, Any], patient: str, timepoint: str) -> dict[str, Any]:
    """Mapea las áreas de Brodmann (§13, ticket B11) y devuelve el `AreasResult` serializado a JSON.

    Escribe `storage/results/<patient>/<timepoint>/brodmann.{nii.gz,json}` (+ `mni/` con las transformaciones).
    Lanza `ValueError` si los IDs son inválidos, el estudio no existe, no tiene GTV o no tiene T1.
    """
    settings = get_settings()
    validate_patient(patient)
    validate_timepoint(timepoint)
    study = catalog.get_study(settings.data_dir, settings.results_dir, patient, timepoint)
    if study is None:
        raise ValueError(f"Estudio no encontrado: {patient}/{timepoint}")

    study_files: dict[str, Path] = {}
    for seq in study.sequences:
        path = catalog.sequence_path(settings.data_dir, patient, timepoint, seq)
        if path is not None:
            study_files[seq] = path

    out_dir = settings.results_dir / patient / timepoint
    result = await _run_blocking(ctx, run_area_mapping, study_files, out_dir, settings.models_dir)
    return result.model_dump(mode="json")


# 1 MiB: los límites de la configuración van en MB
_MIB = 1024 * 1024


def _ingest_sync(zip_file: Path, work_dir: Path, staging_dir: Path, upload_id: str, max_bytes: int) -> list[SeriesInfo]:
    """Parte bloqueante de `ingest_dicom`: extrae, agrupa y convierte cada serie a `staging/<id>/series/<i>.nii.gz`.

    Una serie que dcm2niix no logra convertir (o que no queda en 3D) se reporta con `converted=False`.
    """
    extract_dir = work_dir / "extract"
    safe_extract(zip_file, extract_dir, max_bytes=max_bytes)
    groups = group_series(extract_dir)
    if not groups:
        raise ValueError("No se encontraron series DICOM en el ZIP")

    infos: list[SeriesInfo] = []
    for i, group in enumerate(groups):
        out = series_path(staging_dir, upload_id, i)
        converted = convert_series(group.files, work_dir / "convert" / str(i), out)
        shape: list[int] | None = None
        spacing: list[float] | None = None
        if converted:
            try:
                img = load_nifti(out)
                dims = [int(d) for d in img.shape]
                # Un 4D con la última dimensión 1 cuenta como 3D (igual que en la subida de NIfTI)
                if len(dims) == 4 and dims[3] == 1:
                    dims = dims[:3]
                if len(dims) != 3:
                    raise ValueError("La serie no es un volumen 3D")
                shape = dims
                spacing = [float(z) for z in img.header.get_zooms()[:3]]
            except Exception:
                converted = False
                out.unlink(missing_ok=True)
        infos.append(
            SeriesInfo(
                index=i,
                modality=group.modality,
                description=group.description,
                n_files=len(group.files),
                shape=shape,
                spacing_mm=spacing,
                converted=converted,
                suggested_sequence=suggest_sequence(
                    group.modality, group.description, group.protocol, group.has_contrast_agent
                ),
            )
        )
    return infos


async def ingest_dicom(ctx: dict[str, Any], upload_id: str, zip_path: str) -> dict[str, Any]:
    """Ingesta de un ZIP DICOM (ticket B8) y devuelve el `UploadManifest` final serializado a JSON.

    `safe_extract` → `group_series` → `convert_series` por serie → manifest `ready`. Si algo falla, el manifest
    queda `failed` con un mensaje en español (sin datos del DICOM). En el `finally` se borran **siempre** la
    carpeta temporal con el DICOM extraído y el ZIP (AGENTS.md, regla 4). El ZIP solo se acepta (y se borra) si
    está dentro de `storage/tmp/`.
    """
    settings = get_settings()
    validate_upload_id(upload_id)
    staging_dir = settings.staging_dir
    tmp_root = settings.tmp_dir.resolve()
    zip_file = Path(zip_path).resolve()
    work_dir = settings.tmp_dir / uuid.uuid4().hex
    zip_in_tmp = zip_file.is_relative_to(tmp_root)

    write_manifest(staging_dir, UploadManifest(upload_id=upload_id, status="processing", series=[]))
    try:
        if not zip_in_tmp:
            raise ValueError("El ZIP debe estar en storage/tmp")
        series = await asyncio.to_thread(
            _ingest_sync, zip_file, work_dir, staging_dir, upload_id, settings.max_zip_uncompressed_mb * _MIB
        )
        manifest = UploadManifest(upload_id=upload_id, status="ready", series=series)
    except ValueError as exc:
        manifest = UploadManifest(upload_id=upload_id, status="failed", error=str(exc), series=[])
    except Exception as exc:
        # Mensaje genérico: la excepción podría citar rutas o contenido del DICOM
        manifest = UploadManifest(
            upload_id=upload_id,
            status="failed",
            error=f"Error al procesar el ZIP DICOM ({type(exc).__name__})",
            series=[],
        )
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
        if zip_in_tmp:
            zip_file.unlink(missing_ok=True)

    # Si el usuario canceló (DELETE) mientras se procesaba, no se recrea el staging
    if upload_dir(staging_dir, upload_id).is_dir():
        write_manifest(staging_dir, manifest)
    return manifest.model_dump(mode="json")


class WorkerSettings:
    """Configuración del worker que lee `arq` (atributos de clase)."""

    functions = [segment_study, ingest_dicom, map_areas]
    # staticmethod: arq lee los hooks del atributo de clase y los llama con `ctx`
    on_startup = staticmethod(startup)
    on_shutdown = staticmethod(shutdown)
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    job_timeout = 1800
    # Un solo job a la vez: un modelo en GPU/MPS
    max_jobs = 1
    keep_result = 3600
