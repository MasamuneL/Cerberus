"""Reporte de áreas de Brodmann / estructuras afectadas por el GTV, docs/PLAN_MVP.md §13 ticket B11.

Idea de `cerberus_eda.py:1048` ("Registro a MNI + atlas … para reportar áreas de Brodmann afectadas").

Con el mapa de etiquetas de `atlas.map_atlas` (grid de la referencia, t1gd) se calcula, por etiqueta:
- volumen del área en el paciente (cm³),
- solapamiento con el GTV (cm³ y % del área) y, si existe `monai_seg`, con el WT (tumor + edema),
- distancia mínima del GTV al área en mm (EDT con el spacing real; 0 si se solapan).

Se reportan las áreas solapadas y las que estén a <= `MARGIN_MM`. Es una estimación educativa basada en atlas.
"""

from datetime import UTC, datetime
from pathlib import Path

import nibabel as nib
import numpy as np
from nibabel.processing import resample_from_to
from scipy import ndimage

from cerberus_api import atlas
from cerberus_api.area_kb import area_info, functions_for
from cerberus_api.atlas import ATLAS_NAME, affine_of
from cerberus_api.nifti import load_nifti
from cerberus_api.schemas import AffectedArea, AreaLabel, AreasResult, Hemisphere

__all__ = ["ATLAS_NAME", "MARGIN_MM", "compute_area_report", "run_area_mapping"]

MARGIN_MM = 10.0
AREAS_JSON = "brodmann.json"
SEGMENTATION_FILE = "monai_seg.nii.gz"
WARN_NO_WT = "Sin segmentación MONAI: no se calcula el solapamiento con tumor+edema"

# Los valores del mapa son uint8 (índice del atlas o índice + 100)
_N_LABELS = 256


def _mask_on_grid(img: nib.Nifti1Image, ref: nib.Nifti1Image, threshold: float = 0.5) -> np.ndarray:
    """`img > threshold` en el grid de `ref`; remuestrea con orden 0 solo si el grid no coincide."""
    if img.shape[:3] == ref.shape[:3] and np.allclose(affine_of(img), affine_of(ref), atol=1e-4):
        data = np.asarray(img.dataobj)
    else:
        data = np.asarray(resample_from_to(img, (ref.shape[:3], affine_of(ref)), order=0).dataobj)
    return data > threshold


def label_info(value: int, name: str, hemisphere: Hemisphere) -> AreaLabel:
    """Entrada del LUT con el nombre en español de la base curada (o el del atlas si no está)."""
    info = area_info(name)
    if info is None:
        kind = "cortical" if name.startswith("Brodmann area") else "subcortical"
        return AreaLabel(label=value, name=name, name_es=name, hemisphere=hemisphere, kind=kind)
    return AreaLabel(label=value, name=name, name_es=info.name_es, hemisphere=hemisphere, kind=info.kind)


def _min_distance_mm(lab: np.ndarray, gtv: np.ndarray, zooms: np.ndarray, margin_mm: float) -> np.ndarray:
    """Distancia mínima (mm) del GTV a cada etiqueta; `inf` si está a más de `margin_mm` o no hay GTV.

    El EDT se calcula solo en la caja del GTV ampliada `margin_mm` (+1 vóxel): todo vóxel del GTV queda dentro,
    así que las distancias en la caja son exactas, y lo que queda fuera está a más de `margin_mm`.
    """
    dist = np.full(_N_LABELS, np.inf)
    if not gtv.any():
        return dist
    idx = np.argwhere(gtv)
    pad = np.ceil(margin_mm / zooms).astype(int) + 1
    lo = np.maximum(idx.min(axis=0) - pad, 0)
    hi = np.minimum(idx.max(axis=0) + pad + 1, np.asarray(gtv.shape))
    box = tuple(slice(int(a), int(b)) for a, b in zip(lo, hi, strict=True))
    edt = np.asarray(ndimage.distance_transform_edt(~gtv[box], sampling=zooms))
    lab_box = lab[box]
    present = np.unique(lab_box)
    present = present[present != 0]
    if present.size:
        mins = np.asarray(ndimage.minimum(edt, labels=lab_box, index=present), dtype=float)
        dist[present] = mins
    return dist


def _overlap_cm3(n_voxels: int, vox_cm3: float) -> float:
    """cm³ con 2 decimales, salvo un solapamiento mínimo (< 0.005 cm³), que conserva 4 para no quedar en 0.

    La UI separa "Afectadas" de "Cercanas" con `overlap_gtv_cm3 > 0`: un solapamiento de pocos vóxeles debe
    seguir contando como afectado.
    """
    value = round(n_voxels * vox_cm3, 2)
    return value if value > 0 or n_voxels == 0 else round(n_voxels * vox_cm3, 4)


