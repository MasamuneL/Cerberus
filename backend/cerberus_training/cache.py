"""Caché persistente de volúmenes preparados (docs/PLAN_PIPELINE_FINETUNING.md §3 y §5, ticket FT2).

Estructura bajo `paths.work_dir`:

```text
prepare_report.json     # informe del último `prepare` (siempre, con o sin caché, también si se aborta)
cache/<preprocess_hash>/
  key.json              # componentes de la clave (para inspección)
  <study_id>.npz        # image float32 [4,X,Y,Z], label uint8, brain uint8, meta (JSON en texto)
```

`preprocess_hash` = 16 primeros hex del SHA-256 canónico de: la configuración que afecta a los volúmenes (spacing,
orientación, política de máscara, canales/referencia/etiqueta), `TRANSFORMS_VERSION`, `GEOMETRY_TOL_MM` y las
versiones de numpy, scipy y nibabel. Las fuentes no forman parte de la clave de carpeta: cada entrada guarda en `meta`
el SHA-256 de sus fuentes (`sources`) y solo es válida si coincide con el del inventario actual, así que un cambio de
datos invalida solo los estudios afectados. Cualquier cambio de la clave produce otra carpeta: la caché antigua nunca
se reutiliza (no se borra sola; el límite de tamaño cuenta toda la carpeta `cache/`). El parche, el muestreo y las
augmentations no forman parte de la clave porque se aplican al vuelo.

Integridad: `meta.arrays` guarda el SHA-256 de los bytes de cada array; `is_hit` y `load` los verifican (un byte
alterado invalida la entrada, que se reescribe). Cada estudio se escribe de forma atómica (temporal en la misma
carpeta, `fsync`, `os.replace`); un fallo a mitad no deja archivos parciales y los temporales huérfanos de una
ejecución interrumpida se borran al empezar a escribir. `.npz` sin compresión (`numpy.savez`) se lee con
`allow_pickle=False`. Antes de escribir se comprueban el límite de tamaño (`preprocess.cache_limit_gb`) y el espacio
libre (`preprocess.min_free_disk_gb`). Se supone un único `prepare` a la vez sobre el mismo `work_dir`.
"""

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib.metadata import version
from pathlib import Path
from typing import Any

import numpy as np

from cerberus_api.sequences import validate_patient, validate_timepoint
from cerberus_training.config import TrainConfig
from cerberus_training.manifest import atomic_write_text, fsync_dir
from cerberus_training.splits import canonical_hash
from cerberus_training.transforms import (
    GEOMETRY_TOL_MM,
    TRANSFORMS_VERSION,
    Geometry,
    PreparedStudy,
    StudyError,
    prepare_study,
    study_sources,
)

CACHE_SCHEMA_VERSION = 2
GB = 1024**3
# Margen por archivo (cabeceras zip/npy y metadatos) al estimar el tamaño en disco de una entrada.
ENTRY_OVERHEAD_BYTES = 64 * 1024
REPORT_NAME = "prepare_report.json"
ARRAY_NAMES: tuple[str, ...] = ("image", "label", "brain")
ARRAY_DTYPES: dict[str, type[np.generic]] = {"image": np.float32, "label": np.uint8, "brain": np.uint8}
# Bibliotecas cuyo comportamiento numérico determina los volúmenes preparados.
KEY_LIBRARIES: tuple[str, ...] = ("numpy", "scipy", "nibabel")


class CacheError(RuntimeError):
    """La caché no puede aceptar más datos (límite de tamaño o espacio libre) o está manipulada; detiene `prepare`."""


class CacheEntryError(ValueError):
    """Entrada de caché ausente, dañada o que no corresponde a la clave/fuentes esperadas."""


def library_versions() -> dict[str, str]:
    """Versiones instaladas de las bibliotecas que intervienen en el remuestreo y la normalización."""
    return {name: version(name) for name in KEY_LIBRARIES}


