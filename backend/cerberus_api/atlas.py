"""Atlas Talairach-Brodmann llevado al espacio del paciente, docs/PLAN_MVP.md §13 ticket B9.

Idea de `cerberus_eda.py:1048` ("Registro a MNI + atlas … para reportar áreas de Brodmann afectadas").

Flujo:
1. La T1 sin contraste del paciente (t1eg → t1tse → t1gd), enmascarada con `brain_mask`, se remuestrea a
   `MOVING_SPACING_MM` isotrópico (solo para acelerar el registro) y se registra a la plantilla MNI152 de 1 mm
   (enmascarada con su máscara de cerebro) con ANTs SyN (perfil `full`; `fast` usa 2 mm en ambas, ver
   `REGISTRATION_PROFILES`). El GTV dilatado `GTV_MARGIN_MM` se excluye del costo (`moving_mask`) para que el
   tumor no deforme el campo. Desde REG1 el registro va en dos pasos para ser reproducible: la etapa afín corre en
   un subproceso con 1 hilo (`cerberus_api.linear_reg`) y el SyN, multihilo, parte de ella (`SyNOnly`).
   Al registrar se guarda un QC (determinante y rotación del afín, Dice de la máscara de cerebro en MNI) que
   `map_atlas` convierte en avisos.
2. El atlas, separado por hemisferio en MNI, vuelve al grid de la secuencia de referencia del visor (t1gd si
   existe) con `invtransforms` + `genericLabel`. Las transformaciones viven en el espacio físico, así que sirven
   para cualquier secuencia del estudio (todas están co-registradas en el dataset).
3. Se escribe `brodmann.nii.gz` (uint8) con nibabel y el affine/header EXACTO de la referencia: ANTs trabaja en
   LPS y nibabel en RAS, pero el orden de índices del arreglo es el mismo, por eso solo se copia el arreglo.
"""

import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np
from nibabel.processing import resample_from_to, resample_to_output
from scipy.ndimage import distance_transform_edt

from cerberus_api.config import RegistrationMode
from cerberus_api.nifti import load_nifti
from cerberus_api.runtime import THREAD_ENV_VARS
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

# "SyN" de ANTsPy: afín + SyN con reg_iterations=(40, 20, 0). Desde REG1 se ejecuta en dos pasos (afín con 1 hilo
# en `linear_reg` + `SyNOnly` multihilo) con los mismos parámetros; el nombre sigue siendo el del reporte.
TYPE_OF_TRANSFORM = "SyN"
SYN_STAGE = "SyNOnly"  # SyN sin etapas lineales: parte de la afín del subproceso (`initial_transform`)
RANDOM_SEED = 42
LINEAR_THREADS = 1  # hilos de la etapa afín: con 1 es bit a bit reproducible (REG1)
# Versión del algoritmo de registro en la huella de caché: subirla invalida las transformaciones guardadas.
# 2 = REG1 (afín con 1 hilo + SyNOnly, QC en transforms.json). Las de HW3 (sin versión) se recalculan.
REGISTRATION_VERSION = 2


@dataclass(frozen=True)
class RegistrationProfile:
    """Parámetros del registro paciente → MNI que cambian entre `CERBERUS_REGISTRATION=full|fast` (§25 HW3)."""

    type_of_transform: str
    spacing_mm: float  # remuestreo isotrópico de la imagen móvil
    extra_kwargs: dict[str, Any] = field(default_factory=dict[str, Any])  # kwargs extra de `ants.registration`
    suffix: str = ""  # se añade al texto `registration` del reporte
    fixed_spacing_mm: float | None = None  # remuestreo de la plantilla MNI (None = su 1 mm original)


