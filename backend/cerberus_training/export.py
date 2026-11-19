"""Exportación recargable de un run y ficha del modelo (docs/PLAN_PIPELINE_FINETUNING.md §7, ticket FT4).

`export --run <run>` escribe (nunca sobrescribe; si existe, error):

```text
runs/<run_id>/export[-last]/
  model.pt         # state_dict de SegResNet con 1 salida (GTV), solo tensores (`weights_only=True`)
  export.json      # arquitectura, canales, transformaciones, umbral, hashes, licencia, citación y evaluación
  model_card.md    # ficha del modelo en español
```

El checkpoint se verifica igual que en `evaluate` (hashes del run frente a inventario, split, caché, pesos iniciales
y configuración; correspondencia estricta). **Sin puntuaciones ficticias:** si no hay ninguna evaluación del mismo
checkpoint (`evaluation/*/summary.json` con su `state_sha256`), el estado es `not_evaluated`; si la hay, se citan sus
resúmenes con partición y fecha. `load_export` reconstruye la red desde `export.json` y comprueba el SHA-256 del
archivo de pesos y del `state_dict` (y, opcionalmente, hashes esperados de datos).
"""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cerberus_training.artifacts import environment, run_lock
from cerberus_training.evaluate import (
    EVALUATION_SCHEMA_VERSION,
    METRICS,
    LogFn,
    RunCheckpoint,
    RunContext,
    ThresholdChoice,
    ensure_absent,
    load_run_checkpoint,
    open_run,
    publish_dir,
    read_json_object,
    resolve_threshold,
    run_hashes,
    utc_now,
    write_text_file,
)
from cerberus_training.model import (
    ADAPTED_OUT_CHANNELS,
    SEGRESNET_HEAD,
    SEGRESNET_KWARGS,
    CheckpointError,
    load_strict,
    segresnet_spec,
)
from cerberus_training.train import VAL_OVERLAP, TrainingDataError, state_digest
from cerberus_training.transforms import GEOMETRY_TOL_MM, TRANSFORMS_VERSION

if TYPE_CHECKING:
    from torch import nn

EXPORT_SCHEMA_VERSION = 1
MODEL_FILE = "model.pt"
MANIFEST_FILE = "export.json"
CARD_FILE = "model_card.md"
ARCHITECTURE_NAME = "monai.SegResNet"
DATASET = {
    "name": "CFB-GBM",
    "publisher": "The Cancer Imaging Archive (TCIA)",
    "url": "https://www.cancerimagingarchive.net/collection/cfb-gbm/",
    "doi": "10.7937/v9pn-2f72",
    "doi_url": "https://doi.org/10.7937/v9pn-2f72",
}
LICENSE = {"name": "CC BY 4.0", "url": "https://creativecommons.org/licenses/by/4.0/"}
CITATION = (
    "Colección CFB-GBM, The Cancer Imaging Archive (TCIA). DOI: 10.7937/v9pn-2f72 "
    "(https://doi.org/10.7937/v9pn-2f72). Licencia CC BY 4.0: cite el conjunto de datos según indica TCIA."
)
# Hashes de `export.json` que `load_export(expected=...)` puede contrastar.
HASH_KEYS: tuple[str, ...] = (
    "weights_file_sha256",
    "state_sha256",
    "pretrained_weights_sha256",
    "split_sha256",
    "eligible_records_sha256",
    "cache_key",
    "config_sha256",
)


class ExportError(CheckpointError):
    """Exportación ilegible, incompatible o con hashes que no coinciden."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _no_log(_message: str) -> None:
    return None


def find_evaluations(ctx: RunContext, state_sha256: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Resúmenes de evaluación del run: (del mismo checkpoint del modelo adaptado, del baseline)."""
    adapted: list[dict[str, Any]] = []
    baseline: list[dict[str, Any]] = []
    for path in sorted((ctx.paths.root / "evaluation").glob("*/summary.json")):
        if path.parent.name.startswith("."):
            continue
        summary = read_json_object(path, "el resumen de evaluación")
        if summary.get("schema_version") != EVALUATION_SCHEMA_VERSION or summary.get("run_id") != ctx.run_id:
            continue
        metrics = summary.get("metrics", {})
        cited: dict[str, Any] = {
            "split": summary.get("split"),
            "created_utc": summary.get("created_utc"),
            "summary": str(path.relative_to(ctx.paths.root)),
            "n_studies": summary.get("n_studies"),
            "n_patients": summary.get("n_patients"),
            "threshold": summary.get("threshold"),
            "metrics": {
                m: {k: metrics[m].get(k) for k in ("mean", "median", "ci95", "n_valid_patients", "n_patients")}
                for m in METRICS
                if m in metrics
            },
        }
        if summary.get("model") == "baseline":
            cited["label_caveat"] = summary.get("label_caveat")
            baseline.append(cited)
        elif summary.get("model") == "adapted" and summary.get("checkpoint", {}).get("state_sha256") == state_sha256:
            adapted.append(cited)
    return adapted, baseline