def cache_key_payload(config: TrainConfig) -> dict[str, Any]:
    """Componentes de la clave de caché: configuración de preprocesamiento, transformaciones y bibliotecas."""
    pre = config.preprocess
    return {
        "cache_schema_version": CACHE_SCHEMA_VERSION,
        "transforms_version": TRANSFORMS_VERSION,
        "geometry_tol_mm": GEOMETRY_TOL_MM,
        "libraries": library_versions(),
        "preprocess": {
            "spacing_mm": pre.spacing_mm,
            "orientation": pre.orientation,
            "brain_mask_policy": pre.brain_mask_policy,
        },
        "channels": {
            "order": list(config.channels.order),
            "reference": config.channels.reference,
            "label": config.channels.label,
        },
    }


def preprocess_hash(payload: dict[str, Any]) -> str:
    """Nombre de la carpeta de caché: 16 hex del hash canónico de la clave (el hash completo va en key.json)."""
    return canonical_hash(payload)[:16]


def array_sha256(array: np.ndarray) -> str:
    """SHA-256 de los bytes (C-contiguos) de un array, más su dtype y shape."""
    digest = hashlib.sha256(f"{array.dtype.str}{array.shape}".encode())
    digest.update(np.ascontiguousarray(array).tobytes())
    return digest.hexdigest()


def study_file_name(study_id: str) -> str:
    """Nombre de archivo de un estudio; el `study_id` se revalida antes de construir la ruta."""
    patient, sep, timepoint = study_id.partition("_")
    if not sep:
        raise ValueError(f"study_id inválido: {study_id!r}")
    validate_patient(patient)
    validate_timepoint(timepoint)
    return f"{patient}_{timepoint}.npz"


def dir_size(path: Path) -> int:
    """Bytes de todos los archivos bajo `path` (0 si no existe)."""
    total = 0
    if not path.exists():
        return 0
    for dirpath, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(dirpath) / name).stat().st_size
            except OSError:
                continue
    return total


def entry_bytes(study: PreparedStudy) -> int:
    """Tamaño estimado en disco de un estudio (npz sin comprimir ≈ suma de arrays + margen)."""
    return int(study.image.nbytes + study.label.nbytes + study.brain.nbytes) + ENTRY_OVERHEAD_BYTES


def existing_ancestor(path: Path) -> Path:
    """`path` o su primer ancestro existente (para consultar el disco antes de crear carpetas)."""
    while not path.exists() and path != path.parent:
        path = path.parent
    return path


def free_bytes(path: Path) -> int:
    """Espacio libre en el sistema de archivos de `path` (o de su ancestro existente)."""
    return int(shutil.disk_usage(existing_ancestor(path)).free)


