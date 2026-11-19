"""Tests de FT3: transferencia de SegResNet, trainer, artefactos y reanudación (docs/PLAN_PIPELINE_FINETUNING.md §6).

Caché sintética diminuta (volúmenes 16³, parches 8³) escrita con `StudyCache.store`, inventario y split reales y una
red pequeña inyectable (`ModelSpec`). El cableado de SegResNet real usa pesos artificiales generados en `tmp_path`.
Sin red, sin GPU y sin `Data/`.
"""

import copy
import hashlib
import json
import os
import random
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import torch
from torch import nn

import cerberus_training.train as train_mod
from cerberus_training.__main__ import EXIT_CHECKPOINT, EXIT_CONFIG_ERROR, EXIT_NO_CUDA, main
from cerberus_training.artifacts import RunExistsError, RunLockedError, atomic_torch_save
from cerberus_training.cache import StudyCache
from cerberus_training.config import REPO_ROOT, TrainConfig, load_config, resolve_config
from cerberus_training.inventory import sha256_file, write_inventory
from cerberus_training.model import (
    SEGRESNET_HEAD,
    CheckpointError,
    ModelSpec,
    WeightsError,
    build_transfer_model,
    segresnet_spec,
)
from cerberus_training.splits import build_splits, write_or_reuse_splits
from cerberus_training.train import (
    TIMING_FIELDS,
    DeviceUnavailableError,
    ResumeError,
    TrainingDataError,
    TrainingError,
    dry_run,
    epoch_order,
    load_training_data,
    macro_patient_dice,
    make_loss,
    run_training,
    state_digest,
    train_epoch,
    validate,
)
from cerberus_training.transforms import Geometry, PreparedStudy, make_rng, study_sources, train_sample

EXAMPLE = REPO_ROOT / "configs" / "training" / "gtv_binary.json"
SHAPE = (16, 16, 16)
PATIENTS = ("001", "002", "003", "004", "005", "006")


