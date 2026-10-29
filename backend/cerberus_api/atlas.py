"""Atlas Talairach-Brodmann llevado al espacio del paciente, docs/PLAN_MVP.md §13 ticket B9.

Idea de `cerberus_eda.py:1048` ("Registro a MNI + atlas … para reportar áreas de Brodmann afectadas").

Flujo:
1. La T1 sin contraste del paciente (t1eg → t1tse → t1gd), enmascarada con `brain_mask`, se remuestrea a
   `MOVING_SPACING_MM` isotrópico (solo para acelerar el registro) y se registra a la plantilla MNI152 de 1 mm
   (enmascarada con su máscara de cerebro) con ANTs SyN. El GTV dilatado `GTV_MARGIN_MM` se excluye del costo
   (`moving_mask`) para que el tumor no deforme el campo.
2. El atlas, separado por hemisferio en MNI, vuelve al grid de la secuencia de referencia del visor (t1gd si
   existe) con `invtransforms` + `genericLabel`. Las transformaciones viven en el espacio físico, así que sirven
   para cualquier secuencia del estudio (todas están co-registradas en el dataset).
3. Se escribe `brodmann.nii.gz` (uint8) con nibabel y el affine/header EXACTO de la referencia: ANTs trabaja en
   LPS y nibabel en RAS, pero el orden de índices del arreglo es el mismo, por eso solo se copia el arreglo.
"""

import hashlib
import json
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import nibabel as nib
import numpy as np
from nibabel.processing import resample_from_to, resample_to_output
from scipy.ndimage import distance_transform_edt

from cerberus_api.nifti import load_nifti
from cerberus_api.schemas import Hemisphere

ATLAS_NAME = "Talairach-Brodmann (nilearn)"
RIGHT_OFFSET = 100  # valor = índice del atlas (izquierdo) o índice + 100 (derecho)

REFERENCE_PRIORITY = ("t1gd", "t1eg", "t1tse", "flair")  # grid del visor
MOVING_PRIORITY = ("t1eg", "t1tse", "t1gd")  # T1 sin contraste primero

# Remuestrear la imagen móvil a 1.5 mm reduce ~7x los vóxeles (0.5×0.5×1 mm en el dataset) sin perder
# precisión útil frente a una plantilla de 1 mm y un atlas cuyas áreas miden centímetros.
MOVING_SPACING_MM = 1.5
GTV_MARGIN_MM = 5.0
LARGE_GTV_FRACTION = 0.10

# "SyN" de ANTsPy: afín + SyN con reg_iterations=(40, 20, 0).
TYPE_OF_TRANSFORM = "SyN"
RANDOM_SEED = 42
TX_PREFIX = "pat2mni_"
CACHE_FILE = "transforms.json"

WARN_NO_BRAIN = "Sin brain_mask: el registro es menos preciso"
WARN_ONLY_T1GD = "Solo hay T1 con contraste: el registro usa t1gd"
WARN_LARGE_GTV = "GTV grande (>10 % del cerebro): el atlas puede desplazarse"


@dataclass
class AtlasMapping:
    """Resultado de `map_atlas`: mapa de etiquetas en el grid de la referencia + su LUT."""

    label_path: Path
    entries: list[tuple[int, str, Hemisphere]]  # (valor en el NIfTI, nombre del atlas, hemisferio)
    reference_sequence: str
    registration: str
    warnings: list[str] = field(default_factory=list)


def affine_of(img: nib.Nifti1Image) -> np.ndarray:
    """Affine no opcional (nibabel lo tipa como `ndarray | None`)."""
    if img.affine is None:
        raise ValueError("La imagen no tiene affine")
    return img.affine


def fetch_atlas(models_dir: Path) -> tuple[nib.Nifti1Image, list[str]]:
    """Atlas Talairach nivel `ba` (71 regiones + "Background" en el índice 0), cacheado en `models_dir/atlas`.

    La red solo se usa la primera vez (nilearn reutiliza los archivos de `data_dir`).
    """
    from nilearn.datasets import fetch_atlas_talairach

    atlas = fetch_atlas_talairach("ba", data_dir=models_dir / "atlas", verbose=0)
    maps = atlas.maps
    img = maps if isinstance(maps, nib.Nifti1Image) else load_nifti(str(maps))
    return img, [str(label) for label in atlas.labels]


