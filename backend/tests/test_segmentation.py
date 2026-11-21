"""Tests de segmentation.py con un predictor falso (sin red ni torch)."""

import os
from pathlib import Path

import numpy as np
import pytest
from nibabel.processing import resample_from_to, resample_to_output

from cerberus_api import segmentation
from cerberus_api.config import REPO_ROOT
from cerberus_api.nifti import load_nifti
from cerberus_api.schemas import SegmentationResult
from cerberus_api.segmentation import mask_metrics, normalize_nonzero, run_segmentation
from conftest import MakeStudy


def _files(study_dir: Path) -> dict[str, Path]:
    return {p.name.split("_", 2)[2].removesuffix(".nii.gz"): p for p in study_dir.glob("*.nii.gz")}


def _cube_predictor(x: np.ndarray) -> np.ndarray:
    """WT = [2:12]^3, TC = [4:10]^3, ET = [5:8]^3 (1000, 216, 27 vóxeles)."""
    assert x.ndim == 4 and x.shape[0] == 4 and x.dtype == np.float32
    p = np.zeros((3, *x.shape[1:]), np.float32)
    p[1, 2:12, 2:12, 2:12] = 0.9
    p[0, 4:10, 4:10, 4:10] = 0.9
    p[2, 5:8, 5:8, 5:8] = 0.9
    return p


def test_labels_volumes_and_outputs(tmp_path: Path, make_study: MakeStudy) -> None:
    study = make_study(tmp_path / "Data", seqs=("t1gd", "flair", "gtv"))
    out = tmp_path / "out"
    res = run_segmentation(_files(study), out, tmp_path / "models", predictor=_cube_predictor)

    img = load_nifti(out / "monai_seg.nii.gz")
    assert np.allclose(img.header.get_zooms()[:3], (1, 1, 1))
    ref = resample_to_output(load_nifti(_files(study)["t1gd"]), voxel_sizes=(1, 1, 1), order=1)
    assert img.shape == ref.shape and abs(img.shape[0] - 20) <= 1
    lab = np.asarray(img.dataobj)
    assert lab.dtype == np.uint8
    counts = {v: int((lab == v).sum()) for v in (1, 2, 3)}
    assert counts == {1: 1000 - 216, 2: 216 - 27, 3: 27}
    assert (res.volumes_cm3.wt, res.volumes_cm3.tc, res.volumes_cm3.et) == (1.0, 0.22, 0.03)
    assert res.device == "custom"
    assert res.warnings == [
        "Sin brain_mask: no hay skull-strip",
        "Canal T1 faltante: se usaron ceros",
        "Canal T2 faltante: se usaron ceros",
    ]
    assert [c.sequence for c in res.channels] == ["t1gd", None, None, "flair"]
    assert res.dice_vs_gtv is not None and 0 < res.dice_vs_gtv.wt <= 1
    loaded = SegmentationResult.model_validate_json((out / "monai_seg.json").read_text())
    assert loaded == res


def test_brain_mask_clips_labels(tmp_path: Path, make_study: MakeStudy) -> None:
    study = make_study(tmp_path / "Data", seqs=("flair", "brain_mask"))

    def everywhere(x: np.ndarray) -> np.ndarray:
        return np.ones((3, *x.shape[1:]), np.float32)

    res = run_segmentation(_files(study), tmp_path / "o", tmp_path / "m", predictor=everywhere)
    lab = np.asarray(load_nifti(tmp_path / "o" / "monai_seg.nii.gz").dataobj)
    assert lab[0, 0, 0] == 0 and (lab == 3).any() and not (lab == 1).any()
    assert "Sin brain_mask: no hay skull-strip" not in res.warnings
    assert "Canal T1c faltante: se usaron ceros" in res.warnings
    assert res.dice_vs_gtv is None


def test_perfect_dice(tmp_path: Path, make_study: MakeStudy) -> None:
    files = make_study(tmp_path / "Data", seqs=("t1gd", "gtv"))
    files = _files(files)

    def from_gtv(x: np.ndarray) -> np.ndarray:
        ref = resample_to_output(load_nifti(files["t1gd"]), voxel_sizes=(1, 1, 1), order=1)
        g = np.asarray(resample_from_to(load_nifti(files["gtv"]), ref, order=0).dataobj) > 0.5
        return np.stack([g, g, g]).astype(np.float32)

    res = run_segmentation(files, tmp_path / "o", tmp_path / "m", predictor=from_gtv)
    assert res.dice_vs_gtv is not None
    assert (res.dice_vs_gtv.tc, res.dice_vs_gtv.wt) == (1.0, 1.0)


