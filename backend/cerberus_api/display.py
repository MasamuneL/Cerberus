"""Máscaras suavizadas **solo para visualización** (GTV, segmentación MONAI y áreas de Brodmann).

Las máscaras son mapas de etiquetas por vóxel: vistas de cerca muestran la escalera de la rejilla (0.5 mm en el
plano, 1 mm entre cortes, y 1 mm en todos los ejes para MONAI). Para cada etiqueta:

  1. Recorte al bounding box de la etiqueta con margen de 3σ.
  2. Indicadora binaria → filtro gaussiano (σ en mm, convertido a vóxeles por eje) = "probabilidad" suave.
  3. Remuestreo trilineal a la rejilla de referencia del estudio (la del fondo en el visor).
  4. Cada vóxel toma la etiqueta con mayor probabilidad, si es ≥ 0.5 (la isosuperficie 0.5 queda redondeada).
  5. Los componentes conexos que el suavizado borraría por completo (focos de pocos vóxeles, áreas diminutas)
     se conservan con sus vóxeles originales, para no ocultar lesiones pequeñas.

La volumetría, RANO y Dice **siempre** usan la máscara original; esta copia solo se sirve al visor.
"""

import os
import tempfile
from pathlib import Path

import nibabel as nib
import numpy as np
from scipy import ndimage

from cerberus_api.atlas import affine_of
from cerberus_api.nifti import load_nifti

# Máscaras que el visor puede pedir suavizadas (`?smooth=1` en `/files/{name}.nii.gz`)
SMOOTHABLE: tuple[str, ...] = ("gtv", "monai_seg", "brodmann")
DISPLAY_DIR = "display"
DEFAULT_SIGMA_MM = 1.0
ISO = 0.5


def _voxel_sizes(affine: np.ndarray) -> np.ndarray:
    """Tamaño de vóxel (mm) por eje a partir de las columnas del affine."""
    return np.sqrt((affine[:3, :3] ** 2).sum(axis=0))