def build_manifest(
    ctx: RunContext,
    checkpoint: RunCheckpoint,
    threshold: ThresholdChoice,
    weights_file_sha256: str,
    evaluations: tuple[list[dict[str, Any]], list[dict[str, Any]]],
) -> dict[str, Any]:
    """Contenido de `export.json` (solo datos verificables del run; ninguna cifra inventada)."""
    config = ctx.config
    pre = config.preprocess
    adapted, baseline = evaluations
    hashes = run_hashes(ctx)
    return {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "run_id": ctx.run_id,
        "created_utc": utc_now(),
        "task": config.task,
        "label": {"name": config.channels.label, "description": "GTV binaria de CFB-GBM (excluye edema)"},
        "architecture": {
            "name": ARCHITECTURE_NAME,
            "kwargs": {k: list(v) if isinstance(v, tuple) else v for k, v in SEGRESNET_KWARGS.items()},
            "out_channels": ADAPTED_OUT_CHANNELS,
            "head": SEGRESNET_HEAD,
            "output": "1 logit GTV; probabilidad = sigmoid(logit)",
        },
        "channel_order": list(config.channels.order),
        "channels": config.channels.model_dump(mode="json"),
        "transforms": {
            "transforms_version": TRANSFORMS_VERSION,
            "reference_channel": config.channels.reference,
            "spacing_mm": pre.spacing_mm,
            "orientation": pre.orientation,
            "brain_mask_policy": pre.brain_mask_policy,
            "geometry_tol_mm": GEOMETRY_TOL_MM,
            "steps": [
                "Referencia T1c; canales, GTV y brain_mask deben ocupar su mismo espacio físico (sin registro).",
                "Grid RAS ortogonal de spacing_mm que contiene la T1c (nibabel.spaces.vox2out_vox); imágenes lineal "
                "y máscaras vecino más próximo (scipy.ndimage.affine_transform, mode=grid-constant).",
                "Imágenes × brain_mask si existe; si no, soporte = vóxeles no nulos. Recorte a la caja del soporte.",
                "cerberus_api.segmentation.normalize_nonzero por canal.",
            ],
            "inference": {
                "sliding_window_roi": list(pre.patch_size),
                "overlap": VAL_OVERLAP,
                "activation": "sigmoid",
            },
            "restore": "transforms.restore_to_reference (vecino más próximo) al grid original de la T1c",
        },
        "threshold": {"value": threshold.value, "source": threshold.source, "warnings": list(threshold.warnings)},
        "checkpoint": {
            "kind": checkpoint.kind,
            "epoch": checkpoint.epoch,
            "selection_metric": checkpoint.selection_metric,
        },
        "hashes": {
            "weights_file_sha256": weights_file_sha256,
            "state_sha256": checkpoint.state_sha256,
            "pretrained_weights_sha256": hashes["weights_sha256"],
            "split_sha256": hashes["split_sha256"],
            "eligible_records_sha256": hashes["eligible_records_sha256"],
            "cache_key": hashes["cache_key"],
            "config_sha256": hashes["config_sha256"],
        },
        "pretrained": {"bundle_name": config.weights.bundle_name, "bundle_version": config.weights.bundle_version},
        "dataset": DATASET,
        "license": LICENSE,
        "citation": CITATION,
        "pretraining_overlap": ctx.data.splits.get("pretraining_overlap"),
        "evaluation": {
            "status": "evaluated" if adapted else "not_evaluated",
            "adapted": adapted,
            "baseline_reference": baseline,
        },
        "environment": environment(),
    }


def _fmt(value: Any) -> str:
    return f"{value:.4f}" if isinstance(value, float) else "n/d"