def compute_area_report(
    label_path: Path,
    entries: list[tuple[int, str, Hemisphere]],
    gtv_path: Path,
    wt_mask: np.ndarray | None,
    margin_mm: float = MARGIN_MM,
) -> tuple[list[AffectedArea], list[AreaLabel]]:
    """Áreas afectadas/cercanas al GTV y LUT de las etiquetas presentes en `label_path`.

    `entries`: `(valor, nombre del atlas, hemisferio)`. `wt_mask` (opcional) debe estar en el grid del mapa.
    El GTV se remuestrea (orden 0) al grid del mapa si no coincide. Orden: solapadas por `overlap_gtv_cm3`
    descendente y luego cercanas por distancia ascendente.
    """
    lab_img = load_nifti(label_path)
    lab = np.asarray(lab_img.dataobj).astype(np.int64)
    if lab.min() < 0 or lab.max() >= _N_LABELS:
        raise ValueError("El mapa de etiquetas debe tener valores entre 0 y 255")
    gtv = _mask_on_grid(load_nifti(gtv_path), lab_img)
    if wt_mask is not None and wt_mask.shape != lab.shape:
        raise ValueError(f"La máscara WT no está en el grid del atlas: {wt_mask.shape} != {lab.shape}")

    zooms = np.asarray(lab_img.header.get_zooms()[:3], dtype=float)
    vox_cm3 = float(np.prod(zooms)) / 1000.0

    area_n = np.bincount(lab.ravel(), minlength=_N_LABELS)
    gtv_n = np.bincount(lab[gtv], minlength=_N_LABELS)
    wt_n = np.bincount(lab[wt_mask.astype(bool)], minlength=_N_LABELS) if wt_mask is not None else None
    dist = _min_distance_mm(lab, gtv, zooms, margin_mm)

    lut: list[AreaLabel] = []
    overlapping: list[tuple[int, AffectedArea]] = []
    nearby: list[tuple[float, AffectedArea]] = []
    for value, name, hemisphere in entries:
        n_area = int(area_n[value]) if 0 < value < _N_LABELS else 0
        if n_area == 0:
            continue  # el LUT solo lleva etiquetas presentes en el mapa
        base = label_info(value, name, hemisphere)
        lut.append(base)
        n_gtv = int(gtv_n[value])
        d = 0.0 if n_gtv > 0 else float(dist[value])
        if n_gtv == 0 and not d <= margin_mm:
            continue
        info = area_info(name)
        n_wt = int(wt_n[value]) if wt_n is not None else None
        area = AffectedArea(
            **base.model_dump(),
            area_cm3=round(n_area * vox_cm3, 2),
            overlap_gtv_cm3=_overlap_cm3(n_gtv, vox_cm3),
            overlap_gtv_pct=round(100.0 * n_gtv / n_area, 1),
            overlap_wt_cm3=round(n_wt * vox_cm3, 2) if n_wt is not None else None,
            overlap_wt_pct=round(100.0 * n_wt / n_area, 1) if n_wt is not None else None,
            distance_mm=round(d, 1),
            functions=functions_for(name, hemisphere),
            eloquent=info.eloquent if info is not None else False,
        )
        if n_gtv > 0:
            overlapping.append((n_gtv, area))
        else:
            nearby.append((d, area))

    overlapping.sort(key=lambda t: (-t[0], t[1].label))
    nearby.sort(key=lambda t: (t[0], t[1].label))
    return [a for _, a in overlapping] + [a for _, a in nearby], lut


def run_area_mapping(study_files: dict[str, Path], out_dir: Path, models_dir: Path) -> AreasResult:
    """Mapea el atlas al estudio (`atlas.map_atlas`), calcula el reporte y escribe `out_dir/brodmann.json`.

    `study_files`: secuencia → ruta NIfTI. Usa `out_dir/monai_seg.nii.gz` (WT = etiquetas >= 1) si existe.
    Lanza `ValueError` si no hay GTV o no hay T1 para registrar.
    """
    if "gtv" not in study_files:
        raise ValueError("El estudio no tiene GTV: no se pueden reportar áreas afectadas")
    mapping = atlas.map_atlas(study_files, out_dir, models_dir)
    warnings = list(mapping.warnings)

    wt_mask: np.ndarray | None = None
    seg_path = out_dir / SEGMENTATION_FILE
    if seg_path.is_file():
        wt_mask = _mask_on_grid(load_nifti(seg_path), load_nifti(mapping.label_path))
    else:
        warnings.append(WARN_NO_WT)

    areas, lut = compute_area_report(mapping.label_path, mapping.entries, study_files["gtv"], wt_mask)
    result = AreasResult(
        atlas=ATLAS_NAME,
        registration=mapping.registration,
        reference_sequence=mapping.reference_sequence,
        margin_mm=MARGIN_MM,
        created_at=datetime.now(UTC),
        areas=areas,
        lut=lut,
        warnings=warnings,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / AREAS_JSON).write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return result