def test_no_channels_raises(tmp_path: Path, make_study: MakeStudy) -> None:
    study = make_study(tmp_path / "Data", seqs=("gtv", "brain_mask"))
    with pytest.raises(ValueError):
        run_segmentation(_files(study), tmp_path / "o", tmp_path / "m", predictor=_cube_predictor)


def test_normalize_nonzero() -> None:
    x = np.zeros((2, 4, 1, 1), np.float32)
    x[0, :2, 0, 0] = [1, 3]
    x[1, :2, 0, 0] = [5, 5]
    y = normalize_nonzero(x)
    assert np.allclose(y[0, :, 0, 0], [-1, 1, 0, 0])
    assert np.allclose(y[1, :, 0, 0], [0, 0, 0, 0])


def test_monai_predictor_is_cached_until_weights_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    models = tmp_path / "models"
    weights = models / segmentation.BUNDLE_NAME / "models" / "model.pt"
    weights.parent.mkdir(parents=True)
    weights.write_bytes(b"pesos")
    built: list[Path] = []

    def fake_build(path: Path, device: str | None = None) -> tuple[segmentation.Predictor, str]:
        built.append(path)
        return _cube_predictor, "fake"

    monkeypatch.setattr(segmentation, "_build_predictor", fake_build)
    monkeypatch.setattr(segmentation, "_PREDICTORS", {})

    first = segmentation._monai_predictor(models)
    second = segmentation._monai_predictor(models)
    assert first == second == (_cube_predictor, "fake")
    assert built == [weights]

    # Pesos nuevos (otro mtime) → se reconstruye y la caché conserva una sola entrada.
    st = weights.stat()
    os.utime(weights, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    segmentation._monai_predictor(models)
    segmentation._monai_predictor(models)
    assert built == [weights, weights]
    assert len(segmentation._PREDICTORS) == 1


# --- HW1: amp solo en CUDA, salida en CPU y vuelta a CPU ante OOM (torch.cuda mockeado, sin GPU) ---------------


@pytest.mark.parametrize(("device", "amp"), [("cpu", True), ("mps", True), ("cuda", False), ("cpu", False)])
def test_inference_context_without_autocast(device: str, amp: bool) -> None:
    import contextlib

    assert isinstance(segmentation._inference_context(device, amp), contextlib.nullcontext)


def test_inference_context_autocast_fp16_on_cuda(monkeypatch: pytest.MonkeyPatch) -> None:
    import torch

    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    ctx = segmentation._inference_context("cuda", True)
    assert isinstance(ctx, torch.autocast)
    assert ctx.device == "cuda" and ctx.fast_dtype == torch.float16


class _FakeNet:
    """Red falsa: `eval()`/`to()` no tocan ningún dispositivo real; devuelve 3 canales a partir de la entrada."""

    def __init__(self) -> None:
        self.moved_to: str | None = None

    def eval(self) -> "_FakeNet":
        return self

    def to(self, device: str) -> "_FakeNet":
        self.moved_to = device
        return self


@pytest.mark.parametrize(("device", "amp"), [("cpu", False), ("cuda", True)])
def test_segresnet_predictor_windows_on_device_output_on_cpu(
    monkeypatch: pytest.MonkeyPatch, device: str, amp: bool
) -> None:
    import contextlib

    import monai.inferers.utils as monai_utils
    import torch

    calls: list[dict[str, object]] = []
    contexts: list[tuple[str, bool]] = []

    def fake_swi(inputs: torch.Tensor, roi_size: object, sw_batch_size: int, predictor: object, **kwargs: object):
        calls.append({"input_device": inputs.device.type, "roi": roi_size, "batch": sw_batch_size, **kwargs})
        return torch.zeros((1, 3, *inputs.shape[2:]))

    def fake_context(dev: str, use_amp: bool) -> contextlib.AbstractContextManager[object]:
        contexts.append((dev, use_amp))
        return contextlib.nullcontext()

    monkeypatch.setattr(monai_utils, "sliding_window_inference", fake_swi)
    monkeypatch.setattr(segmentation, "_inference_context", fake_context)
    net = _FakeNet()
    predict = segmentation.segresnet_predictor(net, device, amp=amp)  # type: ignore[arg-type]
    out = predict(np.zeros((4, 5, 6, 7), np.float32))

    assert net.moved_to == device
    assert contexts == [(device, amp)]
    assert calls == [
        {
            "input_device": "cpu",
            "roi": segmentation.ROI_SIZE,
            "batch": 1,
            "overlap": 0.5,
            "sw_device": device,
            "device": "cpu",
        }
    ]
    assert out.shape == (3, 5, 6, 7) and np.allclose(out, 0.5)  # sigmoid(0)


def test_segresnet_predictor_default_is_fp32() -> None:
    """FT4 llama `segresnet_predictor(net, device)` sin `amp`: el valor por defecto debe ser fp32."""
    import inspect

    assert inspect.signature(segmentation.segresnet_predictor).parameters["amp"].default is False


@pytest.mark.parametrize(
    ("cuda", "mps", "expected"), [(True, True, "cuda"), (False, True, "mps"), (False, False, "cpu")]
)
def test_pick_device_order(monkeypatch: pytest.MonkeyPatch, cuda: bool, mps: bool, expected: str) -> None:
    import torch

    monkeypatch.setattr(torch.cuda, "is_available", lambda: cuda)
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: mps)
    assert segmentation._pick_device() == expected


