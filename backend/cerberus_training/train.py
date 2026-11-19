"""Trainer de fine-tuning GTV binario, `--dry-run` y reanudación (docs/PLAN_PIPELINE_FINETUNING.md §6 y §8, FT3).

Datos: `inventory.jsonl` y `splits.json` de `paths.work_dir` y la caché de `prepare` (FT2). `splits.json` debe ser
exactamente el que `split` calcularía con el inventario y la configuración actuales; nunca se redistribuye.

Entrenamiento (por época):

- Orden de los estudios de `train`: permutación sembrada con `(seeds.training, época)`. Cada muestra es un parche de
  `train_sample` (FT2) de un estudio leído de la caché **de uno en uno** (verificando sus SHA-256) con
  `make_rng(seeds.augmentation, época, índice)`. Sin DataLoader: `preprocess.num_workers` debe ser 0.
- Pérdida `dice_weight · DiceLoss(sigmoid=True) + bce_weight · BCEWithLogitsLoss` sobre el logit GTV. AdamW
  (`learning_rate`, `weight_decay`) solo sobre los parámetros no congelados. Acumulación de
  `preprocess.grad_accum_steps` lotes: cada lote aporta `pérdida / tamaño de la ventana` (la última ventana de la
  época puede ser más corta y se escala por su tamaño real).
- Validación cada `validate_every` épocas (y en la última) sobre los volúmenes completos de `val` con
  `monai.inferers.sliding_window_inference` (ventana = `patch_size`, solapamiento 0.5, sin augmentations),
  `sigmoid > threshold` y `cerberus_api.segmentation.dice`. Métrica: **Dice macro por paciente** (media de los tiempos
  de cada paciente y después media de pacientes). `best` = mayor Dice estricto; parada tras
  `early_stopping_patience` validaciones sin mejora.
- NaN/Inf en la pérdida, en los gradientes (sin AMP) o en la salida de validación: error claro, nunca se ignora. Con
  AMP (solo CUDA), un gradiente no finito es el mecanismo normal de `GradScaler`: se salta el paso y se cuenta en
  `amp_skipped_steps`. Sin memoria: error claro; nunca se reduce el batch ni el parche.

Determinismo: se siembran Python, NumPy y PyTorch con `seeds.training` (no hay workers: la carga es en el proceso
principal). Con `seeds.deterministic` se activa `torch.use_deterministic_algorithms` (en CUDA con `warn_only`,
porque el upsample trilineal de SegResNet no tiene backward determinista) y se restaura el estado previo al terminar.
En CPU, N épocas seguidas y k épocas + reanudar N-k dan pesos idénticos bit a bit (probado en los tests).
"""

import json
import math
import os
import random
import time
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from cerberus_training.artifacts import (
    PROVENANCE_SCHEMA_VERSION,
    RunPaths,
    append_jsonl,
    atomic_torch_save,
    create_run_dir,
    environment,
    git_state,
    remove_run_dir,
    rewrite_jsonl,
    run_lock,
    write_json_once,
)
from cerberus_training.cache import CacheEntryError, StudyCache, free_bytes
from cerberus_training.config import ConfigError, TrainConfig, dump_config
from cerberus_training.manifest import InventoryError, read_inventory
from cerberus_training.model import (
    ADAPTED_OUT_CHANNELS,
    CheckpointError,
    ModelSpec,
    TransferReport,
    build_adapted_model,
    build_transfer_model,
    load_strict,
    segresnet_spec,
)
from cerberus_training.splits import SplitError, build_splits, canonical_hash, load_splits
from cerberus_training.transforms import PreparedStudy, eval_sample, make_rng, study_sources, train_sample

if TYPE_CHECKING:
    import torch
    from torch import nn

CHECKPOINT_SCHEMA_VERSION = 1
VAL_OVERLAP = 0.5  # mismo solapamiento que la inferencia de la API
SW_BATCH_SIZE = 1
# Estimación de disco de checkpoints: `last` (red + 2 momentos de AdamW) + `best` (red), float32, más margen 10 %.
CHECKPOINT_TENSOR_COPIES = 4
CHECKPOINT_MARGIN = 1.10
# Campos de `metrics.jsonl` que dependen del reloj (se excluyen al comparar ejecuciones).
TIMING_FIELDS: tuple[str, ...] = ("seconds",)
LogFn = Callable[[str], None]


class TrainingError(RuntimeError):
    """Fallo numérico (NaN/Inf) u otro error durante el entrenamiento."""


class DeviceUnavailableError(RuntimeError):
    """Se pidió CUDA y no está disponible (nunca se degrada en silencio a CPU)."""


class TrainingDataError(ValueError):
    """Inventario, split o caché inutilizables para entrenar."""


class ResourceError(RuntimeError):
    """Memoria o disco insuficientes. Nunca se reduce el batch ni el parche automáticamente."""


class ResumeError(CheckpointError):
    """`last.pt` no es compatible con la configuración/datos actuales (etiquetas, canales, split, config)."""


def _no_log(_message: str) -> None:
    return None


# ---------------------------------------------------------------------------------------------------------------
# Datos
# ---------------------------------------------------------------------------------------------------------------


