"""Transferencia de SegResNet de 3 salidas a 1 logit GTV (docs/PLAN_PIPELINE_FINETUNING.md §6, ticket FT3).

Pasos de `build_transfer_model`:

1. Lee el checkpoint local una vez, verifica que su SHA-256 coincida con `weights.sha256` y lo carga desde esos mismos
   bytes (`weights_only=True`). **Nunca se descarga nada.**
2. Construye la red de 3 salidas con la misma arquitectura que la inferencia de la API
   (`cerberus_api/segmentation.py::_monai_predictor`: 4 entradas, 3 salidas, `init_filters=16`,
   `blocks_down=(1,2,2,4)`, `blocks_up=(1,1,1)`, `dropout_prob=0.2`) y carga el checkpoint con `strict=True`.
   Antes compara llaves y shapes para dar un error claro (faltantes, sobrantes, shapes distintos).
3. Reemplaza **solo** la proyección final por una de 1 salida. En MONAI 1.6.1 (verificado en `.venv/`)
   `SegResNet.conv_final` es `Sequential(GroupNorm, ReLU, Convolution(conv=Conv3d(16, 3, k=1)))`, así que la
   capa reemplazada es `conv_final.2` (llaves `conv_final.2.conv.weight` `[3,16,1,1,1]` y `conv_final.2.conv.bias`
   `[3]`). La GroupNorm `conv_final.0` sí se transfiere. La capa nueva se toma de una red idéntica de 1 salida
   construida con la semilla `seeds.head_init` dentro de `torch.random.fork_rng`, de modo que es determinista y no
   altera el generador global.
4. Registra los tensores transferidos, descartados y nuevos (nombres y conteos) y aplica la congelación explícita
   `training.freeze_modules` (prefijos de módulo), que también se registra.

torch y MONAI se importan dentro de las funciones: importar este módulo no carga dependencias pesadas.
"""

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cerberus_training.config import TrainConfig

if TYPE_CHECKING:
    import torch
    from torch import nn

# Arquitectura del bundle `brats_mri_segmentation` tal como la construye la inferencia de la API.
SEGRESNET_KWARGS: dict[str, Any] = {
    "spatial_dims": 3,
    "init_filters": 16,
    "in_channels": 4,
    "blocks_down": (1, 2, 2, 4),
    "blocks_up": (1, 1, 1),
    "dropout_prob": 0.2,
}
PRETRAINED_OUT_CHANNELS = 3  # TC, WT, ET del bundle
ADAPTED_OUT_CHANNELS = 1  # un logit GTV
# Proyección final real de SegResNet en MONAI 1.6.1 (ver docstring del módulo).
SEGRESNET_HEAD = "conv_final.2"
# Máximo de llaves listadas en un mensaje de incompatibilidad (el resto se resume con un conteo).
MAX_LISTED_KEYS = 10


class WeightsError(ValueError):
    """Pesos ausentes, con SHA-256 distinto del esperado o con un formato no válido."""


class CheckpointError(ValueError):
    """Checkpoint incompatible con la arquitectura (llaves faltantes/sobrantes o shapes distintos)."""


@dataclass(frozen=True)
class ModelSpec:
    """Arquitectura inyectable: `build(out_channels)` construye la red y `head` es la ruta de su proyección final.

    La red real es `segresnet_spec()`; los tests inyectan una red pequeña con la misma interfaz.
    """

    name: str
    build: Callable[[int], "nn.Module"]
    head: str
    in_channels: int = 4


def _build_segresnet(out_channels: int) -> "nn.Module":
    from monai.networks.nets.segresnet import SegResNet

    return SegResNet(out_channels=out_channels, **SEGRESNET_KWARGS)


def segresnet_spec() -> ModelSpec:
    """SegResNet del bundle con la proyección final `conv_final.2`."""
    return ModelSpec(name="monai.SegResNet", build=_build_segresnet, head=SEGRESNET_HEAD, in_channels=4)


