"""Tests de FT3: transferencia de SegResNet, trainer, artefactos y reanudación (docs/PLAN_PIPELINE_FINETUNING.md §6).

Caché sintética diminuta (volúmenes 16³, parches 8³) escrita con `StudyCache.store`, inventario y split reales y una
red pequeña inyectable (`ModelSpec`). El cableado de SegResNet real usa pesos artificiales generados en `tmp_path`.
Sin red, sin GPU y sin `Data/`.
"""

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import torch
from torch import nn

from cerberus_training.__main__ import EXIT_CHECKPOINT, EXIT_CONFIG_ERROR, EXIT_NO_CUDA, main
from cerberus_training.artifacts import RunExistsError, atomic_torch_save
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
    macro_patient_dice,
    run_training,
    state_digest,
)
from cerberus_training.transforms import Geometry, PreparedStudy, study_sources

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


TINY = ModelSpec(name="tiny", build=TinyNet, head="head")
NAN = ModelSpec(name="tiny", build=NanNet, head="head")


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


def _study(record: dict[str, Any], index: int) -> PreparedStudy:
    rng = np.random.default_rng(index)
    label = np.zeros(SHAPE, np.uint8)
    o = 3 + index % 4
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
        label_empty=False,
        sources=study_sources(record),
    )


def write_config(tmp_path: Path, weights: Path, name: str = "config.json", **training: Any) -> Path:
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    data["paths"] = {"data_root": str(tmp_path / "cfb"), "work_dir": str(tmp_path / "work")}
    data["weights"].update({"path": str(weights), "sha256": sha256_file(weights) if weights.is_file() else "0" * 64})
    data["preprocess"].update(
        {"patch_size": [8, 8, 8], "grad_accum_steps": 2, "cache_limit_gb": 1.0, "min_free_disk_gb": 1e-6}
    )
    data["training"].update({"device": "cpu", "amp": False, "max_epochs": 3, "early_stopping_patience": 15})
    data["training"].update(training)
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def make_config(tmp_path: Path, weights: Path, **training: Any) -> TrainConfig:
    return resolve_config(load_config(write_config(tmp_path, weights, **training)))


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


def build_workspace(config: TrainConfig) -> None:
    """Inventario (6 pacientes, 001 con dos tiempos), split real y caché verificable."""
    records = [_record(p, "t0") for p in PATIENTS] + [_record("001", "t1")]
    work = config.paths.work_dir
    write_inventory(records, work / "inventory.jsonl")
    write_or_reuse_splits(build_splits(records, config.split), work / "splits.json")
    cache = StudyCache.from_config(config)
    for index, record in enumerate(records):
        cache.store(_study(record, index))


@pytest.fixture
def tiny(tmp_path: Path) -> TrainConfig:
    config = make_config(tmp_path, tiny_weights(tmp_path))
    build_workspace(config)
    return config


def _metrics(run: Path) -> list[dict[str, Any]]:
    lines = (run / "metrics.jsonl").read_text(encoding="utf-8").splitlines()
    return [{k: v for k, v in json.loads(line).items() if k not in TIMING_FIELDS} for line in lines]


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
