"""Segmentación con MONAI SegResNet (bundle `brats_mri_segmentation`), docs/PLAN_MVP.md §8 ticket B5.

Portado de `cerberus_eda.py:728-775`, generalizando el `stride=2` del notebook a cualquier spacing:
todo se remuestrea a un grid de 1 mm isotrópico tomado del primer canal disponible (prioridad t1gd).
"""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import nibabel as nib
import numpy as np
from nibabel.processing import resample_from_to, resample_to_output
from scipy import ndimage

from cerberus_api.nifti import load_nifti
from cerberus_api.schemas import (
    ChannelUsed,
    DiceVsGtv,
    MaskMetrics,
    MetricsVsGtv,
    SegmentationResult,
    SegmentationVolumes,
)

# Canal del modelo → secuencias candidatas en orden de preferencia (cerberus_eda.py:755)
CHANNEL_MAP: dict[str, tuple[str, ...]] = {
    "T1c": ("t1gd",),
    "T1": ("t1eg", "t1tse"),
    "T2": ("t2tse", "t2star"),
    "FLAIR": ("flair",),
}

# float32 [4,X,Y,Z] normalizado → probabilidades float [3,X,Y,Z] en orden TC, WT, ET
Predictor = Callable[[np.ndarray], np.ndarray]

BUNDLE_NAME = "brats_mri_segmentation"
ROI_SIZE = (240, 240, 160)


def dice(a: np.ndarray, b: np.ndarray) -> float:
    """Dice de dos máscaras (cerberus_eda.py:178-181); 1.0 si ambas están vacías."""
    a, b = a.astype(bool), b.astype(bool)
    den = a.sum() + b.sum()
    return float(2 * (a & b).sum() / den) if den else 1.0


def mask_metrics(prediction: np.ndarray, reference: np.ndarray, spacing: tuple[float, float, float]) -> MaskMetrics:
    """Compara máscaras binarias en el mismo grid ortogonal.

    Dice portado de cerberus_eda.py:178-181. Métricas adicionales: sensibilidad TP/(TP+FN),
    precisión TP/(TP+FP), HD95 simétrico (máximo de percentiles dirigidos) sobre superficies
    de conectividad 1 y error de volumen firmado (predicción menos referencia).
    Sin denominador, recall/precisión/error porcentual son null. HD95 es null si alguna
    máscara está vacía; Dice conserva 1 cuando ambas están vacías.
    """
    pred, ref = prediction.astype(bool), reference.astype(bool)
    if pred.shape != ref.shape or pred.ndim != 3:
        raise ValueError("Las máscaras deben ser 3D y compartir el mismo grid")
    if len(spacing) != 3 or not all(np.isfinite(s) and s > 0 for s in spacing):
        raise ValueError("El spacing debe contener tres valores positivos finitos")
    n_pred, n_ref = int(pred.sum()), int(ref.sum())
    tp = int((pred & ref).sum())
    hd95 = None
    if n_pred and n_ref:
        # Recortar al soporte conjunto reduce memoria sin alterar las distancias entre superficies.
        occupied = np.where(pred | ref)
        box = tuple(slice(int(v.min()), int(v.max()) + 1) for v in occupied)
        p, r = pred[box], ref[box]
        p_surface = p & ~np.asarray(ndimage.binary_erosion(p, border_value=0), dtype=bool)
        r_surface = r & ~np.asarray(ndimage.binary_erosion(r, border_value=0), dtype=bool)
        to_ref = np.asarray(ndimage.distance_transform_edt(~r_surface, sampling=spacing))[p_surface]
        to_pred = np.asarray(ndimage.distance_transform_edt(~p_surface, sampling=spacing))[r_surface]
        hd95 = float(max(np.percentile(to_ref, 95), np.percentile(to_pred, 95)))
    return MaskMetrics(
        dice=dice(pred, ref),
        recall=tp / n_ref if n_ref else None,
        precision=tp / n_pred if n_pred else None,
        hd95_mm=hd95,
        volume_error_cm3=(n_pred - n_ref) * float(np.prod(spacing)) / 1000,
        volume_error_pct=100 * (n_pred - n_ref) / n_ref if n_ref else None,
    )


def normalize_nonzero(x: np.ndarray) -> np.ndarray:
    """Equivale a `NormalizeIntensity(nonzero=True, channel_wise=True)` de MONAI, en numpy.

    Por canal: media y std poblacional (ddof=0, como el `std(unbiased=False)` de MONAI) sobre los vóxeles != 0;
    solo esos vóxeles se normalizan. Si std == 0 se divide entre 1; un canal todo ceros queda igual.
    """
    out = x.astype(np.float32, copy=True)
    for c in range(out.shape[0]):
        ch = out[c]
        nz = ch != 0
        if not nz.any():
            continue
        vals = ch[nz]
        std = float(vals.std())
        ch[nz] = (vals - vals.mean()) / (std if std != 0.0 else 1.0)
    return out


