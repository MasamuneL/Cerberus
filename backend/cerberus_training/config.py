"""Configuración JSON tipada y versionada del pipeline de fine-tuning (docs/PLAN_PIPELINE_FINETUNING.md §3, §5, §6).

Todos los modelos usan `extra="forbid"`: una clave desconocida o mal escrita es un error, nunca se ignora.
Este módulo no importa torch ni MONAI para que `--help` y la validación de la configuración funcionen
sin dependencias pesadas, sin red y sin GPU.
"""

import json
import math
import os
import re
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from cerberus_api.sequences import MRI_SEQS

# Versión del esquema de configuración (campo `schema_version`, obligatorio). Se incrementa ante cambios
# incompatibles; el literal de `TrainConfig.schema_version` debe actualizarse a la vez.
SCHEMA_VERSION = 1

# backend/cerberus_training/config.py → parents[2] = raíz del repo
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = Path("configs/training/gtv_binary.json")

# Orden fijo de canales de entrada del modelo (docs/PLAN_PIPELINE_FINETUNING.md §5).
CHANNEL_ORDER: tuple[str, ...] = ("T1c", "T1", "T2", "FLAIR")
# Perfil estricto: secuencias aceptadas por canal, en orden de preferencia. T2* no sustituye a T2.
STRICT_PREFERENCES: dict[str, tuple[str, ...]] = {
    "T1c": ("t1gd",),
    "T1": ("t1eg", "t1tse"),
    "T2": ("t2tse",),
    "FLAIR": ("flair",),
}

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)


class ConfigError(ValueError):
    """Configuración ilegible o inválida; el mensaje está en español y apto para mostrar al usuario."""


class _Strict(BaseModel):
    """Base: rechaza claves extra y es inmutable (la config resuelta no cambia a mitad de un run)."""

    model_config = ConfigDict(extra="forbid", frozen=True)


PositiveInt = Annotated[int, Field(gt=0)]
PositiveFloat = Annotated[float, Field(gt=0, allow_inf_nan=False)]
NonNegativeInt = Annotated[int, Field(ge=0)]
# Semillas: NumPy exige 0 <= semilla < 2**32 (Python y PyTorch aceptan ese rango).
Seed = Annotated[int, Field(ge=0, lt=2**32)]
# SegResNet con 3 submuestreos (bloques (1,2,2,4)) reduce cada eje por 2**3 = 8: el parche debe ser múltiplo de 8.
PATCH_MULTIPLE = 8


def _reject_empty_path(path: Path) -> Path:
    """`Path("")` equivale a `Path(".")`: una ruta vacía o "." casi siempre es un campo olvidado."""
    if str(path) in ("", "."):
        raise ValueError("La ruta no puede estar vacía ni ser '.'")
    return path


def _norm(path: Path, base: Path) -> Path:
    """Ruta absoluta y normalizada (sin `..` ni symlinks) respecto a `base`."""
    expanded = path.expanduser()
    return (expanded if expanded.is_absolute() else base / expanded).resolve()


def _check_disjoint(data_root: Path, work_dir: Path, base: Path) -> None:
    """`work_dir` no puede ser igual, hijo ni padre de `data_root`: se escribiría sobre datos de solo lectura."""
    data, work = _norm(data_root, base), _norm(work_dir, base)
    if data == work or data in work.parents or work in data.parents:
        raise ValueError(f"work_dir ({work}) no puede coincidir con data_root ({data}) ni estar dentro o contenerlo")


class PathsConfig(_Strict):
    """Rutas: `data_root` es de solo lectura; todo lo generado va bajo `work_dir` (ignorado por Git)."""

    data_root: Path
    work_dir: Path = Path("storage/training")

    @field_validator("data_root", "work_dir")
    @classmethod
    def _check_path(cls, value: Path) -> Path:
        return _reject_empty_path(value)

    @model_validator(mode="after")
    def _check_disjoint_dirs(self) -> Self:
        _check_disjoint(self.data_root, self.work_dir, REPO_ROOT)
        return self


