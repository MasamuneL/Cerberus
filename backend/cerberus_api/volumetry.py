"""Volumetría del GTV, categoría RANO volumétrica y serie longitudinal (docs/PLAN_MVP.md §8, ticket B3).

Las fórmulas y el redondeo están portados sin cambios de `cerberus_eda.py` (volumetría: 209-235;
`rano_vol` y cambio vs t0: 300-312).
"""

from pathlib import Path

import numpy as np
from scipy import ndimage as ndi

from cerberus_api.nifti import load_nifti
from cerberus_api.schemas import LongitudinalPoint, RanoCategory, Volumetry
from cerberus_api.sequences import TIMEPOINT_RE, validate_patient


def gtv_volumetry(gtv_path: Path, brain_path: Path) -> Volumetry:
    """Volumetría del GTV a resolución nativa.

    Portado del cuerpo del loop de `cerberus_eda.py:209-235`, con las mismas fórmulas y redondeos
    (GTV 2 decimales, cerebro 1, fracción 2, extensiones 1, ABC/2 2, error 1).
    A diferencia del notebook, si el GTV está vacío lanza `ValueError`: allí se dividiría entre cero
    (error de ABC/2) y `argwhere` no tendría índices para las extensiones.
    """
    img = load_nifti(gtv_path)
    sx, sy, sz = (float(z) for z in img.header.get_zooms()[:3])
    gtv = np.asanyarray(img.dataobj) > 0
    brain = np.asanyarray(load_nifti(brain_path).dataobj) > 0
    if not gtv.any():
        raise ValueError(f"GTV vacío: {Path(gtv_path).name}")
    vox = sx * sy * sz  # mm³ por vóxel
    idx = np.argwhere(gtv)
    # Extensión de la caja envolvente en mm (LR, AP, SI)
    ext = (idx.max(0) - idx.min(0) + 1) * np.array([sx, sy, sz])
    v = float(gtv.sum() * vox / 1000)  # cm³
    abc2 = float(np.prod(ext) / 2 / 1000)  # aproximación elipsoidal ABC/2, cm³
    # `ndi.label` devuelve (etiquetas, n); pyright infiere también `int` (rama con `output`), de ahí el isinstance
    labeled = ndi.label(gtv)
    n_components = labeled[1] if isinstance(labeled, tuple) else labeled
    return Volumetry(
        gtv_cm3=round(v, 2),
        brain_cm3=round(float(brain.sum() * vox / 1000), 1),
        fraction_pct=round(float(100 * gtv.sum() / brain.sum()), 2),
        lr_mm=round(float(ext[0]), 1),
        ap_mm=round(float(ext[1]), 1),
        si_mm=round(float(ext[2]), 1),
        abc2_cm3=round(abc2, 2),
        abc2_error_pct=round(100 * (abc2 - v) / v, 1),
        components=int(n_components),
        # RANO: lesión medible si todas las extensiones son >= 10 mm
        rano_measurable=bool((ext >= 10).all()),
        spacing_ok=(sx, sy, sz) != (1.0, 1.0, 1.0),
    )


def rano_category(pct: float) -> RanoCategory:
    """Categoría RANO 2.0 volumétrica del cambio porcentual vs t0.

    Portado de `cerberus_eda.py:300-307` (`rano_vol`), devolviendo solo la sigla.
    """
    if pct >= 40:
        return "PD"  # progresión
    if pct <= -65:
        return "PR"  # respuesta parcial
    if pct <= -40:
        return "MR"  # respuesta menor
    return "SD"  # estable


def longitudinal(data_dir: Path, patient: str) -> list[LongitudinalPoint]:
    """Serie del GTV por tiempo con cambio vs t0 y categoría RANO.

    Portado de `cerberus_eda.py:309-312`: base = GTV en t0 y cambio `round(100 * (v / base - 1), 1)`.
    Solo cuenta tiempos con `gtv` y `brain_mask`, ordenados numéricamente (t0, t1, …, t10).
    Sin t0 devuelve `[]`; t0 lleva cambio 0.0 y `rano=None`.
    """
    validate_patient(patient)
    patient_dir = data_dir / patient
    if not patient_dir.is_dir():
        return []
    timepoints = [d.name for d in patient_dir.iterdir() if d.is_dir() and TIMEPOINT_RE.fullmatch(d.name)]
    volumes: list[tuple[str, float]] = []
    for tp in sorted(timepoints, key=lambda t: int(t[1:])):
        gtv_path = patient_dir / tp / f"{int(patient)}_{tp}_gtv.nii.gz"
        brain_path = patient_dir / tp / f"{int(patient)}_{tp}_brain_mask.nii.gz"
        if gtv_path.is_file() and brain_path.is_file():
            volumes.append((tp, gtv_volumetry(gtv_path, brain_path).gtv_cm3))
    base = dict(volumes).get("t0")
    if base is None:
        return []
    points: list[LongitudinalPoint] = []
    for tp, v in volumes:
        if tp == "t0":
            points.append(LongitudinalPoint(timepoint=tp, gtv_cm3=v, change_vs_t0_pct=0.0, rano=None))
            continue
        change = round(100 * (v / base - 1), 1)
        points.append(LongitudinalPoint(timepoint=tp, gtv_cm3=v, change_vs_t0_pct=change, rano=rano_category(change)))
    return points
