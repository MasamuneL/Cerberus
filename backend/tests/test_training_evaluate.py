"""Tests de FT4: evaluación, baseline y exportación (docs/PLAN_PIPELINE_FINETUNING.md §7).

Métricas con valores calculados a mano (spacing anisotrópico), casos vacíos, agregación tiempos → paciente,
bootstrap por paciente, restauración geométrica (affines invertidos y oblicuos) frente a la GTV original, aislamiento
de test, no sobrescritura, baseline con predictor falso y exportación de ida y vuelta. Los estudios son NIfTI
sintéticos diminutos (fantomas de FT2) preparados de verdad; el trainer usa la red pequeña de FT3 o SegResNet con
pesos artificiales. Sin red, sin GPU y sin `Data/`.
"""

import ast
import csv
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import torch
from test_training_prepare import PRE, grid, gtv_fn, world, write_study
from test_training_train import TINY, segresnet_weights, tiny_weights, write_config

import cerberus_training.train as train_mod
from cerberus_training.__main__ import EXIT_CHECKPOINT, EXIT_CONFIG_ERROR, EXIT_DATA_ERROR, main
from cerberus_training.artifacts import RunLockedError, RunPaths, write_json_once
from cerberus_training.cache import StudyCache, prepare_all
from cerberus_training.config import TrainConfig, load_config, resolve_config
from cerberus_training.evaluate import (
    METRICS,
    EvaluationDataError,
    EvaluationError,
    EvaluationExistsError,
    bootstrap_ci,
    evaluate_baseline,
    evaluate_run,
    patient_table,
    study_metrics,
    summarize,
)
from cerberus_training.export import ExportError, export_run, load_export
from cerberus_training.inventory import write_inventory
from cerberus_training.model import CheckpointError, build_adapted_model
from cerberus_training.splits import build_splits, write_or_reuse_splits
from cerberus_training.train import run_training
from cerberus_training.transforms import (
    Geometry,
    prepare_study,
    reference_label,
    reference_spacing,
    restore_to_reference,
)

# ---------------------------------------------------------------------------------------------------------------
# Métricas por estudio: valores calculados a mano
# ---------------------------------------------------------------------------------------------------------------

SPACING = (0.5, 1.0, 2.0)  # anisotrópico: mm por eje de vóxel


def cube(lo: tuple[int, int, int], hi: tuple[int, int, int]) -> np.ndarray:
    out = np.zeros((10, 10, 10), np.uint8)
    out[lo[0] : hi[0], lo[1] : hi[1], lo[2] : hi[2]] = 1
    return out


def test_metrics_shifted_cube_by_hand() -> None:
    # GTV 4×4×4 (64 vóxeles); predicción desplazada 1 vóxel en el eje 2 (2 mm): TP = 4·4·3 = 48.
    ref = cube((2, 2, 2), (6, 6, 6))
    pred = cube((2, 2, 3), (6, 6, 7))
    m = study_metrics(pred, ref, SPACING)
    assert m["dice"] == pytest.approx(2 * 48 / 128)
    assert m["recall"] == pytest.approx(48 / 64) and m["precision"] == pytest.approx(48 / 64)
    # La cara z=6 de la predicción (16 de 56 vóxeles de superficie, > 5 %) está a 2 mm de la superficie de la GTV.
    assert m["hd95_mm"] == pytest.approx(2.0)
    voxel_cm3 = 0.5 * 1.0 * 2.0 / 1000
    assert m["gtv_cm3"] == pytest.approx(64 * voxel_cm3) and m["pred_cm3"] == pytest.approx(64 * voxel_cm3)
    assert m["volume_error_cm3"] == 0 and m["abs_volume_error_cm3"] == 0
    assert m["empty_case"] == "none"


def test_metrics_oversegmentation_by_hand() -> None:
    # Predicción 4×4×5 (80) contiene la GTV 4×4×4 (64): Dice 128/144, recall 1, precisión 0.8.
    ref = cube((2, 2, 2), (6, 6, 6))
    pred = cube((2, 2, 2), (6, 6, 7))
    m = study_metrics(pred, ref, SPACING)
    assert m["dice"] == pytest.approx(128 / 144)
    assert m["recall"] == 1.0 and m["precision"] == pytest.approx(0.8)
    assert m["hd95_mm"] == pytest.approx(2.0)
    assert m["volume_error_cm3"] == pytest.approx(0.016) and m["abs_volume_error_cm3"] == pytest.approx(0.016)
    under = study_metrics(ref, pred, SPACING)  # infra-segmentación: error firmado negativo, absoluto positivo
    assert under["volume_error_cm3"] == pytest.approx(-0.016) and under["abs_volume_error_cm3"] == pytest.approx(0.016)


