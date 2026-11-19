"""Preflight de recursos antes de preparar o entrenar (docs/PLAN_PIPELINE_FINETUNING.md §5, ticket FT2).

Estima a partir del inventario (shapes y affines de cabecera), **nunca** del tamaño comprimido de los `.nii.gz`:

- Disco de caché: vóxeles del grid destino (el mismo `target_grid` que usa `prepare`, sin recorte, así que es una
  cota superior) × 18 bytes (4 canales float32 + GTV uint8 + soporte uint8) + margen por archivo.
- RAM pico por estudio en `prepare`: fuente más grande descomprimida (tipo nativo, cota de 8 bytes, + copia float32)
  + arrays del grid destino (pila de canales, temporal de remuestreo, copia normalizada, máscaras).
- RAM de datos por lote de entrenamiento: el estudio preparado más grande en memoria + parches del lote con sus
  copias de augmentation. No incluye activaciones ni gradientes de la red (dependen del modelo, FT3).

Compara con el espacio libre (`shutil.disk_usage`), `cache_limit_gb` y `min_free_disk_gb`. Todo es aproximado: no se
ha medido sobre la colección real. No escribe nada.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from cerberus_training.cache import (
    ENTRY_OVERHEAD_BYTES,
    GB,
    StudyCache,
    dir_size,
    existing_ancestor,
    free_bytes,
)
from cerberus_training.config import TrainConfig
from cerberus_training.inventory import sha256_file
from cerberus_training.transforms import target_grid

# Bytes por vóxel del grid destino en la caché: 4 canales float32 + GTV uint8 + soporte uint8.
CACHE_BYTES_PER_VOXEL = 4 * 4 + 1 + 1
# RAM de `prepare` por vóxel del grid destino: pila 4×float32, temporal de remuestreo float32, copia normalizada
# 4×float32 y GTV/máscara/soporte (uint8/bool): 16 + 4 + 16 + 3.
PREPARE_RAM_BYTES_PER_TARGET_VOXEL = 39
# RAM por vóxel de la fuente más grande: tipo nativo (cota de 8 bytes, float64) + copia float32.
SOURCE_NATIVE_BYTES_BOUND = 8
PREPARE_RAM_BYTES_PER_SOURCE_VOXEL = SOURCE_NATIVE_BYTES_BOUND + 4
# Copias de un parche durante el muestreo y las augmentations (recorte, intensidad, rotación).
PATCH_COPIES = 3


@dataclass
class PreflightReport:
    studies: int
    max_target_shape: tuple[int, int, int] | None
    cache_bytes: int
    max_study_cache_bytes: int
    prepare_ram_bytes: int
    train_ram_bytes: int
    free_bytes: int
    existing_cache_bytes: int
    current_key_bytes: int
    cache_limit_bytes: int
    min_free_bytes: int
    cache_enabled: bool
    cache_dir: Path | None
    weights: str
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def study_estimate(
    record: dict[str, Any], spacing_mm: float, reference: str = "T1c"
) -> tuple[int, tuple[int, int, int], int]:
    """(vóxeles del grid destino, shape destino, vóxeles de la fuente más grande) de un registro elegible."""
    ref = record["channels"][reference]
    shape, _affine = target_grid(tuple(ref["shape"]), np.asarray(ref["affine"], dtype=np.float64), spacing_mm)
    files = [*record["channels"].values(), record.get("label"), record.get("brain_mask")]
    source = max(int(np.prod(f["shape"])) for f in files if f is not None)
    return int(np.prod(shape)), shape, source


def weights_status(config: TrainConfig) -> str:
    """Estado informativo de los pesos (la verificación obligatoria es de `train`, FT3)."""
    path = config.weights.path
    if not path.is_file():
        return f"no encontrados en {path} (train los exigirá; nunca se descargan)"
    if sha256_file(path) != config.weights.sha256:
        return f"{path} existe pero su SHA-256 no coincide con weights.sha256 (train lo rechazará)"
    return f"{path} (SHA-256 verificado)"


def run_preflight(config: TrainConfig, records: list[dict[str, Any]]) -> PreflightReport:
    """Calcula el informe de recursos para los estudios elegibles del inventario (sin elegibles: `studies == 0`)."""
    pre = config.preprocess
    eligible = [r for r in records if r.get("eligible") is True]
    cache_bytes = 0
    max_entry = 0
    max_target = 0
    max_source = 0
    max_shape: tuple[int, int, int] | None = None
    for record in eligible:
        target, shape, source = study_estimate(record, pre.spacing_mm, config.channels.reference)
        entry = target * CACHE_BYTES_PER_VOXEL + ENTRY_OVERHEAD_BYTES
        cache_bytes += entry
        max_entry = max(max_entry, entry)
        max_source = max(max_source, source)
        if target > max_target:
            max_target, max_shape = target, shape
    prepare_ram = max_target * PREPARE_RAM_BYTES_PER_TARGET_VOXEL + max_source * PREPARE_RAM_BYTES_PER_SOURCE_VOXEL
    patch_voxels = int(np.prod(pre.patch_size))
    train_ram = max_entry + pre.batch_size * patch_voxels * CACHE_BYTES_PER_VOXEL * PATCH_COPIES

    cache = StudyCache.from_config(config)
    existing = dir_size(cache.cache_root)
    current = dir_size(cache.directory)
    free = free_bytes(config.paths.work_dir)
    limit = int(pre.cache_limit_gb * GB)
    min_free = int(pre.min_free_disk_gb * GB)
    problems: list[str] = []
    if pre.cache_enabled:
        stale = existing - current
        if stale + cache_bytes > limit:
            problems.append(
                f"La caché estimada ({_gb(cache_bytes)}) más las claves antiguas ({_gb(stale)}) supera "
                f"cache_limit_gb ({_gb(limit)})."
            )
        pending = max(0, cache_bytes - current)
        if free - pending < min_free:
            problems.append(
                f"Espacio libre insuficiente: {_gb(free)} libres, faltan por escribir hasta {_gb(pending)} y se "
                f"exige un margen de {_gb(min_free)} (min_free_disk_gb)."
            )
    return PreflightReport(
        studies=len(eligible),
        max_target_shape=max_shape,
        cache_bytes=cache_bytes,
        max_study_cache_bytes=max_entry,
        prepare_ram_bytes=prepare_ram,
        train_ram_bytes=train_ram,
        free_bytes=free,
        existing_cache_bytes=existing,
        current_key_bytes=current,
        cache_limit_bytes=limit,
        min_free_bytes=min_free,
        cache_enabled=pre.cache_enabled,
        cache_dir=cache.directory if pre.cache_enabled else None,
        weights=weights_status(config),
        problems=problems,
    )


def _gb(n: int) -> str:
    return f"{n / GB:.2f} GB"


def format_preflight(report: PreflightReport, work_dir: Path) -> str:
    """Informe legible en español."""
    shape = "x".join(str(s) for s in report.max_target_shape) if report.max_target_shape else "—"
    lines = [
        f"Estudios elegibles: {report.studies}; grid destino más grande: {shape} vóxeles",
        "Estimaciones a partir de shapes de cabecera (descomprimido; no se usa el tamaño de los .nii.gz):",
        f"  disco de caché (cota superior, sin recorte): {_gb(report.cache_bytes)} en total, "
        f"{_gb(report.max_study_cache_bytes)} el estudio más grande",
        f"  RAM pico de prepare por estudio (aprox.): {_gb(report.prepare_ram_bytes)}",
        f"  RAM de datos por lote de entrenamiento (aprox., sin activaciones de la red): {_gb(report.train_ram_bytes)}",
        f"Disco en {existing_ancestor(work_dir)}: {_gb(report.free_bytes)} libres; margen exigido "
        f"{_gb(report.min_free_bytes)}",
    ]
    if report.cache_enabled:
        lines.append(
            f"Caché: límite {_gb(report.cache_limit_bytes)}; ocupado {_gb(report.existing_cache_bytes)} "
            f"(clave actual {_gb(report.current_key_bytes)}) en {report.cache_dir}"
        )
    else:
        lines.append("Caché desactivada (preprocess.cache_enabled = false): prepare solo valida.")
    lines.append(f"Pesos: {report.weights}")
    if report.problems:
        lines.extend(f"PROBLEMA: {p}" for p in report.problems)
    else:
        lines.append("Recursos suficientes según la estimación.")
    return "\n".join(lines)