@dataclass
class TrainingData:
    """Inventario, split verificado y caché; los estudios se leen de la caché de uno en uno."""

    config: TrainConfig
    records: dict[str, dict[str, Any]]
    splits: dict[str, Any]
    train_ids: list[str]
    val_ids: list[str]
    cache: StudyCache

    def load(self, study_id: str) -> PreparedStudy:
        """Entrada de caché verificada (clave, fuentes del inventario y SHA-256 de cada array)."""
        try:
            return self.cache.load(study_id, study_sources(self.records[study_id], self.config.channels))
        except CacheEntryError as exc:
            raise TrainingDataError(f"{exc}. Ejecute `prepare` antes de entrenar.") from exc

    def patient(self, study_id: str) -> str:
        return str(self.records[study_id]["patient"])

    def check_entries_exist(self) -> None:
        """Comprobación barata al empezar: existe una entrada por estudio (el contenido se verifica al leerlo)."""
        missing = [sid for sid in (*self.train_ids, *self.val_ids) if not self.cache.path(sid).is_file()]
        if missing:
            raise TrainingDataError(
                f"Faltan {len(missing)} estudio(s) en la caché {self.cache.directory}: {missing[:10]}. "
                "Ejecute `prepare` antes de entrenar."
            )


def check_supported(config: TrainConfig) -> None:
    """Límites de FT3 que se rechazan explícitamente en lugar de ignorarse."""
    if config.preprocess.num_workers != 0:
        raise ConfigError("preprocess.num_workers debe ser 0: el trainer lee la caché en el proceso principal")
    if not config.preprocess.cache_enabled:
        raise ConfigError("train necesita la caché de `prepare` (preprocess.cache_enabled = true)")


def load_training_data(config: TrainConfig) -> TrainingData:
    """Lee el inventario y `splits.json` y exige que el split sea el que se calcularía hoy (sin redistribuir)."""
    work = config.paths.work_dir
    inventory, splits_path = work / "inventory.jsonl", work / "splits.json"
    try:
        records = read_inventory(inventory)
        splits = load_splits(splits_path)
        expected = build_splits(records, config.split)
    except (InventoryError, SplitError) as exc:
        raise TrainingDataError(str(exc)) from exc
    if expected["split_sha256"] != splits["split_sha256"]:
        raise TrainingDataError(
            f"{splits_path} no corresponde al inventario y la configuración actuales (split_sha256 distinto). "
            "Un split no se redistribuye: revise el inventario o use otro work_dir."
        )
    by_id = {r["study_id"]: r for r in records if r.get("eligible") is True}
    parts = splits["partitions"]
    train_ids, val_ids = list(parts["train"]["studies"]), list(parts["val"]["studies"])
    if not train_ids or not val_ids:
        raise TrainingDataError("Las particiones train y val no pueden estar vacías")
    unknown = [sid for sid in (*train_ids, *val_ids) if sid not in by_id]
    if unknown:
        raise TrainingDataError(f"El split menciona estudios que no son elegibles en el inventario: {unknown[:10]}")
    return TrainingData(config, by_id, splits, train_ids, val_ids, StudyCache.from_config(config))


# ---------------------------------------------------------------------------------------------------------------
# Dispositivo y determinismo
# ---------------------------------------------------------------------------------------------------------------


def resolve_device(config: TrainConfig) -> "torch.device":
    """`cuda` exige una GPU disponible; nunca se degrada a CPU en silencio."""
    import torch

    if config.training.device == "cuda":
        if not torch.cuda.is_available():
            raise DeviceUnavailableError(
                "training.device = 'cuda', pero CUDA no está disponible (ver `python -m cerberus_training device`)"
            )
        return torch.device("cuda")
    return torch.device("cpu")


def determinism_limits(config: TrainConfig, device: "torch.device") -> list[str]:
    """Límites conocidos de reproducibilidad en este dispositivo (se guardan en `provenance.json`)."""
    import torch

    limits = [
        f"Reproducible solo con las mismas versiones de torch/MONAI/numpy, plataforma y número de hilos "
        f"(torch.get_num_threads() = {torch.get_num_threads()}).",
    ]
    if not config.seeds.deterministic:
        limits.append("seeds.deterministic = false: no se fuerzan algoritmos deterministas.")
    if device.type == "cpu":
        limits.append("CPU: torch.use_deterministic_algorithms(True); reanudar da pesos idénticos bit a bit.")
    else:
        limits.extend(
            [
                "CUDA: use_deterministic_algorithms(True, warn_only=True); el backward del upsample trilineal de "
                "SegResNet no tiene implementación determinista, así que dos ejecuciones pueden diferir.",
                "CUDA: cudnn.deterministic = True, cudnn.benchmark = False, CUBLAS_WORKSPACE_CONFIG = :4096:8.",
            ]
        )
        if config.training.amp:
            limits.append("AMP (float16) añade variación numérica y pasos saltados por GradScaler.")
    return limits


def seed_all(seed: int) -> None:
    import torch

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)  # también siembra CUDA


@contextmanager
def deterministic_mode(config: TrainConfig, device: "torch.device") -> Iterator[None]:
    """Activa algoritmos deterministas durante el bloque y restaura al salir **todo** el estado global tocado.

    Se restauran los generadores de Python, NumPy, PyTorch y CUDA (el bloque los siembra), los modos deterministas de
    torch/cuDNN y `CUBLAS_WORKSPACE_CONFIG`: quien llama a `run_training`/`dry_run` no ve efectos secundarios.
    """
    import torch

    previous = (torch.are_deterministic_algorithms_enabled(), torch.is_deterministic_algorithms_warn_only_enabled())
    cudnn = (torch.backends.cudnn.deterministic, torch.backends.cudnn.benchmark)
    rngs = rng_state()
    cublas = os.environ.get("CUBLAS_WORKSPACE_CONFIG")
    if config.seeds.deterministic:
        if device.type == "cuda":
            os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
        torch.use_deterministic_algorithms(True, warn_only=device.type == "cuda")
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
    try:
        yield
    finally:
        torch.use_deterministic_algorithms(previous[0], warn_only=previous[1])
        torch.backends.cudnn.deterministic, torch.backends.cudnn.benchmark = cudnn
        set_rng_state(rngs)
        if cublas is None:
            os.environ.pop("CUBLAS_WORKSPACE_CONFIG", None)
        else:
            os.environ["CUBLAS_WORKSPACE_CONFIG"] = cublas