def fetch_template(models_dir: Path) -> tuple[nib.Nifti1Image, nib.Nifti1Image]:
    """Plantilla MNI152 de 1 mm y su máscara de cerebro: `(plantilla, máscara)`.

    Ambas vienen empaquetadas dentro de nilearn (no usan red ni caché); `models_dir` se acepta por simetría con
    `fetch_atlas`. La plantilla ya viene sin cráneo, pero igual se multiplica por la máscara en el registro.
    """
    del models_dir
    from nilearn.datasets import load_mni152_brain_mask, load_mni152_template

    return load_mni152_template(resolution=1), load_mni152_brain_mask(resolution=1)


def split_hemispheres(
    atlas_img: nib.Nifti1Image, labels: list[str] | None = None
) -> tuple[nib.Nifti1Image, list[tuple[int, str, Hemisphere]]]:
    """Separa el atlas por la coordenada x del mundo (RAS: x < 0 izquierdo, x >= 0 derecho).

    Devuelve una imagen uint8 con valor = índice (izquierdo) o índice + 100 (derecho), 0 = fondo, y la lista
    `(valor, nombre, hemisferio)` solo para los valores presentes. `nombre` = `labels[índice]`, o el índice en
    texto si no se pasan etiquetas.
    """
    data = np.asarray(atlas_img.dataobj).astype(np.int64)
    if data.min() < 0 or data.max() >= RIGHT_OFFSET:
        raise ValueError("El atlas debe tener índices entre 0 y 99")
    i, j, k = np.ogrid[: data.shape[0], : data.shape[1], : data.shape[2]]
    a = affine_of(atlas_img)
    x = a[0, 0] * i + a[0, 1] * j + a[0, 2] * k + a[0, 3]
    right = np.broadcast_to(x >= 0, data.shape)

    out = data.copy()
    out[(data > 0) & right] += RIGHT_OFFSET
    out_u8 = out.astype(np.uint8)

    entries: list[tuple[int, str, Hemisphere]] = []
    for value in np.unique(out_u8):
        v = int(value)
        if v == 0:
            continue
        idx = v % RIGHT_OFFSET
        hemi: Hemisphere = "derecho" if v > RIGHT_OFFSET else "izquierdo"
        entries.append((v, labels[idx] if labels is not None else str(idx), hemi))
    header = atlas_img.header.copy()
    header.set_data_dtype(np.uint8)
    header.set_slope_inter(1, 0)
    return nib.Nifti1Image(out_u8, atlas_img.affine, header), entries


def select_sequences(study_files: dict[str, Path]) -> tuple[str, str]:
    """`(referencia, móvil)`: secuencia del grid de salida y secuencia que se registra al MNI.

    Referencia: t1gd → t1eg → t1tse → flair. Móvil: t1eg → t1tse → t1gd (sin contraste primero).
    Lanza `ValueError` si no hay ninguna T1.
    """
    moving = next((s for s in MOVING_PRIORITY if s in study_files), None)
    if moving is None:
        raise ValueError("No hay secuencia T1 (t1eg/t1tse/t1gd) para registrar al MNI")
    reference = next(s for s in REFERENCE_PRIORITY if s in study_files)
    return reference, moving


def _to_grid(img: nib.Nifti1Image, ref: nib.Nifti1Image, order: int) -> np.ndarray:
    res = resample_from_to(img, (ref.shape[:3], ref.affine), order=order)
    return np.asarray(res.dataobj, dtype=np.float32)


def _mask_on(img: nib.Nifti1Image, ref: nib.Nifti1Image) -> np.ndarray:
    """Máscara binaria de `img` en el grid de `ref` (sin remuestrear si ya coinciden)."""
    if img.shape[:3] == ref.shape[:3] and np.allclose(affine_of(img), affine_of(ref), atol=1e-4):
        return np.asarray(img.dataobj) > 0.5
    return _to_grid(img, ref, 0) > 0.5