class TinyNet(nn.Module):
    """Red pequeña con dropout (consume el RNG de torch, como SegResNet) y proyección final `head`."""

    def __init__(self, out_channels: int) -> None:
        super().__init__()
        self.body = nn.Sequential(nn.Conv3d(4, 4, 3, padding=1), nn.ReLU(), nn.Dropout3d(0.2))
        self.head = nn.Conv3d(4, out_channels, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(self.body(x))


class NanNet(TinyNet):
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return super().forward(x) * float("nan")


class NanGradNet(TinyNet):
    """Pérdida finita, pero el gradiente de la cabeza es NaN."""

    def __init__(self, out_channels: int) -> None:
        super().__init__(out_channels)
        self.head.weight.register_hook(lambda grad: grad * float("nan"))


class EvalNanNet(TinyNet):
    """Entrena con normalidad, pero en evaluación (validación) devuelve NaN."""

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out = super().forward(x)
        return out if self.training else out * float("nan")


class NoDropNet(nn.Module):
    def __init__(self, out_channels: int) -> None:
        super().__init__()
        self.body = nn.Conv3d(4, 4, 3, padding=1)
        self.head = nn.Conv3d(4, out_channels, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(torch.relu(self.body(x)))


class ConstNet(nn.Module):
    """Logit constante: -10 (predicción vacía) o +10 (todo GTV)."""

    def __init__(self, value: float) -> None:
        super().__init__()
        self.value = value

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return torch.full((x.shape[0], 1, *x.shape[2:]), self.value)


TINY = ModelSpec(name="tiny", build=TinyNet, head="head")
NAN = ModelSpec(name="tiny", build=NanNet, head="head")
NAN_GRAD = ModelSpec(name="tiny", build=NanGradNet, head="head")
EVAL_NAN = ModelSpec(name="tiny", build=EvalNanNet, head="head")


# ---------------------------------------------------------------------------------------------------------------
# Fixtures: inventario, split y caché sintéticos
# ---------------------------------------------------------------------------------------------------------------


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _record(patient: str, timepoint: str) -> dict[str, Any]:
    sid = f"{patient}_{timepoint}"
    prefix = f"{patient}/{timepoint}/{int(patient)}_{timepoint}"
    seqs = {"T1c": "t1gd", "T1": "t1eg", "T2": "t2tse", "FLAIR": "flair"}
    channels = {ch: {"path": f"{prefix}_{seq}.nii.gz", "sha256": _sha(f"{sid}:{ch}")} for ch, seq in seqs.items()}
    return {
        "schema_version": 1,
        "study_id": sid,
        "patient": patient,
        "timepoint": timepoint,
        "timepoint_index": int(timepoint[1:]),
        "stratum": "baseline" if timepoint == "t0" else "follow_up",
        "channels": channels,
        "selected_sequences": seqs,
        "label": {"path": f"{prefix}_gtv.nii.gz", "sha256": _sha(f"{sid}:gtv"), "empty": False},
        "brain_mask": None,
        "eligible": True,
        "exclusions": [],
        "review_flags": [],
    }


def _study(record: dict[str, Any], index: int, empty: bool = False) -> PreparedStudy:
    rng = np.random.default_rng(index)
    label = np.zeros(SHAPE, np.uint8)
    o = 3 + index % 4
    if not empty:
        label[o : o + 6, o : o + 6, o : o + 6] = 1
    image = rng.normal(0, 1, (4, *SHAPE)).astype(np.float32) + 2.0 * label[None]
    geometry = Geometry(SHAPE, np.eye(4), SHAPE, np.eye(4), 1.0)
    return PreparedStudy(
        study_id=record["study_id"],
        image=image,
        label=label,
        brain=np.ones(SHAPE, np.uint8),
        geometry=geometry,
        brain_mask_source="nonzero_support",
        label_empty=empty,
        sources=study_sources(record),
    )


def write_config(
    tmp_path: Path, weights: Path, name: str = "config.json", preprocess: dict[str, Any] | None = None, **training: Any
) -> Path:
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    data["paths"] = {"data_root": str(tmp_path / "cfb"), "work_dir": str(tmp_path / "work")}
    data["weights"].update({"path": str(weights), "sha256": sha256_file(weights) if weights.is_file() else "0" * 64})
    data["preprocess"].update(
        {"patch_size": [8, 8, 8], "grad_accum_steps": 2, "cache_limit_gb": 1.0, "min_free_disk_gb": 1e-6}
    )
    data["training"].update({"device": "cpu", "amp": False, "max_epochs": 3, "early_stopping_patience": 15})
    data["preprocess"].update(preprocess or {})
    data["training"].update(training)
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def make_config(
    tmp_path: Path, weights: Path, preprocess: dict[str, Any] | None = None, **training: Any
) -> TrainConfig:
    return resolve_config(load_config(write_config(tmp_path, weights, preprocess=preprocess, **training)))


def save_state(model: nn.Module, path: Path) -> Path:
    torch.save(model.state_dict(), path)
    return path


def tiny_weights(tmp_path: Path) -> Path:
    torch.manual_seed(123)
    return save_state(TinyNet(3), tmp_path / "tiny3.pt")


def segresnet_weights(tmp_path: Path) -> Path:
    """Checkpoint artificial de 3 salidas con valores distintos de la inicialización por defecto."""
    torch.manual_seed(7)
    net = segresnet_spec().build(3)
    with torch.no_grad():
        for p in net.parameters():
            p.add_(torch.randn_like(p) * 0.01)
    return save_state(net, tmp_path / "segresnet3.pt")


def build_workspace(config: TrainConfig, empty_labels: bool = False) -> None:
    """Inventario (6 pacientes, 001 con dos tiempos), split real y caché verificable."""
    records = [_record(p, "t0") for p in PATIENTS] + [_record("001", "t1")]
    work = config.paths.work_dir
    write_inventory(records, work / "inventory.jsonl")
    write_or_reuse_splits(build_splits(records, config.split), work / "splits.json")
    cache = StudyCache.from_config(config)
    for index, record in enumerate(records):
        cache.store(_study(record, index, empty_labels))


@pytest.fixture
def tiny(tmp_path: Path) -> TrainConfig:
    config = make_config(tmp_path, tiny_weights(tmp_path))
    build_workspace(config)
    return config


def _metrics(run: Path) -> list[dict[str, Any]]:
    lines = (run / "metrics.jsonl").read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines]
    return [{k: v for k, v in r.items() if k not in TIMING_FIELDS} for r in records if "event" not in r]


def _events(run: Path) -> list[dict[str, Any]]:
    lines = (run / "metrics.jsonl").read_text(encoding="utf-8").splitlines()
    return [r for r in (json.loads(line) for line in lines) if "event" in r]


def scripted_validate(monkeypatch: pytest.MonkeyPatch, values: list[float]) -> None:
    """Sustituye la validación por una secuencia fija de Dice (para probar parada temprana y empates)."""
    it = iter(values)

    def fake(_model: nn.Module, _data: Any, _device: Any) -> dict[str, Any]:
        return {"val_dice": next(it), "val_dice_per_patient": {}, "val_studies": 1, "val_patients": 1}

    monkeypatch.setattr(train_mod, "validate", fake)


def global_rng() -> tuple[Any, ...]:
    _name, keys, pos, *_rest = np.random.get_state(legacy=True)
    return (random.getstate(), (np.asarray(keys).tolist(), pos), torch.get_rng_state())


def _load(path: Path) -> dict[str, Any]:
    return torch.load(path, map_location="cpu", weights_only=True)


def _assert_same_state(a: dict[str, torch.Tensor], b: dict[str, torch.Tensor]) -> None:
    assert a.keys() == b.keys()
    for key in a:
        assert torch.equal(a[key], b[key]), key


# ---------------------------------------------------------------------------------------------------------------
# Transferencia: SegResNet real con pesos artificiales
# ---------------------------------------------------------------------------------------------------------------


def test_segresnet_head_is_conv_final_2() -> None:
    net = segresnet_spec().build(3)
    head = net.get_submodule(SEGRESNET_HEAD)
    assert {k: tuple(v.shape) for k, v in head.state_dict().items()} == {
        "conv.weight": (3, 16, 1, 1, 1),
        "conv.bias": (3,),
    }


def test_segresnet_strict_transfer_and_new_head(tmp_path: Path) -> None:
    weights = segresnet_weights(tmp_path)
    config = make_config(tmp_path, weights)
    state = torch.load(weights, weights_only=True)
    model, report = build_transfer_model(config)
    final = model.state_dict()
    assert report.head == "conv_final.2" and report.discarded == ["conv_final.2.conv.bias", "conv_final.2.conv.weight"]
    assert report.new == ["conv_final.2.conv.bias", "conv_final.2.conv.weight"]
    assert tuple(final["conv_final.2.conv.weight"].shape) == (1, 16, 1, 1, 1)
    assert set(report.transferred) == set(state) - set(report.discarded)
    assert "conv_final.0.weight" in report.transferred  # la GroupNorm final sí se transfiere
    for key in report.transferred:
        assert torch.equal(final[key], state[key]), key
    total = sum(t.numel() for t in state.values())
    assert report.new_numel == 17 and report.transferred_numel + report.discarded_numel == total
    assert model(torch.zeros(1, 4, 16, 16, 16)).shape == (1, 1, 16, 16, 16)

    # Cabeza nueva determinista por semilla, independiente del RNG global
    torch.manual_seed(999)
    again, _ = build_transfer_model(config)
    _assert_same_state(again.state_dict(), final)
    other = config.model_copy(update={"seeds": config.seeds.model_copy(update={"head_init": 99})})
    changed, _ = build_transfer_model(other)
    assert not torch.equal(changed.state_dict()["conv_final.2.conv.weight"], final["conv_final.2.conv.weight"])


def test_wrong_sha_and_missing_weights_fail(tmp_path: Path) -> None:
    weights = segresnet_weights(tmp_path)
    config = make_config(tmp_path, weights)
    bad = config.model_copy(update={"weights": config.weights.model_copy(update={"sha256": "a" * 64})})
    with pytest.raises(WeightsError, match="SHA-256"):
        build_transfer_model(bad)
    missing = config.model_copy(update={"weights": config.weights.model_copy(update={"path": tmp_path / "nope.pt"})})
    with pytest.raises(WeightsError, match="nunca se descargan"):
        build_transfer_model(missing)


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (lambda s: s.pop("convInit.conv.weight"), "faltan 1 llave"),
        (lambda s: s.__setitem__("extra.weight", torch.zeros(1)), "sobran 1 llave"),
        (lambda s: s.__setitem__("conv_final.0.weight", torch.zeros(8)), "shape"),
    ],
)
def test_incompatible_checkpoint_fails(tmp_path: Path, edit: Callable[[dict[str, Any]], Any], message: str) -> None:
    state = torch.load(segresnet_weights(tmp_path), weights_only=True)
    edit(state)
    path = tmp_path / "edited.pt"
    torch.save(state, path)
    with pytest.raises(CheckpointError, match=message):
        build_transfer_model(make_config(tmp_path, path))


