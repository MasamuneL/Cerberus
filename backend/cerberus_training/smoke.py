"""`smoke --synthetic`: recorrido completo de la CLI con datos y pesos artificiales (plan de FT §8).

**SINTÉTICO — NO ES FINE-TUNING REAL.** Todo lo que genera este módulo (pacientes, imágenes, GTV, checkpoint) es ruido
con formas geométricas sencillas. Sirve para comprobar que el cableado de extremo a extremo funciona sin red, sin GPU y
sin el dataset; sus métricas (Dice, etc.) no significan nada clínico ni científico.

Qué hace, en un directorio temporal (o `--work-dir`, que debe ser nuevo o estar vacío y quedar fuera del repo):

1. Genera NIfTI CFB-GBM diminutos con la convención `cerberus_v1` (7 pacientes, varios tiempos, un estudio excluido por
   canal faltante y otro por GTV ausente, un GTV vacío como señal de revisión, un paciente con el eje x invertido) y un
   checkpoint artificial de **SegResNet real de 3 salidas** con su SHA-256, más una configuración derivada.
2. Recorre las **mismas funciones que la CLI** (se invoca `main([...])` de `__main__`, paso a paso):
   `validate` → `inventory` → `split` → `preflight` → `prepare` → `train --dry-run` → `train` (2 pasos de optimización
   en CPU, sin AMP) → corte tras la 1.ª época + `train --resume` (equivalente a la ejecución continua) →
   `evaluate val` → `evaluate test --checkpoint best` → `export` → `load_export`.
3. Imprime un informe en español (✓/✗ por paso, con rutas) y escribe `smoke_report.json` y un archivo marcador
   `SINTETICO_NO_ES_FINE_TUNING.txt` en el directorio de trabajo y en cada run.

Decisión de red: se usa la **SegResNet real** de MONAI (la misma de la API) con parches de 16³ y volúmenes de 32³;
en CPU cada paso cuesta fracciones de segundo, así que no hace falta la red pequeña inyectable de los tests y el smoke
ejercita la transferencia real (`conv_final.2`), la ventana deslizante y `load_export`. El corte tras la 1.ª época usa
`run_training(stop_after_epochs=1)` porque la CLI no expone esa opción (solo la usan los tests); la reanudación sí va
por la CLI (`train --resume`).

Durante el recorrido se **bloquea la red** parcheando `socket.socket.connect` y `connect_ex` (solo familias IPv4/IPv6),
`socket.getaddrinfo` y `socket.create_connection`: un intento lanza `OSError`, se cuenta y hace fallar el smoke. No
intercepta otras vías (p. ej. UDP con `sendto` sin `connect`, sockets abiertos antes ni subprocesos); es una red de
seguridad, no un aislamiento del sistema operativo.
Torch, MONAI, nibabel y numpy se importan aquí; este módulo solo se importa desde el subcomando `smoke`.
"""

import contextlib
import io
import json
import shutil
import socket
import tempfile
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np

from cerberus_training.__main__ import EXIT_CONFIG_ERROR, EXIT_OK, EXIT_SMOKE
from cerberus_training.config import REPO_ROOT, load_config, resolve_config

BANNER = "SINTÉTICO — NO ES FINE-TUNING REAL"
MARKER_NAME = "SINTETICO_NO_ES_FINE_TUNING.txt"
MARKER_TEXT = (
    f"{BANNER}\n\n"
    "Estos datos, pesos y runs los generó `python -m cerberus_training smoke --synthetic` para comprobar el cableado\n"
    "del pipeline de fine-tuning. Las imágenes son ruido con esferas, el checkpoint es una SegResNet con pesos\n"
    "aleatorios y las métricas no tienen valor clínico ni científico. No se descargó nada ni se usó CFB-GBM.\n"
)
REPORT_NAME = "smoke_report.json"
REPORT_SCHEMA_VERSION = 1

SHAPE = (32, 32, 32)
PATCH = 16
SEED = 20261119
CONTINUOUS_RUN = "smoke-sintetico-continuo"
INTERRUPTED_RUN = "smoke-sintetico-interrumpido"
WEIGHTS_NAME = "sintetico_segresnet_3salidas.pt"
SEQUENCES = ("t1gd", "t1eg", "t2tse", "flair")