@pytest.mark.parametrize(
    ("pred_on", "gtv_on", "case", "dice", "recall", "precision"),
    [
        (False, False, "both_empty", 1.0, None, None),
        (False, True, "pred_empty", 0.0, 0.0, None),
        (True, False, "gtv_empty", 0.0, None, 0.0),
    ],
)
def test_metrics_empty_cases(
    pred_on: bool, gtv_on: bool, case: str, dice: float, recall: float | None, precision: float | None
) -> None:
    block = cube((2, 2, 2), (5, 5, 5))
    empty = np.zeros_like(block)
    m = study_metrics(block if pred_on else empty, block if gtv_on else empty, SPACING)
    assert m["empty_case"] == case and m["dice"] == dice and m["hd95_mm"] is None
    assert m["recall"] == recall and m["precision"] == precision


# ---------------------------------------------------------------------------------------------------------------
# Agregación y bootstrap
# ---------------------------------------------------------------------------------------------------------------


def row(study: str, patient: str, dice: float, recall: float | None = 0.5, case: str = "none") -> dict[str, Any]:
    return {
        "study_id": study,
        "patient": patient,
        "dice": dice,
        "recall": recall,
        "precision": 0.5,
        "hd95_mm": None if case != "none" else 1.0,
        "volume_error_cm3": -1.0,
        "abs_volume_error_cm3": 1.0,
        "empty_case": case,
    }


def test_patient_aggregation_by_hand() -> None:
    rows = [
        row("A_t0", "A", 0.9, recall=None),
        row("A_t1", "A", 0.5, recall=0.4),
        row("B_t0", "B", 1.0, recall=None, case="both_empty"),
        row("C_t0", "C", 0.2, recall=None),
    ]
    patients = patient_table(rows)
    assert [p["patient"] for p in patients] == ["A", "B", "C"]
    assert patients[0]["dice"] == pytest.approx(0.7) and patients[0]["n_studies"] == 2
    assert patients[0]["recall"] == pytest.approx(0.4) and patients[0]["recall_n"] == 1
    assert patients[1]["recall"] is None and patients[1]["recall_n"] == 0
    metrics, empty = summarize(rows, patients, samples=200, seed=1)
    d = metrics["dice"]
    # Media de pacientes (0.7, 1.0, 0.2) = 0.6333…, no la media de estudios (0.65).
    assert d["mean"] == pytest.approx(1.9 / 3) and d["median"] == pytest.approx(0.7)
    assert d["std"] == pytest.approx(np.sqrt((0.2 / 3) ** 2 + (1.1 / 3) ** 2 + (1.3 / 3) ** 2) / np.sqrt(2))
    assert d["q1"] == pytest.approx(0.45) and d["q3"] == pytest.approx(0.85) and d["iqr"] == pytest.approx(0.4)
    assert (d["n_valid_patients"], d["n_patients"], d["n_valid_studies"], d["n_studies"]) == (3, 3, 4, 4)
    r = metrics["recall"]
    assert (r["n_valid_patients"], r["n_valid_studies"], r["std"], r["ci95"]) == (1, 1, None, None)
    assert metrics["hd95_mm"]["n_valid_studies"] == 3
    assert empty["both_empty"] == {"count": 1, "studies": ["B_t0"]}
    assert empty["pred_empty"]["count"] == 0 and empty["gtv_empty"]["count"] == 0


def test_bootstrap_is_deterministic_and_resamples_patients() -> None:
    values: dict[str, list[float | None]] = {"dice": [0.1, 0.5, 0.9, 0.7], "recall": [None, 0.2, 0.4, None]}
    first = bootstrap_ci(values, samples=500, seed=7)
    assert first == bootstrap_ci(values, samples=500, seed=7)
    assert first != bootstrap_ci(values, samples=500, seed=8)
    # Referencia manual: índices de paciente (no de estudio) con default_rng(seed), mismas réplicas por métrica.
    idx = np.random.default_rng(7).integers(0, 4, size=(500, 4))
    means = np.asarray(values["dice"], dtype=float)[idx].mean(axis=1)
    assert first["dice"] == pytest.approx(list(np.percentile(means, [2.5, 97.5])))
    rec = np.array([np.nan, 0.2, 0.4, np.nan])[idx]
    valid = ~np.isnan(rec)
    keep = valid.sum(axis=1) > 0
    rec_means = np.where(valid, rec, 0).sum(axis=1)[keep] / valid.sum(axis=1)[keep]
    assert first["recall"] == pytest.approx(list(np.percentile(rec_means, [2.5, 97.5])))


def test_bootstrap_two_valid_of_fifty_patients() -> None:
    # 2 de 50 pacientes con valor: P(réplica sin ninguno) = (48/50)^50 ≈ 0.13; esas réplicas se descartan.
    values: dict[str, list[float | None]] = {"recall": [0.2, 0.8, *([None] * 48)]}
    ci = bootstrap_ci(values, samples=1000, seed=0)["recall"]
    assert ci is not None and 0.2 <= ci[0] <= ci[1] <= 0.8 and all(np.isfinite(ci))
    # Con una sola réplica que no contiene a ninguno de los dos pacientes válidos, no hay IC (None, no NaN).
    seed = next(s for s in range(1000) if not set(np.random.default_rng(s).integers(0, 50, size=(1, 50))[0]) & {0, 1})
    assert bootstrap_ci(values, samples=1, seed=seed)["recall"] is None