# `full` es el registro de referencia: no cambiar sus valores sin revalidar (benchmark de REG1 en 001, 004 y 005).
# `fast` (benchmark de HW3 en 001/t0, 004/t0 y 005/t1): SyN con reg_iterations=(20, 10, 0), imagen móvil y plantilla
# MNI a 2 mm. Bajar solo las iteraciones o la resolución de la móvil rinde ~1.3x porque el costo lo domina la
# plantilla de 1 mm; bajar también la plantilla da ~3x con las mismas áreas «Afectadas». `antsRegistrationSyNQuick[s]`
# (rígido + afín + SyN 100x70x50) resultó 1.6x MÁS LENTO que `full` y se descartó.
REGISTRATION_PROFILES: dict[RegistrationMode, RegistrationProfile] = {
    "full": RegistrationProfile(TYPE_OF_TRANSFORM, MOVING_SPACING_MM),
    "fast": RegistrationProfile(
        TYPE_OF_TRANSFORM, 2.0, {"reg_iterations": (20, 10, 0)}, suffix=" (rápido)", fixed_spacing_mm=2.0
    ),
}
TX_PREFIX = "pat2mni_"
CACHE_FILE = "transforms.json"

WARN_NO_BRAIN = "Sin brain_mask: el registro es menos preciso"
WARN_ONLY_T1GD = "Solo hay T1 con contraste: el registro usa t1gd"
WARN_LARGE_GTV = "GTV grande (>10 % del cerebro): el atlas puede desplazarse"

# QC del registro (REG1). Umbrales elegidos con los 8 estudios del dataset (docs/PLAN_MVP.md §25, fila REG1):
# - Escala: el determinante de la afín (MNI → paciente) es el cociente de volúmenes; se compara con el cociente de
#   las máscaras de cerebro (paciente / MNI) porque los cerebros del dataset miden 1.2–1.6 L y la máscara MNI 1.9 L
#   (001/t0 tiene determinante 0.59 con un registro correcto). Sin brain_mask se usa el determinante crudo.
# - Rotación: el cabeceo real del paciente en el escáner llega a ~22° (004/t0, verificado con QC visual), así que
#   15° daría falsos positivos; se avisa por encima de `MAX_ROTATION_DEG`.
# - Dice de la máscara de cerebro del paciente llevada a MNI contra la de la plantilla.
SCALE_RANGE = (0.7, 1.4)
MAX_ROTATION_DEG = 30.0
MIN_BRAIN_DICE = 0.80
QC_SPACING_MM = 2.0  # grid MNI del Dice de QC: a 2 mm cuesta ~0.1 s en vez de ~0.5 s a 1 mm
WARN_REG_SCALE = "Registro a MNI dudoso: la afín escala el cerebro ×{:.2f} (esperado 0.7–1.4); revisa las áreas"
WARN_REG_ROTATION = "Registro a MNI dudoso: la afín rota {:.0f}° (> {:.0f}°); revisa las áreas"
WARN_REG_DICE = (
    "Registro a MNI dudoso: la máscara de cerebro deformada solapa poco con la de MNI (Dice {:.2f} < {:.2f}); "
    "revisa las áreas"
)


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


def _cache_key(study_files: dict[str, Path], moving_seq: str, mode: RegistrationMode = "full") -> str:
    """Huella del registro: archivos de entrada (ruta, tamaño, mtime) + perfil, parámetros y versión.

    `fast` añade su modo y sus kwargs para no mezclar transformaciones de ambos perfiles. `REGISTRATION_VERSION`
    entra en ambos modos: las transformaciones de antes de REG1 (afín multihilo, no reproducible) se recalculan.
    """
    profile = REGISTRATION_PROFILES[mode]
    h = hashlib.sha256()
    for seq in (moving_seq, "brain_mask", "gtv"):
        p = study_files.get(seq)
        if p is None:
            h.update(f"{seq}:-;".encode())
            continue
        st = p.stat()
        h.update(f"{seq}:{p.resolve()}:{st.st_size}:{st.st_mtime_ns};".encode())
    h.update(f"{profile.type_of_transform}:{profile.spacing_mm}:{GTV_MARGIN_MM}:{RANDOM_SEED}".encode())
    if mode != "full":
        h.update(f":{mode}:{profile.fixed_spacing_mm}:{sorted(profile.extra_kwargs.items())}".encode())
    h.update(f":v{REGISTRATION_VERSION}:{SYN_STAGE}:{LINEAR_THREADS}".encode())
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


