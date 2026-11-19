"""Preprocesamiento determinista y transformaciones de entrenamiento (docs/PLAN_PIPELINE_FINETUNING.md §5, ticket FT2).

Preparación por estudio (`prepare_study`), a partir de un registro **elegible** del inventario validado:

1. Cada fuente se resuelve bajo `data_root` (identificadores revalidados con `cerberus_api.sequences`), se comprueba
   que su SHA-256 coincide con el del inventario y se carga con `cerberus_api.nifti.load_nifti()`.
2. Referencia T1Gd (`T1c`). Cada canal, la GTV y la máscara cerebral deben ocupar el mismo espacio físico que la
   referencia: las 8 esquinas de su caja de vóxeles (bordes, en mm de mundo) deben coincidir con las de la
   referencia a menos de `GEOMETRY_TOL_MM`. Se aceptan spacing, orientación o flips distintos que cubren la misma
   caja; un FOV distinto, un desplazamiento o una rotación se rechazan (`geometry_mismatch`). El remuestreo **no**
   corrige desregistro y esta comprobación solo ve cabeceras: un desregistro de contenido dentro de la misma caja
   no se puede detectar sin registro.
3. Grid destino ortogonal RAS de `spacing_mm` que contiene la referencia (`nibabel.spaces.vox2out_vox`, el
   mismo criterio que `resample_to_output` en la inferencia de `cerberus_api.segmentation`, portado de
   `cerberus_eda.py:728-775`). Imágenes con interpolación lineal; GTV y máscara cerebral con vecino más próximo
   (`scipy.ndimage.affine_transform`, orden 1 y 0, `mode="grid-constant"`: el exterior del FOV vale 0, pero hasta el
   borde exterior de los vóxeles de borde se interpola/copia el vóxel, sin ceros espurios dentro del casco).
4. Máscara cerebral si existe (se multiplica por cada canal); si falta, soporte = vóxeles no nulos de algún canal
   (política `use_if_present`, registrada como señal `no_brain_mask`). Se recorta a la caja del soporte (nunca de la
   GTV) y cada canal se normaliza sobre sus vóxeles no nulos con `normalize_nonzero` de `cerberus_api.segmentation`.
   La GTV no interviene en la normalización ni en el recorte.

Validaciones (`StudyError` con código estable, ver `PREPARE_ERROR_CODES`): contenido finito, GTV binaria (nunca se
binariza en silencio), máscara cerebral binaria y no vacía y soporte no vacío en cada canal. La GTV **nunca** excluye
un estudio por su posición (eso sesgaría validación/prueba): vóxeles de GTV fuera de la máscara cerebral, fuera del
recorte o perdidos por el remuestreo se cuentan como señales de revisión (`PREPARE_REVIEW_CODES`). FT4 evalúa en el
grid de referencia original, así que esos vóxeles perdidos cuentan allí como falsos negativos. Una GTV vacía existente
se conserva vacía y se señala (`empty_label`).

Entrenamiento: parches `patch_size` con muestreo positivo/negativo según `pos_neg_ratio` (GTV vacía → solo
negativos), flips, rotaciones de 90° y perturbaciones suaves de intensidad, todo con un `numpy.random.Generator`
sembrado. Validación/prueba: volumen completo sin augmentations, con su `Geometry` para restaurar la predicción al
grid original (`restore_to_reference`).
"""

from dataclasses import dataclass, field
from itertools import product
from pathlib import Path
from typing import Any

import numpy as np
from nibabel.spaces import vox2out_vox
from scipy import ndimage

from cerberus_api.nifti import load_nifti
from cerberus_api.segmentation import normalize_nonzero
from cerberus_api.sequences import validate_patient, validate_sequence, validate_timepoint
from cerberus_training.config import CHANNEL_ORDER, ChannelsConfig, PreprocessConfig
from cerberus_training.inventory import DEFAULT_LAYOUT, resolve_under_root, sha256_file

