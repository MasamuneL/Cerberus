"""Evaluación explícita de un run y del baseline original (docs/PLAN_PIPELINE_FINETUNING.md §7, ticket FT4).

`evaluate --run <run> --split {val,test}` es un comando **explícito**: `train` nunca lo llama (el bucle de
entrenamiento solo valida sobre `val` para elegir `best`). Pasos:

1. **Run y datos.** Se lee `config.resolved.json` del run, se recalculan inventario, `splits.json` y clave de caché
   (`train.load_training_data`) y la huella `compat`; los hashes de `provenance.json` y del checkpoint deben coincidir
   (split, registros elegibles, caché, pesos iniciales y configuración relevante). Cualquier diferencia es un error.
2. **Checkpoint.** `best.pt` por defecto o `last.pt` con `--checkpoint last` (explícito), cargado con correspondencia
   estricta. Mientras se evalúa, el run queda bloqueado con el candado `.lock` de FT3.
3. **Umbral.** El del checkpoint (`training.threshold`, 0.5 por defecto) o el de `threshold.json` si se optimizó antes
   en validación (`--optimize-threshold`, solo con `--split val`, se escribe una sola vez y nunca si ya hay una
   evaluación de test). **Sobre test nunca se optimiza nada.**
4. **Predicción.** Ventana deslizante en el grid preparado (`train.predict_volume`: ventana `patch_size`, solapamiento
   0.5, sin augmentations), `sigmoid > umbral`.
5. **Grid de comparación documentado.** La máscara binaria se restaura al grid **original de la T1c**
   (`transforms.restore_to_reference`, vecino más próximo) y se compara con la GTV **original** del dataset llevada a
   ese grid (`transforms.reference_label`: tal cual si ya comparte el grid de la T1c; si no, vecino más próximo).
   La GTV nunca pasa por el recorte al soporte: lo que la predicción no cubre fuera del volumen preparado es FN.
6. **Métricas por estudio** con `cerberus_api.segmentation.mask_metrics` (Dice portado de `cerberus_eda.py:178-181`):
   Dice/F1, recall, precisión, HD95 (mm) y error de volumen firmado y absoluto (cm³). Ambos vacíos → Dice 1; HD95
   null si alguna máscara está vacía; recall/precisión null sin denominador. Los casos vacíos se cuentan aparte.
7. **Agregación.** Media de los tiempos dentro de cada paciente (sobre valores no nulos) y después estadísticos entre
   pacientes: media, desviación estándar muestral (ddof = 1), mediana, cuartiles/IQR, denominadores válidos e IC 95 %
   bootstrap percentil **remuestreando pacientes** (semilla fija, `n` configurable, mismas réplicas para todas las
   métricas).

Salidas (nunca se sobrescriben: si la carpeta existe, error):

```text
runs/<run_id>/evaluation/<split>[-last|-baseline]/{per_study.csv,per_patient.csv,summary.json}
runs/<run_id>/threshold.json   # solo con --optimize-threshold (val)
```

`--baseline` evalúa la salida TC del modelo original (3 salidas) con su pipeline de `cerberus_api.segmentation`
(`segment_regions`) frente a la GTV como **referencia imperfecta**: TC no es GTV y esto no es una equivalencia de
etiquetas. El resumen registra sus canales, su preprocesamiento y las diferencias con el modelo adaptado.

Los predictores son inyectables (`predictor`, `baseline_predictor`) para probar sin pesos reales. torch y MONAI se
importan dentro de las funciones.
"""

import csv
import io
import json
import os
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from cerberus_api.segmentation import CHANNEL_MAP, ROI_SIZE, Predictor, dice, mask_metrics
from cerberus_training.artifacts import RunPaths, environment, run_lock, write_json_once
from cerberus_training.config import TrainConfig, load_config, resolve_config
from cerberus_training.manifest import fsync_dir
from cerberus_training.model import (
    PRETRAINED_OUT_CHANNELS,
    CheckpointError,
    ModelSpec,
    build_adapted_model,
    load_strict,
    read_weights,
    segresnet_spec,
)
from cerberus_training.train import (
    VAL_OVERLAP,
    TrainingData,
    TrainingDataError,
    TrainingError,
    check_supported,
    compat_fingerprint,
    load_checkpoint,
    load_training_data,
    macro_patient_dice,
    predict_volume,
    resolve_device,
    state_digest,
)
from cerberus_training.transforms import (
    TRANSFORMS_VERSION,
    Geometry,
    StudyError,
    eval_sample,
    reference_label,
    reference_spacing,
    resample,
    restore_to_reference,
    verified_source_path,
)

if TYPE_CHECKING:
    from torch import nn