def test_bootstrap_unit_is_patient_not_study() -> None:
    # Repetir los estudios de un paciente (mismos valores) no cambia nada: la unidad es el paciente.
    base = [row("A_t0", "A", 0.2), row("B_t0", "B", 0.6), row("C_t0", "C", 0.9)]
    many = base + [row(f"A_t{i}", "A", 0.2) for i in range(1, 10)]
    one, _ = summarize(base, patient_table(base), samples=300, seed=3)
    rep, _ = summarize(many, patient_table(many), samples=300, seed=3)
    assert one["dice"]["ci95"] == rep["dice"]["ci95"] and one["dice"]["mean"] == rep["dice"]["mean"]
    assert rep["dice"]["n_valid_studies"] == 12 and rep["dice"]["n_valid_patients"] == 3


# ---------------------------------------------------------------------------------------------------------------
# Restauración geométrica frente a la GTV original
# ---------------------------------------------------------------------------------------------------------------


@pytest.fixture
def root(tmp_path: Path) -> Path:
    data_root = tmp_path / "cfb"
    data_root.mkdir()
    return data_root.resolve()


@pytest.mark.parametrize(
    ("ref", "exact"),
    [
        (grid(flips=(True, False, True)), True),
        (grid(perm=(2, 0, 1), flips=(False, True, False), spacing=(1.0, 1.0, 2.0)), True),
        (grid(rot_deg=25), False),
    ],
    ids=["flips", "perm-anisotropic", "oblique"],
)
def test_prepared_prediction_matches_original_gtv(root: Path, ref: Any, exact: bool) -> None:
    record = write_study(root, default=ref)
    study = prepare_study(record, root, PRE)
    # Predicción perfecta en el grid preparado (= GTV preparada), restaurada al grid original de la T1c.
    pred = restore_to_reference(study.label, study.geometry)
    gtv, resampled = reference_label(record, root, study.geometry)
    assert not resampled and np.array_equal(gtv, gtv_fn(world(ref)).astype(np.uint8))
    m = study_metrics(pred, gtv, reference_spacing(study.geometry))
    if exact:
        assert m["dice"] == 1.0 and m["hd95_mm"] == 0.0
    else:
        assert m["dice"] > 0.85 and m["recall"] is not None and m["recall"] > 0.85


def test_gtv_on_another_grid_is_resampled_to_t1c(root: Path) -> None:
    ref = grid()
    # Misma caja con ejes permutados e invertidos: el vecino más próximo es exacto.
    record = write_study(root, default=ref, grids={"gtv": grid(perm=(1, 0, 2), flips=(True, False, True))})
    study = prepare_study(record, root, PRE)
    gtv, resampled = reference_label(record, root, study.geometry)
    assert resampled and np.array_equal(gtv, gtv_fn(world(ref)).astype(np.uint8))
    # GTV más fina (0.5 mm): los centros de 1 mm caen entre dos vóxeles fuente; aproximada.
    fine = write_study(root, "002", default=ref, grids={"gtv": grid(spacing=(0.5, 0.5, 0.5))})
    gtv, resampled = reference_label(fine, root, prepare_study(fine, root, PRE).geometry)
    assert resampled and gtv.shape == ref[0]
    assert study_metrics(gtv, gtv_fn(world(ref)), (1.0, 1.0, 1.0))["dice"] > 0.8


def test_gtv_lost_outside_support_counts_as_false_negative(root: Path) -> None:
    def far(w: np.ndarray) -> np.ndarray:  # GTV + una parte en una esquina, fuera de la máscara cerebral
        return gtv_fn(w) | (np.linalg.norm(w - np.array([9.0, 9.0, 7.0]), axis=-1) <= 1.0)

    record = write_study(root, label=far)
    study = prepare_study(record, root, PRE)
    assert study.label_lost_voxels > 0
    pred = restore_to_reference(study.label, study.geometry)  # predicción perfecta dentro del recorte
    gtv, _ = reference_label(record, root, study.geometry)
    m = study_metrics(pred, gtv, reference_spacing(study.geometry))
    assert m["precision"] == 1.0 and m["recall"] is not None and m["recall"] < 1.0
    assert int(gtv.sum()) - int(pred.sum()) == study.label_lost_voxels