@dataclass
class StudyCache:
    """Caché de una clave concreta. `limit_bytes` cuenta toda la carpeta `cache/` (claves antiguas incluidas)."""

    work_dir: Path
    key_payload: dict[str, Any]
    limit_bytes: int
    min_free_bytes: int
    _total: int | None = field(default=None, init=False, repr=False)
    _ready: bool = field(default=False, init=False, repr=False)

    @property
    def cache_root(self) -> Path:
        return self.work_dir / "cache"

    @property
    def key(self) -> str:
        return preprocess_hash(self.key_payload)

    @property
    def directory(self) -> Path:
        return self.cache_root / self.key

    @classmethod
    def from_config(cls, config: TrainConfig) -> "StudyCache":
        pre = config.preprocess
        return cls(
            work_dir=config.paths.work_dir,
            key_payload=cache_key_payload(config),
            limit_bytes=int(pre.cache_limit_gb * GB),
            min_free_bytes=int(pre.min_free_disk_gb * GB),
        )

    def path(self, study_id: str) -> Path:
        return self.directory / study_file_name(study_id)

    def _ensure_dir(self) -> None:
        """Crea la carpeta y `key.json` y borra temporales huérfanos (una vez por instancia).

        Si `key.json` existe y difiere (colisión o manipulación), es un error.
        """
        if self._ready:
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        for orphan in self.directory.glob(".*.tmp"):
            orphan.unlink(missing_ok=True)
        self._total = None  # recalcular tras borrar huérfanos
        key_file = self.directory / "key.json"
        text = json.dumps({"key": canonical_hash(self.key_payload), **self.key_payload}, indent=2, sort_keys=True)
        if key_file.exists():
            if key_file.read_text(encoding="utf-8") != text + "\n":
                raise CacheError(f"{key_file} no corresponde a esta clave de caché; revise o borre {self.directory}")
        else:
            atomic_write_text(key_file, text + "\n")
        self._ready = True

    def total_bytes(self) -> int:
        if self._total is None:
            self._total = dir_size(self.cache_root)
        return self._total

    def load(self, study_id: str, expected_sources: dict[str, str] | None = None) -> PreparedStudy:
        """Lee y verifica una entrada. Lanza `CacheEntryError` si falta, está dañada o no coincide; nunca `None`."""
        path = self.path(study_id)
        if not path.is_file():
            raise CacheEntryError(f"{study_id}: no hay entrada en la caché {self.directory}")
        try:
            with np.load(path, allow_pickle=False) as npz:
                meta = json.loads(str(npz["meta"].item()))
                if not isinstance(meta, dict):
                    raise ValueError("meta no es un objeto JSON")
                arrays = {name: np.asarray(npz[name]) for name in ARRAY_NAMES}
            geometry = Geometry.from_json(meta["geometry"])
        except Exception as exc:  # zip truncado, CRC, clave ausente, JSON inválido…
            raise CacheEntryError(f"{study_id}: entrada de caché ilegible ({type(exc).__name__}: {exc})") from exc
        if meta.get("preprocess_key") != self.key or meta.get("study_id") != study_id:
            raise CacheEntryError(f"{study_id}: la entrada no corresponde a la clave {self.key}")
        if expected_sources is not None and meta.get("sources") != expected_sources:
            raise CacheEntryError(f"{study_id}: las fuentes cambiaron desde que se preparó la entrada")
        hashes = meta.get("arrays")
        for name, array in arrays.items():
            if array.dtype != ARRAY_DTYPES[name] or not isinstance(hashes, dict):
                raise CacheEntryError(f"{study_id}: array {name} con tipo inesperado o sin hash")
            if hashes.get(name) != array_sha256(array):
                raise CacheEntryError(f"{study_id}: el SHA-256 del array {name} no coincide (entrada alterada)")
        shape = geometry.prepared_shape
        if arrays["image"].shape[1:] != shape or arrays["label"].shape != shape or arrays["brain"].shape != shape:
            raise CacheEntryError(f"{study_id}: shapes incoherentes con la geometría")
        return PreparedStudy(
            study_id=study_id,
            image=arrays["image"],
            label=arrays["label"],
            brain=arrays["brain"],
            geometry=geometry,
            brain_mask_source=str(meta["brain_mask_source"]),
            label_empty=bool(meta["label_empty"]),
            sources=dict(meta["sources"]),
            label_lost_voxels=int(meta.get("label_lost_voxels", 0)),
            review_flags=list(meta["review_flags"]),
        )

    def load_geometry(self, study_id: str, expected_sources: dict[str, str] | None = None) -> Geometry:
        """Solo la geometría de una entrada (miembro `meta` del `.npz`), sin leer ni verificar los arrays.

        Comprueba clave, `study_id` y fuentes. La usa el baseline de FT4, que no necesita el volumen preparado.
        """
        path = self.path(study_id)
        if not path.is_file():
            raise CacheEntryError(f"{study_id}: no hay entrada en la caché {self.directory}")
        try:
            with np.load(path, allow_pickle=False) as npz:
                meta = json.loads(str(npz["meta"].item()))
            if not isinstance(meta, dict):
                raise ValueError("meta no es un objeto JSON")
            geometry = Geometry.from_json(meta["geometry"])
        except Exception as exc:  # zip truncado, clave ausente, JSON inválido…
            raise CacheEntryError(f"{study_id}: entrada de caché ilegible ({type(exc).__name__}: {exc})") from exc
        if meta.get("preprocess_key") != self.key or meta.get("study_id") != study_id:
            raise CacheEntryError(f"{study_id}: la entrada no corresponde a la clave {self.key}")
        if expected_sources is not None and meta.get("sources") != expected_sources:
            raise CacheEntryError(f"{study_id}: las fuentes cambiaron desde que se preparó la entrada")
        return geometry

    def is_hit(self, study_id: str, expected_sources: dict[str, str]) -> PreparedStudy | None:
        """Entrada válida (clave, fuentes y SHA-256 de cada array verificados) o `None` si hay que (re)prepararla."""
        try:
            return self.load(study_id, expected_sources)
        except CacheEntryError:
            return None

    def check_room(self, needed: int, replacing: int = 0) -> None:
        """`CacheError` si escribir `needed` bytes supera el límite o deja menos espacio libre del mínimo."""
        total = self.total_bytes() - replacing
        if total + needed > self.limit_bytes:
            raise CacheError(
                f"La caché superaría su límite: {(total + needed) / GB:.2f} GB > {self.limit_bytes / GB:.2f} GB "
                f"(preprocess.cache_limit_gb, cuenta todo {self.cache_root}). Borre carpetas de claves antiguas "
                "o suba el límite."
            )
        free = free_bytes(self.cache_root)
        if free - needed < self.min_free_bytes:
            raise CacheError(
                f"Espacio libre insuficiente en {existing_ancestor(self.cache_root)}: quedan {free / GB:.2f} GB y "
                f"hacen falta {needed / GB:.2f} GB más {self.min_free_bytes / GB:.2f} GB de margen "
                "(preprocess.min_free_disk_gb)."
            )

    def store(self, study: PreparedStudy) -> Path:
        """Escribe el estudio de forma atómica tras comprobar límite y espacio libre. Devuelve la ruta final."""
        final = self.path(study.study_id)
        arrays = {name: np.ascontiguousarray(getattr(study, name), dtype=ARRAY_DTYPES[name]) for name in ARRAY_NAMES}
        if self.directory.exists():
            self._ensure_dir()  # borra huérfanos antes de medir
        needed = entry_bytes(study)
        replacing = final.stat().st_size if final.is_file() else 0
        self.check_room(needed, replacing)
        self._ensure_dir()
        meta = {
            **study.meta(),
            "preprocess_key": self.key,
            "arrays": {name: array_sha256(array) for name, array in arrays.items()},
        }
        fd, tmp = tempfile.mkstemp(dir=self.directory, prefix=f".{final.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as handle:
                meta_text = np.array(json.dumps(meta, sort_keys=True, ensure_ascii=False))
                np.savez(handle, image=arrays["image"], label=arrays["label"], brain=arrays["brain"], meta=meta_text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, final)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        fsync_dir(self.directory)
        self._total = self.total_bytes() - replacing + final.stat().st_size
        return final


@dataclass
class PrepareReport:
    """Resultado de `prepare`: estado por estudio (`prepared`, `cached`, `validated`, `error` o `aborted`)."""

    cache_key: str | None
    studies: list[dict[str, Any]] = field(default_factory=list)
    skipped_ineligible: int = 0
    aborted: str | None = None  # mensaje si un error de recursos/E/S detuvo el proceso

    @property
    def errors(self) -> list[dict[str, Any]]:
        return [s for s in self.studies if s["status"] == "error"]

    def review_totals(self) -> dict[str, dict[str, int]]:
        """Por código de revisión: estudios afectados y vóxeles de GTV implicados (si aplica)."""
        totals: dict[str, dict[str, int]] = {}
        for s in self.studies:
            for flag in s.get("review_flags", []):
                entry = totals.setdefault(flag["code"], {"studies": 0, "voxels": 0})
                entry["studies"] += 1
                entry["voxels"] += int(flag.get("voxels", 0))
        return dict(sorted(totals.items()))

    def to_json(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for s in self.studies:
            counts[s["status"]] = counts.get(s["status"], 0) + 1
        return {
            "cache_schema_version": CACHE_SCHEMA_VERSION,
            "transforms_version": TRANSFORMS_VERSION,
            "cache_key": self.cache_key,
            "completed": self.aborted is None,
            "aborted": self.aborted,
            "counts": dict(sorted(counts.items())),
            "review_totals": self.review_totals(),
            "skipped_ineligible": self.skipped_ineligible,
            "studies": self.studies,
        }


def _no_log(_message: str) -> None:
    return None


def _entry(study: PreparedStudy, status: str) -> dict[str, Any]:
    return {
        "study_id": study.study_id,
        "status": status,
        "prepared_shape": list(study.geometry.prepared_shape),
        "brain_mask_source": study.brain_mask_source,
        "label_empty": study.label_empty,
        "label_lost_voxels": study.label_lost_voxels,
        "review_flags": study.review_flags,
    }


def prepare_all(
    config: TrainConfig, records: list[dict[str, Any]], log: Callable[[str], None] = _no_log
) -> PrepareReport:
    """Prepara los estudios elegibles de uno en uno; un error de estudio se registra y se continúa con el siguiente.

    Con `cache_enabled` se escriben (o reutilizan) las entradas de caché; sin caché solo se valida. Un `CacheError`
    (límite o disco) u otro fallo de E/S detiene el proceso y se propaga. En todos los casos se escribe
    `<work_dir>/prepare_report.json` de forma atómica (con `completed: false` si se abortó).
    """
    pre = config.preprocess
    cache = StudyCache.from_config(config) if pre.cache_enabled else None
    report = PrepareReport(cache_key=cache.key if cache else None)
    eligible = sorted((r for r in records if r.get("eligible") is True), key=lambda r: r["study_id"])
    report.skipped_ineligible = len(records) - len(eligible)
    try:
        for record in eligible:
            study_id = record["study_id"]
            expected = study_sources(record, config.channels)
            hit = cache.is_hit(study_id, expected) if cache is not None else None
            if hit is not None:
                report.studies.append(_entry(hit, "cached"))
                log(f"  {study_id}: en caché")
                continue
            try:
                study = prepare_study(record, config.paths.data_root, pre, config.channels)
            except StudyError as exc:
                report.studies.append({"study_id": study_id, "status": "error", "error": exc.to_json()})
                log(f"  ERROR {study_id}: {exc.code} — {exc.message}")
                continue
            entry = _entry(study, "validated")
            if cache is not None:
                try:
                    cache.store(study)
                except BaseException as exc:
                    message = f"{type(exc).__name__}: {exc}"
                    report.studies.append({**entry, "status": "aborted", "error": {"message": message}})
                    report.aborted = f"{study_id}: {message}"
                    raise
                entry["status"] = "prepared"
            report.studies.append(entry)
            flags = ", ".join(f["code"] for f in study.review_flags)
            suffix = f" [{flags}]" if flags else ""
            log(f"  {study_id}: {entry['status']} {tuple(study.geometry.prepared_shape)}{suffix}")
            del study
    finally:
        atomic_write_text(config.paths.work_dir / REPORT_NAME, json.dumps(report.to_json(), indent=2) + "\n")
    return report


def format_prepare(report: PrepareReport) -> str:
    """Resumen legible del informe de `prepare`."""
    data = report.to_json()
    counts = ", ".join(f"{k}: {v}" for k, v in data["counts"].items()) or "ninguno"
    lines = [f"Estudios elegibles procesados — {counts}; no elegibles omitidos: {report.skipped_ineligible}"]
    by_code: dict[str, int] = {}
    for s in report.errors:
        by_code[s["error"]["code"]] = by_code.get(s["error"]["code"], 0) + 1
    for code, n in sorted(by_code.items()):
        lines.append(f"  error {code}: {n} estudio(s)")
    for code, totals in data["review_totals"].items():
        voxels = f", {totals['voxels']} vóxeles de GTV" if totals["voxels"] else ""
        lines.append(f"  revisión {code}: {totals['studies']} estudio(s){voxels}")
    if report.cache_key is None:
        lines.append("Caché desactivada (preprocess.cache_enabled = false): solo se validó; no se escribió caché.")
    else:
        lines.append(f"Clave de caché: {report.cache_key}")
    return "\n".join(lines)