EVALUATION_SCHEMA_VERSION = 1
THRESHOLD_SCHEMA_VERSION = 1
SPLITS: tuple[str, ...] = ("val", "test")
CHECKPOINTS: tuple[str, ...] = ("best", "last")
DEFAULT_BOOTSTRAP_SAMPLES = 1000
DEFAULT_BOOTSTRAP_SEED = 42
CI_LEVEL = 0.95
# Candidatos fijos (definidos antes de ver datos) para optimizar el umbral en validación.
THRESHOLD_CANDIDATES: tuple[float, ...] = tuple(round(0.05 * i, 2) for i in range(1, 20))
# Métricas por estudio que se agregan (recall, precisión y HD95 pueden ser null).
METRICS: tuple[str, ...] = ("dice", "recall", "precision", "hd95_mm", "volume_error_cm3", "abs_volume_error_cm3")
# Hashes de `provenance.json` que deben coincidir con los datos y la configuración actuales.
RUN_HASH_KEYS: tuple[str, ...] = (
    "eligible_records_sha256",
    "split_sha256",
    "weights_sha256",
    "cache_key",
    "config_sha256",
)
THRESHOLD_FILE = "threshold.json"
COMPARISON_GRID = (
    "Grid original de la T1c (referencia). Predicción binaria restaurada con vecino más próximo desde el grid "
    "preparado; GTV original del dataset en ese grid (tal cual si comparte el grid de la T1c, si no vecino más "
    "próximo). Lo que queda fuera del volumen preparado (recorte al soporte) cuenta como falso negativo."
)
AGGREGATION = (
    "Media de los tiempos de cada paciente sobre valores no nulos y después estadísticos entre pacientes "
    "(desviación estándar muestral ddof=1, cuartiles con interpolación lineal). IC 95 % bootstrap percentil "
    "remuestreando pacientes con reemplazo (mismas réplicas para todas las métricas)."
)
EMPTY_RULES = (
    "Ambas máscaras vacías → Dice 1; HD95 null si alguna está vacía; recall null sin GTV; precisión null sin "
    "predicción. Los casos vacíos se cuentan aparte en `empty_cases`."
)
BASELINE_LABEL_CAVEAT = (
    "Referencia imperfecta: la salida TC (tumor core de BraTS) del modelo original se compara con la GTV de CFB-GBM. "
    "TC y GTV son etiquetas distintas; estas cifras no son una equivalencia de etiquetas ni una comparación justa."
)

LogFn = Callable[[str], None]
# Predictor del modelo adaptado: imagen preparada float32 [4, X, Y, Z] → probabilidad GTV [X, Y, Z].
ProbPredictor = Callable[[np.ndarray], np.ndarray]


class EvaluationError(ValueError):
    """Uso no permitido (p. ej. optimizar el umbral sobre test) o run no evaluable."""


class EvaluationExistsError(FileExistsError):
    """La carpeta de evaluación ya existe: nunca se sobrescribe."""


class EvaluationDataError(ValueError):
    """Un estudio no se puede evaluar (fuente cambiada, GTV no binaria, geometría…)."""


def _no_log(_message: str) -> None:
    return None


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------------------------------------------
# Run, checkpoint y umbral
# ---------------------------------------------------------------------------------------------------------------


@dataclass
class RunContext:
    """Run abierto con sus datos verificados contra los hashes de la procedencia."""

    paths: RunPaths
    config: TrainConfig
    provenance: dict[str, Any]
    data: TrainingData
    compat: dict[str, Any]

    @property
    def run_id(self) -> str:
        return self.paths.root.name