def test_sheared_reference_grid_is_rejected() -> None:
    affine = np.eye(4)
    affine[0, 1] = 0.3
    sheared = Geometry((4, 4, 4), affine, (4, 4, 4), np.eye(4), 1.0)
    with pytest.raises(ValueError, match="cizalla"):
        reference_spacing(sheared)
    rotated = np.eye(4)
    t = np.deg2rad(30)
    rotated[:2, :2] = [[np.cos(t), -np.sin(t)], [np.sin(t), np.cos(t)]]
    rotated[:3, :3] = rotated[:3, :3] @ np.diag([0.5, 1.0, 2.0])
    oblique = Geometry((4, 4, 4), rotated, (4, 4, 4), np.eye(4), 1.0)
    assert reference_spacing(oblique) == pytest.approx((0.5, 1.0, 2.0))


# ---------------------------------------------------------------------------------------------------------------
# Workspace sintético completo: NIfTI → inventario → split → prepare → train
# ---------------------------------------------------------------------------------------------------------------

STUDIES = (
    ("001", "t0", grid()),
    ("001", "t1", grid(flips=(True, False, False))),
    ("002", "t0", grid(flips=(True, False, True))),
    ("003", "t0", grid(rot_deg=20)),
    ("004", "t0", grid(spacing=(1.0, 1.0, 2.0))),
    ("005", "t0", grid(perm=(1, 0, 2))),
)


def build_data(config: TrainConfig) -> list[dict[str, Any]]:
    """Escribe los estudios (contenido distinto por estudio para que no sean duplicados), inventario, split y caché."""
    root = config.paths.data_root
    root.mkdir(parents=True, exist_ok=True)
    records = []
    for i, (patient, timepoint, g) in enumerate(STUDIES):

        def edit(seq: str, data: np.ndarray, k: int = i) -> np.ndarray:
            return data if seq in ("gtv", "brain_mask") else data + np.float32(k)

        records.append(write_study(root, patient, timepoint, default=g, edit=edit))
    work = config.paths.work_dir
    write_inventory(records, work / "inventory.jsonl")
    write_or_reuse_splits(build_splits(records, config.split), work / "splits.json")
    report = prepare_all(config, records)
    assert not report.errors, report.errors
    return records


def tiny_run(tmp_path: Path) -> tuple[TrainConfig, Path]:
    cfg = write_config(tmp_path, tiny_weights(tmp_path), max_epochs=1)
    config = resolve_config(load_config(cfg))
    build_data(config)
    result = run_training(config, run_id="tiny", spec=TINY)
    return config, result.run_dir


def perfect(config: TrainConfig) -> Any:
    """Predictor falso que devuelve la GTV preparada de cada estudio (identificado por la imagen)."""
    cache = StudyCache.from_config(config)
    studies = [cache.load(path.stem) for path in sorted(cache.directory.glob("*.npz"))]

    def predict(image: np.ndarray) -> np.ndarray:
        match = next(s for s in studies if s.image.shape == image.shape and np.array_equal(s.image, image))
        return match.label.astype(np.float32)

    return predict


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def partition(config: TrainConfig, name: str) -> list[str]:
    splits = json.loads((config.paths.work_dir / "splits.json").read_text(encoding="utf-8"))
    return list(splits["partitions"][name]["studies"])


def test_evaluate_with_injected_predictor_writes_outputs(tmp_path: Path) -> None:
    config, run = tiny_run(tmp_path)
    result = evaluate_run(run, "val", spec=TINY, predictor=perfect(config), bootstrap_samples=100)
    out = run / "evaluation" / "val"
    assert result.directory == out
    assert {p.name for p in out.iterdir()} == {"per_study.csv", "per_patient.csv", "summary.json"}
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["model"] == "adapted" and summary["split"] == "val"
    assert summary["threshold"] == {"value": 0.5, "source": "checkpoint"}
    assert summary["checkpoint"]["kind"] == "best" and summary["bootstrap"]["unit"] == "patient"
    provenance = json.loads((run / "provenance.json").read_text(encoding="utf-8"))
    assert summary["hashes"]["split_sha256"] == provenance["hashes"]["split_sha256"]
    rows = read_csv(out / "per_study.csv")
    assert [r["study_id"] for r in rows] == partition(config, "val")
    for r in rows:  # GTV preparada restaurada = GTV original en estos grids alineados
        assert float(r["dice"]) == 1.0 and r["label_resampled"] == "false"
    assert set(read_csv(out / "per_patient.csv")[0]) >= {"patient", "n_studies", *METRICS}


def test_evaluation_is_never_overwritten(tmp_path: Path) -> None:
    config, run = tiny_run(tmp_path)
    evaluate_run(run, "test", checkpoint="best", spec=TINY, predictor=perfect(config), bootstrap_samples=100)
    before = (run / "evaluation" / "test" / "summary.json").read_bytes()
    with pytest.raises(EvaluationExistsError):
        evaluate_run(run, "test", checkpoint="best", spec=TINY, predictor=perfect(config), bootstrap_samples=100)
    assert (run / "evaluation" / "test" / "summary.json").read_bytes() == before
    assert not list((run / "evaluation").glob(".*"))  # sin temporales huérfanos