def _monai_predictor(models_dir: Path) -> tuple[Predictor, str]:
    """Crea el predictor SegResNet real (descarga el bundle si falta). Devuelve (predictor, device)."""
    import torch
    from monai.bundle.scripts import download
    from monai.inferers.utils import sliding_window_inference
    from monai.networks.nets.segresnet import SegResNet

    weights = models_dir / BUNDLE_NAME / "models" / "model.pt"
    if not weights.exists():
        models_dir.mkdir(parents=True, exist_ok=True)
        download(name=BUNDLE_NAME, bundle_dir=str(models_dir))

    device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
    net = SegResNet(
        blocks_down=(1, 2, 2, 4), blocks_up=(1, 1, 1), init_filters=16, in_channels=4, out_channels=3, dropout_prob=0.2
    )
    net.load_state_dict(torch.load(weights, map_location="cpu"))
    net.eval().to(device)

    def predict(x: np.ndarray) -> np.ndarray:
        with torch.no_grad():
            t = torch.from_numpy(np.ascontiguousarray(x, dtype=np.float32))[None].to(device)
            y = sliding_window_inference(t, ROI_SIZE, 1, net, overlap=0.5)
            assert isinstance(y, torch.Tensor)
            return torch.sigmoid(y)[0].cpu().numpy()

    return predict, device


def _to_grid(img: nib.Nifti1Image, ref: nib.Nifti1Image, order: int) -> np.ndarray:
    res = resample_from_to(img, (ref.shape[:3], ref.affine), order=order)
    return np.asarray(res.dataobj, dtype=np.float32)


def run_segmentation(
    study_files: dict[str, Path],
    out_dir: Path,
    models_dir: Path,
    predictor: Predictor | None = None,
) -> SegmentationResult:
    """Segmenta un estudio y escribe `out_dir/monai_seg.nii.gz` + `out_dir/monai_seg.json`.

    `study_files`: secuencia → ruta NIfTI. Lanza `ValueError` si no hay ninguna secuencia de `CHANNEL_MAP`.
    """
    sources: dict[str, str | None] = {
        ch: next((s for s in cands if s in study_files), None) for ch, cands in CHANNEL_MAP.items()
    }
    available = [s for s in sources.values() if s is not None]
    if not available:
        raise ValueError("No hay ninguna secuencia utilizable para el modelo (t1gd/t1eg/t1tse/t2tse/t2star/flair)")

    ref_seq = "t1gd" if "t1gd" in available else available[0]
    ref_img = resample_to_output(load_nifti(study_files[ref_seq]), voxel_sizes=(1, 1, 1), order=1)
    assert isinstance(ref_img, nib.Nifti1Image)
    shape = ref_img.shape[:3]

    warnings: list[str] = []
    brain: np.ndarray | None = None
    if "brain_mask" in study_files:
        brain = _to_grid(load_nifti(study_files["brain_mask"]), ref_img, 0) > 0.5
    else:
        warnings.append("Sin brain_mask: no hay skull-strip")

    chans: list[np.ndarray] = []
    used: list[ChannelUsed] = []
    for ch, src in sources.items():
        used.append(ChannelUsed(model_channel=ch, sequence=src))  # type: ignore[arg-type]
        if src is None:
            warnings.append(f"Canal {ch} faltante: se usaron ceros")
            chans.append(np.zeros(shape, np.float32))
            continue
        vol = (
            np.asarray(ref_img.dataobj, dtype=np.float32)
            if src == ref_seq
            else _to_grid(load_nifti(study_files[src]), ref_img, 1)
        )
        chans.append(vol * brain if brain is not None else vol)
    x = normalize_nonzero(np.stack(chans))

    if predictor is None:
        predictor, device = _monai_predictor(models_dir)
    else:
        device = "custom"
    prob = np.asarray(predictor(x))
    tc, wt, et = (prob[i] > 0.5 for i in range(3))
    if brain is not None:
        tc, wt, et = tc & brain, wt & brain, et & brain

    labels = np.zeros(shape, np.uint8)
    labels[wt] = 1
    labels[tc] = 2
    labels[et] = 3

    out_dir.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(labels, ref_img.affine), out_dir / "monai_seg.nii.gz")

    vox_mm3 = float(np.prod(ref_img.header.get_zooms()[:3]))

    def cm3(m: np.ndarray) -> float:
        return round(int(m.sum()) * vox_mm3 / 1000, 2)

    dice_vs_gtv = None
    metrics_vs_gtv = None
    if "gtv" in study_files:
        gtv = _to_grid(load_nifti(study_files["gtv"]), ref_img, 0) > 0.5
        dice_vs_gtv = DiceVsGtv(tc=round(dice(tc, gtv), 3), wt=round(dice(wt, gtv), 3))
        # resample_to_output fija este grid a 1 mm isotrópico.
        spacing = (1.0, 1.0, 1.0)
        metrics_vs_gtv = MetricsVsGtv(
            tc=mask_metrics(tc, gtv, spacing),
            wt=mask_metrics(wt, gtv, spacing),
        )

    result = SegmentationResult(
        device=device,
        created_at=datetime.now(UTC),
        channels=used,
        volumes_cm3=SegmentationVolumes(wt=cm3(wt), tc=cm3(tc), et=cm3(et)),
        dice_vs_gtv=dice_vs_gtv,
        metrics_vs_gtv=metrics_vs_gtv,
        warnings=warnings,
    )
    (out_dir / "monai_seg.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return result