class ChannelsConfig(_Strict):
    """Perfil de canales estricto: orden fijo, preferencias por canal y política explícita para T2*."""

    profile: Literal["strict"] = "strict"
    order: tuple[str, ...] = CHANNEL_ORDER
    reference: Literal["T1c"] = "T1c"
    preferences: dict[str, tuple[str, ...]] = Field(default_factory=lambda: dict(STRICT_PREFERENCES))
    # T2* nunca sustituye a T2 en el perfil estricto; un perfil de compatibilidad sería otro experimento.
    t2star_policy: Literal["disabled"] = "disabled"
    label: Literal["gtv"] = "gtv"

    @model_validator(mode="after")
    def _check_profile(self) -> Self:
        if self.order != CHANNEL_ORDER:
            raise ValueError(f"El orden de canales debe ser exactamente {list(CHANNEL_ORDER)}")
        if set(self.preferences) != set(self.order):
            raise ValueError(f"`preferences` debe definir exactamente los canales {list(self.order)}")
        for channel, candidates in self.preferences.items():
            if not candidates or len(set(candidates)) != len(candidates):
                raise ValueError(f"Canal {channel}: preferencias vacías o repetidas")
            for seq in candidates:
                if seq not in MRI_SEQS:
                    raise ValueError(f"Canal {channel}: secuencia desconocida {seq!r}")
                if seq == "t2star":
                    raise ValueError("T2* no puede usarse en el perfil estricto (t2star_policy='disabled')")
        if self.preferences != STRICT_PREFERENCES:
            raise ValueError(f"El perfil estricto exige las preferencias {STRICT_PREFERENCES}")
        return self


class SplitConfig(_Strict):
    """Partición por paciente: todos los tiempos de un paciente caen en una sola partición."""

    seed: Seed = 42
    train: float = 0.70
    val: float = 0.15
    test: float = 0.15
    group_by: Literal["patient"] = "patient"

    @model_validator(mode="after")
    def _check_ratios(self) -> Self:
        parts = (self.train, self.val, self.test)
        if not all(math.isfinite(p) and 0 < p < 1 for p in parts):
            raise ValueError("Cada proporción del split debe estar en el intervalo abierto (0, 1)")
        if not math.isclose(sum(parts), 1.0, abs_tol=1e-9):
            raise ValueError(f"Las proporciones train/val/test deben sumar 1 (suman {sum(parts):.6f})")
        return self


class PreprocessConfig(_Strict):
    """Preprocesamiento, parches y límites de recursos (docs/PLAN_PIPELINE_FINETUNING.md §5)."""

    spacing_mm: PositiveFloat = 1.0
    orientation: Literal["RAS"] = "RAS"
    brain_mask_policy: Literal["use_if_present"] = "use_if_present"
    patch_size: tuple[PositiveInt, PositiveInt, PositiveInt] = (96, 96, 96)
    batch_size: PositiveInt = 1
    grad_accum_steps: PositiveInt = 4
    # Relación de parches positivos:negativos en entrenamiento (1:1); GTV vacío → solo negativos.
    pos_neg_ratio: tuple[PositiveInt, PositiveInt] = (1, 1)
    num_workers: NonNegativeInt = 0
    cache_enabled: bool = True
    cache_limit_gb: PositiveFloat = 20.0
    # Espacio libre mínimo que `preflight` exigirá además del tamaño estimado de la caché.
    min_free_disk_gb: PositiveFloat = 5.0

    @field_validator("patch_size")
    @classmethod
    def _check_patch(cls, value: tuple[int, int, int]) -> tuple[int, int, int]:
        if any(side % PATCH_MULTIPLE for side in value):
            raise ValueError(
                f"Cada lado del parche debe ser múltiplo de {PATCH_MULTIPLE} (3 submuestreos de SegResNet)"
            )
        return value


class WeightsConfig(_Strict):
    """Pesos iniciales locales. Nunca se descargan en `train`; el SHA-256 esperado es obligatorio."""

    path: Path
    sha256: str
    bundle_name: str = "brats_mri_segmentation"
    bundle_version: str = "0.5.4"

    @field_validator("path")
    @classmethod
    def _check_path(cls, value: Path) -> Path:
        return _reject_empty_path(value)

    @field_validator("sha256")
    @classmethod
    def _check_sha256(cls, value: str) -> str:
        value = value.strip().lower()
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("sha256 debe ser una cadena hexadecimal de 64 caracteres")
        return value


class SeedsConfig(_Strict):
    """Semillas independientes por componente (Python, NumPy, PyTorch y workers derivan de `training`)."""

    training: Seed = 42
    augmentation: Seed = 42
    head_init: Seed = 42
    deterministic: bool = True


class TrainingConfig(_Strict):
    """Hiperparámetros iniciales ajustables; no son un óptimo validado."""

    loss: Literal["dice_bce"] = "dice_bce"
    dice_weight: PositiveFloat = 1.0
    bce_weight: PositiveFloat = 1.0
    optimizer: Literal["adamw"] = "adamw"
    learning_rate: PositiveFloat = 1e-4
    weight_decay: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 1e-5
    max_epochs: PositiveInt = 100
    validate_every: PositiveInt = 1
    early_stopping_patience: PositiveInt = 15
    threshold: Annotated[float, Field(gt=0, lt=1)] = 0.5
    # Prefijos de módulos a congelar; vacío = entrenar toda la red. Se registra en la procedencia del run.
    freeze_modules: tuple[str, ...] = ()
    device: Literal["cpu", "cuda"] = "cpu"
    amp: bool = False

    @field_validator("freeze_modules")
    @classmethod
    def _check_freeze(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not name.strip() for name in value) or len(set(value)) != len(value):
            raise ValueError("freeze_modules no admite nombres vacíos ni repetidos")
        return value

    @model_validator(mode="after")
    def _check_amp(self) -> Self:
        if self.amp and self.device != "cuda":
            raise ValueError("amp solo está soportado con device='cuda'")
        return self