@pytest.mark.parametrize(("device", "amp"), [("cuda", True), ("mps", False), ("cpu", False)])
def test_build_predictor_amp_only_on_cuda(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, device: str, amp: bool
) -> None:
    import torch
    from monai.networks.nets.segresnet import SegResNet

    net = SegResNet(
        blocks_down=(1, 2, 2, 4), blocks_up=(1, 1, 1), init_filters=16, in_channels=4, out_channels=3, dropout_prob=0.2
    )
    weights = tmp_path / "model.pt"
    torch.save(net.state_dict(), weights)
    seen: list[tuple[str, bool]] = []

    def spy(net: object, dev: str, amp: bool = False) -> segmentation.Predictor:
        seen.append((dev, amp))
        return _cube_predictor

    monkeypatch.setattr(segmentation, "segresnet_predictor", spy)
    monkeypatch.setattr(segmentation, "_pick_device", lambda: device)
    assert segmentation._build_predictor(weights) == (_cube_predictor, device)
    # Un device explícito manda sobre el detectado (vuelta a CPU tras OOM).
    assert segmentation._build_predictor(weights, "cpu") == (_cube_predictor, "cpu")
    assert seen == [(device, amp), ("cpu", False)]


def test_cuda_oom_falls_back_to_cpu(tmp_path: Path, make_study: MakeStudy, monkeypatch: pytest.MonkeyPatch) -> None:
    import torch

    def oom_predictor(x: np.ndarray) -> np.ndarray:
        raise torch.cuda.OutOfMemoryError("CUDA out of memory. Tried to allocate 2.00 GiB")

    built: list[tuple[Path, str | None]] = []

    def fake_build(path: Path, device: str | None = None) -> tuple[segmentation.Predictor, str]:
        built.append((path, device))
        return _cube_predictor, "cpu"

    emptied: list[bool] = []
    monkeypatch.setattr(segmentation, "_monai_predictor", lambda models_dir: (oom_predictor, "cuda"))
    monkeypatch.setattr(segmentation, "_build_predictor", fake_build)
    monkeypatch.setattr(torch.cuda, "empty_cache", lambda: emptied.append(True))

    study = make_study(tmp_path / "Data", seqs=("t1gd", "flair", "gtv"))
    models = tmp_path / "models"
    res = run_segmentation(_files(study), tmp_path / "out", models)

    assert res.device == "cpu"
    assert segmentation.CUDA_OOM_WARNING in res.warnings
    assert res.volumes_cm3.wt == 1.0 and res.volumes_cm3.et == 0.03
    assert built == [(models / segmentation.BUNDLE_NAME / "models" / "model.pt", "cpu")]
    assert emptied == [True]