@dataclass
class TransferReport:
    """Qué se transfirió del checkpoint, qué se descartó, qué es nuevo y qué está congelado."""

    model: str
    head: str
    weights_sha256: str
    head_init_seed: int
    transferred: list[str] = field(default_factory=list)  # llaves del state_dict copiadas del checkpoint
    discarded: list[str] = field(default_factory=list)  # llaves del checkpoint que no se usan (cabeza de 3 salidas)
    new: list[str] = field(default_factory=list)  # llaves nuevas (cabeza de 1 salida)
    transferred_numel: int = 0
    discarded_numel: int = 0
    new_numel: int = 0
    frozen_modules: list[str] = field(default_factory=list)
    frozen_parameters: list[str] = field(default_factory=list)
    trainable_numel: int = 0
    frozen_numel: int = 0

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def _under(name: str, prefix: str) -> bool:
    return name == prefix or name.startswith(prefix + ".")


def read_weights(path: Path, expected_sha256: str) -> dict[str, "torch.Tensor"]:
    """Lee el checkpoint local **una sola vez**: SHA-256 de esos bytes y `torch.load(weights_only=True)` sobre ellos.

    Así el archivo verificado y el cargado son el mismo (sin carrera entre hash y carga). Nunca descarga.
    """
    import hashlib
    import io

    import torch

    if not path.is_file():
        raise WeightsError(f"No existe el checkpoint local {path} (los pesos nunca se descargan en `train`)")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise WeightsError(f"No se pudo leer el checkpoint {path}: {exc.strerror or exc}") from exc
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected_sha256:
        raise WeightsError(
            f"El SHA-256 de {path} es {actual} y la configuración espera {expected_sha256} (weights.sha256)"
        )
    try:
        state = torch.load(io.BytesIO(raw), map_location="cpu", weights_only=True)
    except Exception as exc:  # pickle inválido, archivo truncado, tipo no permitido…
        raise WeightsError(f"No se pudo leer el checkpoint {path}: {type(exc).__name__}: {exc}") from exc
    del raw
    if not isinstance(state, Mapping) or not state:
        raise WeightsError(f"{path} no contiene un state_dict (se esperaba un diccionario llave → tensor)")
    out: dict[str, torch.Tensor] = {}
    for key, value in state.items():
        if not isinstance(key, str) or not isinstance(value, torch.Tensor):
            raise WeightsError(f"{path}: la entrada {key!r} no es un tensor con llave de texto")
        out[key] = value
    return out


def _listed(keys: list[str]) -> str:
    shown = ", ".join(keys[:MAX_LISTED_KEYS])
    return shown + (f" … (+{len(keys) - MAX_LISTED_KEYS})" if len(keys) > MAX_LISTED_KEYS else "")


def check_state_dict(model: "nn.Module", state: Mapping[str, "torch.Tensor"], source: str) -> None:
    """Compara llaves y shapes antes de `load_state_dict(strict=True)` para dar un error claro y completo."""
    expected = model.state_dict()
    missing = sorted(set(expected) - set(state))
    unexpected = sorted(set(state) - set(expected))
    shapes = sorted(
        f"{k} {tuple(state[k].shape)} ≠ {tuple(expected[k].shape)}"
        for k in set(expected) & set(state)
        if tuple(state[k].shape) != tuple(expected[k].shape)
    )
    problems = []
    if missing:
        problems.append(f"faltan {len(missing)} llave(s): {_listed(missing)}")
    if unexpected:
        problems.append(f"sobran {len(unexpected)} llave(s): {_listed(unexpected)}")
    if shapes:
        problems.append(f"{len(shapes)} shape(s) distintos (checkpoint ≠ red): {_listed(shapes)}")
    if problems:
        raise CheckpointError(f"Checkpoint {source} incompatible con la arquitectura: " + "; ".join(problems))


def load_strict(model: "nn.Module", state: Mapping[str, "torch.Tensor"], source: str) -> None:
    """Carga con correspondencia estricta; nunca `strict=False`."""
    check_state_dict(model, state, source)
    try:
        model.load_state_dict(state, strict=True)
    except RuntimeError as exc:  # por si torch detecta algo más (p. ej. dtype no convertible)
        raise CheckpointError(f"Checkpoint {source} incompatible: {exc}") from exc


def _split_path(path: str) -> tuple[str, str]:
    parent, _, leaf = path.rpartition(".")
    return parent, leaf