def read_json_object(path: Path, what: str) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TrainingDataError(f"No se pudo leer {what} {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise TrainingDataError(f"{what} {path} no es un objeto JSON")
    return data


def open_run(run_dir: Path, spec: ModelSpec | None = None) -> RunContext:
    """Abre un run y comprueba que sus hashes coinciden con inventario, split, caché, pesos y configuración actuales."""
    paths = RunPaths(run_dir.resolve())
    if not paths.config.is_file() or not paths.provenance.is_file():
        raise TrainingDataError(f"{paths.root} no es un run completo (faltan config.resolved.json o provenance.json)")
    config = resolve_config(load_config(paths.config))
    if paths.root.parent != (config.paths.work_dir / "runs").resolve():
        raise TrainingDataError(f"El run {paths.root} no está en {config.paths.work_dir / 'runs'} de su configuración")
    check_supported(config)
    provenance = read_json_object(paths.provenance, "la procedencia")
    data = load_training_data(config)
    compat = compat_fingerprint(config, data, spec or segresnet_spec())
    stored = provenance.get("hashes")
    if not isinstance(stored, dict):
        raise CheckpointError(f"{paths.provenance} no tiene hashes")
    diffs = [k for k in RUN_HASH_KEYS if stored.get(k) != compat[k]]
    if diffs:
        raise CheckpointError(
            f"El run {paths.root.name} no corresponde a los datos/configuración actuales: difieren {', '.join(diffs)}"
        )
    return RunContext(paths, config, provenance, data, compat)


def split_ids(ctx: RunContext, split: str) -> list[str]:
    """Estudios de la partición (de `splits.json` verificado), elegibles y con entrada en la caché."""
    if split not in SPLITS:
        raise EvaluationError(f"Partición no evaluable: {split!r} (use {', '.join(SPLITS)})")
    ids = list(ctx.data.splits["partitions"][split]["studies"])
    if not ids:
        raise TrainingDataError(f"La partición {split} está vacía")
    unknown = [s for s in ids if s not in ctx.data.records]
    if unknown:
        raise TrainingDataError(f"El split menciona estudios que no son elegibles en el inventario: {unknown[:10]}")
    missing = [s for s in ids if not ctx.data.cache.path(s).is_file()]
    if missing:
        raise TrainingDataError(f"Faltan {len(missing)} estudio(s) de {split} en la caché: {missing[:10]}")
    return ids


@dataclass
class RunCheckpoint:
    kind: str
    path: Path
    epoch: int | None  # best: época del mejor Dice; last: épocas completadas
    threshold: float  # umbral guardado en el checkpoint (best) o de la configuración (last)
    state_sha256: str
    model: "nn.Module"
    selection_metric: dict[str, Any] | None


def load_run_checkpoint(ctx: RunContext, kind: str, spec: ModelSpec | None = None) -> RunCheckpoint:
    """Carga `best.pt`/`last.pt` con su huella `compat` idéntica a la actual y correspondencia estricta."""
    if kind not in CHECKPOINTS:
        raise EvaluationError(f"Checkpoint desconocido: {kind!r} (use {', '.join(CHECKPOINTS)})")
    path = ctx.paths.best if kind == "best" else ctx.paths.last
    if not path.is_file():
        raise CheckpointError(f"No existe {path} (¿el run llegó a validar?)")
    payload = load_checkpoint(path, kind)
    stored = payload.get("compat")
    if not isinstance(stored, dict):
        raise CheckpointError(f"{path} no tiene huella de compatibilidad")
    diffs = [k for k in sorted(set(stored) | set(ctx.compat)) if stored.get(k) != ctx.compat.get(k)]
    if diffs:
        raise CheckpointError(f"{path} no es compatible con el run/datos actuales: difiere en {', '.join(diffs)}")
    model = build_adapted_model(ctx.config, spec)
    load_strict(model, payload["model"], str(path))
    model.eval()
    threshold = float(payload["threshold"]) if kind == "best" else ctx.config.training.threshold
    epoch = payload.get("epoch")
    metric = payload.get("metric") if kind == "best" else None
    return RunCheckpoint(
        kind=kind,
        path=path,
        epoch=int(epoch) if isinstance(epoch, int) else None,
        threshold=threshold,
        state_sha256=state_digest(model),
        model=model,
        selection_metric=metric if isinstance(metric, dict) else None,
    )


@dataclass(frozen=True)
class ThresholdChoice:
    value: float
    source: str  # "checkpoint" (training.threshold) u "optimized_on_val" (threshold.json)
    warnings: tuple[str, ...] = ()


def read_threshold_file(path: Path) -> dict[str, Any]:
    """Lee `threshold.json` y exige esquema, valor en (0, 1) y que se optimizara en val."""
    data = read_json_object(path, "el umbral")
    value = data.get("threshold")
    if data.get("schema_version") != THRESHOLD_SCHEMA_VERSION or not isinstance(value, float) or not 0 < value < 1:
        raise TrainingDataError(f"{path}: umbral con esquema o valor no válido")
    if data.get("split") != "val":
        raise TrainingDataError(f"{path}: el umbral debe estar optimizado en val (no {data.get('split')!r})")
    return data


def resolve_threshold(ctx: RunContext, checkpoint: RunCheckpoint) -> ThresholdChoice:
    """`threshold.json` (optimizado en val y persistido antes) si es del mismo checkpoint; si no, el del checkpoint."""
    path = ctx.paths.root / THRESHOLD_FILE
    if not path.is_file():
        return ThresholdChoice(checkpoint.threshold, "checkpoint")
    data = read_threshold_file(path)
    bound = data.get("checkpoint")
    if not isinstance(bound, dict) or bound.get("state_sha256") != checkpoint.state_sha256:
        warning = (
            f"{THRESHOLD_FILE} se optimizó para otro checkpoint; se usa el umbral del checkpoint "
            f"{checkpoint.kind} ({checkpoint.threshold})"
        )
        return ThresholdChoice(checkpoint.threshold, "checkpoint", (warning,))
    return ThresholdChoice(float(data["threshold"]), "optimized_on_val")


# ---------------------------------------------------------------------------------------------------------------
# Métricas por estudio y agregación
# ---------------------------------------------------------------------------------------------------------------


def empty_case(pred_voxels: int, gtv_voxels: int) -> str:
    """`both_empty`, `pred_empty` (solo la predicción vacía), `gtv_empty` (solo la GTV vacía) o `none`."""
    if not pred_voxels and not gtv_voxels:
        return "both_empty"
    if not pred_voxels:
        return "pred_empty"
    if not gtv_voxels:
        return "gtv_empty"
    return "none"


def study_metrics(prediction: np.ndarray, reference: np.ndarray, spacing: tuple[float, float, float]) -> dict[str, Any]:
    """Métricas de un estudio en un grid ortogonal, reutilizando `mask_metrics` (Dice de `cerberus_eda.py:178-181`)."""
    m = mask_metrics(prediction, reference, spacing)
    n_pred, n_ref = int(np.count_nonzero(prediction)), int(np.count_nonzero(reference))
    voxel_cm3 = float(np.prod(spacing)) / 1000
    return {
        "gtv_voxels": n_ref,
        "pred_voxels": n_pred,
        "gtv_cm3": n_ref * voxel_cm3,
        "pred_cm3": n_pred * voxel_cm3,
        "empty_case": empty_case(n_pred, n_ref),
        "dice": m.dice,
        "recall": m.recall,
        "precision": m.precision,
        "hd95_mm": m.hd95_mm,
        "volume_error_cm3": m.volume_error_cm3,
        "abs_volume_error_cm3": abs(m.volume_error_cm3),
    }


def patient_table(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Una fila por paciente: media de sus tiempos por métrica (sobre valores no nulos) y denominadores válidos."""
    by_patient: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_patient.setdefault(str(row["patient"]), []).append(row)
    out: list[dict[str, Any]] = []
    for patient in sorted(by_patient):
        studies = by_patient[patient]
        entry: dict[str, Any] = {"patient": patient, "n_studies": len(studies)}
        for metric in METRICS:
            valid = [float(r[metric]) for r in studies if r[metric] is not None]
            entry[metric] = float(np.mean(valid)) if valid else None
            entry[f"{metric}_n"] = len(valid)
        out.append(entry)
    return out


def describe(values: list[float]) -> dict[str, Any]:
    """Media, desviación estándar muestral (ddof=1; null con n < 2), mediana, cuartiles e IQR."""
    if not values:
        return {"mean": None, "std": None, "median": None, "q1": None, "q3": None, "iqr": None}
    arr = np.asarray(values, dtype=np.float64)
    q1, median, q3 = (float(v) for v in np.percentile(arr, [25, 50, 75]))
    return {
        "mean": float(arr.mean()),
        "std": float(arr.std(ddof=1)) if arr.size > 1 else None,
        "median": median,
        "q1": q1,
        "q3": q3,
        "iqr": q3 - q1,
    }


def bootstrap_ci(
    patient_values: dict[str, list[float | None]], samples: int, seed: int, level: float = CI_LEVEL
) -> dict[str, list[float] | None]:
    """IC bootstrap percentil de la media entre pacientes, **remuestreando pacientes** con reemplazo.

    `patient_values`: métrica → valor por paciente (mismo orden de pacientes en todas). Las mismas `samples` réplicas
    de índices de paciente (`numpy.random.default_rng(seed)`) sirven para todas las métricas. En cada réplica se
    promedian los pacientes remuestreados con valor no nulo (réplicas sin ninguno se descartan). Null si hay menos de
    2 pacientes con valor.
    """
    if samples < 1:
        raise ValueError("El número de réplicas bootstrap debe ser positivo")
    lengths = {len(v) for v in patient_values.values()}
    if len(lengths) > 1:
        raise ValueError("Todas las métricas deben tener un valor (o null) por paciente")
    n_patients = lengths.pop() if lengths else 0
    if n_patients == 0:
        return {metric: None for metric in patient_values}
    idx = np.random.default_rng(seed).integers(0, n_patients, size=(samples, n_patients))
    alpha = (1 - level) / 2 * 100
    out: dict[str, list[float] | None] = {}
    for metric, values in patient_values.items():
        arr = np.array([np.nan if v is None else float(v) for v in values], dtype=np.float64)
        if int(np.count_nonzero(~np.isnan(arr))) < 2:
            out[metric] = None
            continue
        sample = arr[idx]
        valid = ~np.isnan(sample)
        counts = valid.sum(axis=1)
        sums = np.where(valid, sample, 0.0).sum(axis=1)
        means = sums[counts > 0] / counts[counts > 0]
        lo, hi = np.percentile(means, [alpha, 100 - alpha])
        out[metric] = [float(lo), float(hi)]
    return out


def summarize(
    rows: list[dict[str, Any]], patients: list[dict[str, Any]], samples: int, seed: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Estadísticos por métrica entre pacientes y casos vacíos (por estudio)."""
    ci = bootstrap_ci({m: [p[m] for p in patients] for m in METRICS}, samples, seed)
    metrics: dict[str, Any] = {}
    for metric in METRICS:
        values = [float(p[metric]) for p in patients if p[metric] is not None]
        metrics[metric] = {
            "n_valid_patients": len(values),
            "n_patients": len(patients),
            "n_valid_studies": sum(1 for r in rows if r[metric] is not None),
            "n_studies": len(rows),
            **describe(values),
            "ci95": ci[metric],
        }
    empty: dict[str, Any] = {}
    for case in ("both_empty", "pred_empty", "gtv_empty"):
        studies = sorted(str(r["study_id"]) for r in rows if r["empty_case"] == case)
        empty[case] = {"count": len(studies), "studies": studies}
    return metrics, empty


# ---------------------------------------------------------------------------------------------------------------
# Escritura de resultados (nunca se sobrescriben)
# ---------------------------------------------------------------------------------------------------------------


def evaluation_dir(paths: RunPaths, split: str, model: str = "adapted", checkpoint: str = "best") -> Path:
    """`evaluation/<split>` (best), `<split>-last` (last) o `<split>-baseline` (modelo original)."""
    suffix = "-baseline" if model == "baseline" else ("" if checkpoint == "best" else f"-{checkpoint}")
    return paths.root / "evaluation" / f"{split}{suffix}"


def ensure_absent(path: Path) -> None:
    if path.exists():
        raise EvaluationExistsError(f"{path} ya existe: una evaluación/exportación nunca se sobrescribe")


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return repr(value)
    return str(value)


def to_csv(rows: list[dict[str, Any]], columns: list[str]) -> str:
    """CSV con cabecera; null → celda vacía, floats con `repr` (sin pérdida de precisión)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_cell(row.get(c)) for c in columns])
    return buffer.getvalue()


def publish_dir(final: Path, write: Callable[[Path], None]) -> None:
    """Rellena una carpeta temporal hermana con `write(tmp)` y la renombra a `final`; falla si `final` ya existe.

    Un fallo a mitad no deja una carpeta final parcial (el temporal se borra).
    """
    parent = final.parent
    parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(dir=parent, prefix=f".{final.name}.", suffix=".tmp"))
    try:
        write(tmp)
        os.chmod(tmp, 0o755)
        ensure_absent(final)
        os.rename(tmp, final)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    fsync_dir(parent)


def write_text_file(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())


STUDY_COLUMNS = [
    "study_id",
    "patient",
    "timepoint",
    "threshold",
    "gtv_voxels",
    "pred_voxels",
    "gtv_cm3",
    "pred_cm3",
    "empty_case",
    *METRICS,
    "spacing_mm",
    "label_resampled",
    "label_lost_voxels",
]
BASELINE_EXTRA_COLUMNS = ["baseline_channels", "baseline_warnings"]
PATIENT_COLUMNS = ["patient", "n_studies", *(c for m in METRICS for c in (m, f"{m}_n"))]


@dataclass
class EvaluationResult:
    directory: Path
    split: str
    model: str  # "adapted" o "baseline"
    rows: list[dict[str, Any]]
    patients: list[dict[str, Any]]
    summary: dict[str, Any]
    threshold_file: Path | None = None
    warnings: list[str] = field(default_factory=list)


def _write_result(
    directory: Path,
    rows: list[dict[str, Any]],
    patients: list[dict[str, Any]],
    summary: dict[str, Any],
    extra: list[str],
) -> None:
    files = {
        "per_study.csv": to_csv(rows, [*STUDY_COLUMNS, *extra]),
        "per_patient.csv": to_csv(patients, PATIENT_COLUMNS),
        "summary.json": json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    }

    def write(tmp: Path) -> None:
        for name, text in files.items():
            write_text_file(tmp / name, text)

    publish_dir(directory, write)


# ---------------------------------------------------------------------------------------------------------------
# Evaluación del modelo adaptado
# ---------------------------------------------------------------------------------------------------------------


def _checked_prob(predictor: ProbPredictor, image: np.ndarray, geometry: Geometry, study_id: str) -> np.ndarray:
    prob = np.asarray(predictor(image), dtype=np.float32)
    if prob.shape != geometry.prepared_shape:
        raise TrainingError(f"{study_id}: el predictor devolvió {prob.shape} y se esperaba {geometry.prepared_shape}")
    if not bool(np.all(np.isfinite(prob))):
        raise TrainingError(f"{study_id}: la predicción contiene NaN/Inf")
    return prob


def _reference(ctx: RunContext, study_id: str, geometry: Geometry) -> tuple[np.ndarray, bool]:
    try:
        return reference_label(ctx.data.records[study_id], ctx.config.paths.data_root, geometry)
    except StudyError as exc:
        raise EvaluationDataError(f"{study_id}: {exc.code} — {exc.message}") from exc


def _spacing(geometry: Geometry, study_id: str) -> tuple[float, float, float]:
    try:
        return reference_spacing(geometry)
    except ValueError as exc:
        raise EvaluationDataError(f"{study_id}: {exc}") from exc


def _row_base(ctx: RunContext, study_id: str) -> dict[str, Any]:
    record = ctx.data.records[study_id]
    return {"study_id": study_id, "patient": str(record["patient"]), "timepoint": str(record["timepoint"])}


def run_hashes(ctx: RunContext) -> dict[str, Any]:
    return {k: ctx.compat[k] for k in RUN_HASH_KEYS}


def optimize_threshold(
    ctx: RunContext, ids: list[str], predictor: ProbPredictor, checkpoint: RunCheckpoint, log: LogFn = _no_log
) -> dict[str, Any]:
    """Elige el umbral de `THRESHOLD_CANDIDATES` con mayor Dice macro por paciente **en val**, en el grid de
    referencia. Empates: el más cercano al umbral del checkpoint y después el menor. Devuelve el contenido de
    `threshold.json` (aún sin escribir)."""
    per_threshold: dict[float, dict[str, float]] = {t: {} for t in THRESHOLD_CANDIDATES}
    for study_id in ids:
        image, _label, geometry = eval_sample(ctx.data.load(study_id))
        prob = _checked_prob(predictor, image, geometry, study_id)
        gtv, _resampled = _reference(ctx, study_id, geometry)
        for t in THRESHOLD_CANDIDATES:
            pred = restore_to_reference((prob > t).astype(np.uint8), geometry)
            per_threshold[t][study_id] = dice(pred, gtv)
        log(f"  {study_id}: umbrales evaluados")
    scores = {t: float(macro_patient_dice(v, ctx.data.patient)["val_dice"]) for t, v in per_threshold.items()}
    default = checkpoint.threshold
    best = max(THRESHOLD_CANDIDATES, key=lambda t: (scores[t], -abs(t - default), -t))
    return {
        "schema_version": THRESHOLD_SCHEMA_VERSION,
        "threshold": float(best),
        "source": "optimized_on_val",
        "split": "val",
        "metric": "dice_macro_patient_reference_grid",
        "candidates": list(THRESHOLD_CANDIDATES),
        "scores": {f"{t:.2f}": scores[t] for t in THRESHOLD_CANDIDATES},
        "default_threshold": default,
        "checkpoint": {"kind": checkpoint.kind, "epoch": checkpoint.epoch, "state_sha256": checkpoint.state_sha256},
        "hashes": run_hashes(ctx),
        "created_utc": utc_now(),
    }


def _base_summary(ctx: RunContext, split: str, model: str, samples: int, seed: int) -> dict[str, Any]:
    return {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "model": model,
        "run_id": ctx.run_id,
        "split": split,
        "created_utc": utc_now(),
        "hashes": run_hashes(ctx),
        "comparison_grid": COMPARISON_GRID,
        "aggregation": AGGREGATION,
        "empty_rules": EMPTY_RULES,
        "bootstrap": {"samples": samples, "seed": seed, "unit": "patient", "method": "percentile", "level": CI_LEVEL},
        "environment": environment(),
    }


def device_config(config: TrainConfig, device: str | None) -> TrainConfig:
    """Copia con `training.device` sustituido (AMP solo se mantiene con CUDA)."""
    if device is None:
        return config
    training = config.training.model_copy(update={"device": device, "amp": config.training.amp and device == "cuda"})
    return config.model_copy(update={"training": training})


def _check_common(split: str, bootstrap_samples: int) -> None:
    if split not in SPLITS:
        raise EvaluationError(f"Partición no evaluable: {split!r} (use {', '.join(SPLITS)})")
    if bootstrap_samples < 1:
        raise EvaluationError("--bootstrap debe ser un entero positivo")


def evaluate_run(
    run_dir: Path,
    split: str,
    *,
    checkpoint: str = "best",
    optimize: bool = False,
    predictor: ProbPredictor | None = None,
    spec: ModelSpec | None = None,
    device: str | None = None,
    bootstrap_samples: int = DEFAULT_BOOTSTRAP_SAMPLES,
    bootstrap_seed: int = DEFAULT_BOOTSTRAP_SEED,
    log: LogFn = _no_log,
) -> EvaluationResult:
    """Evalúa el modelo adaptado de un run en `split` (ver docstring del módulo).

    `optimize` (solo `split="val"`) optimiza el umbral, lo persiste en `threshold.json` y evalúa val con él.
    `predictor` sustituye a la red (tests); el checkpoint se carga y verifica igualmente.
    """
    _check_common(split, bootstrap_samples)
    if optimize and split != "val":
        raise EvaluationError("El umbral solo se optimiza en validación (--split val); nunca sobre test")
    spec = spec or segresnet_spec()
    ctx = open_run(run_dir, spec)
    out_dir = evaluation_dir(ctx.paths, split, "adapted", checkpoint)
    ensure_absent(out_dir)
    threshold_path = ctx.paths.root / THRESHOLD_FILE
    with run_lock(ctx.paths):
        ckpt = load_run_checkpoint(ctx, checkpoint, spec)
        ids = split_ids(ctx, split)
        if predictor is None:
            config = device_config(ctx.config, device)
            dev = resolve_device(config)
            model = ckpt.model.to(dev)

            def predict(image: np.ndarray) -> np.ndarray:
                return predict_volume(model, image, config, dev)

            predictor = predict
        written: Path | None = None
        if optimize:
            if threshold_path.exists():
                raise EvaluationError(f"{threshold_path} ya existe: el umbral se optimiza una sola vez")
            tested = sorted(p.name for p in (ctx.paths.root / "evaluation").glob("test*"))
            if tested:
                raise EvaluationError(
                    f"Ya hay evaluaciones de test ({', '.join(tested)}): optimizar el umbral ahora usaría un umbral "
                    "elegido después de ver test"
                )
            log(f"Optimizando el umbral en val ({len(THRESHOLD_CANDIDATES)} candidatos)…")
            choice = optimize_threshold(ctx, ids, predictor, ckpt, log)
            write_json_once(threshold_path, choice)
            written = threshold_path
            log(f"Umbral elegido en val: {choice['threshold']} (guardado en {threshold_path})")
        threshold = resolve_threshold(ctx, ckpt)
        warnings = list(threshold.warnings)
        if split == "val" and threshold.source == "optimized_on_val":
            warnings.append("Umbral optimizado en esta misma partición (val): las métricas de val son optimistas")
        rows: list[dict[str, Any]] = []
        for study_id in ids:
            study = ctx.data.load(study_id)
            image, _label, geometry = eval_sample(study)
            prob = _checked_prob(predictor, image, geometry, study_id)
            pred = restore_to_reference((prob > threshold.value).astype(np.uint8), geometry)
            del image, prob
            gtv, resampled = _reference(ctx, study_id, geometry)
            spacing = _spacing(geometry, study_id)
            row = _row_base(ctx, study_id)
            row.update(threshold=threshold.value, **study_metrics(pred, gtv, spacing))
            row.update(
                spacing_mm=";".join(repr(s) for s in spacing),
                label_resampled=resampled,
                label_lost_voxels=study.label_lost_voxels,
            )
            rows.append(row)
            log(f"  {study_id}: Dice {row['dice']:.4f}")
            del study
        patients = patient_table(rows)
        metrics, empty = summarize(rows, patients, bootstrap_samples, bootstrap_seed)
        summary = _base_summary(ctx, split, "adapted", bootstrap_samples, bootstrap_seed)
        summary.update(
            checkpoint={
                "kind": ckpt.kind,
                "epoch": ckpt.epoch,
                "state_sha256": ckpt.state_sha256,
                "selection_metric": ckpt.selection_metric,
            },
            threshold={"value": threshold.value, "source": threshold.source},
            inference={
                "sliding_window_roi": list(ctx.config.preprocess.patch_size),
                "overlap": VAL_OVERLAP,
                "activation": "sigmoid",
                "transforms_version": TRANSFORMS_VERSION,
                "channel_order": list(ctx.config.channels.order),
            },
            n_studies=len(rows),
            n_patients=len(patients),
            metrics=metrics,
            empty_cases=empty,
            warnings=warnings,
        )
        _write_result(out_dir, rows, patients, summary, [])
    log(f"Evaluación escrita en {out_dir}")
    return EvaluationResult(out_dir, split, "adapted", rows, patients, summary, written, warnings)


# ---------------------------------------------------------------------------------------------------------------
# Baseline: salida TC del modelo original con su pipeline (cerberus_api.segmentation)
# ---------------------------------------------------------------------------------------------------------------

BASELINE_PREPROCESSING: tuple[str, ...] = (
    "Canales [T1c, T1, T2, FLAIR] según CHANNEL_MAP de cerberus_api.segmentation (T2 admite t2star; un canal "
    "faltante se rellena con ceros). Con el perfil estricto del inventario siempre se pasan t1gd, t1eg/t1tse, "
    "t2tse y flair, así que la selección de secuencias coincide con la del modelo adaptado.",
    "Grid de 1 mm de nibabel `resample_to_output` sobre la T1c (orden 1); el resto de canales y la brain_mask se "
    "llevan a ese grid con `resample_from_to` (orden 1 y 0). Sin recorte al soporte.",
    "Imágenes multiplicadas por la brain_mask si existe; `normalize_nonzero` por canal.",
    f"Ventana deslizante {list(ROI_SIZE)}, solapamiento 0.5, sigmoide; TC = canal 0 > 0.5, recortado a la "
    "brain_mask si existe. Restaurado al grid original de la T1c con vecino más próximo.",
)
BASELINE_DIFFERENCES: tuple[str, ...] = (
    "Etiqueta: TC (tumor core de BraTS, canal 0 de 3 salidas) frente a GTV binaria (1 logit) del modelo adaptado.",
    "Umbral: fijo 0.5 en el baseline; el adaptado usa el umbral del run (training.threshold o threshold.json).",
    "Grid de inferencia: resample_to_output de nibabel sin recorte en el baseline; el adaptado usa el grid RAS "
    "de vox2out_vox remuestreado con scipy (mode=grid-constant) y recortado a la caja del soporte (FT2).",
    "Máscara cerebral: el baseline recorta además la predicción a la brain_mask; el adaptado solo enmascara las "
    "imágenes.",
    "Ventana deslizante: ROI 240×240×160 en el baseline frente a preprocess.patch_size en el adaptado.",
    "Canales faltantes: el baseline admite T2* y canales a cero; el adaptado exige el perfil estricto (aquí no "
    "aplica: los estudios elegibles tienen los cuatro canales).",
    "Pesos: los del bundle original (weights.sha256); el adaptado, los del checkpoint del run.",
)


def baseline_files(ctx: RunContext, study_id: str) -> dict[str, Path]:
    """Secuencia → ruta (verificada) de los canales seleccionados y de la brain_mask, para `segment_regions`."""
    record = ctx.data.records[study_id]
    root = ctx.config.paths.data_root
    files: dict[str, Path] = {}
    try:
        for name in ctx.config.channels.order:
            entry = record["channels"][name]
            files[str(entry["sequence"])] = verified_source_path(root, record, entry, name)
        if record.get("brain_mask") is not None:
            files["brain_mask"] = verified_source_path(root, record, record["brain_mask"], "brain_mask")
    except StudyError as exc:
        raise EvaluationDataError(f"{study_id}: {exc.code} — {exc.message}") from exc
    except (KeyError, TypeError) as exc:
        raise EvaluationDataError(f"{study_id}: registro del inventario incompleto ({exc})") from exc
    return files


def evaluate_baseline(
    run_dir: Path,
    split: str,
    *,
    baseline_predictor: Predictor | None = None,
    device: str | None = None,
    bootstrap_samples: int = DEFAULT_BOOTSTRAP_SAMPLES,
    bootstrap_seed: int = DEFAULT_BOOTSTRAP_SEED,
    log: LogFn = _no_log,
) -> EvaluationResult:
    """Evalúa la salida TC del modelo original frente a la GTV (referencia imperfecta) en los estudios de `split`.

    Usa los datos del run (split, caché para la geometría de referencia). Sin `baseline_predictor`, construye la red
    de 3 salidas con los pesos de `weights.path` verificados por SHA-256 (nunca descarga) y la inferencia de
    `cerberus_api.segmentation.segresnet_predictor`.
    """
    from cerberus_api.segmentation import segment_regions, segresnet_predictor

    _check_common(split, bootstrap_samples)
    ctx = open_run(run_dir)
    out_dir = evaluation_dir(ctx.paths, split, "baseline")
    ensure_absent(out_dir)
    with run_lock(ctx.paths):
        ids = split_ids(ctx, split)
        predictor_label = "custom"
        if baseline_predictor is None:
            weights = ctx.config.weights
            net = segresnet_spec().build(PRETRAINED_OUT_CHANNELS)
            load_strict(net, read_weights(weights.path, weights.sha256), str(weights.path))
            dev = resolve_device(device_config(ctx.config, device))
            baseline_predictor = segresnet_predictor(net, str(dev))
            predictor_label = f"segresnet_predictor ({dev})"
        rows: list[dict[str, Any]] = []
        for study_id in ids:
            geometry = ctx.data.load(study_id).geometry
            files = baseline_files(ctx, study_id)
            regions = segment_regions(files, ctx.config.paths.work_dir, baseline_predictor)
            tc = resample(
                regions.tc.astype(np.uint8),
                np.asarray(regions.ref_img.affine, dtype=np.float64),
                geometry.reference_shape,
                geometry.reference_affine,
                order=0,
            )
            gtv, resampled = _reference(ctx, study_id, geometry)
            spacing = _spacing(geometry, study_id)
            row = _row_base(ctx, study_id)
            row.update(threshold=0.5, **study_metrics(tc, gtv, spacing))
            row.update(
                spacing_mm=";".join(repr(s) for s in spacing),
                label_resampled=resampled,
                label_lost_voxels=None,  # el baseline no recorta al soporte
                baseline_channels=";".join(f"{c.model_channel}={c.sequence or 'ceros'}" for c in regions.channels),
                baseline_warnings=" | ".join(regions.warnings),
            )
            rows.append(row)
            log(f"  {study_id}: Dice TC↔GTV {row['dice']:.4f}")
        patients = patient_table(rows)
        metrics, empty = summarize(rows, patients, bootstrap_samples, bootstrap_seed)
        summary = _base_summary(ctx, split, "baseline", bootstrap_samples, bootstrap_seed)
        summary.update(
            label_caveat=BASELINE_LABEL_CAVEAT,
            baseline={
                "bundle_name": ctx.config.weights.bundle_name,
                "bundle_version": ctx.config.weights.bundle_version,
                "weights_sha256": ctx.config.weights.sha256,
                "predictor": predictor_label,
                "output_used": "TC (canal 0 de [TC, WT, ET]) > 0.5",
                "channel_map": {k: list(v) for k, v in CHANNEL_MAP.items()},
                "preprocessing": list(BASELINE_PREPROCESSING),
            },
            differences_vs_adapted=list(BASELINE_DIFFERENCES),
            threshold={"value": 0.5, "source": "baseline_fixed"},
            n_studies=len(rows),
            n_patients=len(patients),
            metrics=metrics,
            empty_cases=empty,
            warnings=[BASELINE_LABEL_CAVEAT],
        )
        _write_result(out_dir, rows, patients, summary, BASELINE_EXTRA_COLUMNS)
    log(f"Evaluación del baseline escrita en {out_dir}")
    return EvaluationResult(out_dir, split, "baseline", rows, patients, summary, None, [BASELINE_LABEL_CAVEAT])


def format_evaluation(result: EvaluationResult) -> str:
    """Resumen legible para la CLI."""
    s = result.summary
    head = "Baseline TC↔GTV (referencia imperfecta)" if result.model == "baseline" else "Modelo adaptado"
    lines = [
        f"{head}, partición {result.split}: {s['n_studies']} estudios, {s['n_patients']} pacientes; "
        f"umbral {s['threshold']['value']} ({s['threshold']['source']})",
    ]
    for metric in METRICS:
        m = s["metrics"][metric]
        if m["mean"] is None:
            lines.append(f"  {metric}: sin valores válidos")
            continue
        ci = m["ci95"]
        ci_text = f"IC95 [{ci[0]:.4f}, {ci[1]:.4f}]" if ci is not None else "IC95 n/d"
        lines.append(
            f"  {metric}: media {m['mean']:.4f}, mediana {m['median']:.4f}, {ci_text} "
            f"(pacientes válidos {m['n_valid_patients']}/{m['n_patients']})"
        )
    empty = s["empty_cases"]
    lines.append(
        f"  vacíos: ambos {empty['both_empty']['count']}, solo predicción {empty['pred_empty']['count']}, "
        f"solo GTV {empty['gtv_empty']['count']}"
    )
    lines.extend(f"  AVISO: {w}" for w in result.warnings)
    return "\n".join(lines)