def _ref_box(
    s0: np.ndarray, s1: np.ndarray, ref_from_src: np.ndarray, ref_shape: tuple[int, ...]
) -> tuple[np.ndarray, np.ndarray]:
    """Caja [r0, r1) de la rejilla de referencia que cubre la caja de origen [s0, s1)."""
    lo, hi = s0 - 0.5, s1 - 0.5
    corners = np.array([[x, y, z, 1.0] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
    mapped = (ref_from_src @ corners.T)[:3].T
    r0 = np.clip(np.floor(mapped.min(axis=0)).astype(int), 0, ref_shape)
    r1 = np.clip(np.ceil(mapped.max(axis=0)).astype(int) + 1, 0, ref_shape)
    return r0, r1


def smooth_labels(
    data: np.ndarray,
    src_affine: np.ndarray,
    ref_shape: tuple[int, int, int],
    ref_affine: np.ndarray,
    sigma_mm: float = DEFAULT_SIGMA_MM,
) -> np.ndarray:
    """Mapa de etiquetas `data` (rejilla `src_affine`) suavizado y remuestreado a la rejilla de referencia.

    Devuelve un arreglo entero de forma `ref_shape` con las mismas etiquetas (0 = fondo). Con varias etiquetas
    contiguas (Brodmann) el contorno exterior sale de suavizar su unión, y dentro de él gana la etiqueta más
    probable: así las fronteras entre áreas no dejan huecos donde ninguna llega a 0.5.
    """
    labels_img = np.rint(data).astype(np.int32)
    labels_img[labels_img < 0] = 0
    max_label = int(labels_img.max())
    out, best = _accumulate(labels_img, src_affine, ref_shape, ref_affine, sigma_mm)
    if max_label <= 1:
        foreground = best >= ISO
    else:
        union = (labels_img > 0).astype(np.int32)
        foreground = _accumulate(union, src_affine, ref_shape, ref_affine, sigma_mm)[1] >= ISO
        foreground |= best >= 1.0  # focos conservados (paso 5) aunque la unión suavizada no los cubra
    out[~foreground] = 0
    return out


def _accumulate(
    labels_img: np.ndarray,
    src_affine: np.ndarray,
    ref_shape: tuple[int, int, int],
    ref_affine: np.ndarray,
    sigma_mm: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Etiqueta más probable por vóxel de referencia y su probabilidad suavizada (sin umbral)."""
    max_label = int(labels_img.max())
    out = np.zeros(ref_shape, dtype=np.min_scalar_type(max(max_label, 1)))
    best = np.zeros(ref_shape, dtype=np.float16)
    if max_label == 0:
        return out, best

    src_from_ref = np.linalg.inv(src_affine) @ ref_affine
    ref_from_src = np.linalg.inv(src_from_ref)
    identity = labels_img.shape == tuple(ref_shape) and np.allclose(src_from_ref, np.eye(4), atol=1e-4)
    sigma_vox = sigma_mm / _voxel_sizes(src_affine)
    pad = np.ceil(3 * sigma_vox).astype(int) + 1
    src_shape = np.array(labels_img.shape)

    for idx, box in enumerate(ndimage.find_objects(labels_img)):
        if box is None:
            continue
        label = idx + 1
        s0 = np.maximum([b.start for b in box] - pad, 0)
        s1 = np.minimum([b.stop for b in box] + pad, src_shape)
        crop = (labels_img[tuple(slice(a, b) for a, b in zip(s0, s1, strict=True))] == label).astype(np.float32)
        prob = ndimage.gaussian_filter(crop, sigma=sigma_vox, mode="constant")

        if identity:
            r0, r1 = s0, s1
            near = crop > ISO
        else:
            r0, r1 = _ref_box(s0, s1, ref_from_src, ref_shape)
            if np.any(r1 <= r0):
                continue
            # Matriz homogénea vóxel de referencia (local a la caja) → vóxel de origen (local al recorte)
            local = src_from_ref.copy()
            local[:3, 3] = src_from_ref[:3, :3] @ r0 + src_from_ref[:3, 3] - s0
            shape = tuple(int(v) for v in r1 - r0)
            prob = ndimage.affine_transform(prob, local, output_shape=shape, order=1, cval=0.0)
            near = ndimage.affine_transform(crop, local, output_shape=shape, order=0, cval=0.0) > ISO

        # Focos que desaparecerían: se mantienen con sus vóxeles originales (prob = 1, ganan a las vecinas).
        inside = prob >= ISO
        if np.any(near & ~inside):
            # `ndimage.label` devuelve (etiquetas, n); pyright infiere también `int`, de ahí el isinstance
            labeled = ndimage.label(near)
            if not isinstance(labeled, tuple):
                raise TypeError("ndimage.label debía devolver (etiquetas, n)")
            comps, n = labeled
            kept = np.unique(comps[inside & near])
            lost = np.setdiff1d(np.arange(1, n + 1), kept)
            if lost.size:
                prob = np.where(np.isin(comps, lost), np.float32(1.0), prob)

        region = tuple(slice(int(a), int(b)) for a, b in zip(r0, r1, strict=True))
        win = (prob > 0) & (prob > best[region])
        best[region][win] = prob[win]
        out[region][win] = label
    return out, best


def display_path(results_dir: Path, patient: str, timepoint: str, name: str) -> Path:
    """Ruta de la copia suavizada. `patient`, `timepoint` y `name` deben venir ya validados."""
    return results_dir / patient / timepoint / DISPLAY_DIR / f"{name}.nii.gz"


def ensure_smoothed(source: Path, reference: Path | None, target: Path, sigma_mm: float = DEFAULT_SIGMA_MM) -> Path:
    """Genera (o reutiliza) `target`, la versión suavizada de `source` en la rejilla de `reference`.

    Se regenera si falta o si `source`/`reference` son más nuevos. La escritura es atómica (temporal +
    `os.replace`) para que dos peticiones simultáneas nunca sirvan un archivo a medias.
    """
    deps = [source] if reference is None else [source, reference]
    if target.is_file() and target.stat().st_mtime >= max(p.stat().st_mtime for p in deps):
        return target
    src = load_nifti(source)
    ref = src if reference is None else load_nifti(reference)
    ref_shape = tuple(int(v) for v in ref.shape[:3])
    data = np.asarray(src.dataobj)
    if data.ndim > 3:
        data = data[..., 0]
    ref_affine = affine_of(ref)
    smoothed = smooth_labels(data, affine_of(src), (ref_shape[0], ref_shape[1], ref_shape[2]), ref_affine, sigma_mm)
    img = nib.Nifti1Image(smoothed, ref_affine)
    img.header.set_xyzt_units("mm")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".nii.gz")
    os.close(fd)
    try:
        nib.save(img, tmp)
        os.replace(tmp, target)
    finally:
        Path(tmp).unlink(missing_ok=True)
    return target
