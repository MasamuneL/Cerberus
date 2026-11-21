"""Evalúa el TC (núcleo) exportado por Cerberus frente al GTV, por estudio."""

import argparse
import json
import os
import shutil
import statistics
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from nibabel.filebasedimages import ImageFileError

from cerberus_api import catalog, runtime
from cerberus_api.nifti import load_nifti
from cerberus_api.schemas import SegmentationResult
from cerberus_api.segmentation import CHANNEL_MAP, _to_grid, _weights_path, mask_metrics, run_segmentation
from cerberus_api.sequences import validate_file_name, validate_patient, validate_timepoint

METRICS = ("gtv_cm3", "tc_cm3", "dice", "hd95_mm", "recall", "precision")
MASK_FILE = f"{validate_file_name('monai_seg')}.nii.gz"
RESULT_FILE = "monai_seg.json"


@dataclass
class StudyMetrics:
    gtv_cm3: float
    tc_cm3: float
    dice: float
    hd95_mm: float | None
    recall: float | None
    precision: float | None


def score(mask_path: Path, gtv_path: Path) -> StudyMetrics:
    """Aplica B13 en el grid de la predicción, con el GTV remuestreado por vecino más cercano."""
    image = load_nifti(mask_path)
    labels = np.asarray(image.dataobj)
    tc = (labels == 2) | (labels == 3)
    gtv = _to_grid(load_nifti(gtv_path), image, 0) > 0.5
    sx, sy, sz = (float(value) for value in image.header.get_zooms()[:3])
    metrics = mask_metrics(tc, gtv, (sx, sy, sz))
    # Volumen por recuento de vóxeles, como en cerberus_eda.py:209-235, en el grid de evaluación.
    voxel_cm3 = sx * sy * sz / 1000
    return StudyMetrics(
        gtv_cm3=int(gtv.sum()) * voxel_cm3,
        tc_cm3=int(tc.sum()) * voxel_cm3,
        dice=metrics.dice,
        hd95_mm=metrics.hd95_mm,
        recall=metrics.recall,
        precision=metrics.precision,
    )


def reusable_result(directory: Path, newer_than_ns: int, channels: dict[str, str | None]) -> SegmentationResult | None:
    mask_path = directory / MASK_FILE
    result_path = directory / RESULT_FILE
    if not mask_path.is_file() or not result_path.is_file():
        return None

    mask_mtime = mask_path.stat().st_mtime_ns
    if not newer_than_ns < mask_mtime <= result_path.stat().st_mtime_ns:
        return None
    try:
        result = SegmentationResult.model_validate_json(result_path.read_bytes())
    except (OSError, ValueError):
        return None
    if {channel.model_channel: channel.sequence for channel in result.channels} != channels:
        return None
    return result