def test_non_state_dict_checkpoint_fails(tmp_path: Path) -> None:
    path = tmp_path / "weird.pt"
    torch.save({"model": [1, 2, 3]}, path)
    with pytest.raises(WeightsError, match="no es un tensor"):
        build_transfer_model(make_config(tmp_path, path), TINY)


def test_freeze_modules(tmp_path: Path) -> None:
    weights = tiny_weights(tmp_path)
    model, report = build_transfer_model(make_config(tmp_path, weights, freeze_modules=["body"]), TINY)
    assert report.frozen_parameters == ["body.0.bias", "body.0.weight"] and report.frozen_modules == ["body"]
    assert all(not p.requires_grad for p in model.get_submodule("body").parameters())
    assert all(p.requires_grad for p in model.get_submodule("head").parameters())
    assert report.frozen_numel == 4 * 4 * 27 + 4 and report.trainable_numel == 4 + 1
    for prefixes, message in ((["nada"], "ningún parámetro"), (["head"], "cabeza nueva")):
        with pytest.raises(CheckpointError, match=message):
            build_transfer_model(make_config(tmp_path, weights, freeze_modules=prefixes), TINY)


# ---------------------------------------------------------------------------------------------------------------
# Trainer
# ---------------------------------------------------------------------------------------------------------------