def test_cuda_other_errors_propagate(tmp_path: Path, make_study: MakeStudy, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(x: np.ndarray) -> np.ndarray:
        raise RuntimeError("CUDA error: device-side assert triggered")

    monkeypatch.setattr(segmentation, "_monai_predictor", lambda models_dir: (broken, "cuda"))
    monkeypatch.setattr(segmentation, "_build_predictor", lambda *a, **k: pytest.fail("no debe reconstruir en CPU"))
    study = make_study(tmp_path / "Data", seqs=("t1gd",))
    with pytest.raises(RuntimeError, match="device-side assert"):
        run_segmentation(_files(study), tmp_path / "out", tmp_path / "models")


@pytest.mark.slow
def test_real_model_on_data(tmp_path: Path) -> None:
    study = REPO_ROOT / "Data" / "001" / "t0"
    if not study.is_dir():
        pytest.skip("Sin Data/001/t0")
    pytest.importorskip("monai")
    res = run_segmentation(_files(study), tmp_path, REPO_ROOT / "models")
    assert res.volumes_cm3.wt > 0
    assert res.dice_vs_gtv is not None and res.dice_vs_gtv.tc > 0.3


def test_metrics_known_overlap() -> None:
    pred = np.zeros((5, 5, 5), bool)
    ref = pred.copy()
    pred[1:4, 2, 2] = True
    ref[1:3, 2, 2] = True
    m = mask_metrics(pred, ref, (2.0, 1.0, 1.0))
    assert m.dice == pytest.approx(0.8)
    assert m.recall == 1
    assert m.precision == pytest.approx(2 / 3)
    assert m.hd95_mm == pytest.approx(1.8)
    assert m.volume_error_cm3 == pytest.approx(0.002)
    assert m.volume_error_pct == 50


def test_metrics_distance_and_undersegmentation() -> None:
    pred = np.zeros((4, 4, 4), bool)
    ref = pred.copy()
    pred[1, 1, 1] = True
    ref[2, 1, 1] = True
    m = mask_metrics(pred, ref, (3.0, 1.0, 1.0))
    assert m.dice == m.recall == m.precision == 0
    assert m.hd95_mm == 3
    ref[1, 1, 1] = True
    m = mask_metrics(pred, ref, (3.0, 1.0, 1.0))
    assert m.recall == 0.5 and m.precision == 1
    assert m.volume_error_pct == -50
    assert m.volume_error_cm3 == pytest.approx(-0.003)


@pytest.mark.parametrize("pred_positive,ref_positive", [(False, False), (True, False), (False, True)])
def test_metrics_empty_masks(pred_positive: bool, ref_positive: bool) -> None:
    pred = np.full((2, 2, 2), pred_positive)
    ref = np.full((2, 2, 2), ref_positive)
    m = mask_metrics(pred, ref, (1.0, 1.0, 1.0))
    assert m.hd95_mm is None
    assert m.dice == (1 if not pred_positive and not ref_positive else 0)
    assert m.recall == (0 if ref_positive else None)
    assert m.precision == (0 if pred_positive else None)
    assert m.volume_error_pct == (-100 if ref_positive else None)
    assert "NaN" not in m.model_dump_json()


def test_metrics_perfect_and_old_results(tmp_path: Path, make_study: MakeStudy) -> None:
    mask = np.ones((3, 3, 3), bool)
    m = mask_metrics(mask, mask, (1.0, 1.0, 1.0))
    assert m.dice == m.recall == m.precision == 1
    assert m.hd95_mm == m.volume_error_cm3 == m.volume_error_pct == 0
    study = make_study(tmp_path / "Data", seqs=("t1gd", "gtv"))
    result = run_segmentation(_files(study), tmp_path / "out", tmp_path / "models", predictor=_cube_predictor)
    assert result.metrics_vs_gtv is not None
    assert result.dice_vs_gtv is not None
    assert round(result.metrics_vs_gtv.tc.dice, 3) == result.dice_vs_gtv.tc
    old = result.model_dump(exclude={"metrics_vs_gtv"})
    assert SegmentationResult.model_validate(old).metrics_vs_gtv is None


def test_metrics_reject_invalid_grid() -> None:
    mask = np.ones((2, 2, 2), bool)
    with pytest.raises(ValueError):
        mask_metrics(mask, mask[:1], (1.0, 1.0, 1.0))
    with pytest.raises(ValueError):
        mask_metrics(mask, mask, (0.0, 1.0, 1.0))