# (paciente, tiempo, variante). `flip` invierte el eje x (affine con signo negativo); `no_flair` y `no_gtv` se excluyen.
STUDIES: tuple[tuple[str, str, str], ...] = (
    ("001", "t0", "ok"),
    ("001", "t1", "ok"),
    ("002", "t0", "flip"),
    ("002", "t1", "ok"),
    ("002", "t2", "no_gtv"),
    ("003", "t0", "ok"),
    ("004", "t0", "ok"),
    ("005", "t0", "ok"),
    ("006", "t0", "ok"),
    ("006", "t1", "empty_gtv"),
    ("007", "t0", "no_flair"),
)
EXPECTED_ELIGIBLE = 9
EXPECTED_EXCLUSIONS = {"missing_channel": 1, "missing_label": 1}
EXPECTED_REVIEW = {"empty_label": 1}

STEP_NAMES: tuple[str, ...] = (
    "datos y pesos sintéticos",
    "validate",
    "inventory",
    "split",
    "preflight",
    "prepare",
    "train --dry-run",
    "train (2 pasos)",
    "reanudación",
    "evaluate val",
    "evaluate test",
    "export",
    "load_export",
)


class SmokeError(RuntimeError):
    """Un paso del recorrido falló (el mensaje está en español)."""


@dataclass
class StepResult:
    name: str
    ok: bool
    seconds: float
    detail: str
    paths: list[str] = field(default_factory=list)
    output: str = ""  # salida capturada de la CLI (solo se imprime si falla o con --verbose)


# ---------------------------------------------------------------------------------------------------------------
# Datos sintéticos
# ---------------------------------------------------------------------------------------------------------------


def _ellipsoid(center: tuple[float, float, float], radii: tuple[float, float, float]) -> np.ndarray:
    idx = np.stack(np.meshgrid(*[np.arange(n) for n in SHAPE], indexing="ij"), axis=-1).astype(np.float64)
    return (((idx - np.asarray(center)) / np.asarray(radii)) ** 2).sum(axis=-1) <= 1.0


def _write_study(root: Path, patient: str, timepoint: str, variant: str, index: int) -> None:
    """Escribe un estudio `cerberus_v1`. Cada archivo lleva ruido propio: no hay duplicados exactos."""
    center = (15.5, 15.5, 15.5)
    brain = _ellipsoid(center, (12.0 + index % 3, 12.0, 12.0))
    rng = np.random.default_rng([SEED, index])
    offset = rng.integers(-4, 5, size=3)
    tumor_center = (float(center[0] + offset[0]), float(center[1] + offset[1]), float(center[2] + offset[2]))
    gtv = _ellipsoid(tumor_center, (4.0, 4.0, 4.0)) & brain
    if variant == "empty_gtv":
        gtv = np.zeros(SHAPE, dtype=bool)
    edema = _ellipsoid(tumor_center, (7.0, 7.0, 7.0)) & brain
    affine = np.eye(4)
    flip = variant == "flip"
    if flip:  # eje x invertido (LAS en vez de RAS): el mismo espacio físico con otra orientación de vóxeles
        affine[0, 0], affine[0, 3] = -1.0, SHAPE[0] - 1.0

    def save(seq: str, data: np.ndarray, dtype: Any) -> None:
        arr = data[::-1] if flip else data
        path = root / patient / timepoint / f"{int(patient)}_{timepoint}_{seq}.nii.gz"
        path.parent.mkdir(parents=True, exist_ok=True)
        nib.save(nib.Nifti1Image(np.ascontiguousarray(arr).astype(dtype), affine), str(path))

    for k, seq in enumerate(SEQUENCES):
        if variant == "no_flair" and seq == "flair":
            continue
        noise = np.random.default_rng([SEED, index, k]).normal(0.0, 8.0, SHAPE)
        image = 100.0 + 15.0 * k + noise + (60.0 if seq == "t1gd" else 25.0) * gtv + 20.0 * edema
        save(seq, np.where(brain, image, 0.0), np.float32)
    save("brain_mask", brain, np.uint8)
    if variant != "no_gtv":
        save("gtv", gtv, np.uint8)