def rng_state() -> dict[str, Any]:
    """Estados de Python, NumPy y PyTorch en tipos que `torch.load(weights_only=True)` acepta."""
    import torch

    name, keys, pos, has_gauss, cached = np.random.get_state(legacy=True)
    return {
        "python": random.getstate(),
        "numpy": {
            "bit_generator": str(name),
            "keys": torch.from_numpy(np.asarray(keys, dtype=np.int64)),
            "pos": int(pos),
            "has_gauss": int(has_gauss),
            "cached_gaussian": float(cached),
        },
        "torch": torch.get_rng_state(),
        "cuda": torch.cuda.get_rng_state_all() if torch.cuda.is_available() else None,
    }


def set_rng_state(state: dict[str, Any]) -> None:
    import torch

    random.setstate(state["python"])
    npy = state["numpy"]
    np.random.set_state(
        (
            npy["bit_generator"],
            npy["keys"].numpy().astype(np.uint32),
            npy["pos"],
            npy["has_gauss"],
            npy["cached_gaussian"],
        )
    )
    torch.set_rng_state(state["torch"])
    if state.get("cuda") is not None and torch.cuda.is_available():
        torch.cuda.set_rng_state_all(state["cuda"])


# ---------------------------------------------------------------------------------------------------------------
# Pérdida, época y validación
# ---------------------------------------------------------------------------------------------------------------


def make_loss(config: TrainConfig) -> Callable[["torch.Tensor", "torch.Tensor"], "torch.Tensor"]:
    """`dice_weight · Dice(sigmoid) + bce_weight · BCE con logits`."""
    from monai.losses.dice import DiceLoss
    from torch import nn

    training = config.training
    dice_loss = DiceLoss(sigmoid=True)
    bce_loss = nn.BCEWithLogitsLoss()

    def loss(logits: "torch.Tensor", target: "torch.Tensor") -> "torch.Tensor":
        return training.dice_weight * dice_loss(logits, target) + training.bce_weight * bce_loss(logits, target)

    return loss


def epoch_order(study_ids: list[str], seed: int, epoch: int) -> list[str]:
    """Orden de los estudios de entrenamiento en una época (independiente de cualquier estado global)."""
    perm = np.random.default_rng((seed, epoch)).permutation(len(study_ids))
    return [study_ids[int(i)] for i in perm]


def _trainable(model: "nn.Module") -> list["torch.nn.Parameter"]:
    return [p for p in model.parameters() if p.requires_grad]


def _grads_finite(params: list["torch.nn.Parameter"]) -> bool:
    import torch

    return all(p.grad is None or bool(torch.isfinite(p.grad).all()) for p in params)


@dataclass
class EpochStats:
    loss: float
    step: int
    batches: int
    amp_skipped_steps: int


def train_epoch(
    model: "nn.Module",
    optimizer: "torch.optim.Optimizer",
    scaler: "torch.amp.GradScaler | None",
    loss_fn: Callable[["torch.Tensor", "torch.Tensor"], "torch.Tensor"],
    data: TrainingData,
    epoch: int,
    step: int,
    device: "torch.device",
) -> EpochStats:
    """Una época de parches con acumulación de gradiente; devuelve la pérdida media y el paso global."""
    import torch

    config = data.config
    pre, seeds = config.preprocess, config.seeds
    amp = scaler is not None and device.type == "cuda"
    params = _trainable(model)
    order = epoch_order(data.train_ids, seeds.training, epoch)
    batches = [order[i : i + pre.batch_size] for i in range(0, len(order), pre.batch_size)]
    model.train()
    optimizer.zero_grad(set_to_none=True)
    losses: list[float] = []
    skipped = 0
    window_start, window = 0, min(pre.grad_accum_steps, len(batches))
    for b, batch_ids in enumerate(batches):
        images, labels = [], []
        for j, study_id in enumerate(batch_ids):
            study = data.load(study_id)
            image, label = train_sample(study, pre, make_rng(seeds.augmentation, epoch, b * pre.batch_size + j))
            del study  # un estudio en memoria a la vez
            images.append(image)
            labels.append(label)
        x = torch.from_numpy(np.stack(images)).to(device)
        y = torch.from_numpy(np.stack(labels)[:, None].astype(np.float32)).to(device)
        with torch.autocast(device.type, dtype=torch.float16, enabled=amp):
            logits = model(x)
        loss = loss_fn(logits.float(), y)
        if not bool(torch.isfinite(loss)):
            raise TrainingError(
                f"Pérdida no finita ({float(loss.detach())}) en la época {epoch}, lote {b} (estudios {batch_ids})"
            )
        scaled = loss / window
        if scaler is not None:
            scaler.scale(scaled).backward()
        else:
            scaled.backward()
        losses.append(float(loss.detach()))
        if b - window_start + 1 == window:
            if scaler is not None:
                scaler.unscale_(optimizer)
                if not _grads_finite(params):
                    skipped += 1  # GradScaler salta el paso y reduce la escala
                scaler.step(optimizer)
                scaler.update()
            else:
                if not _grads_finite(params):
                    raise TrainingError(f"Gradiente no finito en la época {epoch}, paso {step}")
                optimizer.step()
            optimizer.zero_grad(set_to_none=True)
            step += 1
            window_start = b + 1
            window = min(pre.grad_accum_steps, len(batches) - window_start)
    return EpochStats(loss=float(np.mean(losses)), step=step, batches=len(batches), amp_skipped_steps=skipped)