def test_test_split_is_isolated_and_threshold_never_tuned_on_test(tmp_path: Path) -> None:
    # El trainer no importa ni llama a la evaluación explícita.
    tree = ast.parse(Path(train_mod.__file__).read_text(encoding="utf-8"))
    imported = {
        node.module if isinstance(node, ast.ImportFrom) else alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in node.names
    }
    assert not any(name and ("evaluate" in name or "export" in name) for name in imported)
    config, run = tiny_run(tmp_path)
    assert not (run / "evaluation").exists()  # entrenar no evalúa nada
    with pytest.raises(EvaluationError, match="nunca sobre test"):
        evaluate_run(run, "test", optimize=True, spec=TINY, predictor=perfect(config))
    assert not (run / "threshold.json").exists() and not (run / "evaluation").exists()

    # Optimizar en val, persistir y después evaluar test con ese umbral (sin volver a optimizar).
    val = evaluate_run(run, "val", optimize=True, spec=TINY, predictor=perfect(config), bootstrap_samples=100)
    stored = json.loads((run / "threshold.json").read_text(encoding="utf-8"))
    assert val.threshold_file == run / "threshold.json" and stored["split"] == "val"
    assert stored["threshold"] == 0.5  # predicción perfecta: todos empatan → el más cercano al del checkpoint
    assert any("optimistas" in w for w in val.summary["warnings"])
    test = evaluate_run(run, "test", checkpoint="best", spec=TINY, predictor=perfect(config), bootstrap_samples=100)
    assert test.summary["threshold"] == {"value": stored["threshold"], "source": "optimized_on_val"}
    with pytest.raises(EvaluationError, match="una sola vez"):
        evaluate_run(run, "val", checkpoint="last", optimize=True, spec=TINY, predictor=perfect(config))


def test_threshold_cannot_be_tuned_after_test_was_seen(tmp_path: Path) -> None:
    config, run = tiny_run(tmp_path)
    evaluate_run(run, "test", checkpoint="best", spec=TINY, predictor=perfect(config), bootstrap_samples=100)
    with pytest.raises(EvaluationError, match="después de ver test"):
        evaluate_run(run, "val", optimize=True, spec=TINY, predictor=perfect(config))
    assert not (run / "threshold.json").exists()


def test_run_hashes_and_lock_are_checked(tmp_path: Path) -> None:
    config, run = tiny_run(tmp_path)
    paths = RunPaths(run)
    paths.lock.write_text("123\n", encoding="utf-8")
    with pytest.raises(RunLockedError):
        evaluate_run(run, "val", spec=TINY, predictor=perfect(config))
    paths.lock.unlink()
    with pytest.raises(CheckpointError, match="difiere en head, model"):  # run de la red pequeña cargado como SegResNet
        evaluate_run(run, "val", predictor=perfect(config))
    provenance = json.loads(paths.provenance.read_text(encoding="utf-8"))
    provenance["hashes"]["split_sha256"] = "f" * 64
    paths.provenance.write_text(json.dumps(provenance), encoding="utf-8")
    with pytest.raises(CheckpointError, match="split_sha256"):
        evaluate_run(run, "val", spec=TINY, predictor=perfect(config))
    assert not (run / "evaluation").exists()


def test_changed_gtv_source_is_a_data_error(tmp_path: Path) -> None:
    config, run = tiny_run(tmp_path)
    patient, timepoint = partition(config, "val")[0].split("_")
    gtv = config.paths.data_root / patient / timepoint / f"{int(patient)}_{timepoint}_gtv.nii.gz"
    gtv.write_bytes(gtv.read_bytes() + b"\0")
    with pytest.raises(EvaluationDataError, match="source_changed") as info:
        evaluate_run(run, "val", spec=TINY, predictor=perfect(config))
    assert info.value.code == "source_changed"
    assert not (run / "evaluation").exists()


def noisy(config: TrainConfig, calls: list[int] | None = None, fail_after: int | None = None) -> Any:
    """GTV preparada con probabilidad 1 y ruido de falsos positivos en [0, 0.7) dentro del soporte."""
    base = perfect(config)

    def predict(image: np.ndarray) -> np.ndarray:
        if calls is not None:
            calls.append(1)
            if fail_after is not None and len(calls) > fail_after:
                raise RuntimeError("fallo simulado del predictor")
        label = base(image)
        rng = np.random.default_rng(int(image.size))
        noise = rng.uniform(0.0, 0.7, label.shape).astype(np.float32) * (image[0] != 0)
        return np.maximum(label, noise)

    return predict