# Versión de las transformaciones deterministas (forma parte de la clave de caché). Súbala ante cualquier cambio que
# altere los volúmenes preparados: geometría, interpolación, recorte, normalización o formato.
TRANSFORMS_VERSION = "ft2-v2"
# Distancia máxima (mm) entre esquinas homólogas de la caja de vóxeles de un archivo y la de la referencia.
# Menor que medio vóxel de 1 mm: absorbe redondeos de cabecera, no desplazamientos reales.
GEOMETRY_TOL_MM = 0.5
MIN_ABS_DET = 1e-6

# Augmentations de entrenamiento (no afectan a la caché; se documentan en docs/TRAINING.md).
FLIP_PROB = 0.5
ROT90_PROB = 0.5
INTENSITY_SCALE = 0.10  # factor multiplicativo en [1 - s, 1 + s] por canal
INTENSITY_SHIFT = 0.10  # desplazamiento aditivo en [-d, d] por canal (datos ya normalizados)

# Códigos de error de `prepare` (estables; no renombrar sin subir TRANSFORMS_VERSION).
PREPARE_ERROR_CODES: dict[str, str] = {
    "not_eligible": "el estudio no es elegible en el inventario",
    "invalid_source": "la ficha del inventario no corresponde a un archivo válido del estudio",
    "source_changed": "el SHA-256 de una fuente no coincide con el inventario",
    "unreadable": "no se pudieron leer los vóxeles o la cabecera",
    "invalid_geometry": "volumen no 3D o affine no invertible",
    "geometry_mismatch": "canal, GTV o máscara no comparte espacio físico con la referencia T1c",
    "non_finite": "contenido con NaN o Inf",
    "non_binary_label": "GTV con valores fuera de {0, 1}",
    "non_binary_mask": "máscara cerebral con valores fuera de {0, 1}",
    "empty_brain_mask": "máscara cerebral sin vóxeles",
    "empty_image": "canal sin vóxeles no nulos dentro del soporte",
}
# Señales de revisión de `prepare`: no impiden usar el estudio.
PREPARE_REVIEW_CODES: dict[str, str] = {
    "empty_label": "la GTV existe y está vacía; se conserva vacía",
    "no_brain_mask": "sin máscara cerebral: soporte = vóxeles no nulos (política use_if_present)",
    "label_outside_brain_mask": "vóxeles de la GTV fuera de la máscara cerebral (se conservan si caen en el recorte)",
    "label_outside_support": "vóxeles de la GTV fuera de la caja del soporte: se pierden del volumen preparado",
    "label_vanished": "la GTV no vacía quedó vacía tras el remuestreo al grid destino",
}