def model_card(manifest: dict[str, Any]) -> str:
    """Ficha del modelo en español, construida solo con datos de `export.json` (sin cifras inventadas)."""
    arch, tr, thr, h = manifest["architecture"], manifest["transforms"], manifest["threshold"], manifest["hashes"]
    ev, ckpt = manifest["evaluation"], manifest["checkpoint"]
    epoch = ckpt["epoch"] if ckpt["epoch"] is not None else "n/d"
    lines = [
        f"# Ficha del modelo: SegResNet GTV binaria (run `{manifest['run_id']}`)",
        "",
        f"Exportado el {manifest['created_utc']}. Estado de evaluación: **`{ev['status']}`**.",
        "",
        "## Uso previsto",
        "",
        "Modelo **experimental** de investigación que segmenta la GTV binaria (excluye edema) del dataset CFB-GBM. "
        "No es un dispositivo médico ni está validado para uso clínico, y no está integrado en la API ni en la UI "
        "de Cerberus.",
        "",
        "## Arquitectura",
        "",
        f"- `{arch['name']}` con `{json.dumps(arch['kwargs'], ensure_ascii=False)}` y "
        f"`out_channels={arch['out_channels']}` (cabeza `{arch['head']}`, inicializada desde el bundle "
        f"`{manifest['pretrained']['bundle_name']}` {manifest['pretrained']['bundle_version']}).",
        f"- Salida: {arch['output']}; umbral **{thr['value']}** (origen `{thr['source']}`).",
        "",
        "## Entradas y transformaciones",
        "",
        f"- Orden de canales: `{manifest['channel_order']}`; referencia `{tr['reference_channel']}`.",
        f"- `TRANSFORMS_VERSION` = `{tr['transforms_version']}`; spacing {tr['spacing_mm']} mm, orientación "
        f"{tr['orientation']}, política de máscara cerebral `{tr['brain_mask_policy']}`.",
        *(f"- {step}" for step in tr["steps"]),
        f"- Inferencia: ventana deslizante {tr['inference']['sliding_window_roi']}, solapamiento "
        f"{tr['inference']['overlap']}, {tr['inference']['activation']}; restauración: {tr['restore']}.",
        "",
        "## Selección del checkpoint",
        "",
        f"- Checkpoint `{ckpt['kind']}` (época {epoch}).",
    ]
    metric = ckpt.get("selection_metric")
    if isinstance(metric, dict) and isinstance(metric.get("value"), float):
        lines.append(
            f"- Métrica de selección durante el entrenamiento (`{metric.get('name')}`, val, grid preparado): "
            f"{metric['value']:.4f}. **No es una evaluación**: es el criterio con el que se eligió `best`."
        )
    lines += ["", "## Evaluación", ""]
    if not ev["adapted"]:
        lines.append(
            "Sin evaluar (`not_evaluated`): no existe ninguna evaluación de este checkpoint. Ejecute "
            "`python -m cerberus_training evaluate --run <run> --split val|test` y vuelva a exportar."
        )
    for item in ev["adapted"]:
        lines.append(
            f"- Partición **{item['split']}** ({item['created_utc']}, `{item['summary']}`): "
            f"{item['n_studies']} estudios, {item['n_patients']} pacientes, umbral {item['threshold']['value']}."
        )
        for name, m in item["metrics"].items():
            ci = m.get("ci95")
            ci_text = f"[{_fmt(ci[0])}, {_fmt(ci[1])}]" if isinstance(ci, list) else "n/d"
            lines.append(
                f"  - {name}: media {_fmt(m.get('mean'))}, mediana {_fmt(m.get('median'))}, IC95 {ci_text} "
                f"({m.get('n_valid_patients')}/{m.get('n_patients')} pacientes válidos)"
            )
    if ev["baseline_reference"]:
        lines += ["", "Referencia imperfecta (modelo original, salida TC frente a GTV; no equivale a GTV):"]
        for item in ev["baseline_reference"]:
            dice = item["metrics"].get("dice", {})
            lines.append(
                f"- {item['split']} ({item['created_utc']}, `{item['summary']}`): Dice TC↔GTV media "
                f"{_fmt(dice.get('mean'))}."
            )
    lines += [
        "",
        "## Limitaciones",
        "",
        "- La GTV excluye edema; el modelo no segmenta WT/TC/ET de BraTS.",
        "- El remuestreo no corrige desregistro entre secuencias; los estudios desalineados se excluyen en `prepare`.",
        f"- Solapamiento con el preentrenamiento del bundle: `{manifest['pretraining_overlap']}`.",
        "- Un umbral optimizado en val da métricas de val optimistas; test nunca se usa para elegir nada.",
        "",
        "## Hashes",
        "",
        *(f"- `{k}`: `{v}`" for k, v in h.items()),
        "",
        "## Datos, licencia y citación",
        "",
        f"- Dataset: {manifest['dataset']['name']} ({manifest['dataset']['publisher']}), {manifest['dataset']['url']}.",
        f"- Licencia: {manifest['license']['name']} ({manifest['license']['url']}).",
        f"- Cite: {manifest['citation']}",
        "",
    ]
    return "\n".join(lines)


@dataclass
class ExportResult:
    directory: Path
    manifest: dict[str, Any]


def export_dir(ctx: RunContext, checkpoint: str) -> Path:
    return ctx.paths.root / ("export" if checkpoint == "best" else f"export-{checkpoint}")