def generate_dataset(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for index, (patient, timepoint, variant) in enumerate(STUDIES):
        _write_study(root, patient, timepoint, variant, index)


def generate_weights(path: Path) -> str:
    """Checkpoint artificial de SegResNet de 3 salidas (pesos aleatorios con semilla) y su SHA-256."""
    import torch

    from cerberus_training.inventory import sha256_file
    from cerberus_training.model import segresnet_spec

    path.parent.mkdir(parents=True, exist_ok=True)
    with torch.random.fork_rng():
        torch.manual_seed(SEED % 2**31)
        net = segresnet_spec().build(3)
        with torch.no_grad():
            for p in net.parameters():
                p.add_(torch.randn_like(p) * 0.01)
    torch.save(net.state_dict(), path)
    return sha256_file(path)


def derive_config(work: Path, sha256: str) -> dict[str, Any]:
    """Configuración derivada: CPU, sin AMP, parche 16³ (múltiplo de 8), 2 épocas de un paso cada una."""
    return {
        "schema_version": 1,
        "paths": {"data_root": str(work / "data" / "CFB-GBM-sintetico"), "work_dir": str(work / "training")},
        "preprocess": {
            "patch_size": [PATCH, PATCH, PATCH],
            "batch_size": 1,
            # Más que los estudios de train: cada época hace una sola ventana de acumulación = 1 paso de optimización.
            "grad_accum_steps": 8,
            "cache_limit_gb": 1.0,
            "min_free_disk_gb": 0.001,
        },
        "weights": {
            "path": str(work / "pesos_sinteticos" / WEIGHTS_NAME),
            "sha256": sha256,
            "bundle_name": "sintetico_no_es_el_bundle_real",
            "bundle_version": "0.0.0-sintetico",
        },
        "training": {"device": "cpu", "amp": False, "max_epochs": 2, "learning_rate": 1e-3},
    }


# ---------------------------------------------------------------------------------------------------------------
# Bloqueo de red
# ---------------------------------------------------------------------------------------------------------------


@contextlib.contextmanager
def network_blocked() -> Iterator[list[str]]:
    """Bloquea `socket.socket.connect`/`connect_ex` (familias IPv4 e IPv6), `socket.getaddrinfo` y
    `socket.create_connection`; devuelve la lista de intentos bloqueados y restaura todo al salir.

    Los sockets `AF_UNIX` no se tocan (no salen de la máquina). No cubre `sendto` sin `connect`, sockets creados
    antes del bloqueo ni subprocesos.
    """
    attempts: list[str] = []
    real_connect, real_connect_ex = socket.socket.connect, socket.socket.connect_ex
    real_getaddrinfo, real_create = socket.getaddrinfo, socket.create_connection

    def block(what: str) -> Any:
        attempts.append(what)
        raise OSError(f"Red bloqueada durante el smoke sintético ({what})")

    def connect(self: socket.socket, address: Any) -> Any:
        if self.family in (socket.AF_INET, socket.AF_INET6):
            return block(f"connect {address!r}")
        return real_connect(self, address)

    def connect_ex(self: socket.socket, address: Any) -> Any:
        if self.family in (socket.AF_INET, socket.AF_INET6):
            return block(f"connect_ex {address!r}")
        return real_connect_ex(self, address)

    def getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        return block(f"getaddrinfo {host!r}")

    def create_connection(address: Any, *args: Any, **kwargs: Any) -> Any:
        return block(f"create_connection {address!r}")

    socket.socket.connect, socket.socket.connect_ex = connect, connect_ex  # type: ignore[method-assign,assignment]
    socket.getaddrinfo, socket.create_connection = getaddrinfo, create_connection  # type: ignore[assignment]
    try:
        yield attempts
    finally:
        socket.socket.connect, socket.socket.connect_ex = real_connect, real_connect_ex  # type: ignore[method-assign]
        socket.getaddrinfo, socket.create_connection = real_getaddrinfo, real_create


# ---------------------------------------------------------------------------------------------------------------
# Recorrido
# ---------------------------------------------------------------------------------------------------------------

Cli = Callable[[Sequence[str]], int]
StepAction = Callable[[], tuple[str, list[Path]]]


class _Runner:
    """Ejecuta los pasos en orden, registra su resultado y se detiene en el primer fallo."""

    def __init__(self, cli: Cli, work: Path, verbose: bool, out: Callable[[str], None]) -> None:
        self.cli, self.work, self.verbose, self.out = cli, work, verbose, out
        self.steps: list[StepResult] = []
        self.config_path = work / "config.json"
        self.training = work / "training"
        self.last_output = ""
        self.facts: dict[str, Any] = {}

    def run_cli(self, argv: Sequence[str], expect: int = 0) -> None:
        """Invoca la CLI real capturando su salida; un código distinto del esperado es un fallo del paso."""
        buffer = io.StringIO()
        try:
            with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
                code = self.cli(list(argv))
        except SystemExit as exc:  # argparse
            code = exc.code if isinstance(exc.code, int) else 2
        self.last_output += buffer.getvalue()
        if code != expect:
            raise SmokeError(f"`{' '.join(argv)}` terminó con código {code} (se esperaba {expect})")

    def step(self, name: str, action: StepAction) -> bool:
        index = len(self.steps) + 1
        started = time.monotonic()
        self.last_output = ""
        try:
            detail, paths = action()
            ok = True
        except Exception as exc:  # cada paso informa su propio fallo; el smoke no debe abortar sin informe
            detail, paths, ok = f"{type(exc).__name__}: {exc}", [], False
        result = StepResult(
            name, ok, round(time.monotonic() - started, 2), detail, [str(p) for p in paths], self.last_output
        )
        self.steps.append(result)
        mark = "✓" if ok else "✗"
        self.out(f"[{index:>2}/{len(STEP_NAMES)}] {mark} {name} ({result.seconds:.1f} s) — {detail}")
        for path in paths:
            self.out(f"        {path}")
        if self.verbose or not ok:
            for line in self.last_output.rstrip().splitlines():
                self.out(f"        | {line}")
        return ok


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeError(message)


def _load_ckpt(path: Path) -> dict[str, Any]:
    import torch

    return torch.load(path, map_location="cpu", weights_only=True)


def _assert_same_state(a: dict[str, Any], b: dict[str, Any], what: str) -> None:
    import torch

    _check(a.keys() == b.keys(), f"{what}: llaves distintas")
    different = [k for k in a if not torch.equal(a[k], b[k])]
    _check(not different, f"{what}: {len(different)} tensor(es) distintos (p. ej. {different[:2]})")


def _assert_same_tree(a: Any, b: Any, what: str) -> None:
    """Igualdad exacta de estructuras anidadas (dict/list/tensores/escalares), p. ej. el estado del optimizador."""
    import torch

    if isinstance(a, torch.Tensor) and isinstance(b, torch.Tensor):
        _check(torch.equal(a, b), f"{what}: tensor distinto")
    elif isinstance(a, dict) and isinstance(b, dict):
        _check(a.keys() == b.keys(), f"{what}: llaves distintas")
        for key in a:
            _assert_same_tree(a[key], b[key], f"{what}.{key}")
    elif isinstance(a, list | tuple) and isinstance(b, list | tuple):
        _check(len(a) == len(b), f"{what}: longitudes distintas")
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            _assert_same_tree(x, y, f"{what}[{i}]")
    else:
        _check(a == b, f"{what}: {a!r} != {b!r}")


def _metrics(run: Path) -> list[dict[str, Any]]:
    from cerberus_training.train import TIMING_FIELDS

    rows = [r for r in _read_jsonl(run / "metrics.jsonl") if "event" not in r]
    return [{k: v for k, v in r.items() if k not in TIMING_FIELDS} for r in rows]


def _count_codes(records: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        for item in record[key]:
            counts[item["code"]] = counts.get(item["code"], 0) + 1
    return counts


def _build_steps(runner: _Runner) -> list[StepAction]:
    work, cfg, training = runner.work, runner.config_path, runner.training
    cfg_arg = ["--config", str(cfg)]
    run_dir = training / "runs" / CONTINUOUS_RUN
    cut_dir = training / "runs" / INTERRUPTED_RUN
    weights_path = work / "pesos_sinteticos" / WEIGHTS_NAME

    def generate() -> tuple[str, list[Path]]:
        data_root = work / "data" / "CFB-GBM-sintetico"
        generate_dataset(data_root)
        sha = generate_weights(weights_path)
        cfg.write_text(json.dumps(derive_config(work, sha), indent=2) + "\n", encoding="utf-8")
        (work / MARKER_NAME).write_text(MARKER_TEXT, encoding="utf-8")
        return (
            f"{len(STUDIES)} estudios de {len({s[0] for s in STUDIES})} pacientes, SegResNet de 3 salidas "
            f"(sha256 {sha[:12]}…), parche {PATCH}³, CPU sin AMP",
            [data_root, weights_path, cfg],
        )

    def validate() -> tuple[str, list[Path]]:
        runner.run_cli(["validate", *cfg_arg])
        return "configuración derivada válida", [cfg]

    def inventory() -> tuple[str, list[Path]]:
        from cerberus_training.manifest import read_inventory

        summary = training / "inventory_summary.json"
        runner.run_cli(["inventory", *cfg_arg, "--summary", str(summary)])
        records = read_inventory(training / "inventory.jsonl")
        eligible = [r for r in records if r["eligible"]]
        exclusions, review = _count_codes(records, "exclusions"), _count_codes(records, "review_flags")
        _check(len(records) == len(STUDIES), f"se esperaban {len(STUDIES)} estudios y hay {len(records)}")
        _check(len(eligible) == EXPECTED_ELIGIBLE, f"elegibles: {len(eligible)} (esperados {EXPECTED_ELIGIBLE})")
        _check(exclusions == EXPECTED_EXCLUSIONS, f"exclusiones {exclusions} (esperadas {EXPECTED_EXCLUSIONS})")
        _check(review == EXPECTED_REVIEW, f"señales de revisión {review} (esperadas {EXPECTED_REVIEW})")
        runner.facts["eligible"] = len(eligible)
        runner.facts["exclusions"] = exclusions
        return (
            f"{len(eligible)} elegibles de {len(records)}; exclusiones {exclusions}; revisión {review}",
            [training / "inventory.jsonl", summary],
        )

    def split() -> tuple[str, list[Path]]:
        runner.run_cli(["split", *cfg_arg])
        parts = json.loads((training / "splits.json").read_text(encoding="utf-8"))["partitions"]
        patients = {name: set(parts[name]["patients"]) for name in ("train", "val", "test")}
        _check(all(patients.values()), f"particiones vacías: { {k: len(v) for k, v in patients.items()} }")
        total = len(patients["train"] | patients["val"] | patients["test"])
        _check(total == sum(len(v) for v in patients.values()), "un paciente aparece en más de una partición")
        sizes = {k: (len(v), len(parts[k]["studies"])) for k, v in patients.items()}
        runner.facts["split_patients_studies"] = sizes
        return f"pacientes/estudios {sizes}", [training / "splits.json"]

    def preflight() -> tuple[str, list[Path]]:
        runner.run_cli(["preflight", *cfg_arg])
        return "recursos y pesos comprobados", []

    def prepare() -> tuple[str, list[Path]]:
        runner.run_cli(["prepare", *cfg_arg])
        report = json.loads((training / "prepare_report.json").read_text(encoding="utf-8"))
        _check(not report.get("errors"), f"errores de preparación: {report.get('errors')}")
        _check(report.get("completed") is True, "prepare no terminó")
        return f"{runner.facts['eligible']} estudios en caché", [training / "prepare_report.json", training / "cache"]

    def dry_run() -> tuple[str, list[Path]]:
        runner.run_cli(["train", *cfg_arg, "--dry-run"])
        _check(not (training / "runs").exists(), "el dry-run creó un run")
        return "sin backward, sin run creado", []

    def train() -> tuple[str, list[Path]]:
        import torch

        runner.run_cli(["train", *cfg_arg, "--run-id", CONTINUOUS_RUN])
        last = _load_ckpt(run_dir / "checkpoints" / "last.pt")
        _check(
            last["step"] == 2 and last["epoch"] == 2, f"pasos {last['step']}, épocas {last['epoch']} (esperados 2/2)"
        )
        rows = _metrics(run_dir)
        _check(len(rows) == 2 and all(np.isfinite(r["train_loss"]) for r in rows), "pérdida de entrenamiento no finita")
        key = "convInit.conv.weight"
        _check(
            not torch.equal(_load_ckpt(weights_path)[key], last["model"][key]), "los pesos no cambiaron tras 2 pasos"
        )
        _check((run_dir / "checkpoints" / "best.pt").is_file(), "no se guardó best.pt")
        return (
            f"2 pasos de optimización (2 épocas), pérdida {rows[0]['train_loss']:.3f} → {rows[1]['train_loss']:.3f}, "
            f"val Dice {rows[1]['val_dice']:.3f} (sin valor clínico)",
            [run_dir],
        )

    def resume() -> tuple[str, list[Path]]:
        from cerberus_training.train import run_training

        config = resolve_config(load_config(cfg))
        with contextlib.redirect_stdout(io.StringIO()):
            cut = run_training(config, run_id=INTERRUPTED_RUN, stop_after_epochs=1)
        _check(cut.epochs_completed == 1 and not cut.finished, "el corte tras la 1.ª época no dejó el run abierto")
        runner.run_cli(["train", *cfg_arg, "--resume", str(cut_dir / "checkpoints" / "last.pt")])
        a, b = _load_ckpt(run_dir / "checkpoints" / "last.pt"), _load_ckpt(cut_dir / "checkpoints" / "last.pt")
        _check(a["step"] == b["step"] == 2 and a["epoch"] == b["epoch"] == 2, "la reanudación no llegó a 2 pasos")
        _assert_same_state(a["model"], b["model"], "last.pt (continuo vs reanudado)")
        _assert_same_tree(a["optimizer"], b["optimizer"], "estado del optimizador (continuo vs reanudado)")
        _assert_same_state(
            _load_ckpt(run_dir / "checkpoints" / "best.pt")["model"],
            _load_ckpt(cut_dir / "checkpoints" / "best.pt")["model"],
            "best.pt (continuo vs reanudado)",
        )
        _check(_metrics(run_dir) == _metrics(cut_dir), "metrics.jsonl difiere entre continuo y reanudado")
        return "corte tras la época 1 + `--resume` idéntico a la ejecución continua (pesos, optimizador y métricas)", [
            cut_dir
        ]

    def evaluate_val() -> tuple[str, list[Path]]:
        runner.run_cli(["evaluate", "--run", str(run_dir), "--split", "val", "--bootstrap", "100"])
        summary = run_dir / "evaluation" / "val" / "summary.json"
        data = json.loads(summary.read_text(encoding="utf-8"))
        _check(data["n_studies"] >= 1 and data["n_patients"] >= 1, "evaluación de val sin estudios")
        return f"{data['n_studies']} estudios / {data['n_patients']} pacientes (bootstrap 100)", [summary.parent]

    def evaluate_test() -> tuple[str, list[Path]]:
        argv = ["evaluate", "--run", str(run_dir), "--split", "test", "--checkpoint", "best", "--bootstrap", "100"]
        runner.run_cli(argv)
        summary = run_dir / "evaluation" / "test" / "summary.json"
        data = json.loads(summary.read_text(encoding="utf-8"))
        _check(data["n_studies"] >= 1, "evaluación de test sin estudios")
        return f"{data['n_studies']} estudios / {data['n_patients']} pacientes (checkpoint best)", [summary.parent]

    def export() -> tuple[str, list[Path]]:
        runner.run_cli(["export", "--run", str(run_dir)])
        manifest = json.loads((run_dir / "export" / "export.json").read_text(encoding="utf-8"))
        _check(manifest["evaluation"]["status"] == "evaluated_test", f"estado {manifest['evaluation']['status']}")
        for name in ("model.pt", "export.json", "model_card.md"):
            _check((run_dir / "export" / name).is_file(), f"falta {name} en la exportación")
        return f"estado de evaluación {manifest['evaluation']['status']}", [run_dir / "export"]

    def roundtrip() -> tuple[str, list[Path]]:
        import torch

        from cerberus_training.export import load_export

        provenance = json.loads((run_dir / "provenance.json").read_text(encoding="utf-8"))
        expected = {k: provenance["hashes"][k] for k in ("split_sha256", "cache_key")}
        loaded = load_export(run_dir / "export", expected=expected)
        best = _load_ckpt(run_dir / "checkpoints" / "best.pt")
        _assert_same_state(dict(loaded.model.state_dict()), best["model"], "load_export vs best.pt")
        with torch.no_grad():
            out = loaded.model(torch.zeros(1, 4, PATCH, PATCH, PATCH))
        _check(tuple(out.shape) == (1, 1, PATCH, PATCH, PATCH) and bool(torch.isfinite(out).all()), "salida inválida")
        return (
            f"modelo recargado idéntico a best.pt; umbral {loaded.threshold}, canales {loaded.channel_order}",
            [run_dir / "export"],
        )

    return [
        generate,
        validate,
        inventory,
        split,
        preflight,
        prepare,
        dry_run,
        train,
        resume,
        evaluate_val,
        evaluate_test,
        export,
        roundtrip,
    ]


def _inside(child: Path, parent: Path) -> bool:
    return child == parent or parent in child.parents


def _prepare_work_dir(requested: Path | None) -> tuple[Path, bool]:
    """Directorio de trabajo y si lo creamos nosotros como temporal (solo entonces se borra al terminar)."""
    repo = REPO_ROOT.resolve()
    if requested is None:
        work = Path(tempfile.mkdtemp(prefix="cerberus-smoke-")).resolve()
        if _inside(work, repo):
            shutil.rmtree(work, ignore_errors=True)
            raise SmokeError(f"El directorio temporal {work} cae dentro del repo; defina TMPDIR o use --work-dir")
        return work, True
    work = requested.expanduser().resolve()
    if _inside(work, repo):
        raise SmokeError(f"--work-dir ({work}) no puede estar dentro del repo ({repo}): use una ruta externa")
    if work.exists() and (not work.is_dir() or any(work.iterdir())):
        raise SmokeError(f"--work-dir ({work}) debe no existir o estar vacío: el smoke nunca pisa archivos ajenos")
    work.mkdir(parents=True, exist_ok=True)
    return work, False


def _write_markers(work: Path) -> None:
    runs = work / "training" / "runs"
    for run in sorted(runs.iterdir()) if runs.is_dir() else []:
        if run.is_dir():
            (run / MARKER_NAME).write_text(MARKER_TEXT, encoding="utf-8")


def run_smoke(
    cli: Cli,
    *,
    work_dir: Path | None = None,
    keep: bool = False,
    verbose: bool = False,
    out: Callable[[str], None] = print,
) -> int:
    """Ejecuta el recorrido completo con `cli` (el `main` de la CLI) y devuelve 0 solo si todos los pasos pasan."""
    out(BANNER)
    out("Datos, pesos y métricas artificiales: solo comprueba el cableado, sin red ni GPU. No es un experimento.")
    try:
        work, temporary = _prepare_work_dir(work_dir)
    except (SmokeError, OSError) as exc:
        out(f"Error: {exc}")
        return EXIT_CONFIG_ERROR
    out(f"Directorio de trabajo: {work}")
    cleanup = temporary and not keep
    try:
        started = time.monotonic()
        runner = _Runner(cli, work, verbose, out)
        with network_blocked() as attempts:
            for name, action in zip(STEP_NAMES, _build_steps(runner), strict=True):
                if not runner.step(name, action):
                    break
        ok = len(runner.steps) == len(STEP_NAMES) and all(s.ok for s in runner.steps)
        for name in STEP_NAMES[len(runner.steps) :]:
            out(f"[ - ] — {name}: omitido por un fallo anterior")
        seconds = round(time.monotonic() - started, 1)
        if attempts:
            ok = False
            out(f"✗ Se bloquearon {len(attempts)} intento(s) de red: {attempts[:3]}")
        keep = keep or not temporary
        report: dict[str, Any] = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "banner": BANNER,
            "synthetic": True,
            "real_finetuning": False,
            "ok": ok,
            "created_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "seconds": seconds,
            "network_attempts_blocked": len(attempts),
            "facts": runner.facts,
            "steps": [asdict(s) | {"output": ""} for s in runner.steps],
        }
        if keep:
            _write_markers(work)
            (work / REPORT_NAME).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        passed = sum(s.ok for s in runner.steps)
        out(f"{BANNER}: {passed}/{len(STEP_NAMES)} pasos correctos en {seconds} s — {'OK' if ok else 'FALLÓ'}")
        if keep:
            out(f"Artefactos conservados en {work} (informe: {work / REPORT_NAME})")
        else:
            shutil.rmtree(work, ignore_errors=True)
            out(f"Directorio temporal {work} borrado (use --keep para conservarlo)")
        return EXIT_OK if ok else EXIT_SMOKE
    finally:
        if cleanup:  # también ante KeyboardInterrupt o excepciones inesperadas
            shutil.rmtree(work, ignore_errors=True)