def test_threshold_optimization_is_non_trivial_and_used_on_test(tmp_path: Path) -> None:
    config, run = tiny_run(tmp_path)
    val = evaluate_run(run, "val", optimize=True, spec=TINY, predictor=noisy(config), bootstrap_samples=100)
    stored = json.loads((run / "threshold.json").read_text(encoding="utf-8"))
    # Con umbrales < 0.7 entra ruido (Dice < 1); desde 0.70 la predicción es perfecta → el más cercano a 0.5: 0.70.
    assert stored["threshold"] == 0.7 and stored["scores"]["0.70"] == 1.0 and stored["scores"]["0.50"] < 1.0
    assert val.summary["threshold"] == {"value": 0.7, "source": "optimized_on_val"}
    assert all(r["dice"] == 1.0 for r in val.rows)
    test = evaluate_run(run, "test", checkpoint="best", spec=TINY, predictor=noisy(config), bootstrap_samples=100)
    assert test.summary["threshold"] == {"value": 0.7, "source": "optimized_on_val"}
    assert all(r["dice"] == 1.0 for r in test.rows)


def test_threshold_is_written_only_after_successful_val_evaluation(tmp_path: Path) -> None:
    config, run = tiny_run(tmp_path)
    n_val = len(partition(config, "val"))
    calls: list[int] = []
    with pytest.raises(RuntimeError, match="fallo simulado"):  # falla en la pasada de evaluación, tras optimizar
        evaluate_run(run, "val", optimize=True, spec=TINY, predictor=noisy(config, calls, fail_after=n_val))
    assert len(calls) == n_val + 1
    assert not (run / "threshold.json").exists() and not (run / "evaluation" / "val").exists()


def test_threshold_of_another_checkpoint_is_not_used(tmp_path: Path) -> None:
    config, run = tiny_run(tmp_path)
    write_json_once(
        run / "threshold.json",
        {
            "schema_version": 1,
            "threshold": 0.85,
            "split": "val",
            "checkpoint": {"kind": "best", "state_sha256": "a" * 64},
        },
    )
    result = evaluate_run(run, "test", checkpoint="best", spec=TINY, predictor=perfect(config), bootstrap_samples=100)
    assert result.summary["threshold"] == {"value": 0.5, "source": "checkpoint"}
    assert any("otro checkpoint" in w for w in result.summary["warnings"])


def test_baseline_pipeline_errors_are_data_errors_with_code(tmp_path: Path) -> None:
    _config, run = tiny_run(tmp_path)

    def wrong_shape(x: np.ndarray) -> np.ndarray:
        return np.zeros((3, 2, 2, 2), np.float32)  # no casa con la brain_mask del grid del baseline

    with pytest.raises(EvaluationDataError) as info:
        evaluate_baseline(run, "val", baseline_predictor=wrong_shape)
    assert info.value.code == "baseline_failed"
    assert not (run / "evaluation" / "val-baseline").exists()


def test_baseline_with_fake_predictor_records_differences(tmp_path: Path) -> None:
    _config, run = tiny_run(tmp_path)
    seen: list[tuple[int, ...]] = []

    def fake(x: np.ndarray) -> np.ndarray:
        """TC = canal T1c normalizado > 0 (mitad brillante del fantoma); WT y ET vacíos."""
        seen.append(x.shape)
        out = np.zeros((3, *x.shape[1:]), np.float32)
        out[0] = (x[0] > 0).astype(np.float32)
        return out

    result = evaluate_baseline(run, "test", baseline_predictor=fake, bootstrap_samples=100)
    assert seen and all(s[0] == 4 for s in seen)
    out = run / "evaluation" / "test-baseline"
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert result.directory == out and summary["model"] == "baseline"
    assert "no son una equivalencia de etiquetas" in summary["label_caveat"]
    assert summary["baseline"]["channel_map"]["T2"] == ["t2tse", "t2star"]
    assert summary["baseline"]["output_used"].startswith("TC") and summary["baseline"]["predictor"] == "custom"
    assert any("TC" in d and "GTV" in d for d in summary["differences_vs_adapted"])
    assert len(summary["baseline"]["preprocessing"]) >= 3
    rows = read_csv(out / "per_study.csv")
    assert rows and all(r["baseline_channels"] == "T1c=t1gd;T1=t1eg;T2=t2tse;FLAIR=flair" for r in rows)
    for r in rows:
        assert 0.0 < float(r["dice"]) < 1.0 and r["label_lost_voxels"] == ""
    with pytest.raises(EvaluationExistsError):
        evaluate_baseline(run, "test", baseline_predictor=fake)
    assert not (run / "evaluation" / "test").exists()  # el baseline no escribe en la carpeta del adaptado


# ---------------------------------------------------------------------------------------------------------------
# SegResNet real (pesos artificiales): exportación de ida y vuelta y CLI de extremo a extremo
# ---------------------------------------------------------------------------------------------------------------


BUNDLE_METADATA = {
    "version": "9.9.9-sintetico",
    "name": "Bundle sintético",
    "authors": "Autores de prueba",
    "copyright": "Copyright de prueba",
    "data_source": "Datos sintéticos",
    "intended_use": "Solo tests",
    "references": ["Referencia sintética A", "Referencia sintética B"],
}