def macro_patient_dice(per_study: dict[str, float], patient_of: Callable[[str], str]) -> dict[str, Any]:
    """Media de los tiempos dentro de cada paciente y después media de pacientes."""
    by_patient: dict[str, list[float]] = {}
    for study_id, value in sorted(per_study.items()):
        by_patient.setdefault(patient_of(study_id), []).append(value)
    per_patient = {p: float(np.mean(v)) for p, v in sorted(by_patient.items())}
    return {
        "val_dice": float(np.mean(list(per_patient.values()))),
        "val_dice_per_patient": per_patient,
        "val_studies": len(per_study),
        "val_patients": len(per_patient),
    }


def predict_volume(model: "nn.Module", image: np.ndarray, config: TrainConfig, device: "torch.device") -> np.ndarray:
    """Probabilidades GTV de un volumen completo `[4, X, Y, Z]` por ventana deslizante (sin augmentations)."""
    import torch
    from monai.inferers.utils import sliding_window_inference

    amp = config.training.amp and device.type == "cuda"
    x = torch.from_numpy(np.ascontiguousarray(image, dtype=np.float32))[None].to(device)
    with torch.no_grad(), torch.autocast(device.type, dtype=torch.float16, enabled=amp):
        logits = sliding_window_inference(
            x, roi_size=config.preprocess.patch_size, sw_batch_size=SW_BATCH_SIZE, predictor=model, overlap=VAL_OVERLAP
        )
    if not isinstance(logits, torch.Tensor):
        raise TrainingError("sliding_window_inference no devolvió un tensor")
    prob = torch.sigmoid(logits.float())[0, 0].cpu().numpy()
    if not np.isfinite(prob).all():
        raise TrainingError("La predicción de validación contiene NaN/Inf")
    return prob


def validate(model: "nn.Module", data: TrainingData, device: "torch.device") -> dict[str, Any]:
    """Dice macro por paciente sobre los volúmenes completos de `val` (umbral `training.threshold`)."""
    from cerberus_api.segmentation import dice

    model.eval()
    per_study: dict[str, float] = {}
    for study_id in data.val_ids:
        image, label, _geometry = eval_sample(data.load(study_id))
        prob = predict_volume(model, image, data.config, device)
        per_study[study_id] = dice(prob > data.config.training.threshold, label)
    return macro_patient_dice(per_study, data.patient)


# ---------------------------------------------------------------------------------------------------------------
# Compatibilidad, procedencia y checkpoints
# ---------------------------------------------------------------------------------------------------------------


# Campos que no cambian el experimento (rutas y límites de recursos): no entran en la huella de reanudación.
# `weights.path` ya queda fijado por `weights_sha256`.
RESOURCE_FIELDS: tuple[tuple[str, str], ...] = (
    ("weights", "path"),
    ("preprocess", "cache_enabled"),
    ("preprocess", "cache_limit_gb"),
    ("preprocess", "min_free_disk_gb"),
    ("preprocess", "num_workers"),
)
# Campos que pueden **subir** (nunca bajar) al reanudar; el cambio queda registrado como evento en metrics.jsonl.
EXTENDABLE_FIELDS: tuple[tuple[str, str], ...] = (
    ("training", "max_epochs"),
    ("training", "early_stopping_patience"),
)


def relevant_config(config: TrainConfig) -> dict[str, Any]:
    """Configuración que define el experimento: todo salvo `paths`, los límites de recursos (`RESOURCE_FIELDS`) y
    los campos ampliables (`EXTENDABLE_FIELDS`, que se comparan aparte). Los datos quedan fijados por los hashes de
    inventario, split y caché."""
    data = config.model_dump(mode="json")
    data.pop("paths")
    for section, key in (*RESOURCE_FIELDS, *EXTENDABLE_FIELDS):
        data[section].pop(key)
    return data


def compat_fingerprint(config: TrainConfig, data: TrainingData, spec: ModelSpec) -> dict[str, Any]:
    """Lo que debe coincidir para reanudar: etiquetas, canales, arquitectura, datos, split, pesos y configuración."""
    return {
        "task": config.task,
        "label": config.channels.label,
        "channel_order": list(config.channels.order),
        "in_channels": spec.in_channels,
        "out_channels": ADAPTED_OUT_CHANNELS,
        "model": spec.name,
        "head": spec.head,
        "split_sha256": data.splits["split_sha256"],
        "eligible_records_sha256": data.splits["eligible_records_sha256"],
        "cache_key": data.cache.key,
        "weights_sha256": config.weights.sha256,
        "config_sha256": canonical_hash(relevant_config(config)),
    }


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            out.update(_flatten(item, f"{prefix}{key}."))
        return out
    return {prefix.rstrip("."): value}


def _stored_config(checkpoint: dict[str, Any]) -> dict[str, Any]:
    try:
        data = json.loads(checkpoint["config"])
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ResumeError("El checkpoint no contiene una configuración legible") from exc
    if not isinstance(data, dict):
        raise ResumeError("El checkpoint no contiene una configuración legible")
    return data


