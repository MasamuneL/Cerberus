"""CLI del pipeline de fine-tuning: `uv run python -m cerberus_training <subcomando>`.

Los subcomandos del plan (docs/PLAN_PIPELINE_FINETUNING.md §8) se declaran aquí. Existen `validate` y `device`
(FT0), `inventory` y `split` (FT1), `prepare` y `preflight` (FT2), `train` (FT3), `evaluate` y `export` (FT4) y
`smoke` (FT5). Si se declara un subcomando sin implementar (hoy ninguno), valida la configuración (si se pasa
`--config`) y termina con código 3.
Este módulo no importa torch, MONAI, nibabel ni numpy: cada subcomando importa sus dependencias de forma perezosa.
"""

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from cerberus_training import __version__
from cerberus_training.config import DEFAULT_CONFIG_PATH, ConfigError, load_config, write_resolved_config

EXIT_OK = 0
EXIT_CONFIG_ERROR = 2  # misma convención que argparse para uso/entrada inválida
EXIT_NOT_IMPLEMENTED = 3
EXIT_DATA_ERROR = 4  # dataset/inventario inutilizable o split existente incompatible
EXIT_STUDY_ERRORS = 5  # `prepare` terminó, pero algún estudio falló (los demás se prepararon)
EXIT_RESOURCES = 6  # recursos insuficientes: límite de caché o espacio libre (`prepare` se detiene, `preflight` avisa)
EXIT_NO_CUDA = 1  # `device --require-cuda` o `train` con training.device = "cuda" sin GPU
EXIT_CHECKPOINT = 7  # pesos ausentes/SHA-256 distinto, checkpoint incompatible o reanudación rechazada
EXIT_TRAINING = 8  # fallo numérico (NaN/Inf) durante el entrenamiento
EXIT_SMOKE = 9  # `smoke --synthetic`: algún paso del recorrido sintético falló

# Ticket del plan (§9) que implementa cada subcomando todavía pendiente (vacío: FT0–FT5 están implementados).
PENDING: dict[str, str] = {}


def _add_config(parser: argparse.ArgumentParser, required: bool = True) -> None:
    parser.add_argument(
        "--config",
        type=Path,
        required=required,
        metavar="RUTA",
        help=f"configuración JSON del experimento (ej. {DEFAULT_CONFIG_PATH})",
    )