def bundle_weights(tmp_path: Path) -> Path:
    """Pesos artificiales con la estructura de un bundle MONAI: `<bundle>/models/model.pt`, metadata y LICENSE."""
    bundle = tmp_path / "bundle"
    (bundle / "models").mkdir(parents=True)
    (bundle / "configs").mkdir()
    weights = segresnet_weights(tmp_path).rename(bundle / "models" / "model.pt")
    (bundle / "configs" / "metadata.json").write_text(json.dumps(BUNDLE_METADATA), encoding="utf-8")
    (bundle / "LICENSE").write_text("Apache License\nVersion 2.0, January 2004\n", encoding="utf-8")
    return weights


def segresnet_run(tmp_path: Path, bundle: bool = False) -> tuple[TrainConfig, Path]:
    weights = bundle_weights(tmp_path) if bundle else segresnet_weights(tmp_path)
    cfg = write_config(tmp_path, weights, max_epochs=1)
    config = resolve_config(load_config(cfg))
    build_data(config)
    assert main(["train", "--config", str(cfg), "--run-id", "seg"]) == 0
    return config, config.paths.work_dir / "runs" / "seg"


def test_export_roundtrip_status_and_tampering(tmp_path: Path) -> None:
    config, run = segresnet_run(tmp_path, bundle=True)
    exported = export_run(run)
    out = run / "export"
    assert exported.directory == out
    assert {p.name for p in out.iterdir()} == {"model.pt", "export.json", "model_card.md"}
    manifest = exported.manifest
    assert manifest["evaluation"]["status"] == "not_evaluated" and manifest["evaluation"]["adapted"] == []
    assert manifest["channel_order"] == ["T1c", "T1", "T2", "FLAIR"]
    assert manifest["transforms"]["transforms_version"] == "ft2-v2" and manifest["threshold"]["value"] == 0.5
    assert manifest["architecture"]["kwargs"]["blocks_down"] == [1, 2, 2, 4]
    assert manifest["license"]["name"] == "CC BY 4.0" and manifest["dataset"]["doi"] == "10.7937/v9pn-2f72"
    assert set(manifest["hashes"]) >= {"weights_file_sha256", "split_sha256", "eligible_records_sha256", "cache_key"}
    pre = manifest["pretrained"]
    assert pre["version"] == "9.9.9-sintetico" and pre["name"] == "Bundle sintético"
    assert pre["version_matches_config"] is False  # la configuración dice 0.5.4
    assert (
        pre["license"].startswith("Apache-2.0") and pre["citation"] == "Referencia sintética A; Referencia sintética B"
    )
    assert manifest["transforms"]["inference"]["amp_training"] is False
    card = (out / "model_card.md").read_text(encoding="utf-8")
    assert "not_evaluated" in card and "10.7937/v9pn-2f72" in card and "CC BY 4.0" in card and "Sin evaluar" in card
    assert "Referencia sintética A" in card and "Apache-2.0" in card and "9.9.9-sintetico" in card

    # Ida y vuelta: mismas salidas que el checkpoint best.
    loaded = load_export(out, expected={"split_sha256": manifest["hashes"]["split_sha256"]})
    best = torch.load(run / "checkpoints" / "best.pt", map_location="cpu", weights_only=True)
    reference = build_adapted_model(config)
    reference.load_state_dict(best["model"])
    reference.eval()
    x = torch.randn(1, 4, 16, 16, 16, generator=torch.Generator().manual_seed(0))
    with torch.no_grad():
        assert torch.equal(loaded.model(x), reference(x))
    assert loaded.threshold == 0.5 and loaded.channel_order == ["T1c", "T1", "T2", "FLAIR"]

    with pytest.raises(EvaluationExistsError):
        export_run(run)
    with pytest.raises(ExportError, match="esperados"):
        load_export(out, expected={"split_sha256": "0" * 64})
    manifest_path = out / "export.json"
    original = manifest_path.read_text(encoding="utf-8")
    tampered = json.loads(original)
    tampered["hashes"]["state_sha256"] = "1" * 64
    manifest_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ExportError, match="state_dict"):
        load_export(out)
    tampered = json.loads(original)
    tampered["architecture"]["kwargs"]["init_filters"] = 8
    manifest_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ExportError, match="SEGRESNET_KWARGS"):
        load_export(out)
    manifest_path.write_text(original, encoding="utf-8")
    weights = out / "model.pt"
    data = bytearray(weights.read_bytes())
    data[-10] ^= 0xFF
    weights.write_bytes(bytes(data))
    with pytest.raises(ExportError, match="alterado"):
        load_export(out)

    # Con una evaluación del mismo checkpoint, la exportación la cita con partición y fecha.
    evaluate_run(run, "val", predictor=perfect(config), bootstrap_samples=100)
    evaluated = export_run(run, checkpoint="last").manifest  # 1 época: last tiene los mismos pesos que best
    assert evaluated["evaluation"]["status"] == "evaluated_val"
    assert evaluated["evaluation"]["splits_evaluated"] == ["val"]
    cited = evaluated["evaluation"]["adapted"][0]
    assert cited["split"] == "val" and cited["summary"] == "evaluation/val/summary.json" and cited["created_utc"]
    assert cited["metrics"]["dice"]["mean"] == 1.0
    card = (run / "export-last" / "model_card.md").read_text(encoding="utf-8")
    assert "Partición **val**" in card and "not_evaluated" not in card and "Evaluado solo en validación" in card