def check_resume_compat(
    checkpoint: dict[str, Any], current: dict[str, Any], config: TrainConfig
) -> dict[str, dict[str, Any]]:
    """Rechaza reanudar si cambió algo relevante (el mensaje nombra cada diferencia).

    Devuelve los campos ampliables que subieron (`{"training.max_epochs": {"from": 3, "to": 5}}`); bajarlos se rechaza.
    """
    stored = checkpoint.get("compat")
    if not isinstance(stored, dict):
        raise ResumeError("El checkpoint no tiene huella de compatibilidad")
    old_config = _stored_config(checkpoint)
    diffs = [k for k in sorted(set(stored) | set(current)) if stored.get(k) != current.get(k)]
    if diffs:
        detail = ""
        if "config_sha256" in diffs:
            new_config = config.model_dump(mode="json")
            old = _flatten({k: v for k, v in old_config.items() if k != "paths"})
            new = _flatten({k: v for k, v in new_config.items() if k != "paths"})
            ignored = {f"{a}.{b}" for a, b in (*RESOURCE_FIELDS, *EXTENDABLE_FIELDS)}
            changed = sorted(k for k in set(old) | set(new) if old.get(k) != new.get(k) and k not in ignored)
            if changed:
                detail = f" (configuración: {', '.join(changed[:10])})"
        raise ResumeError(f"No se puede reanudar: el checkpoint difiere en {', '.join(diffs)}{detail}")
    overrides: dict[str, dict[str, Any]] = {}
    current_config = config.model_dump(mode="json")
    for section, key in EXTENDABLE_FIELDS:
        before = old_config.get(section, {}).get(key)
        after = current_config[section][key]
        if not isinstance(before, int) or after < before:
            raise ResumeError(f"No se puede reanudar: {section}.{key} solo puede subir ({before} → {after})")
        if after != before:
            overrides[f"{section}.{key}"] = {"from": before, "to": after}
    return overrides


def default_run_id(config: TrainConfig) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{canonical_hash(relevant_config(config))[:8]}"


def build_provenance(
    config: TrainConfig,
    data: TrainingData,
    compat: dict[str, Any],
    transfer: TransferReport,
    device: "torch.device",
    run_id: str,
) -> dict[str, Any]:
    from cerberus_training.device import probe_device

    return {
        "schema_version": PROVENANCE_SCHEMA_VERSION,
        "run_id": run_id,
        "created_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git": git_state(),
        "environment": environment(),
        "device": {"selected": str(device), "report": asdict(probe_device())},
        "determinism_limits": determinism_limits(config, device),
        "seeds": config.seeds.model_dump(mode="json"),
        "hashes": {
            "eligible_records_sha256": compat["eligible_records_sha256"],
            "split_sha256": compat["split_sha256"],
            "weights_sha256": compat["weights_sha256"],
            "cache_key": compat["cache_key"],
            "config_sha256": compat["config_sha256"],
        },
        "data": {
            "train_studies": len(data.train_ids),
            "val_studies": len(data.val_ids),
            "train_patients": len({data.patient(s) for s in data.train_ids}),
            "val_patients": len({data.patient(s) for s in data.val_ids}),
            "pretraining_overlap": data.splits["pretraining_overlap"],
        },
        "transfer": transfer.to_json(),
    }


@dataclass
class LoopState:
    """Estado que se guarda en `last.pt` al final de cada época."""

    epoch: int = 0  # épocas completadas (= índice de la siguiente)
    step: int = 0  # pasos de optimizador
    best_metric: float | None = None
    best_epoch: int | None = None
    epochs_without_improvement: int = 0  # validaciones seguidas sin mejora
    finished: bool = False
    stop_reason: str | None = None
    history: list[dict[str, Any]] = field(default_factory=list)


def _last_payload(
    model: "nn.Module",
    optimizer: "torch.optim.Optimizer",
    scaler: "torch.amp.GradScaler | None",
    state: LoopState,
    config: TrainConfig,
    compat: dict[str, Any],
    transfer: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "kind": "last",
        "model": model.state_dict(),
        "optimizer": optimizer.state_dict(),
        "scheduler": None,  # no hay scheduler configurado en FT3
        "scaler": scaler.state_dict() if scaler is not None else None,
        "epoch": state.epoch,
        "step": state.step,
        "best_metric": state.best_metric,
        "best_epoch": state.best_epoch,
        "early_stopping": {
            "epochs_without_improvement": state.epochs_without_improvement,
            "patience": config.training.early_stopping_patience,
        },
        "finished": state.finished,
        "stop_reason": state.stop_reason,
        "rng": rng_state(),
        "config": dump_config(config),
        "compat": compat,
        "hashes": {k: compat[k] for k in ("eligible_records_sha256", "split_sha256", "weights_sha256", "cache_key")},
        "metrics_history": json.dumps(state.history, sort_keys=True),
        "transfer": json.dumps(transfer, sort_keys=True),
    }


def _best_payload(
    model: "nn.Module", state: LoopState, config: TrainConfig, compat: dict[str, Any], transfer: dict[str, Any]
) -> dict[str, Any]:
    return {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "kind": "best",
        "model": model.state_dict(),
        "epoch": state.best_epoch,
        "metric": {"name": "val_dice_macro_patient", "value": state.best_metric},
        "threshold": config.training.threshold,
        "config": dump_config(config),
        "compat": compat,
        "transfer": json.dumps(transfer, sort_keys=True),
    }