class LinearStage:
    """Etapa afín en un subproceso con `LINEAR_THREADS` hilos (`cerberus_api.linear_reg`).

    Hace falta otro proceso porque ITK fija sus hilos al importarse y el worker ya importó ANTs con N hilos. Se lanza
    al principio de `_register` para que el arranque (~1 s) se solape con la preparación de las imágenes; `submit`
    le manda los argumentos y `result` espera la ruta de la afín. `close` mata el proceso si sigue vivo.
    """

    def __init__(self, tmp: Path) -> None:
        env = dict(os.environ)
        for var in THREAD_ENV_VARS:
            env[var] = str(LINEAR_THREADS)
        self._stderr_path = tmp / "linear_stderr.txt"
        self._stderr = self._stderr_path.open("w", encoding="utf-8")
        self._proc = subprocess.Popen(
            [sys.executable, "-m", "cerberus_api.linear_reg"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._stderr,  # a archivo: un pipe lleno bloquearía al hijo
            text=True,
            env=env,
        )

    def submit(self, args: dict[str, Any]) -> None:
        """Envía los argumentos (ver `linear_reg`) y cierra stdin: el hijo empieza a registrar."""
        assert self._proc.stdin is not None
        self._proc.stdin.write(json.dumps(args))
        self._proc.stdin.close()

    def result(self) -> str:
        """Espera al hijo y devuelve la ruta del `.mat`; `RuntimeError` si falló."""
        assert self._proc.stdout is not None
        out = self._proc.stdout.read()
        code = self._proc.wait()
        lines = out.strip().splitlines()
        if code != 0 or not lines or not Path(lines[-1]).is_file():
            self._stderr.flush()
            detail = self._stderr_path.read_text(encoding="utf-8", errors="replace").strip()[-500:]
            raise RuntimeError(f"Falló la etapa afín del registro (código {code}): {detail}")
        return lines[-1]

    def close(self) -> None:
        if self._proc.poll() is None:
            self._proc.kill()
            self._proc.wait()
        for stream in (self._proc.stdin, self._proc.stdout):
            if stream is not None and not stream.closed:
                stream.close()
        self._stderr.close()


def affine_matrix(mat_path: Path) -> np.ndarray:
    """Parte lineal 3x3 de una afín de ANTs (`*GenericAffine.mat`: 9 coeficientes por filas + traslación)."""
    import ants

    params = np.asarray(ants.read_transform(str(mat_path)).parameters, dtype=float)
    if params.size != 12:
        raise ValueError(f"Afín 3D inesperada: {params.size} parámetros")
    return params[:9].reshape(3, 3)


def affine_qc(matrix: np.ndarray) -> tuple[float, float]:
    """`(determinante, rotación en grados)` de la parte lineal de una afín.

    La rotación sale de la descomposición polar (`R = U Vᵀ` de la SVD), así que no la contaminan escala ni cizalla.
    """
    u, _, vt = np.linalg.svd(matrix)
    rot = u @ vt
    cos = float(np.clip((np.trace(rot) - 1.0) / 2.0, -1.0, 1.0))
    return float(np.linalg.det(matrix)), math.degrees(math.acos(cos))


def dice(a: np.ndarray, b: np.ndarray) -> float:
    """Dice de dos máscaras binarias del mismo grid (1.0 si ambas están vacías)."""
    total = int(a.sum()) + int(b.sum())
    return 2.0 * int((a & b).sum()) / total if total else 1.0


def registration_warnings(qc: dict[str, Any]) -> list[str]:
    """Avisos en español a partir del QC guardado en `transforms.json` (claves ausentes = sin aviso).

    `scale` = determinante / cociente de volúmenes de cerebro (o el determinante crudo sin brain_mask).
    """
    out: list[str] = []
    scale = qc.get("scale")
    if scale is not None and not SCALE_RANGE[0] <= scale <= SCALE_RANGE[1]:
        out.append(WARN_REG_SCALE.format(scale))
    rotation = qc.get("rotation_deg")
    if rotation is not None and rotation > MAX_ROTATION_DEG:
        out.append(WARN_REG_ROTATION.format(rotation, MAX_ROTATION_DEG))
    brain_dice = qc.get("brain_dice")
    if brain_dice is not None and brain_dice < MIN_BRAIN_DICE:
        out.append(WARN_REG_DICE.format(brain_dice, MIN_BRAIN_DICE))
    return out


def _registration_qc(
    affine_path: Path,
    fwdtransforms: list[str],
    tmp: Path,
    fixed_brain: np.ndarray,
    fixed_voxel_mm3: float,
    moving_brain: np.ndarray | None,
    moving_voxel_mm3: float,
) -> dict[str, Any]:
    """QC del registro recién hecho: determinante, rotación, escala relativa y Dice del cerebro en MNI.

    El Dice se mide en un grid MNI de `QC_SPACING_MM` (la máscara MNI remuestreada por vecino más cercano).
    """
    import ants

    det, rotation = affine_qc(affine_matrix(affine_path))
    qc: dict[str, Any] = {"det": round(det, 4), "rotation_deg": round(rotation, 2), "scale": round(det, 4)}
    if moving_brain is not None and moving_brain.any() and fixed_brain.any():
        ratio = moving_brain.sum() * moving_voxel_mm3 / (fixed_brain.sum() * fixed_voxel_mm3)
        qc["volume_ratio"] = round(float(ratio), 4)
        qc["scale"] = round(det / float(ratio), 4)
        grid = ants.resample_image(
            ants.image_read(str(tmp / "fixed_mask.nii.gz")), (QC_SPACING_MM,) * 3, use_voxels=False, interp_type=1
        )
        warped = ants.apply_transforms(
            fixed=grid,
            moving=ants.image_read(str(tmp / "moving_brain.nii.gz")),
            transformlist=fwdtransforms,
            interpolator="genericLabel",
        )
        qc["brain_dice"] = round(dice(warped.numpy() > 0.5, grid.numpy() > 0.5), 4)
    return qc


def _load_qc(mni_dir: Path) -> dict[str, Any]:
    """QC guardado en `transforms.json` (vacío si no existe o no se puede leer)."""
    try:
        meta = json.loads((mni_dir / CACHE_FILE).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    qc = meta.get("qc") if isinstance(meta, dict) else None
    return qc if isinstance(qc, dict) else {}


@dataclass
class _Inputs:
    """Lo que `_prepare_inputs` deja en `tmp` y el QC necesita después."""

    mni_brain: np.ndarray  # máscara de la plantilla en su grid
    fixed_voxel_mm3: float
    brain: np.ndarray | None  # brain_mask del paciente en el grid de la imagen móvil
    moving_voxel_mm3: float


def _prepare_inputs(
    study_files: dict[str, Path], moving_seq: str, models_dir: Path, tmp: Path, profile: RegistrationProfile
) -> _Inputs:
    """Escribe en `tmp` la plantilla, la imagen móvil, sus máscaras de costo y el cerebro del paciente."""
    spacing = profile.spacing_mm
    template, template_mask = fetch_template(models_dir)
    if profile.fixed_spacing_mm is not None:
        # Plantilla y máscara a menor resolución: las transformaciones viven en el espacio físico, así que el
        # atlas de 1 mm sigue pudiendo llevarse al paciente con ellas.
        voxel_sizes = (profile.fixed_spacing_mm,) * 3
        template = resample_to_output(template, voxel_sizes=voxel_sizes, order=1)
        template_mask = resample_to_output(template_mask, voxel_sizes=voxel_sizes, order=0)
        assert isinstance(template, nib.Nifti1Image) and isinstance(template_mask, nib.Nifti1Image)
    mni_brain = np.asarray(template_mask.dataobj) > 0
    fixed_np = np.asarray(template.dataobj, dtype=np.float32) * mni_brain
    nib.save(nib.Nifti1Image(fixed_np, template.affine), tmp / "fixed.nii.gz")
    nib.save(nib.Nifti1Image(mni_brain.astype(np.uint8), template.affine), tmp / "fixed_mask.nii.gz")

    moving_img = resample_to_output(load_nifti(study_files[moving_seq]), voxel_sizes=(spacing,) * 3, order=1)
    assert isinstance(moving_img, nib.Nifti1Image)
    moving_np = np.nan_to_num(np.asarray(moving_img.dataobj, dtype=np.float32))
    cost = np.ones(moving_np.shape, bool)
    brain: np.ndarray | None = None
    if "brain_mask" in study_files:
        brain = _mask_on(load_nifti(study_files["brain_mask"]), moving_img)
        moving_np = moving_np * brain
        cost &= brain
        nib.save(nib.Nifti1Image(brain.astype(np.uint8), moving_img.affine), tmp / "moving_brain.nii.gz")
    if "gtv" in study_files:
        gtv = _mask_on(load_nifti(study_files["gtv"]), moving_img)
        if gtv.any():
            # GTV dilatado GTV_MARGIN_MM: todo vóxel a <= 5 mm del GTV queda fuera del costo
            dist = np.asarray(distance_transform_edt(~gtv, sampling=(spacing,) * 3))
            cost &= dist > GTV_MARGIN_MM
    nib.save(nib.Nifti1Image(moving_np, moving_img.affine), tmp / "moving.nii.gz")
    nib.save(nib.Nifti1Image(cost.astype(np.uint8), moving_img.affine), tmp / "moving_mask.nii.gz")
    fixed_voxel_mm3 = float(np.prod(template.header.get_zooms()[:3]))
    return _Inputs(mni_brain, fixed_voxel_mm3, brain, spacing**3)


def _register(
    study_files: dict[str, Path],
    moving_seq: str,
    mni_dir: Path,
    models_dir: Path,
    tmp: Path,
    mode: RegistrationMode = "full",
    while_linear: Callable[[], None] | None = None,
) -> list[str]:
    """Registra paciente → MNI con ANTs y guarda las transformaciones en `mni_dir`. Devuelve `invtransforms`.

    `mode` elige el perfil de `REGISTRATION_PROFILES`: `full` usa SyN y 1.5 mm; `fast`, ver su definición.
    Dos pasos (REG1): afín con 1 hilo en un subproceso (`LinearStage`) y `SyNOnly` multihilo que parte de ella.
    Con `-z 1` ANTs colapsa la afín inicial en `pat2mni_0GenericAffine.mat`, así que la salida tiene la misma forma
    que el "SyN" de un paso (afín + `1Warp`/`1InverseWarp`). `transforms.json` guarda además el QC.
    `while_linear` (opcional) se ejecuta mientras el subproceso calcula la afín (trabajo de un hilo del llamador).
    """
    import ants

    profile = REGISTRATION_PROFILES[mode]
    stage = LinearStage(tmp)  # arranca ya: importa ANTs mientras se preparan las imágenes
    try:
        inputs = _prepare_inputs(study_files, moving_seq, models_dir, tmp, profile)
        # Paso 1: afín reproducible (1 hilo). `moving_mask` (sin GTV) también entra en esta etapa, como hacía
        # `mask_all_stages=True` en el SyN de un paso. Sus archivos quedan en `tmp`: el SyN la colapsa en su salida.
        stage.submit(
            {
                "fixed": str(tmp / "fixed.nii.gz"),
                "moving": str(tmp / "moving.nii.gz"),
                "mask": str(tmp / "fixed_mask.nii.gz"),
                "moving_mask": str(tmp / "moving_mask.nii.gz"),
                "outprefix": str(tmp / "linear_"),
                "random_seed": RANDOM_SEED,
            }
        )
        if while_linear is not None:
            while_linear()
        linear = stage.result()
    finally:
        stage.close()

    # Limpia transformaciones viejas: ANTsPy arma la lista de salida con glob(outprefix + "*")
    if mni_dir.exists():
        shutil.rmtree(mni_dir)
    mni_dir.mkdir(parents=True)
    # Paso 2: SyN multihilo desde la afín (mismos parámetros de SyN que el "SyN" de ANTsPy)
    reg = ants.registration(
        fixed=ants.image_read(str(tmp / "fixed.nii.gz")),
        moving=ants.image_read(str(tmp / "moving.nii.gz")),
        type_of_transform=SYN_STAGE,
        initial_transform=[linear],
        outprefix=str(mni_dir / TX_PREFIX),
        mask=ants.image_read(str(tmp / "fixed_mask.nii.gz")),
        moving_mask=ants.image_read(str(tmp / "moving_mask.nii.gz")),
        mask_all_stages=True,
        random_seed=RANDOM_SEED,
        **profile.extra_kwargs,
    )
    fwd = [str(p) for p in reg["fwdtransforms"]]
    inv = [str(p) for p in reg["invtransforms"]]
    affine_out = next((Path(p) for p in fwd if p.endswith(".mat")), None)
    if affine_out is None or not any("Warp" in Path(p).name for p in fwd):
        raise RuntimeError(f"Transformaciones inesperadas del registro: {[Path(p).name for p in fwd]}")
    qc = _registration_qc(
        affine_out, fwd, tmp, inputs.mni_brain, inputs.fixed_voxel_mm3, inputs.brain, inputs.moving_voxel_mm3
    )
    meta = {
        "key": _cache_key(study_files, moving_seq, mode),
        "moving_sequence": moving_seq,
        "registration_mode": mode,
        "type_of_transform": profile.type_of_transform,
        "registration_version": REGISTRATION_VERSION,
        "fwdtransforms": [Path(p).name for p in fwd],
        "invtransforms": [Path(p).name for p in inv],
        "qc": qc,
    }
    (mni_dir / CACHE_FILE).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return inv


def which_to_invert(invtransforms: list[str]) -> list[bool]:
    """Las afines (`.mat`) se invierten al aplicarlas; los campos `InverseWarp` ya son la inversa."""
    return [p.endswith(".mat") for p in invtransforms]


def map_atlas(
    study_files: dict[str, Path], out_dir: Path, models_dir: Path, mode: RegistrationMode = "full"
) -> AtlasMapping:
    """Registra el estudio a MNI y escribe `out_dir/brodmann.nii.gz` en el grid de la referencia.

    `study_files`: secuencia → ruta NIfTI. Las transformaciones se guardan en `out_dir/mni/` (`mni_fast/` en `fast`)
    y se reutilizan si las entradas y el perfil `mode` no cambiaron. Lanza `ValueError` si no hay T1 para registrar.
    """
    import ants

    reference_seq, moving_seq = select_sequences(study_files)
    prep: dict[str, Any] = {}

    def prepare(tmp: Path) -> None:
        """Avisos de entrada, atlas por hemisferio e imágenes ANTs del remuestreo final.

        Es trabajo de un hilo: en un registro nuevo corre mientras el subproceso calcula la afín.
        """
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
        nib.save(split_img, tmp / "atlas.nii.gz")
        prep.update(
            ref_img=ref_img,
            warnings=warnings,
            brain_ref=brain_ref,
            entries=split_entries,
            ants_ref=ants.image_read(str(study_files[reference_seq])),
            ants_atlas=ants.image_read(str(tmp / "atlas.nii.gz")),
        )

    # Un directorio por modo: `full` conserva `mni/` (y su caché) y alternar modos no se pisa
    mni_dir = out_dir / ("mni" if mode == "full" else f"mni_{mode}")
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cerberus_atlas_") as tmp_str:
        tmp = Path(tmp_str)
        inv = _load_cached(mni_dir, _cache_key(study_files, moving_seq, mode))
        if inv is None:
            inv = _register(study_files, moving_seq, mni_dir, models_dir, tmp, mode, while_linear=lambda: prepare(tmp))
        if not prep:
            prepare(tmp)
        ref_img: nib.Nifti1Image = prep["ref_img"]
        warnings: list[str] = prep["warnings"]
        brain_ref: np.ndarray | None = prep["brain_ref"]
        names: dict[int, tuple[str, Hemisphere]] = {v: (name, hemi) for v, name, hemi in prep["entries"]}
        warnings.extend(registration_warnings(_load_qc(mni_dir)))

        warped = ants.apply_transforms(
            fixed=prep["ants_ref"],
            moving=prep["ants_atlas"],
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
    profile = REGISTRATION_PROFILES[mode]
    registration = f"ANTs {profile.type_of_transform} {moving_seq}→MNI152{excluded}, atlas {ATLAS_NAME}{profile.suffix}"
    return AtlasMapping(
        label_path=label_path,
        entries=entries,
        reference_sequence=reference_seq,
        registration=registration,
        warnings=warnings,
    )