class TrainConfig(_Strict):
    """Raíz de la configuración (`schema_version` permite migrar o rechazar archivos antiguos)."""

    @field_validator("schema_version")
    @classmethod
    def _check_version(cls, value: int) -> int:
        if value != SCHEMA_VERSION:
            raise ValueError(f"schema_version {value} no soportado (esta versión del código espera {SCHEMA_VERSION})")
        return value

    schema_version: int
    task: Literal["gtv_binary"] = "gtv_binary"
    paths: PathsConfig
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    split: SplitConfig = Field(default_factory=SplitConfig)
    preprocess: PreprocessConfig = Field(default_factory=PreprocessConfig)
    weights: WeightsConfig
    training: TrainingConfig = Field(default_factory=TrainingConfig)
    seeds: SeedsConfig = Field(default_factory=SeedsConfig)


def _format_validation_error(path: Path, exc: ValidationError) -> str:
    lines = [f"Configuración inválida en {path}:"]
    for err in exc.errors():
        loc = ".".join(str(part) for part in err["loc"]) or "<raíz>"
        lines.append(f"  - {loc}: {err['msg']}")
    return "\n".join(lines)


def load_config(path: str | Path) -> TrainConfig:
    """Lee y valida un JSON de configuración en modo estricto (sin coerciones: `true` no es 1, `"1e-4"` no es float).

    Lanza `ConfigError` si el archivo falta, no es UTF-8, no es JSON o viola el esquema.
    """
    path = Path(path)
    try:
        raw = path.read_bytes().decode("utf-8")
    except OSError as exc:
        raise ConfigError(f"No se pudo leer la configuración {path}: {exc.strerror or exc}") from exc
    except UnicodeDecodeError as exc:
        raise ConfigError(f"La configuración {path} no está codificada en UTF-8: {exc.reason}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"La configuración {path} no es JSON válido: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"La configuración {path} debe ser un objeto JSON")
    try:
        return TrainConfig.model_validate_json(raw, strict=True)
    except ValidationError as exc:
        raise ConfigError(_format_validation_error(path, exc)) from exc


def resolve_config(config: TrainConfig, base_dir: str | Path = REPO_ROOT) -> TrainConfig:
    """Devuelve una copia con las rutas absolutas y normalizadas (relativas a `base_dir`, por defecto el repo).

    Vuelve a comprobar que `work_dir` y `data_root` sean disjuntos con `base_dir`, que puede diferir del repo.
    """
    base = Path(base_dir)
    try:
        _check_disjoint(config.paths.data_root, config.paths.work_dir, base)
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc
    return config.model_copy(
        update={
            "paths": config.paths.model_copy(
                update={
                    "data_root": _norm(config.paths.data_root, base),
                    "work_dir": _norm(config.paths.work_dir, base),
                }
            ),
            "weights": config.weights.model_copy(update={"path": _norm(config.weights.path, base)}),
        }
    )


def dump_config(config: TrainConfig) -> str:
    """Serializa a JSON canónico (claves en orden de declaración, sangría 2, salto de línea final)."""
    return json.dumps(config.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"


def write_resolved_config(config: TrainConfig, output: str | Path, base_dir: str | Path = REPO_ROOT) -> Path:
    """Escribe la configuración resuelta (permisos 0644). No sobrescribe un archivo existente.

    La creación exclusiva (`O_EXCL`) evita pisar un run creado en paralelo sin depender de hardlinks. Si la
    escritura falla a medias se borra el archivo parcial. Todo `OSError` se reporta como `ConfigError`.
    """
    output = Path(output)
    payload = dump_config(resolve_config(config, base_dir))
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ConfigError(f"No se pudo crear {output.parent}: {exc.strerror or exc}") from exc
    try:
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError as exc:
        raise ConfigError(f"No se sobrescribe un archivo existente: {output}") from exc
    except OSError as exc:
        raise ConfigError(f"No se pudo crear {output}: {exc.strerror or exc}") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
    except OSError as exc:
        output.unlink(missing_ok=True)
        raise ConfigError(f"No se pudo escribir {output}: {exc.strerror or exc}") from exc
    return output