def export_run(run_dir: Path, *, checkpoint: str = "best", log: LogFn = _no_log) -> ExportResult:
    """Exporta el checkpoint (`best` por defecto) de un run SegResNet a `export/` (ver docstring del módulo)."""
    import io

    import torch

    spec = segresnet_spec()
    ctx = open_run(run_dir, spec)
    out = export_dir(ctx, checkpoint)
    ensure_absent(out)
    with run_lock(ctx.paths):
        ckpt = load_run_checkpoint(ctx, checkpoint, spec)
        threshold = resolve_threshold(ctx, ckpt)
        buffer = io.BytesIO()
        torch.save({k: v.detach().cpu().contiguous() for k, v in ckpt.model.state_dict().items()}, buffer)
        weights = buffer.getvalue()
        evaluations = find_evaluations(ctx, ckpt.state_sha256)
        manifest = build_manifest(ctx, ckpt, threshold, _sha256_bytes(weights), evaluations)

        def write(tmp: Path) -> None:
            with (tmp / MODEL_FILE).open("wb") as handle:
                handle.write(weights)
            text = json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
            write_text_file(tmp / MANIFEST_FILE, text)
            write_text_file(tmp / CARD_FILE, model_card(manifest))

        publish_dir(out, write)
    log(f"Exportación escrita en {out} (estado {manifest['evaluation']['status']})")
    return ExportResult(out, manifest)


@dataclass
class LoadedExport:
    model: "nn.Module"
    manifest: dict[str, Any]

    @property
    def threshold(self) -> float:
        return float(self.manifest["threshold"]["value"])

    @property
    def channel_order(self) -> list[str]:
        return list(self.manifest["channel_order"])


def load_export(directory: Path, expected: Mapping[str, str] | None = None) -> LoadedExport:
    """Reconstruye SegResNet de 1 salida desde `export.json` y carga `model.pt` verificando hashes.

    Comprueba el SHA-256 del archivo de pesos, la correspondencia estricta y el SHA-256 del `state_dict` cargado.
    `expected` (p. ej. `{"split_sha256": ..., "cache_key": ...}`, claves de `HASH_KEYS`) se contrasta con los hashes
    del manifiesto. Lanza `ExportError` ante cualquier discrepancia.
    """
    import io

    import torch
    from monai.networks.nets.segresnet import SegResNet

    try:
        manifest = read_json_object(directory / MANIFEST_FILE, "la exportación")
    except TrainingDataError as exc:
        raise ExportError(str(exc)) from exc
    if manifest.get("schema_version") != EXPORT_SCHEMA_VERSION:
        raise ExportError(f"{directory}: exportación con esquema no soportado")
    hashes, arch = manifest.get("hashes"), manifest.get("architecture")
    if not isinstance(hashes, dict) or not isinstance(arch, dict):
        raise ExportError(f"{directory}: export.json incompleto (faltan hashes o arquitectura)")
    if expected:
        unknown = sorted(set(expected) - set(HASH_KEYS))
        if unknown:
            raise ExportError(f"Hashes esperados desconocidos: {', '.join(unknown)}")
        diffs = sorted(k for k, v in expected.items() if hashes.get(k) != v)
        if diffs:
            raise ExportError(f"{directory}: los hashes no coinciden con los esperados ({', '.join(diffs)})")
    try:
        raw = (directory / MODEL_FILE).read_bytes()
    except OSError as exc:
        raise ExportError(f"No se pudo leer {directory / MODEL_FILE}: {exc.strerror or exc}") from exc
    if _sha256_bytes(raw) != hashes.get("weights_file_sha256"):
        raise ExportError(f"{directory / MODEL_FILE}: el SHA-256 no coincide con export.json (archivo alterado)")
    if arch.get("name") != ARCHITECTURE_NAME or arch.get("out_channels") != ADAPTED_OUT_CHANNELS:
        raise ExportError(f"{directory}: arquitectura no soportada ({arch.get('name')}, {arch.get('out_channels')})")
    raw_kwargs = arch.get("kwargs")
    if not isinstance(raw_kwargs, dict):
        raise ExportError(f"{directory}: export.json sin parámetros de arquitectura")
    kwargs: dict[str, Any] = {str(k): tuple(v) if isinstance(v, list) else v for k, v in raw_kwargs.items()}
    try:
        model = SegResNet(out_channels=ADAPTED_OUT_CHANNELS, **kwargs)
        state = torch.load(io.BytesIO(raw), map_location="cpu", weights_only=True)
    except Exception as exc:  # parámetros inválidos, pickle dañado…
        raise ExportError(f"{directory}: no se pudo reconstruir el modelo ({type(exc).__name__}: {exc})") from exc
    if not isinstance(state, dict):
        raise ExportError(f"{directory / MODEL_FILE} no contiene un state_dict")
    try:
        load_strict(model, state, str(directory / MODEL_FILE))
    except CheckpointError as exc:
        raise ExportError(str(exc)) from exc
    if state_digest(model) != hashes.get("state_sha256"):
        raise ExportError(f"{directory}: el SHA-256 del state_dict no coincide con export.json")
    model.eval()
    return LoadedExport(model, manifest)
