"""CLI del pipeline de fine-tuning: `uv run python -m cerberus_training <subcomando>`.

Los subcomandos del plan (docs/PLAN_PIPELINE_FINETUNING.md §8) se declaran aquí, pero en FT0 solo existen
`validate` y `device`; el resto valida la configuración (si se pasa `--config`) y termina con código 3 indicando
qué ticket los implementa. Este módulo no importa torch ni MONAI: cada subcomando los importará de forma perezosa.
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

# Ticket del plan (§9) que implementa cada subcomando todavía pendiente.
PENDING: dict[str, str] = {
    "inventory": "FT1",
    "split": "FT1",
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
        "En FT0 solo están implementados `validate` y `device`.",
    )
    parser.add_argument("--version", action="version", version=f"cerberus_training {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<subcomando>")

    p = sub.add_parser("validate", help="valida la configuración y opcionalmente escribe la versión resuelta")
    _add_config(p)
    p.add_argument("--write-resolved", type=Path, metavar="RUTA", help="escribe la configuración con rutas absolutas")

    p = sub.add_parser("device", help="informa versión de torch/CUDA y GPUs visibles (no falla en CPU)")
    p.add_argument("--json", action="store_true", help="salida en JSON")
    p.add_argument("--require-cuda", action="store_true", help="termina con código 1 si CUDA no está disponible")

    p = sub.add_parser("inventory", help="[FT1] inventaría el dataset externo (solo lectura)")
    _add_config(p, required=False)
    p.add_argument("--data-root", type=Path, required=True, metavar="DIR", help="raíz del dataset CFB-GBM")
    p.add_argument("--output", type=Path, required=True, metavar="RUTA", help="inventory.jsonl de salida")

    p = sub.add_parser("prepare", help="[FT2] valida y prepara los volúmenes (caché)")
    _add_config(p)

    p = sub.add_parser("split", help="[FT1] genera la partición determinista por paciente")
    _add_config(p)

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
    """Punto de entrada; devuelve el código de salida (0 ok, 2 config inválida, 3 pendiente)."""
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
        return _cmd_pending(args)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return EXIT_CONFIG_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