def _cache_key(study_files: dict[str, Path], moving_seq: str) -> str:
    """Huella del registro: archivos de entrada (ruta, tamaño, mtime) + parámetros."""
    h = hashlib.sha256()
    for seq in (moving_seq, "brain_mask", "gtv"):
        p = study_files.get(seq)
        if p is None:
            h.update(f"{seq}:-;".encode())
            continue
        st = p.stat()
        h.update(f"{seq}:{p.resolve()}:{st.st_size}:{st.st_mtime_ns};".encode())
    h.update(f"{TYPE_OF_TRANSFORM}:{MOVING_SPACING_MM}:{GTV_MARGIN_MM}:{RANDOM_SEED}".encode())
    return h.hexdigest()


def _load_cached(mni_dir: Path, key: str) -> list[str] | None:
    """Rutas de `invtransforms` guardadas si la huella coincide y los archivos existen."""
    meta_path = mni_dir / CACHE_FILE
    if not meta_path.is_file():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if meta.get("key") != key:
        return None
    inv = [str(mni_dir / name) for name in meta.get("invtransforms", [])]
    return inv if inv and all(Path(p).is_file() for p in inv) else None


def _register(study_files: dict[str, Path], moving_seq: str, mni_dir: Path, models_dir: Path, tmp: Path) -> list[str]:
    """Registra paciente → MNI con ANTs y guarda las transformaciones en `mni_dir`. Devuelve `invtransforms`."""
    import ants

    template, template_mask = fetch_template(models_dir)
    mni_brain = np.asarray(template_mask.dataobj) > 0
    fixed_np = np.asarray(template.dataobj, dtype=np.float32) * mni_brain
    nib.save(nib.Nifti1Image(fixed_np, template.affine), tmp / "fixed.nii.gz")
    nib.save(nib.Nifti1Image(mni_brain.astype(np.uint8), template.affine), tmp / "fixed_mask.nii.gz")

    moving_img = resample_to_output(load_nifti(study_files[moving_seq]), voxel_sizes=(MOVING_SPACING_MM,) * 3, order=1)
    assert isinstance(moving_img, nib.Nifti1Image)
    moving_np = np.nan_to_num(np.asarray(moving_img.dataobj, dtype=np.float32))
    cost = np.ones(moving_np.shape, bool)
    if "brain_mask" in study_files:
        brain = _mask_on(load_nifti(study_files["brain_mask"]), moving_img)
        moving_np = moving_np * brain
        cost &= brain
    if "gtv" in study_files:
        gtv = _mask_on(load_nifti(study_files["gtv"]), moving_img)
        if gtv.any():
            # GTV dilatado GTV_MARGIN_MM: todo vóxel a <= 5 mm del GTV queda fuera del costo
            dist = np.asarray(distance_transform_edt(~gtv, sampling=(MOVING_SPACING_MM,) * 3))
            cost &= dist > GTV_MARGIN_MM
    nib.save(nib.Nifti1Image(moving_np, moving_img.affine), tmp / "moving.nii.gz")
    nib.save(nib.Nifti1Image(cost.astype(np.uint8), moving_img.affine), tmp / "moving_mask.nii.gz")

    # Limpia transformaciones viejas: ANTsPy arma la lista de salida con glob(outprefix + "*")
    if mni_dir.exists():
        shutil.rmtree(mni_dir)
    mni_dir.mkdir(parents=True)
    reg = ants.registration(
        fixed=ants.image_read(str(tmp / "fixed.nii.gz")),
        moving=ants.image_read(str(tmp / "moving.nii.gz")),
        type_of_transform=TYPE_OF_TRANSFORM,
        outprefix=str(mni_dir / TX_PREFIX),
        mask=ants.image_read(str(tmp / "fixed_mask.nii.gz")),
        moving_mask=ants.image_read(str(tmp / "moving_mask.nii.gz")),
        mask_all_stages=True,  # el GTV queda fuera del costo también en la etapa afín
        random_seed=RANDOM_SEED,
    )
    inv = [str(p) for p in reg["invtransforms"]]
    meta = {
        "key": _cache_key(study_files, moving_seq),
        "moving_sequence": moving_seq,
        "type_of_transform": TYPE_OF_TRANSFORM,
        "fwdtransforms": [Path(p).name for p in reg["fwdtransforms"]],
        "invtransforms": [Path(p).name for p in inv],
    }
    (mni_dir / CACHE_FILE).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return inv