def test_cli_evaluate_and_export_end_to_end(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _config, run = segresnet_run(tmp_path)
    capsys.readouterr()
    assert main(["evaluate", "--run", str(run), "--split", "val", "--bootstrap", "100"]) == 0
    out = capsys.readouterr().out
    assert "Modelo adaptado, partición val" in out and "dice: media" in out
    summary = json.loads((run / "evaluation" / "val" / "summary.json").read_text(encoding="utf-8"))
    assert summary["bootstrap"]["samples"] == 100 and summary["n_studies"] >= 1
    assert all(0.0 <= float(r["dice"]) <= 1.0 for r in read_csv(run / "evaluation" / "val" / "per_study.csv"))
    assert main(["evaluate", "--run", str(run), "--split", "val"]) == EXIT_CONFIG_ERROR  # no sobrescribe
    assert "nunca se sobrescribe" in capsys.readouterr().err
    assert main(["evaluate", "--run", str(run), "--split", "test"]) == EXIT_CONFIG_ERROR  # sin --checkpoint
    assert "--checkpoint" in capsys.readouterr().err
    argv = ["evaluate", "--run", str(run), "--split", "val", "--checkpoint", "last", "--bootstrap", "50"]
    assert main(argv) == EXIT_CONFIG_ERROR
    assert "al menos 100" in capsys.readouterr().err
    argv = ["evaluate", "--run", str(run), "--split", "test", "--optimize-threshold"]
    assert main(argv) == EXIT_CONFIG_ERROR
    assert "nunca se optimiza sobre test" in capsys.readouterr().err
    assert main(["evaluate", "--run", str(run), "--split", "test", "--checkpoint", "last"]) == 0
    first_test = json.loads((run / "evaluation" / "test-last" / "summary.json").read_text(encoding="utf-8"))
    assert first_test["prior_test_evaluations"] == [] and "AVISO" not in capsys.readouterr().out
    assert main(["evaluate", "--run", str(run), "--split", "test", "--checkpoint", "best"]) == 0
    assert "AVISO: Ya existían 1 evaluación(es) de test" in capsys.readouterr().out
    second = json.loads((run / "evaluation" / "test" / "summary.json").read_text(encoding="utf-8"))
    assert [p["evaluation"] for p in second["prior_test_evaluations"]] == ["test-last"]
    assert any("Ya existían" in w for w in second["warnings"])
    assert main(["export", "--run", str(run)]) == 0
    manifest = json.loads((run / "export" / "export.json").read_text(encoding="utf-8"))
    assert manifest["pretrained"]["license"] == "no verificado"  # pesos fuera de la estructura de un bundle
    assert manifest["evaluation"]["splits_evaluated"] == ["test", "val"]
    assert "Estado de evaluación: evaluated_test" in capsys.readouterr().out
    assert main(["export", "--run", str(run)]) == EXIT_CONFIG_ERROR
    assert main(["evaluate", "--run", str(tmp_path / "nope"), "--split", "val"]) == EXIT_DATA_ERROR
    provenance = run / "provenance.json"
    data = json.loads(provenance.read_text(encoding="utf-8"))
    data["hashes"]["cache_key"] = "0" * 16
    provenance.write_text(json.dumps(data), encoding="utf-8")
    assert main(["evaluate", "--run", str(run), "--split", "test", "--checkpoint", "best"]) == EXIT_CHECKPOINT
    assert "cache_key" in capsys.readouterr().err


@pytest.mark.slow
def test_baseline_real_segresnet_path_with_artificial_weights(tmp_path: Path) -> None:
    """Ruta real de `evaluate_baseline`: pesos de 3 salidas verificados por SHA-256 y `segresnet_predictor` (ROI
    240×240×160 en CPU, lento)."""
    _config, run = segresnet_run(tmp_path)
    result = evaluate_baseline(run, "val", device="cpu", bootstrap_samples=100)
    baseline = result.summary["baseline"]
    assert baseline["predictor"] == "segresnet_predictor (cpu)" and baseline["amp"] is False
    assert baseline["weights_sha256"] == _config.weights.sha256
    assert result.rows and all(0.0 <= r["dice"] <= 1.0 for r in result.rows)