class StudyError(ValueError):
    """Error de preparación de un estudio: excluye solo ese estudio. `code` es una clave de `PREPARE_ERROR_CODES`."""

    def __init__(self, code: str, message: str, channel: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.channel = channel

    def to_json(self) -> dict[str, str]:
        out = {"code": self.code, "message": self.message}
        if self.channel is not None:
            out["channel"] = self.channel
        return out


def _shape3(values: Any) -> tuple[int, int, int]:
    a, b, c = (int(v) for v in values)
    return (a, b, c)


@dataclass(frozen=True)
class Geometry:
    """Metadatos geométricos para restaurar una predicción al grid original de la referencia T1c."""

    reference_shape: tuple[int, int, int]
    reference_affine: np.ndarray
    prepared_shape: tuple[int, int, int]
    prepared_affine: np.ndarray
    spacing_mm: float

    def to_json(self) -> dict[str, Any]:
        return {
            "reference_shape": list(self.reference_shape),
            "reference_affine": self.reference_affine.tolist(),
            "prepared_shape": list(self.prepared_shape),
            "prepared_affine": self.prepared_affine.tolist(),
            "spacing_mm": self.spacing_mm,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Geometry":
        return cls(
            reference_shape=_shape3(data["reference_shape"]),
            reference_affine=np.asarray(data["reference_affine"], dtype=np.float64),
            prepared_shape=_shape3(data["prepared_shape"]),
            prepared_affine=np.asarray(data["prepared_affine"], dtype=np.float64),
            spacing_mm=float(data["spacing_mm"]),
        )


@dataclass
class PreparedStudy:
    """Estudio preparado en el grid destino recortado.

    `image` float32 `[4, X, Y, Z]` en orden `[T1c, T1, T2, FLAIR]`; `label` (GTV) y `brain` (soporte usado) uint8
    `[X, Y, Z]` con valores {0, 1}. `sources`: canal/etiqueta → SHA-256 de la fuente usada.
    """

    study_id: str
    image: np.ndarray
    label: np.ndarray
    brain: np.ndarray
    geometry: Geometry
    brain_mask_source: str  # "brain_mask" o "nonzero_support"
    label_empty: bool
    sources: dict[str, str]
    label_lost_voxels: int = 0  # vóxeles de GTV (grid destino) que quedan fuera del recorte
    review_flags: list[dict[str, Any]] = field(default_factory=list)

    def meta(self) -> dict[str, Any]:
        """Metadatos JSON (sin vóxeles) que acompañan al estudio en la caché."""
        return {
            "study_id": self.study_id,
            "transforms_version": TRANSFORMS_VERSION,
            "channel_order": list(CHANNEL_ORDER),
            "geometry": self.geometry.to_json(),
            "brain_mask_source": self.brain_mask_source,
            "label_empty": self.label_empty,
            "label_voxels": int(np.count_nonzero(self.label)),
            "label_lost_voxels": self.label_lost_voxels,
            "sources": dict(sorted(self.sources.items())),
            "review_flags": self.review_flags,
        }


# ---------------------------------------------------------------------------------------------------------------
# Geometría
# ---------------------------------------------------------------------------------------------------------------


def box_corners(shape: tuple[int, ...], affine: np.ndarray) -> np.ndarray:
    """Las 8 esquinas (mm de mundo) de la caja de vóxeles, por sus bordes (índices -0.5 y n - 0.5)."""
    edges = [(-0.5, n - 0.5) for n in shape[:3]]
    vox = np.array(list(product(*edges)), dtype=np.float64)
    return vox @ affine[:3, :3].T + affine[:3, 3]


def corner_distance(
    shape: tuple[int, ...], affine: np.ndarray, ref_shape: tuple[int, ...], ref_affine: np.ndarray
) -> float:
    """Distancia de Hausdorff (mm) entre las esquinas de dos cajas; 0 si ocupan el mismo espacio físico.

    Es independiente del orden de los ejes: un flip o una permutación que cubre la misma caja da 0.
    """
    a, b = box_corners(shape, affine), box_corners(ref_shape, ref_affine)
    dist = np.linalg.norm(a[:, None, :] - b[None, :, :], axis=-1)
    return float(max(dist.min(axis=1).max(), dist.min(axis=0).max()))


def target_grid(
    ref_shape: tuple[int, ...], ref_affine: np.ndarray, spacing_mm: float
) -> tuple[tuple[int, int, int], np.ndarray]:
    """Grid ortogonal RAS (diagonal positiva) de `spacing_mm` que contiene todos los vóxeles de la referencia."""
    shape, affine = vox2out_vox((tuple(ref_shape[:3]), ref_affine), (spacing_mm,) * 3)
    return _shape3(shape), np.asarray(affine, dtype=np.float64)


def resample(
    data: np.ndarray, src_affine: np.ndarray, out_shape: tuple[int, int, int], out_affine: np.ndarray, order: int
) -> np.ndarray:
    """Remuestrea `data` (grid `src_affine`) al grid (`out_shape`, `out_affine`); fuera del FOV vale 0.

    `order=1` (lineal) para imágenes y `order=0` (vecino más próximo) para etiquetas y máscaras: con orden 0 los
    valores de salida son siempre valores de entrada, así que una máscara binaria sigue siendo binaria.
    """
    vox = np.linalg.inv(src_affine) @ out_affine  # vóxel de salida → vóxel de entrada (homogénea 4×4)
    return ndimage.affine_transform(
        data,
        vox,
        output_shape=out_shape,
        order=order,
        mode="grid-constant",
        cval=0.0,
        prefilter=False,
    )


def restore_to_reference(prepared: np.ndarray, geometry: Geometry, order: int = 0) -> np.ndarray:
    """Lleva un volumen del grid preparado al grid original de la referencia T1c (vecino más próximo por defecto).

    Para una máscara binaria predicha usa `order=0`; para probabilidades puede usarse `order=1` y umbralizar después.
    """
    if tuple(prepared.shape) != geometry.prepared_shape:
        raise ValueError(f"El volumen {prepared.shape} no tiene la forma preparada {geometry.prepared_shape}")
    return resample(prepared, geometry.prepared_affine, geometry.reference_shape, geometry.reference_affine, order)


# ---------------------------------------------------------------------------------------------------------------
# Carga y validación de fuentes
# ---------------------------------------------------------------------------------------------------------------


@dataclass
class _Source:
    data: np.ndarray
    affine: np.ndarray
    shape: tuple[int, int, int]
    sha256: str


def _source_path(root: Path, record: dict[str, Any], entry: Any, channel: str) -> Path:
    """Ruta de una fuente: identificadores revalidados **antes** de construir el `Path` y confinada a la raíz."""
    try:
        if not isinstance(entry, dict):
            raise ValueError("ficha ausente")
        patient = validate_patient(str(record["patient"]))
        timepoint = validate_timepoint(str(record["timepoint"]))
        sequence = validate_sequence(str(entry["sequence"]))
        name = DEFAULT_LAYOUT.file_name(patient, timepoint, sequence)
        if entry.get("path") != f"{patient}/{timepoint}/{name}":
            raise ValueError("la ruta del inventario no sigue la convención del estudio")
        return resolve_under_root(root, patient, timepoint, name)
    except (KeyError, ValueError) as exc:
        raise StudyError("invalid_source", f"Fuente {channel} no válida: {exc}", channel) from exc


def _load_source(root: Path, record: dict[str, Any], entry: Any, channel: str) -> _Source:
    path = _source_path(root, record, entry, channel)
    try:
        digest = sha256_file(path)
    except OSError as exc:
        raise StudyError("unreadable", f"No se pudo leer {channel}: {exc.strerror or exc}", channel) from exc
    if digest != entry.get("sha256"):
        raise StudyError("source_changed", f"{channel}: el archivo cambió desde el inventario (SHA-256)", channel)
    try:
        img = load_nifti(path)
        data = np.asarray(img.dataobj)
        affine = np.asarray(img.affine, dtype=np.float64)
    except Exception as exc:  # nibabel lanza tipos variados ante archivos dañados
        msg = f"No se pudieron leer los vóxeles de {channel}: {type(exc).__name__}"
        raise StudyError("unreadable", msg, channel) from exc
    if data.ndim != 3 or affine.shape != (4, 4) or not bool(np.all(np.isfinite(affine))):
        raise StudyError("invalid_geometry", f"{channel}: se esperaba un volumen 3D con affine finito", channel)
    if abs(float(np.linalg.det(affine[:3, :3]))) < MIN_ABS_DET:
        raise StudyError("invalid_geometry", f"{channel}: affine no invertible", channel)
    if np.issubdtype(data.dtype, np.floating) and not bool(np.all(np.isfinite(data))):
        raise StudyError("non_finite", f"{channel}: contiene NaN o Inf", channel)
    return _Source(data, affine, _shape3(data.shape), digest)


def _check_space(src: _Source, ref: _Source, channel: str) -> None:
    dist = corner_distance(src.shape, src.affine, ref.shape, ref.affine)
    if dist > GEOMETRY_TOL_MM:
        msg = (
            f"{channel} no comparte espacio físico con la referencia T1c (esquinas a {dist:.3f} mm > "
            f"{GEOMETRY_TOL_MM} mm): desregistro, FOV distinto o affine incompatible; requiere registro"
        )
        raise StudyError("geometry_mismatch", msg, channel)


def _binary(src: _Source, channel: str, code: str) -> np.ndarray:
    """Devuelve la máscara como uint8 si solo contiene 0 y 1; si no, `StudyError(code)`. Nunca binariza."""
    values = np.unique(src.data)
    if not bool(np.all(np.isin(values, (0, 1)))):
        shown = ", ".join(f"{float(v):g}" for v in values[:6].tolist())
        more = "…" if values.size > 6 else ""
        raise StudyError(code, f"{channel}: valores fuera de {{0, 1}} ({shown}{more})", channel)
    return src.data.astype(np.uint8)


def _bbox(mask: np.ndarray) -> tuple[slice, slice, slice]:
    """Caja mínima (por eje) que contiene los vóxeles no nulos de `mask` (no vacía)."""
    out: list[slice] = []
    for axis in range(3):
        others = tuple(a for a in range(3) if a != axis)
        idx = np.flatnonzero(mask.any(axis=others))
        out.append(slice(int(idx[0]), int(idx[-1]) + 1))
    return (out[0], out[1], out[2])


# ---------------------------------------------------------------------------------------------------------------
# Preparación de un estudio
# ---------------------------------------------------------------------------------------------------------------


def _flag(code: str, voxels: int | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"code": code, "message": PREPARE_REVIEW_CODES[code]}
    if voxels is not None:
        out["voxels"] = voxels
    return out


def prepare_study(
    record: dict[str, Any],
    data_root: Path,
    preprocess: PreprocessConfig | None = None,
    channels: ChannelsConfig | None = None,
) -> PreparedStudy:
    """Prepara un estudio elegible del inventario (ver docstring del módulo). Lanza `StudyError` si no es usable.

    Un estudio por vez: las fuentes se cargan de una en una y se liberan tras remuestrearlas. Un registro con claves
    ausentes o de tipo inesperado (manipulado) es un `StudyError("invalid_source")`, nunca un `KeyError`.
    """
    try:
        return _prepare(record, data_root, preprocess or PreprocessConfig(), channels or ChannelsConfig())
    except (KeyError, TypeError, AttributeError) as exc:
        msg = f"Registro del inventario incompleto o manipulado ({type(exc).__name__}: {exc})"
        raise StudyError("invalid_source", msg) from exc


def _prepare(
    record: dict[str, Any], data_root: Path, preprocess: PreprocessConfig, channels: ChannelsConfig
) -> PreparedStudy:
    study_id = str(record.get("study_id"))
    if record.get("eligible") is not True:
        raise StudyError("not_eligible", f"{study_id}: el inventario lo excluye")
    root = data_root.resolve()
    spacing = float(preprocess.spacing_mm)
    review: list[dict[str, Any]] = []
    sources: dict[str, str] = {}

    ref_name = channels.reference
    ref = _load_source(root, record, record["channels"][ref_name], ref_name)
    out_shape, out_affine = target_grid(ref.shape, ref.affine, spacing)
    ref_geo = _Source(np.empty(0), ref.affine, ref.shape, ref.sha256)  # solo geometría, sin retener vóxeles

    # GTV primero: validación barata (binaria, finita, mismo espacio) antes de remuestrear las imágenes.
    lab = _load_source(root, record, record["label"], "label")
    _check_space(lab, ref_geo, "label")
    lab_src = _binary(lab, "label", "non_binary_label")
    label_src_voxels = int(np.count_nonzero(lab_src))
    label = resample(lab_src, lab.affine, out_shape, out_affine, order=0).astype(np.uint8)
    sources["label"] = lab.sha256
    del lab, lab_src
    if label_src_voxels == 0:
        review.append(_flag("empty_label"))
    elif not label.any():
        review.append(_flag("label_vanished", label_src_voxels))

    brain: np.ndarray | None = None
    if record.get("brain_mask") is not None:
        bm = _load_source(root, record, record["brain_mask"], "brain_mask")
        _check_space(bm, ref_geo, "brain_mask")
        bm_src = _binary(bm, "brain_mask", "non_binary_mask")
        brain = resample(bm_src, bm.affine, out_shape, out_affine, order=0).astype(bool)
        sources["brain_mask"] = bm.sha256
        del bm, bm_src
        if not brain.any():
            msg = "La máscara cerebral no tiene vóxeles en el grid destino"
            raise StudyError("empty_brain_mask", msg, "brain_mask")
        outside_brain = int(np.count_nonzero(label.astype(bool) & ~brain))
        if outside_brain:
            review.append(_flag("label_outside_brain_mask", outside_brain))

    stack = np.zeros((len(channels.order), *out_shape), dtype=np.float32)
    for i, name in enumerate(channels.order):
        src = ref if name == ref_name else _load_source(root, record, record["channels"][name], name)
        _check_space(src, ref_geo, name)
        stack[i] = resample(src.data.astype(np.float32), src.affine, out_shape, out_affine, order=1)
        sources[name] = src.sha256
        src.data = np.empty(0, dtype=np.float32)  # libera los vóxeles de la fuente (incluida la referencia)
        del src
    del ref
    if brain is not None:
        stack *= brain[None]
        support = brain
        brain_source = "brain_mask"
    else:
        support = np.any(stack != 0, axis=0)
        brain_source = "nonzero_support"
        review.append(_flag("no_brain_mask"))
    for i, name in enumerate(channels.order):
        if not bool(np.any(stack[i] != 0)):
            raise StudyError("empty_image", f"{name}: sin vóxeles no nulos dentro del soporte", name)

    # Recorte a la caja del soporte (imágenes/máscara cerebral, nunca la GTV). La GTV fuera del recorte se cuenta.
    box = _bbox(support)
    lost = int(np.count_nonzero(label)) - int(np.count_nonzero(label[box]))
    if lost:
        review.append(_flag("label_outside_support", lost))
    start = np.array([s.start for s in box], dtype=np.float64)
    prepared_affine = out_affine.copy()
    prepared_affine[:3, 3] = out_affine[:3, :3] @ start + out_affine[:3, 3]
    image = normalize_nonzero(stack[(slice(None), *box)])
    del stack
    label = np.ascontiguousarray(label[box])
    brain_out = np.ascontiguousarray(support[box].astype(np.uint8))
    if not bool(np.all(np.isfinite(image))):  # salvaguarda: no debería ocurrir con fuentes finitas
        raise StudyError("non_finite", "El volumen preparado contiene NaN o Inf")

    label_empty = not bool(label.any())
    geometry = Geometry(
        reference_shape=ref_geo.shape,
        reference_affine=ref_geo.affine,
        prepared_shape=_shape3(label.shape),
        prepared_affine=prepared_affine,
        spacing_mm=spacing,
    )
    return PreparedStudy(
        study_id=study_id,
        image=np.ascontiguousarray(image, dtype=np.float32),
        label=label,
        brain=brain_out,
        geometry=geometry,
        brain_mask_source=brain_source,
        label_empty=label_empty,
        sources=sources,
        label_lost_voxels=lost,
        review_flags=review,
    )


# ---------------------------------------------------------------------------------------------------------------
# Evaluación (FT4): fuentes verificadas y GTV original en el grid de referencia
# ---------------------------------------------------------------------------------------------------------------

# Tolerancia (mm en el affine) para considerar que la GTV ya está en el grid de la referencia T1c.
SAME_GRID_ATOL_MM = 1e-4
# Tolerancia relativa para aceptar los ejes del grid de referencia como ortogonales (HD95 usa spacing por eje).
ORTHOGONAL_RTOL = 1e-4


def verified_source_path(data_root: Path, record: dict[str, Any], entry: Any, channel: str) -> Path:
    """Ruta de una fuente del inventario con identificadores revalidados, confinada a la raíz y SHA-256 verificado.

    Lanza `StudyError` (`invalid_source`, `unreadable` o `source_changed`). La usa el baseline de FT4 para pasar
    archivos al pipeline original de `cerberus_api.segmentation`.
    """
    path = _source_path(data_root.resolve(), record, entry, channel)
    try:
        digest = sha256_file(path)
    except OSError as exc:
        raise StudyError("unreadable", f"No se pudo leer {channel}: {exc.strerror or exc}", channel) from exc
    if digest != entry.get("sha256"):
        raise StudyError("source_changed", f"{channel}: el archivo cambió desde el inventario (SHA-256)", channel)
    return path


def reference_spacing(geometry: Geometry) -> tuple[float, float, float]:
    """Spacing (mm) por eje de vóxel del grid de referencia; exige ejes ortogonales (sin cizalla).

    `mask_metrics` calcula HD95 con una transformada de distancia de spacing por eje, válida en grids ortogonales,
    también si están rotados (oblicuos). Con cizalla lanza `ValueError` en lugar de dar distancias erróneas.
    """
    m = geometry.reference_affine[:3, :3]
    gram = m.T @ m
    norms = np.sqrt(np.diag(gram))
    off = gram - np.diag(np.diag(gram))
    if float(np.abs(off).max()) > ORTHOGONAL_RTOL * float(norms.max()) ** 2:
        raise ValueError("El grid de referencia tiene ejes no ortogonales (cizalla): HD95 no sería válido")
    return (float(norms[0]), float(norms[1]), float(norms[2]))


def reference_label(record: dict[str, Any], data_root: Path, geometry: Geometry) -> tuple[np.ndarray, bool]:
    """GTV **original** (fuente del dataset) en el grid de referencia de la T1c, para evaluar (FT4).

    La fuente se reconstruye con identificadores revalidados, se confina a `data_root`, se verifica su SHA-256
    contra el inventario y debe ocupar el mismo espacio físico que la referencia y ser binaria (nunca se binariza).
    Si la GTV ya está en el grid de la T1c (mismo shape y affine), se usa tal cual (`False`); si no (otro spacing,
    orden de ejes o flips sobre la misma caja), se lleva al grid de la T1c con vecino más próximo (`True`). La GTV
    nunca pasa por el recorte ni el grid preparado: lo que la predicción pierda fuera del soporte cuenta como FN.
    """
    try:
        lab = _load_source(data_root.resolve(), record, record["label"], "label")
    except (KeyError, TypeError, AttributeError) as exc:
        raise StudyError("invalid_source", f"Registro sin GTV válida ({type(exc).__name__}: {exc})") from exc
    ref_geo = _Source(np.empty(0), geometry.reference_affine, geometry.reference_shape, "")
    _check_space(lab, ref_geo, "label")
    data = _binary(lab, "label", "non_binary_label")
    same = lab.shape == geometry.reference_shape and bool(
        np.allclose(lab.affine, geometry.reference_affine, rtol=0.0, atol=SAME_GRID_ATOL_MM)
    )
    if same:
        return data, False
    out = resample(data, lab.affine, geometry.reference_shape, geometry.reference_affine, order=0)
    return out.astype(np.uint8), True


def study_sources(record: dict[str, Any], channels: ChannelsConfig | None = None) -> dict[str, str]:
    """SHA-256 esperados (del inventario) de las fuentes que usa `prepare_study` para este registro."""
    channels = channels or ChannelsConfig()
    out = {name: str(record["channels"][name]["sha256"]) for name in channels.order}
    out["label"] = str(record["label"]["sha256"])
    if record.get("brain_mask") is not None:
        out["brain_mask"] = str(record["brain_mask"]["sha256"])
    return dict(sorted(out.items()))


# ---------------------------------------------------------------------------------------------------------------
# Entrenamiento: parches y augmentations sembrados
# ---------------------------------------------------------------------------------------------------------------


def make_rng(seed: int, epoch: int, index: int) -> np.random.Generator:
    """Generador reproducible por (semilla, época, índice de muestra), independiente del orden de ejecución."""
    return np.random.default_rng((seed, epoch, index))


@dataclass(frozen=True)
class Patch:
    image: np.ndarray  # float32 [4, *patch_size]
    label: np.ndarray  # uint8 [*patch_size]
    brain: np.ndarray  # uint8 [*patch_size]
    positive: bool  # centro tomado de la GTV
    start: tuple[int, int, int]  # esquina en el volumen (tras el relleno, si lo hubo)


def _pad_to(arr: np.ndarray, size: tuple[int, int, int]) -> np.ndarray:
    spatial = arr.shape[-3:]
    pad = [max(0, s - n) for s, n in zip(size, spatial, strict=True)]
    if not any(pad):
        return arr
    widths = [(0, 0)] * (arr.ndim - 3) + [(0, p) for p in pad]
    return np.pad(arr, widths, mode="constant", constant_values=0)


def sample_patch(
    study: PreparedStudy, patch_size: tuple[int, int, int], pos_neg_ratio: tuple[int, int], rng: np.random.Generator
) -> Patch:
    """Recorta un parche: positivo (centro en la GTV) con probabilidad `pos/(pos+neg)`, si no negativo.

    Negativo = **centro** en el soporte cerebral fuera de la GTV (el parche puede contener GTV en su periferia).
    Con GTV vacía todos los parches son negativos. Si el volumen es menor que el parche en algún eje, se rellena
    con ceros al final de ese eje.
    """
    image, label, brain = (_pad_to(a, patch_size) for a in (study.image, study.label, study.brain))
    pos, neg = pos_neg_ratio
    want_positive = bool(rng.random() < pos / (pos + neg))
    positive = want_positive and bool(label.any())
    if positive:
        candidates = np.flatnonzero(label)
    else:
        candidates = np.flatnonzero((brain != 0) & (label == 0))
        if candidates.size == 0:
            candidates = np.flatnonzero(label == 0)
        if candidates.size == 0:  # volumen entero de GTV: solo quedan centros positivos
            candidates, positive = np.flatnonzero(label), True
    center = np.unravel_index(int(candidates[int(rng.integers(candidates.size))]), label.shape)
    start = _shape3(
        min(max(int(c) - p // 2, 0), n - p) for c, p, n in zip(center, patch_size, label.shape, strict=True)
    )
    box = tuple(slice(s, s + p) for s, p in zip(start, patch_size, strict=True))
    return Patch(
        image=np.ascontiguousarray(image[(slice(None), *box)]),
        label=np.ascontiguousarray(label[box]),
        brain=np.ascontiguousarray(brain[box]),
        positive=positive,
        start=start,
    )


def augment(
    image: np.ndarray, label: np.ndarray, rng: np.random.Generator, support: np.ndarray | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Augmentations de entrenamiento (nunca en validación/prueba), deterministas para un mismo `rng`.

    1. Intensidad por canal: `x·a + b` con `a ∈ [1 - INTENSITY_SCALE, 1 + INTENSITY_SCALE]` y
       `b ∈ [-INTENSITY_SHIFT, INTENSITY_SHIFT]`, solo dentro de `support` (o de los vóxeles no nulos del canal).
    2. Flip por eje con probabilidad `FLIP_PROB`.
    3. Rotación de 90°·k (k ∈ 1..3) con probabilidad `ROT90_PROB` en un plano cuyos dos lados son iguales.
    La GTV recibe exactamente las mismas transformaciones geométricas y sigue siendo binaria.
    """
    img = image.astype(np.float32, copy=True)
    lab = label.copy()
    for c in range(img.shape[0]):
        a = 1.0 + float(rng.uniform(-INTENSITY_SCALE, INTENSITY_SCALE))
        b = float(rng.uniform(-INTENSITY_SHIFT, INTENSITY_SHIFT))
        region = support.astype(bool) if support is not None else img[c] != 0
        img[c][region] = img[c][region] * a + b
    for axis in range(3):
        if rng.random() < FLIP_PROB:
            img = np.flip(img, axis=axis + 1)
            lab = np.flip(lab, axis=axis)
    planes = [(i, j) for i, j in ((0, 1), (0, 2), (1, 2)) if lab.shape[i] == lab.shape[j]]
    if planes and rng.random() < ROT90_PROB:
        i, j = planes[int(rng.integers(len(planes)))]
        k = int(rng.integers(1, 4))
        img = np.rot90(img, k, axes=(i + 1, j + 1))
        lab = np.rot90(lab, k, axes=(i, j))
    return np.ascontiguousarray(img, dtype=np.float32), np.ascontiguousarray(lab)


def train_sample(
    study: PreparedStudy, preprocess: PreprocessConfig, rng: np.random.Generator
) -> tuple[np.ndarray, np.ndarray]:
    """Muestra de entrenamiento: parche + augmentations, ambos con el mismo generador sembrado."""
    patch = sample_patch(study, preprocess.patch_size, preprocess.pos_neg_ratio, rng)
    return augment(patch.image, patch.label, rng, patch.brain)


def eval_sample(study: PreparedStudy) -> tuple[np.ndarray, np.ndarray, Geometry]:
    """Validación/prueba/inferencia: volumen completo sin augmentations ni recortes por GTV, con su geometría.

    La ventana deslizante sobre este volumen corresponde a FT3/FT4.
    """
    return study.image, study.label, study.geometry
