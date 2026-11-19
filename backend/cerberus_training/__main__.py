"""CLI del pipeline de fine-tuning: `uv run python -m cerberus_training <subcomando>`.

Los subcomandos del plan (docs/PLAN_PIPELINE_FINETUNING.md §8) se declaran aquí. Existen `validate` y `device`
(FT0) e `inventory` y `split` (FT1); el resto valida la configuración (si se pasa `--config`) y termina con
código 3 indicando qué ticket los implementa. Este módulo no importa torch, MONAI, nibabel ni numpy: cada
subcomando importa sus dependencias de forma perezosa.
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from cerberus_training import __version__
from cerberus_training.config import DEFAULT_CONFIG_PATH, ConfigError, load_config, write_resolved_config

EXIT_OK = 0
EXIT_CONFIG_ERROR = 2  # misma convención que argparse para uso/entrada inválida
EXIT_NOT_IMPLEMENTED = 3
EXIT_DATA_ERROR = 4  # dataset/inventario inutilizable o split existente incompatible

# Ticket del plan (§9) que implementa cada subcomando todavía pendiente.
PENDING: dict[str, str] = {
    "prepare": "FT2",
    "preflight": "FT2",
    "train": "FT3",
    "evaluate": "FT4",
    "export": "FT4",
    "smoke": "FT5",
}


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
        "Implementados: `validate`, `device`, `inventory` y `split`.",
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

    p = sub.add_parser("prepare", help="[FT2] valida y prepara los volúmenes (caché)")
    _add_config(p)

    p = sub.add_parser("split", help="genera (o reutiliza) la partición determinista e inmutable por paciente")
    _add_config(p)
    p.add_argument("--inventory", type=Path, metavar="RUTA", help="por defecto <paths.work_dir>/inventory.jsonl")
    p.add_argument("--output", type=Path, metavar="RUTA", help="por defecto <paths.work_dir>/splits.json")

    p = sub.add_parser("preflight", help="[FT2] comprueba fuentes, pesos, disco y dispositivo")
    _add_config(p)

    p = sub.add_parser("train", help="[FT3] entrena o reanuda el fine-tuning")
    _add_config(p)
    p.add_argument("--dry-run", action="store_true", help="valida todo sin backward ni actualizar pesos")
    p.add_argument("--resume", type=Path, metavar="LAST.PT", help="reanuda desde un checkpoint last.pt")

    p = sub.add_parser("evaluate", help="[FT4] evalúa un run en una partición")
    p.add_argument("--run", type=Path, required=True, metavar="DIR", help="directorio del run")
    p.add_argument("--split", choices=("val", "test"), required=True, help="partición a evaluar")

    p = sub.add_parser("export", help="[FT4] exporta el modelo de un run con su ficha")
    p.add_argument("--run", type=Path, required=True, metavar="DIR", help="directorio del run")

    p = sub.add_parser("smoke", help="[FT5] recorrido completo en CPU con datos y pesos sintéticos")
    p.add_argument("--synthetic", action="store_true", required=True, help="usa datos y pesos artificiales")

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
        return 1
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
    """Punto de entrada; devuelve el código de salida (0 ok, 2 config inválida, 3 pendiente, 4 datos/split)."""
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
        return _cmd_pending(args)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return EXIT_CONFIG_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