def build_parser() -> argparse.ArgumentParser:
    """Construye el parser; no tiene efectos secundarios ni importa dependencias pesadas."""
    parser = argparse.ArgumentParser(
        prog="python -m cerberus_training",
        description="Pipeline local de fine-tuning de SegResNet (GTV binario) sobre CFB-GBM. "
        "Implementados: `validate`, `device`, `inventory`, `split`, `prepare`, `preflight`, `train`, `evaluate`, "
        "`export` y `smoke`.",
    )
    parser.add_argument("--version", action="version", version=f"cerberus_training {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<subcomando>")

    p = sub.add_parser("validate", help="valida la configuración y opcionalmente escribe la versión resuelta")
    _add_config(p)
    p.add_argument("--write-resolved", type=Path, metavar="RUTA", help="escribe la configuración con rutas absolutas")

    p = sub.add_parser("device", help="informa versión de torch/CUDA y GPUs visibles (no falla en CPU)")
    p.add_argument("--json", action="store_true", help="salida en JSON")
    p.add_argument("--require-cuda", action="store_true", help="termina con código 1 si CUDA no está disponible")

    p = sub.add_parser("inventory", help="inventaría el dataset externo (solo lectura, solo cabeceras)")
    _add_config(p, required=False)
    p.add_argument("--data-root", type=Path, metavar="DIR", help="raíz del dataset CFB-GBM (o paths.data_root)")
    p.add_argument(
        "--output", type=Path, metavar="RUTA", help="inventory.jsonl de salida (o <paths.work_dir>/inventory.jsonl)"
    )
    p.add_argument("--summary", type=Path, metavar="RUTA", help="guarda además el resumen en JSON")

    p = sub.add_parser("prepare", help="valida y prepara los estudios elegibles, uno por vez (caché)")
    _add_config(p)
    p.add_argument("--inventory", type=Path, metavar="RUTA", help="por defecto <paths.work_dir>/inventory.jsonl")

    p = sub.add_parser("split", help="genera (o reutiliza) la partición determinista e inmutable por paciente")
    _add_config(p)
    p.add_argument("--inventory", type=Path, metavar="RUTA", help="por defecto <paths.work_dir>/inventory.jsonl")
    p.add_argument("--output", type=Path, metavar="RUTA", help="por defecto <paths.work_dir>/splits.json")

    p = sub.add_parser("preflight", help="estima disco de caché y RAM, y comprueba espacio libre y pesos")
    _add_config(p)
    p.add_argument("--inventory", type=Path, metavar="RUTA", help="por defecto <paths.work_dir>/inventory.jsonl")

    p = sub.add_parser("train", help="entrena, valida (--dry-run) o reanuda (--resume) el fine-tuning")
    _add_config(p)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="valida todo sin backward ni actualizar pesos")
    mode.add_argument("--resume", type=Path, metavar="LAST.PT", help="reanuda desde runs/<id>/checkpoints/last.pt")
    p.add_argument("--run-id", metavar="ID", help="nombre del run nuevo (por defecto fecha UTC + hash de config)")

    p = sub.add_parser("evaluate", help="evalúa un run (o el baseline original) en val o test; nunca sobrescribe")
    p.add_argument("--run", type=Path, required=True, metavar="DIR", help="directorio del run (runs/<run_id>)")
    p.add_argument("--split", choices=("val", "test"), required=True, help="partición a evaluar")
    p.add_argument(
        "--checkpoint",
        choices=("best", "last"),
        help="checkpoint del run: obligatorio con --split test; en val, best por defecto",
    )
    p.add_argument(
        "--baseline",
        action="store_true",
        help="evalúa la salida TC del modelo original frente a la GTV (referencia imperfecta)",
    )
    p.add_argument(
        "--optimize-threshold",
        action="store_true",
        help="solo con --split val: optimiza y guarda el umbral en threshold.json antes de evaluar",
    )
    p.add_argument(
        "--bootstrap", type=int, default=1000, metavar="N", help="réplicas bootstrap por paciente (1000; mínimo 100)"
    )
    p.add_argument("--bootstrap-seed", type=int, default=42, metavar="S", help="semilla del bootstrap (42)")
    p.add_argument("--device", choices=("cpu", "cuda"), help="sustituye training.device del run")

    p = sub.add_parser("export", help="exporta el modelo de un run con su ficha (export/); nunca sobrescribe")
    p.add_argument("--run", type=Path, required=True, metavar="DIR", help="directorio del run (runs/<run_id>)")
    p.add_argument(
        "--checkpoint", choices=("best", "last"), default="best", help="checkpoint del run (por defecto best)"
    )

    p = sub.add_parser(
        "smoke", help="recorrido completo en CPU con datos y pesos sintéticos (NO es fine-tuning real; sin red)"
    )
    p.add_argument("--synthetic", action="store_true", required=True, help="usa datos y pesos artificiales")
    p.add_argument(
        "--work-dir",
        type=Path,
        metavar="DIR",
        help="directorio de trabajo nuevo o vacío, fuera del repo (se conserva); por defecto uno temporal que se borra",
    )
    p.add_argument("--keep", action="store_true", help="conserva el directorio temporal y sus artefactos")
    p.add_argument("--verbose", action="store_true", help="muestra también la salida de cada subcomando")

    return parser