def summarize(rows: list[StudyMetrics]) -> dict[str, dict[str, float | int | None]]:
    summary = {}
    for name in METRICS:
        values: list[float] = [value for row in rows if (value := getattr(row, name)) is not None]
        summary[name] = {
            "n": len(values),
            "mean": statistics.mean(values) if values else None,
            "std": statistics.stdev(values) if len(values) > 1 else None,
        }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path(os.environ.get("CERBERUS_DATA_DIR", "Data")))
    parser.add_argument("--storage-dir", type=Path, default=Path(os.environ.get("CERBERUS_STORAGE_DIR", "storage")))
    parser.add_argument("--models-dir", type=Path, default=Path(os.environ.get("CERBERUS_MODELS_DIR", "models")))
    parser.add_argument(
        "--reuse", action=argparse.BooleanOptionalAction, default=True, help="Reutiliza máscaras vigentes"
    )
    parser.add_argument("--reuse-storage-dir", type=Path, help="Storage adicional de solo lectura para --reuse")
    parser.add_argument("--out", type=Path, required=True, help="Ruta de la tabla JSON")
    args = parser.parse_args()

    if not args.data_dir.is_dir():
        parser.error(f"Directorio de datos inexistente: {args.data_dir}")
    if args.reuse_storage_dir and args.storage_dir.resolve() == args.reuse_storage_dir.resolve():
        parser.error("--storage-dir y --reuse-storage-dir deben ser distintos")
    weights = _weights_path(args.models_dir)
    if not weights.is_file():
        parser.error(f"Pesos locales inexistentes: {weights}")
    weights_mtime_ns = weights.stat().st_mtime_ns
    results_dir = args.storage_dir / "results"
    studies = catalog.list_studies(args.data_dir, results_dir)
    if not studies:
        parser.error(f"No se encontraron estudios NIfTI en {args.data_dir}")

    threads, _ = runtime.configure_threads()
    print(f"Hilos del worker: {threads}", flush=True)
    if uptime := shutil.which("uptime"):
        subprocess.run([uptime], check=False)

    rows: list[dict[str, object]] = []
    measured: list[StudyMetrics] = []
    excluded: list[dict[str, str]] = []
    failed: list[dict[str, str]] = []
    for study in studies:
        patient = validate_patient(study.patient)
        timepoint = validate_timepoint(study.timepoint)
        key = {"patient": patient, "timepoint": timepoint}
        files = {}
        for sequence in study.sequences:
            path = catalog.sequence_path(args.data_dir, patient, timepoint, sequence)
            if path is not None:
                files[sequence] = path
        channels = {
            name: next((sequence for sequence in candidates if sequence in files), None)
            for name, candidates in CHANNEL_MAP.items()
        }
        missing = []
        if "gtv" not in files:
            missing.append("sin GTV")
        if not any(channels.values()):
            missing.append("sin secuencias utilizables por MONAI")
        if missing:
            excluded.append({**key, "reason": ", ".join(missing)})
            continue

        out_dir = results_dir / patient / timepoint
        print(f"{patient}/{timepoint}", flush=True)
        try:
            source = "inferencia"
            result = None
            mask_path = out_dir / MASK_FILE
            if args.reuse:
                inputs = [files[sequence] for sequence in channels.values() if sequence is not None]
                if "brain_mask" in files:
                    inputs.append(files["brain_mask"])
                newest_ns = max(weights_mtime_ns, *(path.stat().st_mtime_ns for path in inputs))
                candidates = [(out_dir, "storage de trabajo")]
                if args.reuse_storage_dir:
                    candidates.insert(0, (args.reuse_storage_dir / "results" / patient / timepoint, "storage previo"))
                for directory, location in candidates:
                    result = reusable_result(directory, newest_ns, channels)
                    if result is not None:
                        mask_path = directory / MASK_FILE
                        source = location
                        break
            if result is None:
                out_dir.mkdir(parents=True, exist_ok=True)
                with TemporaryDirectory(dir=out_dir) as temporary:
                    staging = Path(temporary)
                    result = run_segmentation(files, staging, args.models_dir)
                    (staging / MASK_FILE).replace(mask_path)
                    (staging / RESULT_FILE).replace(out_dir / RESULT_FILE)
            metrics = score(mask_path, files["gtv"])
        except (OSError, ValueError, RuntimeError, ImageFileError) as exc:
            print(f"  Falló: {exc}", flush=True)
            failed.append({**key, "reason": str(exc)})
            continue

        print(f"  {source}, {result.device}, Dice {metrics.dice:.6f}", flush=True)
        measured.append(metrics)
        rows.append(
            {
                **key,
                **asdict(metrics),
                "source": source,
                "device": result.device,
                "channels": channels,
                "warnings": result.warnings,
            }
        )

    report = {
        "weights_mtime_utc": datetime.fromtimestamp(weights_mtime_ns / 1e9, UTC).isoformat(),
        "studies": rows,
        "summary": summarize(measured),
        "excluded": excluded,
        "failed": failed,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")
    return int(bool(failed))


if __name__ == "__main__":
    raise SystemExit(main())