def test_macro_patient_dice_averages_timepoints_first() -> None:
    result = macro_patient_dice({"001_t0": 1.0, "001_t1": 0.0, "002_t0": 1.0}, lambda s: s.split("_")[0])
    assert result["val_dice_per_patient"] == {"001": 0.5, "002": 1.0}
    assert result["val_dice"] == 0.75 and result["val_patients"] == 2 and result["val_studies"] == 3


def test_training_writes_artifacts(tiny: TrainConfig) -> None:
    result = run_training(tiny, run_id="r1", spec=TINY)
    run = tiny.paths.work_dir / "runs" / "r1"
    assert result.run_dir == run and result.finished and result.stop_reason == "max_epochs"
    assert result.epochs_completed == 3
    assert load_config(run / "config.resolved.json") == tiny
    prov = json.loads((run / "provenance.json").read_text(encoding="utf-8"))
    splits = json.loads((tiny.paths.work_dir / "splits.json").read_text(encoding="utf-8"))
    assert prov["hashes"]["split_sha256"] == splits["split_sha256"]
    assert prov["hashes"]["weights_sha256"] == tiny.weights.sha256
    assert prov["seeds"]["training"] == 42 and prov["device"]["selected"] == "cpu"
    assert prov["transfer"]["new"] == ["head.bias", "head.weight"] and prov["determinism_limits"]
    assert set(prov["git"]) == {"commit", "dirty"} and "torch" in prov["environment"]["libraries"]
    metrics = _metrics(run)
    assert [m["epoch"] for m in metrics] == [0, 1, 2]
    assert all(0.0 <= m["val_dice"] <= 1.0 and np.isfinite(m["train_loss"]) for m in metrics)
    train_studies = len(splits["partitions"]["train"]["studies"])
    assert metrics[0]["train_batches"] == train_studies
    assert metrics[-1]["step"] == 3 * -(-train_studies // 2)  # batch 1, acumulación 2
    last, best = _load(run / "checkpoints" / "last.pt"), _load(run / "checkpoints" / "best.pt")
    assert last["kind"] == "last" and last["epoch"] == 3 and last["finished"] and last["scheduler"] is None
    assert set(last["rng"]) == {"python", "numpy", "torch", "cuda"} and last["optimizer"]["state"]
    assert last["hashes"]["split_sha256"] == splits["split_sha256"]
    assert best["kind"] == "best" and best["epoch"] == last["best_epoch"] and best["threshold"] == 0.5
    assert best["metric"]["value"] == max(m["val_dice"] for m in metrics)
    assert not torch.are_deterministic_algorithms_enabled()  # el estado global se restaura


def test_backward_updates_real_segresnet_and_respects_freeze(tmp_path: Path) -> None:
    config = make_config(tmp_path, segresnet_weights(tmp_path), max_epochs=1, freeze_modules=["convInit"])
    build_workspace(config)
    initial, _ = build_transfer_model(config)
    run_training(config, run_id="seg")
    trained = _load(config.paths.work_dir / "runs" / "seg" / "checkpoints" / "last.pt")["model"]
    before = initial.state_dict()
    params = dict(initial.named_parameters())
    for name in params:
        if name.startswith("convInit."):
            assert torch.equal(trained[name], before[name]), name
    changed = [n for n in params if not n.startswith("convInit.") and not torch.equal(trained[n], before[n])]
    assert "conv_final.2.conv.weight" in changed and len(changed) > len(params) // 2


def test_nan_loss_fails_clearly(tmp_path: Path) -> None:
    config = make_config(tmp_path, tiny_weights(tmp_path))
    build_workspace(config)
    with pytest.raises(TrainingError, match="Pérdida no finita"):
        run_training(config, run_id="nan", spec=NAN)


def test_cuda_requested_without_gpu_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    config = make_config(tmp_path, tiny_weights(tmp_path), device="cuda")
    with pytest.raises(DeviceUnavailableError, match="CUDA no está disponible"):
        run_training(config, spec=TINY)
    assert main(["train", "--config", str(tmp_path / "config.json")]) == EXIT_NO_CUDA


def test_missing_cache_entry_is_data_error(tiny: TrainConfig) -> None:
    StudyCache.from_config(tiny).path("002_t0").unlink()
    with pytest.raises(TrainingDataError, match="Faltan 1 estudio"):
        run_training(tiny, spec=TINY)


def test_existing_run_is_not_overwritten(tiny: TrainConfig) -> None:
    run_training(tiny, run_id="r1", spec=TINY)
    run = tiny.paths.work_dir / "runs" / "r1"
    snapshot = {p.name: p.read_bytes() for p in run.rglob("*") if p.is_file()}
    with pytest.raises(RunExistsError):
        run_training(tiny, run_id="r1", spec=TINY)
    assert {p.name: p.read_bytes() for p in run.rglob("*") if p.is_file()} == snapshot
    with pytest.raises(ValueError, match="run_id inválido"):
        run_training(tiny, run_id="../fuera", spec=TINY)


def test_atomic_checkpoint_write_leaves_no_partial_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "checkpoints" / "last.pt"
    atomic_torch_save({"v": torch.ones(2)}, target)
    assert target.stat().st_mode & 0o777 == 0o644
    original = target.read_bytes()

    def broken_save(_obj: Any, handle: Any) -> None:
        handle.write(b"parcial")
        raise OSError("disco lleno simulado")

    monkeypatch.setattr(torch, "save", broken_save)
    with pytest.raises(OSError, match="disco lleno"):
        atomic_torch_save({"v": torch.zeros(2)}, target)
    with pytest.raises(OSError, match="disco lleno"):
        atomic_torch_save({"v": torch.zeros(2)}, target.parent / "best.pt")
    assert target.read_bytes() == original
    assert sorted(p.name for p in target.parent.iterdir()) == ["last.pt"]  # sin temporales ni best parcial


# ---------------------------------------------------------------------------------------------------------------
# Reanudación
# ---------------------------------------------------------------------------------------------------------------


def test_resume_is_bitwise_equivalent(tmp_path: Path) -> None:
    config = make_config(tmp_path, tiny_weights(tmp_path), max_epochs=4)
    build_workspace(config)
    runs = config.paths.work_dir / "runs"
    run_training(config, run_id="straight", spec=TINY)
    partial = run_training(config, run_id="split", spec=TINY, stop_after_epochs=2)
    assert not partial.finished and partial.epochs_completed == 2
    resumed = run_training(config, resume=runs / "split" / "checkpoints" / "last.pt", spec=TINY)
    assert resumed.resumed_from == 2 and resumed.finished and resumed.epochs_completed == 4
    a, b = _load(runs / "straight" / "checkpoints" / "last.pt"), _load(runs / "split" / "checkpoints" / "last.pt")
    _assert_same_state(a["model"], b["model"])
    for sa, sb in zip(a["optimizer"]["state"].values(), b["optimizer"]["state"].values(), strict=True):
        for key in sa:
            assert torch.equal(torch.as_tensor(sa[key]), torch.as_tensor(sb[key]))
    assert torch.equal(a["rng"]["torch"], b["rng"]["torch"]) and a["step"] == b["step"]
    _assert_same_state(
        _load(runs / "straight" / "checkpoints" / "best.pt")["model"],
        _load(runs / "split" / "checkpoints" / "best.pt")["model"],
    )
    assert _metrics(runs / "straight") == _metrics(runs / "split")


def _tamper(path: Path, edit: Callable[[dict[str, Any]], None]) -> None:
    payload = _load(path)
    edit(payload)
    torch.save(payload, path)


@pytest.mark.parametrize(
    ("key", "value"),
    [("split_sha256", "f" * 64), ("channel_order", ["T1c", "T1", "FLAIR", "T2"]), ("in_channels", 3)],
)
def test_resume_rejects_changed_split_or_channels(tiny: TrainConfig, key: str, value: Any) -> None:
    run_training(tiny, run_id="r", spec=TINY, stop_after_epochs=1)
    last = tiny.paths.work_dir / "runs" / "r" / "checkpoints" / "last.pt"
    _tamper(last, lambda p: p["compat"].__setitem__(key, value))
    with pytest.raises(ResumeError, match=key):
        run_training(tiny, resume=last, spec=TINY)


def test_resume_rejects_changed_config(tmp_path: Path) -> None:
    weights = tiny_weights(tmp_path)
    config = make_config(tmp_path, weights)
    build_workspace(config)
    run_training(config, run_id="r", spec=TINY, stop_after_epochs=1)
    last = config.paths.work_dir / "runs" / "r" / "checkpoints" / "last.pt"
    changed = make_config(tmp_path, weights, learning_rate=0.5)
    with pytest.raises(ResumeError, match="training.learning_rate"):
        run_training(changed, resume=last, spec=TINY)
    with pytest.raises(ResumeError, match="last.pt"):
        run_training(config, resume=last.parent / "best.pt", spec=TINY)


def test_resume_truncates_metrics_after_checkpoint(tiny: TrainConfig) -> None:
    run_training(tiny, run_id="r", spec=TINY, stop_after_epochs=1)
    run = tiny.paths.work_dir / "runs" / "r"
    with (run / "metrics.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"epoch": 1, "huérfana": True}) + "\n")  # corte tras escribir una época sin last
    run_training(tiny, resume=run / "checkpoints" / "last.pt", spec=TINY)
    assert [m["epoch"] for m in _metrics(run)] == [0, 1, 2]
    assert all("huérfana" not in m for m in _metrics(run))


# ---------------------------------------------------------------------------------------------------------------
# Dry-run y CLI
# ---------------------------------------------------------------------------------------------------------------


def test_dry_run_does_not_change_weights_nor_create_run(tiny: TrainConfig) -> None:
    weights_sha = sha256_file(tiny.weights.path)
    report = dry_run(tiny, spec=TINY)
    expected, _ = build_transfer_model(tiny, TINY)
    assert report.ok and report.state_sha256 == state_digest(expected)
    assert report.output_shape == (1, 1, 8, 8, 8) and report.val_studies >= 1
    assert report.val_volume_shape == SHAPE  # volumen 16³ > parche 8³: ventana deslizante
    assert report.train_studies + report.val_studies <= 7
    assert sha256_file(tiny.weights.path) == weights_sha
    assert not (tiny.paths.work_dir / "runs").exists()


def test_cli_train_dry_run_and_real_with_segresnet(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    weights = segresnet_weights(tmp_path)
    cfg = write_config(tmp_path, weights, max_epochs=1)
    build_workspace(resolve_config(load_config(cfg)))
    assert main(["train", "--config", str(cfg), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Dry-run correcto" in out and "conv_final.2" in out
    assert not (tmp_path / "work" / "runs").exists()
    assert main(["train", "--config", str(cfg), "--run-id", "cli"]) == 0
    assert "1 épocas" in capsys.readouterr().out
    assert main(["train", "--config", str(cfg), "--run-id", "cli"]) == EXIT_CONFIG_ERROR  # no se sobrescribe
    last = tmp_path / "work" / "runs" / "cli" / "checkpoints" / "last.pt"
    assert main(["train", "--config", str(cfg), "--resume", str(last)]) == 0  # ya terminado: nada que hacer
    assert "no hay nada que reanudar" in capsys.readouterr().out
    bad = write_config(tmp_path, weights, name="bad.json", max_epochs=1)
    data = json.loads(bad.read_text(encoding="utf-8"))
    data["weights"]["sha256"] = "b" * 64
    bad.write_text(json.dumps(data), encoding="utf-8")
    assert main(["train", "--config", str(bad), "--dry-run"]) == EXIT_CHECKPOINT
    assert "SHA-256" in capsys.readouterr().err


@pytest.mark.slow
def test_segresnet_full_size_patch_dry_forward(tmp_path: Path) -> None:
    """Forward sin gradiente de SegResNet real con parche 96³ (lento en CPU)."""
    model, _ = build_transfer_model(make_config(tmp_path, segresnet_weights(tmp_path)))
    model.eval()
    with torch.no_grad():
        assert model(torch.zeros(1, 4, 96, 96, 96)).shape == (1, 1, 96, 96, 96)


# ---------------------------------------------------------------------------------------------------------------
# Revisión FT3: estado global, parada temprana, fallos numéricos, AMP, acumulación, cortes y candado
# ---------------------------------------------------------------------------------------------------------------


def test_global_rng_and_env_are_restored(tiny: TrainConfig) -> None:
    random.seed(1)
    np.random.seed(2)
    torch.manual_seed(3)
    before = global_rng()
    cublas = os.environ.get("CUBLAS_WORKSPACE_CONFIG")
    run_training(tiny, run_id="rng", spec=TINY)
    after_train = global_rng()
    dry_run(tiny, spec=TINY)
    after_dry = global_rng()
    for after in (after_train, after_dry):
        assert after[0] == before[0] and after[1] == before[1] and torch.equal(after[2], before[2])
    assert os.environ.get("CUBLAS_WORKSPACE_CONFIG") == cublas


def test_early_stopping_and_tie_is_not_improvement(tiny: TrainConfig, monkeypatch: pytest.MonkeyPatch) -> None:
    config = tiny.model_copy(
        update={"training": tiny.training.model_copy(update={"max_epochs": 10, "early_stopping_patience": 2})}
    )
    scripted_validate(monkeypatch, [0.5, 0.5, 0.5, 0.9])
    result = run_training(config, run_id="es", spec=TINY)
    assert result.stop_reason == "early_stopping" and result.epochs_completed == 3
    assert result.best_epoch == 0 and result.best_metric == 0.5
    metrics = _metrics(result.run_dir)
    assert [m["improved"] for m in metrics] == [True, False, False]
    assert [m["epochs_without_improvement"] for m in metrics] == [0, 1, 2]
    assert _load(result.run_dir / "checkpoints" / "best.pt")["epoch"] == 0


def test_validate_every_two(tiny: TrainConfig, monkeypatch: pytest.MonkeyPatch) -> None:
    training = tiny.training.model_copy(update={"max_epochs": 5, "validate_every": 2})
    scripted_validate(monkeypatch, [0.1, 0.2, 0.3])
    result = run_training(tiny.model_copy(update={"training": training}), run_id="ve", spec=TINY)
    validated = [m["epoch"] for m in _metrics(result.run_dir) if "val_dice" in m]
    assert validated == [1, 3, 4]  # cada 2 épocas y siempre en la última
    assert result.best_epoch == 4 and result.finished


def test_nan_gradient_with_finite_loss_fails(tiny: TrainConfig) -> None:
    with pytest.raises(TrainingError, match="Gradiente no finito"):
        run_training(tiny, run_id="ng", spec=NAN_GRAD)


def test_nan_validation_prediction_fails(tiny: TrainConfig) -> None:
    with pytest.raises(TrainingError, match="validación contiene NaN"):
        run_training(tiny, run_id="vn", spec=EVAL_NAN)


class FakeScaler:
    """Imita `GradScaler`: escala 1 y salta el paso si algún gradiente no es finito."""

    def __init__(self) -> None:
        self.updates = 0

    def scale(self, tensor: torch.Tensor) -> torch.Tensor:
        return tensor

    def unscale_(self, _optimizer: torch.optim.Optimizer) -> None:
        return None

    def step(self, optimizer: torch.optim.Optimizer) -> None:
        grads = [p.grad for group in optimizer.param_groups for p in group["params"] if p.grad is not None]
        if all(bool(torch.isfinite(g).all()) for g in grads):
            optimizer.step()

    def update(self) -> None:
        self.updates += 1


def test_amp_skipped_steps_are_counted(tiny: TrainConfig) -> None:
    data = load_training_data(tiny)
    model, _ = build_transfer_model(tiny, NAN_GRAD)
    before = state_digest(model)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
    scaler: Any = FakeScaler()
    stats = train_epoch(model, optimizer, scaler, make_loss(tiny), data, 0, 0, torch.device("cpu"))
    assert stats.amp_skipped_steps == stats.step == scaler.updates > 0
    assert state_digest(model) == before  # todos los pasos se saltaron


def test_short_final_accumulation_window_matches_manual_reference(tmp_path: Path) -> None:
    torch.manual_seed(5)
    weights = save_state(NoDropNet(3), tmp_path / "nodrop.pt")
    config = make_config(tmp_path, weights, preprocess={"grad_accum_steps": 3})
    build_workspace(config)
    data = load_training_data(config)
    n = len(data.train_ids)
    assert n % 3 != 0  # la última ventana es más corta
    model, _ = build_transfer_model(config, ModelSpec(name="nodrop", build=NoDropNet, head="head"))
    reference = copy.deepcopy(model)
    loss_fn, lr = make_loss(config), 0.5

    order = epoch_order(data.train_ids, config.seeds.training, 0)
    samples = []
    for i, sid in enumerate(order):
        image, label = train_sample(data.load(sid), config.preprocess, make_rng(config.seeds.augmentation, 0, i))
        samples.append((torch.from_numpy(image[None]), torch.from_numpy(label[None, None].astype(np.float32))))
    for start in range(0, n, 3):
        window = samples[start : start + 3]
        reference.zero_grad()
        (sum((loss_fn(reference(x), y) for x, y in window), torch.zeros(())) / len(window)).backward()
        with torch.no_grad():
            for p in reference.parameters():
                assert p.grad is not None
                p -= lr * p.grad

    optimizer = torch.optim.SGD(model.parameters(), lr=lr)
    stats = train_epoch(model, optimizer, None, loss_fn, data, 0, 0, torch.device("cpu"))
    assert stats.step == -(-n // 3)
    for (name, a), b in zip(model.state_dict().items(), reference.state_dict().values(), strict=True):
        assert torch.allclose(a, b, atol=1e-6), name


def test_validation_with_empty_gtv(tmp_path: Path) -> None:
    config = make_config(tmp_path, tiny_weights(tmp_path))
    build_workspace(config, empty_labels=True)
    data = load_training_data(config)
    cpu = torch.device("cpu")
    assert validate(ConstNet(-10.0), data, cpu)["val_dice"] == 1.0  # ambas vacías: Dice 1
    assert validate(ConstNet(10.0), data, cpu)["val_dice"] == 0.0  # falsos positivos sobre GTV vacía
    run_training(config, run_id="empty", spec=TINY)  # parches solo negativos: entrena sin errores


def test_crash_between_best_and_last_then_resume(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config(tmp_path, tiny_weights(tmp_path))
    build_workspace(config)
    runs = config.paths.work_dir / "runs"
    scripted_validate(monkeypatch, [0.1, 0.2, 0.3])
    run_training(config, run_id="straight", spec=TINY)

    real_save = train_mod.atomic_torch_save

    def crashing_save(obj: dict[str, Any], path: Path) -> None:
        if path.name == "last.pt" and obj["epoch"] == 2:
            raise OSError("corte simulado entre best y last")
        real_save(obj, path)

    monkeypatch.setattr(train_mod, "atomic_torch_save", crashing_save)
    scripted_validate(monkeypatch, [0.1, 0.2])
    with pytest.raises(OSError, match="corte simulado"):
        run_training(config, run_id="crash", spec=TINY)
    crash = runs / "crash"
    assert _load(crash / "checkpoints" / "best.pt")["epoch"] == 1
    assert _load(crash / "checkpoints" / "last.pt")["epoch"] == 1
    assert not (crash / ".lock").exists()  # el candado se libera también ante errores

    monkeypatch.setattr(train_mod, "atomic_torch_save", real_save)
    scripted_validate(monkeypatch, [0.2, 0.3])
    run_training(config, resume=crash / "checkpoints" / "last.pt", spec=TINY)
    assert (crash / "checkpoints" / "best.orphan-epoch1.pt").is_file()
    assert [e["event"] for e in _events(crash)] == ["best_orphaned"]
    for name in ("best.pt", "last.pt"):
        _assert_same_state(
            _load(runs / "straight" / "checkpoints" / name)["model"], _load(crash / "checkpoints" / name)["model"]
        )
    assert _metrics(runs / "straight") == _metrics(crash)


def test_resume_allows_resource_changes_and_extensions(tmp_path: Path) -> None:
    weights = tiny_weights(tmp_path)
    config = make_config(tmp_path, weights, max_epochs=2)
    build_workspace(config)
    run_training(config, run_id="r", spec=TINY)
    run = config.paths.work_dir / "runs" / "r"
    last = run / "checkpoints" / "last.pt"
    moved = Path(shutil.copy(weights, tmp_path / "moved.pt"))
    resources = {"cache_limit_gb": 2.0, "min_free_disk_gb": 1e-5}
    result = run_training(make_config(tmp_path, moved, preprocess=resources, max_epochs=4), resume=last, spec=TINY)
    assert result.finished and result.epochs_completed == 4 and result.stop_reason == "max_epochs"
    change = {"training.max_epochs": {"from": 2, "to": 4}}
    assert _events(run) == [{"event": "resume_override", "epoch": 2, "changes": change}]
    assert [m["epoch"] for m in _metrics(run)] == [0, 1, 2, 3]
    with pytest.raises(ResumeError, match="solo puede subir"):
        run_training(make_config(tmp_path, weights, max_epochs=3), resume=last, spec=TINY)
    with pytest.raises(ResumeError, match="training.validate_every"):
        run_training(make_config(tmp_path, weights, max_epochs=4, validate_every=2), resume=last, spec=TINY)


def test_resume_with_more_patience_reopens_early_stopped_run(
    tiny: TrainConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = make_config(tmp_path, tiny.weights.path, max_epochs=10, early_stopping_patience=1)
    scripted_validate(monkeypatch, [0.5, 0.4])
    first = run_training(config, run_id="p", spec=TINY)
    assert first.stop_reason == "early_stopping" and first.epochs_completed == 2
    scripted_validate(monkeypatch, [0.6, 0.6, 0.6, 0.6])  # mejora en la época 2 y 3 empates sin mejora
    more = make_config(tmp_path, tiny.weights.path, max_epochs=10, early_stopping_patience=3)
    result = run_training(more, resume=first.run_dir / "checkpoints" / "last.pt", spec=TINY)
    assert result.stop_reason == "early_stopping" and result.epochs_completed == 6 and result.best_epoch == 2
    assert _events(first.run_dir)[0]["changes"] == {"training.early_stopping_patience": {"from": 1, "to": 3}}


def test_run_lock_and_cleanup_of_half_created_run(tiny: TrainConfig, monkeypatch: pytest.MonkeyPatch) -> None:
    run_training(tiny, run_id="lk", spec=TINY, stop_after_epochs=1)
    run = tiny.paths.work_dir / "runs" / "lk"
    assert not (run / ".lock").exists()
    (run / ".lock").write_text("12345\n", encoding="utf-8")  # otro proceso (o candado huérfano)
    with pytest.raises(RunLockedError, match="en uso"):
        run_training(tiny, resume=run / "checkpoints" / "last.pt", spec=TINY)
    assert (run / ".lock").read_text(encoding="utf-8") == "12345\n"  # no se pisa el candado ajeno

    def broken(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise OSError("fallo simulado al escribir la procedencia")

    monkeypatch.setattr(train_mod, "build_provenance", broken)
    with pytest.raises(OSError, match="procedencia"):
        run_training(tiny, run_id="half", spec=TINY)
    assert not (tiny.paths.work_dir / "runs" / "half").exists()