def _cmd_validate(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    print(f"Configuración válida: {args.config} (schema_version {config.schema_version})")
    if args.write_resolved is not None:
        written = write_resolved_config(config, args.write_resolved)
        print(f"Configuración resuelta escrita en {written}")
    return EXIT_OK


def _cmd_device(args: argparse.Namespace) -> int:
    from cerberus_training.device import format_report, probe_device  # perezoso: torch solo aquí

    report = probe_device()
    print(format_report(report, as_json=args.json))
    if args.require_cuda and not report.cuda_available:
        print("CUDA no está disponible y se pasó --require-cuda.", file=sys.stderr)
        return EXIT_NO_CUDA
    return EXIT_OK


def _data_error(exc: Exception) -> int:
    print(f"Error: {exc}", file=sys.stderr)
    return EXIT_DATA_ERROR


def _cmd_inventory(args: argparse.Namespace) -> int:
    from cerberus_training.inventory import InventoryError  # perezoso: nibabel/numpy solo aquí

    try:
        return _run_inventory(args)
    except (InventoryError, OSError) as exc:
        return _data_error(exc)


def _run_inventory(args: argparse.Namespace) -> int:
    from cerberus_training.config import resolve_config
    from cerberus_training.inventory import (
        atomic_write_text,
        build_inventory,
        dump_summary,
        ensure_distinct,
        ensure_outside_root,
        format_summary,
        summarize,
        write_inventory,
    )

    config = resolve_config(load_config(args.config)) if args.config is not None else None
    data_root: Path | None = args.data_root or (config.paths.data_root if config else None)
    output: Path | None = args.output or (config.paths.work_dir / "inventory.jsonl" if config else None)
    if data_root is None or output is None:
        print("inventory necesita --data-root y --output, o bien --config.", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    ensure_outside_root(output, data_root)
    if args.summary is not None:
        ensure_outside_root(args.summary, data_root)
        ensure_distinct(args.summary, output, "--summary y --output")
    result = build_inventory(data_root, config.channels if config else None)
    write_inventory(result.records, output)
    summary = summarize(result)
    print(format_summary(summary))
    print(f"Inventario escrito en {output}")
    if args.summary is not None:
        atomic_write_text(args.summary, dump_summary(summary))
        print(f"Resumen escrito en {args.summary}")
    return EXIT_OK


def _cmd_split(args: argparse.Namespace) -> int:
    from cerberus_training.config import resolve_config
    from cerberus_training.manifest import InventoryError, ensure_distinct, ensure_outside_root, read_inventory
    from cerberus_training.splits import SplitError, build_splits, format_splits, write_or_reuse_splits

    config = resolve_config(load_config(args.config))
    inventory: Path = args.inventory or config.paths.work_dir / "inventory.jsonl"
    output: Path = args.output or config.paths.work_dir / "splits.json"
    try:
        ensure_outside_root(output, config.paths.data_root)
        ensure_distinct(output, inventory, "--output e --inventory")
        payload = build_splits(read_inventory(inventory), config.split)
        reused = write_or_reuse_splits(payload, output)
    except (InventoryError, SplitError, OSError) as exc:
        return _data_error(exc)
    print(format_splits(payload))
    print(f"Split existente reutilizado: {output}" if reused else f"Split escrito en {output}")
    return EXIT_OK


def _cmd_prepare(args: argparse.Namespace) -> int:
    from cerberus_training.cache import CacheError, format_prepare, prepare_all  # perezoso: numpy/nibabel aquí
    from cerberus_training.config import resolve_config
    from cerberus_training.manifest import InventoryError, ensure_outside_root, read_inventory

    config = resolve_config(load_config(args.config))
    inventory: Path = args.inventory or config.paths.work_dir / "inventory.jsonl"
    try:
        ensure_outside_root(config.paths.work_dir, config.paths.data_root)
        records = read_inventory(inventory)
    except (InventoryError, OSError) as exc:
        return _data_error(exc)
    if not any(r.get("eligible") is True for r in records):
        return _data_error(InventoryError(f"El inventario {inventory} no tiene estudios elegibles"))
    print(f"Preparando estudios elegibles de {inventory}:")
    try:
        report = prepare_all(config, records, log=print)
    except CacheError as exc:
        print(f"Error de recursos: {exc}", file=sys.stderr)
        return EXIT_RESOURCES
    except OSError as exc:
        return _data_error(exc)
    print(format_prepare(report))
    if report.errors:
        print(f"{len(report.errors)} estudio(s) con errores; revise el informe antes de entrenar.", file=sys.stderr)
        return EXIT_STUDY_ERRORS
    return EXIT_OK


def _cmd_preflight(args: argparse.Namespace) -> int:
    from cerberus_training.config import resolve_config
    from cerberus_training.manifest import InventoryError, read_inventory
    from cerberus_training.preflight import format_preflight, run_preflight  # perezoso: numpy/nibabel aquí

    config = resolve_config(load_config(args.config))
    inventory: Path = args.inventory or config.paths.work_dir / "inventory.jsonl"
    try:
        records = read_inventory(inventory)
        report = run_preflight(config, records)
    except (InventoryError, OSError) as exc:
        return _data_error(exc)
    if report.studies == 0:
        return _data_error(InventoryError(f"El inventario {inventory} no tiene estudios elegibles"))
    print(format_preflight(report, config.paths.work_dir))
    return EXIT_OK if report.ok else EXIT_RESOURCES


def _cmd_train(args: argparse.Namespace) -> int:
    from cerberus_training.artifacts import RunExistsError, RunLockedError  # perezoso: torch/MONAI solo aquí
    from cerberus_training.config import resolve_config
    from cerberus_training.model import CheckpointError, WeightsError
    from cerberus_training.train import (
        DeviceUnavailableError,
        ResourceError,
        TrainingDataError,
        TrainingError,
        dry_run,
        format_dry_run,
        run_training,
    )

    config = resolve_config(load_config(args.config))
    if args.run_id is not None and (args.resume is not None or args.dry_run):
        print("--run-id solo se usa al crear un run nuevo (no con --resume ni --dry-run).", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    try:
        if args.dry_run:
            report = dry_run(config, log=print)
            print(format_dry_run(report))
            return EXIT_OK if report.ok else EXIT_RESOURCES
        result = run_training(config, run_id=args.run_id, resume=args.resume, log=print)
    except DeviceUnavailableError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_NO_CUDA
    except TrainingDataError as exc:
        return _data_error(exc)
    except (WeightsError, CheckpointError) as exc:
        print(f"Error de pesos/checkpoint: {exc}", file=sys.stderr)
        return EXIT_CHECKPOINT
    except ResourceError as exc:
        print(f"Error de recursos: {exc}", file=sys.stderr)
        return EXIT_RESOURCES
    except TrainingError as exc:
        print(f"Error de entrenamiento: {exc}", file=sys.stderr)
        return EXIT_TRAINING
    except (RunExistsError, RunLockedError, ValueError) as exc:  # run existente/en uso o --run-id inválido
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    except OSError as exc:
        return _data_error(exc)
    best = f"{result.best_metric:.4f} (época {result.best_epoch})" if result.best_metric is not None else "sin validar"
    status = f"terminado ({result.stop_reason})" if result.finished else "interrumpido en límite de época"
    print(
        f"Run {result.run_dir}: {result.epochs_completed} épocas, {result.step} pasos, {status}; mejor val Dice {best}"
    )
    return EXIT_OK


def _evaluation_errors(action: Callable[[], int]) -> int:
    """Traduce los errores de `evaluate`/`export` a los códigos de salida documentados."""
    import torch  # perezoso: solo evaluate/export, que ya necesitan torch

    from cerberus_training.artifacts import RunLockedError
    from cerberus_training.evaluate import EvaluationDataError, EvaluationError, EvaluationExistsError
    from cerberus_training.model import CheckpointError, WeightsError
    from cerberus_training.train import DeviceUnavailableError, TrainingDataError, TrainingError

    try:
        return action()
    except DeviceUnavailableError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_NO_CUDA
    except (TrainingDataError, EvaluationDataError) as exc:
        return _data_error(exc)
    except (WeightsError, CheckpointError) as exc:
        print(f"Error de pesos/checkpoint: {exc}", file=sys.stderr)
        return EXIT_CHECKPOINT
    except TrainingError as exc:
        print(f"Error numérico: {exc}", file=sys.stderr)
        return EXIT_TRAINING
    except (EvaluationExistsError, RunLockedError, EvaluationError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    except (torch.OutOfMemoryError, MemoryError) as exc:
        print(f"Error de recursos: memoria insuficiente ({type(exc).__name__})", file=sys.stderr)
        return EXIT_RESOURCES
    except OSError as exc:
        return _data_error(exc)


def _cmd_evaluate(args: argparse.Namespace) -> int:
    from cerberus_training.evaluate import evaluate_baseline, evaluate_run, format_evaluation  # perezoso

    if args.baseline and (args.optimize_threshold or args.checkpoint is not None):
        print("--baseline no admite --optimize-threshold ni --checkpoint (evalúa el modelo original).", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    if args.optimize_threshold and args.split != "val":
        print("--optimize-threshold solo se permite con --split val: nunca se optimiza sobre test.", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    if args.split == "test" and not args.baseline and args.checkpoint is None:
        print("Evaluar test exige --checkpoint best|last explícito.", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    def action() -> int:
        if args.baseline:
            result = evaluate_baseline(
                args.run,
                args.split,
                device=args.device,
                bootstrap_samples=args.bootstrap,
                bootstrap_seed=args.bootstrap_seed,
                log=print,
            )
        else:
            result = evaluate_run(
                args.run,
                args.split,
                checkpoint=args.checkpoint,
                optimize=args.optimize_threshold,
                device=args.device,
                bootstrap_samples=args.bootstrap,
                bootstrap_seed=args.bootstrap_seed,
                log=print,
            )
        print(format_evaluation(result))
        return EXIT_OK

    return _evaluation_errors(action)


def _cmd_export(args: argparse.Namespace) -> int:
    from cerberus_training.export import export_run  # perezoso: torch/MONAI solo aquí

    def action() -> int:
        result = export_run(args.run, checkpoint=args.checkpoint, log=print)
        print(f"Estado de evaluación: {result.manifest['evaluation']['status']}")
        return EXIT_OK

    return _evaluation_errors(action)


def _cmd_smoke(args: argparse.Namespace) -> int:
    from cerberus_training.smoke import run_smoke  # perezoso: torch/MONAI/nibabel solo aquí

    return run_smoke(main, work_dir=args.work_dir, keep=args.keep, verbose=args.verbose)


def _cmd_pending(args: argparse.Namespace) -> int:
    config_path: Path | None = getattr(args, "config", None)
    if config_path is not None:
        load_config(config_path)  # un config inválido se reporta antes que "pendiente"
    print(
        f"El subcomando '{args.command}' aún no está implementado: pendiente de {PENDING[args.command]} "
        "(docs/PLAN_PIPELINE_FINETUNING.md §9).",
        file=sys.stderr,
    )
    return EXIT_NOT_IMPLEMENTED


def main(argv: Sequence[str] | None = None) -> int:
    """Punto de entrada; devuelve el código de salida (ver docs/TRAINING.md, «Códigos de salida»)."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help(sys.stderr)
        return EXIT_CONFIG_ERROR
    try:
        if args.command == "validate":
            return _cmd_validate(args)
        if args.command == "device":
            return _cmd_device(args)
        if args.command == "inventory":
            return _cmd_inventory(args)
        if args.command == "split":
            return _cmd_split(args)
        if args.command == "prepare":
            return _cmd_prepare(args)
        if args.command == "preflight":
            return _cmd_preflight(args)
        if args.command == "train":
            return _cmd_train(args)
        if args.command == "evaluate":
            return _cmd_evaluate(args)
        if args.command == "export":
            return _cmd_export(args)
        if args.command == "smoke":
            return _cmd_smoke(args)
        return _cmd_pending(args)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return EXIT_CONFIG_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