def which_to_invert(invtransforms: list[str]) -> list[bool]:
    """Las afines (`.mat`) se invierten al aplicarlas; los campos `InverseWarp` ya son la inversa."""
    return [p.endswith(".mat") for p in invtransforms]


def map_atlas(study_files: dict[str, Path], out_dir: Path, models_dir: Path) -> AtlasMapping:
    """Registra el estudio a MNI y escribe `out_dir/brodmann.nii.gz` en el grid de la referencia.

    `study_files`: secuencia → ruta NIfTI. Las transformaciones se guardan en `out_dir/mni/` y se reutilizan
    si las entradas no cambiaron. Lanza `ValueError` si no hay T1 para registrar.
    """
    import ants

    reference_seq, moving_seq = select_sequences(study_files)
    ref_img = load_nifti(study_files[reference_seq])

    warnings: list[str] = []
    brain_ref: np.ndarray | None = None
    if "brain_mask" in study_files:
        brain_ref = _mask_on(load_nifti(study_files["brain_mask"]), ref_img)
    else:
        warnings.append(WARN_NO_BRAIN)
    if moving_seq == "t1gd":
        warnings.append(WARN_ONLY_T1GD)
    if "gtv" in study_files and brain_ref is not None and brain_ref.any():
        gtv_ref = _mask_on(load_nifti(study_files["gtv"]), ref_img)
        if (gtv_ref & brain_ref).sum() > LARGE_GTV_FRACTION * brain_ref.sum():
            warnings.append(WARN_LARGE_GTV)

    atlas_img, labels = fetch_atlas(models_dir)
    split_img, split_entries = split_hemispheres(atlas_img, labels)
    names: dict[int, tuple[str, Hemisphere]] = {v: (name, hemi) for v, name, hemi in split_entries}

    mni_dir = out_dir / "mni"
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cerberus_atlas_") as tmp_str:
        tmp = Path(tmp_str)
        inv = _load_cached(mni_dir, _cache_key(study_files, moving_seq))
        if inv is None:
            inv = _register(study_files, moving_seq, mni_dir, models_dir, tmp)

        nib.save(split_img, tmp / "atlas.nii.gz")
        warped = ants.apply_transforms(
            fixed=ants.image_read(str(study_files[reference_seq])),
            moving=ants.image_read(str(tmp / "atlas.nii.gz")),
            transformlist=inv,
            whichtoinvert=which_to_invert(inv),
            interpolator="genericLabel",
        )
        lab = np.rint(warped.numpy()).astype(np.uint8)

    if lab.shape != ref_img.shape[:3]:
        raise RuntimeError(f"Forma inesperada del atlas remuestreado: {lab.shape} != {ref_img.shape[:3]}")
    if brain_ref is not None:
        lab[~brain_ref] = 0

    header = ref_img.header.copy()
    header.set_data_dtype(np.uint8)
    header.set_slope_inter(1, 0)
    label_path = out_dir / "brodmann.nii.gz"
    nib.save(nib.Nifti1Image(lab, ref_img.affine, header), label_path)
    if not np.allclose(affine_of(load_nifti(label_path)), affine_of(ref_img), atol=1e-5):
        raise RuntimeError("El affine de brodmann.nii.gz no coincide con el de la referencia")

    present = sorted(int(v) for v in np.unique(lab) if v != 0)
    entries: list[tuple[int, str, Hemisphere]] = [(v, *names[v]) for v in present if v in names]
    excluded = " (GTV excluido del costo)" if "gtv" in study_files else ""
    registration = f"ANTs {TYPE_OF_TRANSFORM} {moving_seq}→MNI152{excluded}, atlas {ATLAS_NAME}"
    return AtlasMapping(
        label_path=label_path,
        entries=entries,
        reference_sequence=reference_seq,
        registration=registration,
        warnings=warnings,
    )