def load_checkpoint(path: Path, kind: str) -> dict[str, Any]:
    """Lee un checkpoint propio con `weights_only=True` y comprueba esquema y tipo."""
    import torch

    try:
        payload = torch.load(path, map_location="cpu", weights_only=True)
    except Exception as exc:
        raise ResumeError(f"No se pudo leer el checkpoint {path}: {type(exc).__name__}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != CHECKPOINT_SCHEMA_VERSION:
        raise ResumeError(f"{path}: checkpoint con esquema no soportado (se espera {CHECKPOINT_SCHEMA_VERSION})")
    if payload.get("kind") != kind:
        raise ResumeError(f"{path}: se esperaba un checkpoint '{kind}' y es '{payload.get('kind')}'")
    return payload


def _resume_paths(last: Path, config: TrainConfig) -> RunPaths:
    """El checkpoint debe ser `<work_dir>/runs/<run_id>/checkpoints/last.pt` de esta configuración."""
    resolved = last.resolve()
    paths = RunPaths(resolved.parent.parent)
    if resolved != paths.last or not resolved.is_file():
        raise ResumeError(f"--resume debe apuntar a runs/<run_id>/checkpoints/last.pt (recibido {last})")
    if paths.root.parent != (config.paths.work_dir / "runs").resolve():
        raise ResumeError(f"El run {paths.root} no está en {config.paths.work_dir / 'runs'}")
    if not paths.config.is_file() or not paths.metrics.is_file():
        raise ResumeError(f"El run {paths.root} está incompleto (faltan config.resolved.json o metrics.jsonl)")
    return paths


# ---------------------------------------------------------------------------------------------------------------
# Bucle principal
# ---------------------------------------------------------------------------------------------------------------


@dataclass
class TrainResult:
    run_dir: Path
    epochs_completed: int
    step: int
    best_metric: float | None
    best_epoch: int | None
    finished: bool
    stop_reason: str | None
    resumed_from: int | None = None


def _make_optimizer(model: "nn.Module", config: TrainConfig) -> "torch.optim.Optimizer":
    import torch

    training = config.training
    return torch.optim.AdamW(_trainable(model), lr=training.learning_rate, weight_decay=training.weight_decay)


def _make_scaler(config: TrainConfig, device: "torch.device") -> "torch.amp.GradScaler | None":
    import torch

    if config.training.amp and device.type == "cuda":
        return torch.amp.GradScaler("cuda")
    return None


def _reconcile_best(paths: RunPaths, state: LoopState, log: LogFn) -> dict[str, Any] | None:
    """Coherencia de `best.pt` con `last.pt` al reanudar.

    `best.pt` se escribe antes que `last.pt`; un corte entre ambos deja un `best.pt` de una época que `last.pt` no
    registra. Ese archivo se aparta como `best.orphan-epoch<N>.pt` (no se borra) y la repetición de la época lo
    regenera si vuelve a mejorar (en CPU, de forma idéntica). Devuelve el evento a registrar, o `None`.
    """
    if not paths.best.is_file():
        if state.best_epoch is None:
            return None
        log(f"AVISO: falta {paths.best} aunque last.pt registra la mejor época {state.best_epoch}")
        return {"event": "best_missing", "epoch": state.epoch, "last_best_epoch": state.best_epoch}
    best_epoch = load_checkpoint(paths.best, "best").get("epoch")
    if best_epoch == state.best_epoch:
        return None
    orphan = paths.checkpoints / f"best.orphan-epoch{best_epoch}.pt"
    os.replace(paths.best, orphan)
    log(
        f"AVISO: best.pt era de la época {best_epoch} y last.pt registra {state.best_epoch} (corte entre ambos); "
        f"se apartó como {orphan.name} y se regenerará al repetir las épocas"
    )
    return {
        "event": "best_orphaned",
        "epoch": state.epoch,
        "best_pt_epoch": best_epoch,
        "last_best_epoch": state.best_epoch,
        "moved_to": orphan.name,
    }


def _unfinish(state: LoopState, config: TrainConfig) -> None:
    """Tras subir `max_epochs` o la paciencia, un run terminado por ese motivo vuelve a estar abierto."""
    training = config.training
    if state.stop_reason == "max_epochs" and state.epoch < training.max_epochs:
        state.finished, state.stop_reason = False, None
    elif state.stop_reason == "early_stopping" and state.epochs_without_improvement < training.early_stopping_patience:
        state.finished, state.stop_reason = False, None


def run_training(
    config: TrainConfig,
    *,
    run_id: str | None = None,
    resume: Path | None = None,
    spec: ModelSpec | None = None,
    stop_after_epochs: int | None = None,
    log: LogFn = _no_log,
) -> TrainResult:
    """Entrena (o reanuda) un run. `config` debe estar resuelta (`resolve_config`).

    `stop_after_epochs` detiene la sesión tras ese número de épocas, como una interrupción en límite de época (los
    tests lo usan para comprobar la equivalencia de la reanudación). El run queda protegido por un candado `.lock`.
    """
    import torch

    spec = spec or segresnet_spec()
    check_supported(config)
    device = resolve_device(config)
    data = load_training_data(config)
    data.check_entries_exist()
    compat = compat_fingerprint(config, data, spec)
    with deterministic_mode(config, device), ExitStack() as stack:
        seed_all(config.seeds.training)
        resumed_from: int | None = None
        if resume is not None:
            paths = _resume_paths(resume, config)
            stack.enter_context(run_lock(paths))
            checkpoint = load_checkpoint(paths.last, "last")
            overrides = check_resume_compat(checkpoint, compat, config)
            model = build_adapted_model(config, spec)
            load_strict(model, checkpoint["model"], str(paths.last))
            model.to(device)
            optimizer = _make_optimizer(model, config)
            optimizer.load_state_dict(checkpoint["optimizer"])
            scaler = _make_scaler(config, device)
            if scaler is not None and checkpoint.get("scaler") is not None:
                scaler.load_state_dict(checkpoint["scaler"])
            state = LoopState(
                epoch=int(checkpoint["epoch"]),
                step=int(checkpoint["step"]),
                best_metric=checkpoint["best_metric"],
                best_epoch=checkpoint["best_epoch"],
                epochs_without_improvement=int(checkpoint["early_stopping"]["epochs_without_improvement"]),
                finished=bool(checkpoint["finished"]),
                stop_reason=checkpoint["stop_reason"],
                history=json.loads(checkpoint["metrics_history"]),
            )
            transfer = json.loads(checkpoint["transfer"])
            set_rng_state(checkpoint["rng"])
            event = _reconcile_best(paths, state, log)
            if event is not None:
                state.history.append(event)
            if overrides:
                state.history.append({"event": "resume_override", "epoch": state.epoch, "changes": overrides})
                log(f"Cambios explícitos al reanudar: {overrides}")
                _unfinish(state, config)
            rewrite_jsonl(paths.metrics, state.history)  # descarta líneas de épocas posteriores al checkpoint
            resumed_from = state.epoch
            log(f"Reanudando {paths.root.name} desde la época {state.epoch} (paso {state.step})")
            if state.finished:
                log(f"El run ya había terminado ({state.stop_reason}); no hay nada que reanudar.")
        else:
            model, report = build_transfer_model(config, spec)
            model.to(device)
            transfer = report.to_json()
            optimizer = _make_optimizer(model, config)
            scaler = _make_scaler(config, device)
            state = LoopState()
            run_id = run_id or default_run_id(config)
            paths = create_run_dir(config.paths.work_dir, run_id)
            try:
                stack.enter_context(run_lock(paths))
                write_json_once(paths.config, json.loads(dump_config(config)))
                write_json_once(paths.provenance, build_provenance(config, data, compat, report, device, run_id))
                paths.metrics.touch(exist_ok=False)
            except BaseException:
                remove_run_dir(paths)  # nunca queda un run a medias sin config/procedencia
                raise
            log(
                f"Run {run_id}: {report.transferred_numel} parámetros transferidos, {report.new_numel} nuevos "
                f"({spec.head}), {report.frozen_numel} congelados; dispositivo {device}"
            )
        loss_fn = make_loss(config)
        training = config.training
        session_epochs = 0
        try:
            while not state.finished:
                if stop_after_epochs is not None and session_epochs >= stop_after_epochs:
                    break
                epoch = state.epoch
                started = time.monotonic()
                stats = train_epoch(model, optimizer, scaler, loss_fn, data, epoch, state.step, device)
                state.step = stats.step
                record: dict[str, Any] = {
                    "epoch": epoch,
                    "step": stats.step,
                    "train_loss": stats.loss,
                    "train_batches": stats.batches,
                    "lr": training.learning_rate,
                    "amp_skipped_steps": stats.amp_skipped_steps,
                }
                last_epoch = epoch + 1 >= training.max_epochs
                if (epoch + 1) % training.validate_every == 0 or last_epoch:
                    record.update(validate(model, data, device))
                    improved = state.best_metric is None or record["val_dice"] > state.best_metric
                    if improved:
                        state.best_metric, state.best_epoch = float(record["val_dice"]), epoch
                        state.epochs_without_improvement = 0
                    else:
                        state.epochs_without_improvement += 1
                    record.update(
                        improved=improved,
                        best_val_dice=state.best_metric,
                        best_epoch=state.best_epoch,
                        epochs_without_improvement=state.epochs_without_improvement,
                    )
                    if improved:
                        atomic_torch_save(_best_payload(model, state, config, compat, transfer), paths.best)
                state.epoch = epoch + 1
                if state.epochs_without_improvement >= training.early_stopping_patience:
                    state.finished, state.stop_reason = True, "early_stopping"
                elif last_epoch:
                    state.finished, state.stop_reason = True, "max_epochs"
                record["seconds"] = round(time.monotonic() - started, 3)
                state.history.append(record)
                atomic_torch_save(_last_payload(model, optimizer, scaler, state, config, compat, transfer), paths.last)
                append_jsonl(paths.metrics, record)
                session_epochs += 1
                val = f", val Dice {record['val_dice']:.4f}" if "val_dice" in record else ""
                log(f"  época {epoch}: pérdida {stats.loss:.4f}{val}")
        except (torch.OutOfMemoryError, MemoryError) as exc:
            raise ResourceError(
                f"Memoria insuficiente durante el entrenamiento ({type(exc).__name__}). No se reduce el batch ni el "
                "parche automáticamente: ajuste preprocess.patch_size/batch_size a conciencia y reanude."
            ) from exc
    return TrainResult(
        run_dir=paths.root,
        epochs_completed=state.epoch,
        step=state.step,
        best_metric=state.best_metric,
        best_epoch=state.best_epoch,
        finished=state.finished,
        stop_reason=state.stop_reason,
        resumed_from=resumed_from,
    )


# ---------------------------------------------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------------------------------------------


@dataclass
class DryRunReport:
    device: str
    train_studies: int
    val_studies: int
    train_patients: int
    val_patients: int
    max_prepared_shape: tuple[int, int, int]
    transfer: TransferReport
    output_shape: tuple[int, ...]
    val_volume_shape: tuple[int, ...]
    state_sha256: str
    checkpoint_bytes: int
    free_bytes: int
    determinism: list[str]
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def state_digest(model: "nn.Module") -> str:
    """SHA-256 de todos los tensores del state_dict (en orden de llave)."""
    import hashlib

    digest = hashlib.sha256()
    for key, tensor in sorted(model.state_dict().items()):
        digest.update(key.encode())
        digest.update(tensor.detach().cpu().contiguous().numpy().tobytes())
    return digest.hexdigest()


def dry_run(config: TrainConfig, *, spec: ModelSpec | None = None, log: LogFn = _no_log) -> DryRunReport:
    """Valida configuración, dispositivo, inventario, split, caché completa, pesos (SHA-256 y carga estricta) y disco.

    Hace un forward sin gradiente de un parche y una predicción por ventana deslizante del primer volumen de val; no
    hay backward, no se actualiza ningún peso, no se crea el run y no
    se descarga nada. Comprueba que el state_dict no cambió.
    """
    import torch

    spec = spec or segresnet_spec()
    check_supported(config)
    device = resolve_device(config)
    data = load_training_data(config)
    max_shape = (0, 0, 0)
    for study_id in (*data.train_ids, *data.val_ids):
        study = data.load(study_id)  # verificación completa de la entrada
        shape = study.geometry.prepared_shape
        if math.prod(shape) > math.prod(max_shape):
            max_shape = shape
        del study
    log(f"Caché verificada: {len(data.train_ids)} estudios de train y {len(data.val_ids)} de val")
    with deterministic_mode(config, device):
        seed_all(config.seeds.training)
        model, transfer = build_transfer_model(config, spec)
        log(f"Pesos verificados ({config.weights.sha256[:12]}…) y cargados con strict=True; cabeza {spec.head}")
        model.to(device).eval()
        before = state_digest(model)
        image, _label = train_sample(
            data.load(data.train_ids[0]), config.preprocess, make_rng(config.seeds.augmentation, 0, 0)
        )
        amp = config.training.amp and device.type == "cuda"
        try:
            with torch.no_grad(), torch.autocast(device.type, dtype=torch.float16, enabled=amp):
                out = model(torch.from_numpy(image[None]).to(device))
        except (torch.OutOfMemoryError, MemoryError) as exc:
            raise ResourceError(f"Memoria insuficiente en el forward de prueba ({type(exc).__name__})") from exc
        expected = (1, ADAPTED_OUT_CHANNELS, *config.preprocess.patch_size)
        if tuple(out.shape) != expected:
            raise CheckpointError(f"La red devuelve {tuple(out.shape)} y se esperaba {expected}")
        if not bool(torch.isfinite(out).all()):
            raise TrainingError("El forward de prueba produjo NaN/Inf")
        try:  # validación por ventana deslizante sobre el primer volumen de val (puede ser mayor que el parche)
            val_image, _val_label, _geometry = eval_sample(data.load(data.val_ids[0]))
            val_prob = predict_volume(model, val_image, config, device)
        except (torch.OutOfMemoryError, MemoryError) as exc:
            raise ResourceError(f"Memoria insuficiente en la validación de prueba ({type(exc).__name__})") from exc
        if val_prob.shape != val_image.shape[1:]:
            raise TrainingError(
                f"La ventana deslizante devolvió {val_prob.shape} para un volumen {val_image.shape[1:]}"
            )
        after = state_digest(model)
        if after != before:
            raise TrainingError("El dry-run modificó los pesos (no debería ocurrir)")
        determinism = determinism_limits(config, device)
    numel = sum(t.numel() for t in model.state_dict().values())
    checkpoint_bytes = int(numel * 4 * CHECKPOINT_TENSOR_COPIES * CHECKPOINT_MARGIN)
    free = free_bytes(config.paths.work_dir)
    min_free = int(config.preprocess.min_free_disk_gb * 1024**3)
    problems = []
    if free - checkpoint_bytes < min_free:
        problems.append(
            f"Espacio libre insuficiente para los checkpoints: quedan {free / 1024**3:.2f} GB, hacen falta "
            f"{checkpoint_bytes / 1024**3:.3f} GB más {config.preprocess.min_free_disk_gb} GB de margen"
        )
    return DryRunReport(
        device=str(device),
        train_studies=len(data.train_ids),
        val_studies=len(data.val_ids),
        train_patients=len({data.patient(s) for s in data.train_ids}),
        val_patients=len({data.patient(s) for s in data.val_ids}),
        max_prepared_shape=max_shape,
        transfer=transfer,
        output_shape=tuple(out.shape),
        val_volume_shape=tuple(val_prob.shape),
        state_sha256=after,
        checkpoint_bytes=checkpoint_bytes,
        free_bytes=free,
        determinism=determinism,
        problems=problems,
    )


def format_dry_run(report: DryRunReport) -> str:
    t = report.transfer
    lines = [
        f"Dispositivo: {report.device}",
        f"Datos: train {report.train_studies} estudios / {report.train_patients} pacientes; "
        f"val {report.val_studies} estudios / {report.val_patients} pacientes; "
        f"mayor volumen preparado {report.max_prepared_shape}",
        f"Modelo {t.model}: {len(t.transferred)} tensores transferidos ({t.transferred_numel} valores), "
        f"{len(t.discarded)} descartados ({t.discarded_numel}), {len(t.new)} nuevos en {t.head} ({t.new_numel}); "
        f"congelados {t.frozen_numel} (módulos {t.frozen_modules or 'ninguno'}), entrenables {t.trainable_numel}",
        f"Forward de prueba sin gradiente: salida {report.output_shape}; ventana deslizante sobre un volumen de val "
        f"{report.val_volume_shape}; "
        f"pesos sin cambios ({report.state_sha256[:12]}…)",
        f"Checkpoints estimados {report.checkpoint_bytes / 1024**2:.1f} MiB; "
        f"libre {report.free_bytes / 1024**3:.2f} GB",
        *(f"Determinismo: {d}" for d in report.determinism),
    ]
    lines.extend(f"PROBLEMA: {p}" for p in report.problems)
    lines.append(
        "Dry-run correcto: sin backward, sin actualizar pesos, sin descargas."
        if report.ok
        else "Dry-run con problemas."
    )
    return "\n".join(lines)