def replace_head(model: "nn.Module", spec: ModelSpec, out_channels: int, seed: int) -> list[str]:
    """Sustituye `spec.head` por la de una red idéntica de `out_channels` salidas construida con `seed`.

    Devuelve las llaves nuevas del state_dict. La construcción va dentro de `fork_rng`: el generador global de
    PyTorch queda igual que antes.
    """
    import torch

    old = model.get_submodule(spec.head)
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        donor = spec.build(out_channels)
    new = donor.get_submodule(spec.head)
    if type(new) is not type(old):
        raise CheckpointError(f"La cabeza nueva ({type(new).__name__}) no es del tipo de {spec.head}")
    old_keys = set(old.state_dict())
    if set(new.state_dict()) != old_keys:
        raise CheckpointError(f"La cabeza nueva no tiene las mismas llaves que {spec.head}")
    parent_name, leaf = _split_path(spec.head)
    parent = model.get_submodule(parent_name) if parent_name else model
    setattr(parent, leaf, new)
    return sorted(f"{spec.head}.{k}" for k in new.state_dict())


def apply_freeze(model: "nn.Module", prefixes: tuple[str, ...], protected: str) -> list[str]:
    """Congela (`requires_grad=False`) los parámetros bajo cada prefijo. Devuelve sus nombres.

    Un prefijo que no corresponde a ningún parámetro es un error (evita erratas silenciosas), igual que congelar la
    cabeza nueva (`protected`) o la red entera.
    """
    names = [name for name, _ in model.named_parameters()]
    frozen: list[str] = []
    for prefix in prefixes:
        matched = [n for n in names if _under(n, prefix)]
        if not matched:
            raise CheckpointError(f"training.freeze_modules: {prefix!r} no corresponde a ningún parámetro")
        if any(_under(n, protected) for n in matched) or _under(protected, prefix):
            raise CheckpointError(f"training.freeze_modules: {prefix!r} congelaría la cabeza nueva {protected}")
        frozen.extend(matched)
    frozen_set = set(frozen)
    for name, param in model.named_parameters():
        param.requires_grad_(name not in frozen_set)
    if not any(p.requires_grad for p in model.parameters()):
        raise CheckpointError("training.freeze_modules congela todos los parámetros: no quedaría nada que entrenar")
    return sorted(frozen_set)


def _numel(state: Mapping[str, "torch.Tensor"], keys: list[str]) -> int:
    return int(sum(state[k].numel() for k in keys))


def build_transfer_model(config: TrainConfig, spec: ModelSpec | None = None) -> tuple["nn.Module", TransferReport]:
    """Verifica pesos, construye la red de 3 salidas, carga estricta, cabeza de 1 salida y congelación registrada."""
    import torch

    spec = spec or segresnet_spec()
    weights = config.weights
    state = read_weights(weights.path, weights.sha256)
    model = spec.build(PRETRAINED_OUT_CHANNELS)
    load_strict(model, state, str(weights.path))
    seed = config.seeds.head_init
    new_keys = replace_head(model, spec, ADAPTED_OUT_CHANNELS, seed)
    final = model.state_dict()
    transferred = sorted(k for k in final if not _under(k, spec.head))
    discarded = sorted(k for k in state if _under(k, spec.head))
    for key in transferred:  # invariante: lo transferido es exactamente lo del checkpoint
        if not torch.equal(final[key], state[key].to(final[key].dtype)):
            raise CheckpointError(f"El tensor transferido {key} no coincide con el checkpoint")
    frozen = apply_freeze(model, config.training.freeze_modules, spec.head)
    params = dict(model.named_parameters())
    report = TransferReport(
        model=spec.name,
        head=spec.head,
        weights_sha256=weights.sha256,
        head_init_seed=seed,
        transferred=transferred,
        discarded=discarded,
        new=new_keys,
        transferred_numel=_numel(final, transferred),
        discarded_numel=_numel(state, discarded),
        new_numel=_numel(final, new_keys),
        frozen_modules=list(config.training.freeze_modules),
        frozen_parameters=frozen,
        trainable_numel=int(sum(p.numel() for p in params.values() if p.requires_grad)),
        frozen_numel=int(sum(p.numel() for p in params.values() if not p.requires_grad)),
    )
    return model, report


def build_adapted_model(config: TrainConfig, spec: ModelSpec | None = None) -> "nn.Module":
    """Red de 1 salida sin pesos iniciales (para cargar un `last.pt` al reanudar), con la misma congelación."""
    spec = spec or segresnet_spec()
    model = spec.build(ADAPTED_OUT_CHANNELS)
    apply_freeze(model, config.training.freeze_modules, spec.head)
    return model
