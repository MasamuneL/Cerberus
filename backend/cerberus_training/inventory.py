"""Inventario de solo lectura del dataset CFB-GBM externo (docs/PLAN_PIPELINE_FINETUNING.md §3 y §4, ticket FT1).

Recorre `data_root` estudio por estudio. La **validación** usa solo cabeceras NIfTI (`load_nifti` es perezoso: la
matriz de vóxeles queda en un `ArrayProxy` sin tocar). Dos lecturas completas, ambas en streaming y sin cargar la
colección en memoria:

- El SHA-256 de cada archivo seleccionado (canales, GTV y máscara cerebral) recorre todos sus bytes en bloques de
  1 MiB, para detectar duplicados exactos.
- La GTV se decodifica entera para saber si está vacía: una máscara vacía existente debe conservarse y marcarse
  para revisión (§4.2), y eso no se puede saber por la cabecera. Las imágenes nunca se decodifican.

Seguridad de rutas (AGENTS.md, regla 9): cada nombre de carpeta pasa por `cerberus_api.sequences` antes de
construir cualquier `Path`; los nombres de archivo se construyen a partir de identificadores ya validados, y cada
ruta se resuelve (siguiendo symlinks) y debe quedar bajo la raíz autorizada. Entre la primera y la última
apertura de un archivo se comprueba que su identidad, tamaño y `mtime_ns` no cambien.

Privacidad: el manifest no guarda datos clínicos ni DICOM; el paciente es el ID seudónimo de carpeta y las rutas
son relativas a `data_root`. Las carpetas rechazadas nunca se emiten por su nombre (podría contener un nombre real):
solo nivel, código y los 8 primeros hex del SHA-256 del nombre.
"""

import hashlib
import json
import math
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np
from nibabel.openers import ImageOpener

from cerberus_api.nifti import load_nifti
from cerberus_api.sequences import validate_patient, validate_sequence, validate_timepoint
from cerberus_training.config import CHANNEL_ORDER, ChannelsConfig
from cerberus_training.manifest import (
    INVENTORY_SCHEMA_VERSION,
    InventoryError,
    atomic_write_text,
    duplicate_groups,
    ensure_distinct,
    ensure_outside_root,
    read_inventory,
    write_inventory,
)

__all__ = [
    "INVENTORY_SCHEMA_VERSION",
    "InventoryError",
    "atomic_write_text",
    "duplicate_groups",
    "ensure_distinct",
    "ensure_outside_root",
    "read_inventory",
    "write_inventory",
]

LABEL_SEQUENCE = "gtv"
BRAIN_MASK_SEQUENCE = "brain_mask"
T2STAR_SEQUENCE = "t2star"
HASH_CHUNK = 1 << 20  # 1 MiB por lectura al calcular SHA-256
# |det| por debajo de esto se considera singular (affines en mm: un vóxel de 1e-6 mm³ ya sería absurdo).
MIN_ABS_DET = 1e-6
# Tolerancia relativa entre pixdim y la norma de cada columna de affine[:3, :3].
SPACING_RTOL = 1e-3

# Códigos de exclusión estables (se cuentan en el resumen; no renombrar sin subir INVENTORY_SCHEMA_VERSION).
EXCLUSION_CODES: dict[str, str] = {
    "missing_channel": "falta un canal obligatorio del perfil estricto",
    "missing_label": "falta la máscara GTV",
    "path_outside_root": "la ruta resuelve fuera de la raíz autorizada",
    "not_a_file": "la ruta no es un archivo regular",
    "unreadable": "archivo o carpeta ilegible, NIfTI-2 o no NIfTI-1, o modificado durante el inventario",
    "not_3d": "el volumen no es 3D",
    "invalid_shape": "dimensiones no positivas",
    "invalid_affine": "affine no finito o no invertible",
    "invalid_spacing": "spacing no finito o no positivo",
    "spacing_affine_mismatch": "pixdim no coincide con las normas de columna del affine",
}
# Señales de revisión: no excluyen el estudio, pero deben revisarse antes de entrenar.
REVIEW_CODES: dict[str, str] = {
    "empty_label": "la máscara GTV existe pero está vacía",
    "invalid_brain_mask": "la máscara cerebral existe pero no es válida; se ignora",
    "duplicate_within_study": "dos archivos del estudio tienen contenido idéntico",
}
# Códigos de entradas de la raíz que no llegan a ser estudios.
REJECTION_CODES: dict[str, str] = {
    "invalid_identifier": "nombre de carpeta que no es un paciente o tiempo válido",
    "path_outside_root": "carpeta que resuelve fuera de la raíz autorizada",
    "unreadable": "carpeta que no se pudo listar",
}

_FILE_RE = re.compile(r"(\d+)_(t\d{1,2})_([a-z0-9_]+)\.nii\.gz", re.ASCII)


@dataclass(frozen=True)
class CerberusLayout:
    """Adaptador de la convención de nombres del dataset, la misma que usa la API (`cerberus_api.catalog`).

    `<data_root>/<paciente>/<tiempo>/<int(paciente)>_<tiempo>_<secuencia>.nii.gz`, por ejemplo
    `001/t0/1_t0_flair.nii.gz`: paciente de 3 dígitos, tiempo `t` + 1-2 dígitos y prefijo numérico sin ceros a
    la izquierda. Si la descarga de TCIA usa otra estructura, se escribe otro adaptador con la misma interfaz
    (`name`, `file_name`, `parse_file`) en lugar de relajar los validadores de la API.
    """

    name: str = "cerberus_v1"

    def file_name(self, patient: str, timepoint: str, sequence: str) -> str:
        """Nombre de archivo esperado; los tres identificadores deben venir ya validados."""
        return f"{int(patient)}_{timepoint}_{sequence}.nii.gz"

    def parse_file(self, patient: str, timepoint: str, name: str) -> str | None:
        """Secuencia de `name` si cumple la convención de su carpeta; si no, `None`."""
        m = _FILE_RE.fullmatch(name)
        if m is None or int(m.group(1)) != int(patient) or m.group(2) != timepoint:
            return None
        try:
            return validate_sequence(m.group(3))
        except ValueError:
            return None


DEFAULT_LAYOUT = CerberusLayout()


@dataclass
class _Issue:
    code: str
    message: str
    channel: str | None = None

    def to_json(self) -> dict[str, str]:
        out = {"code": self.code, "message": self.message}
        if self.channel is not None:
            out["channel"] = self.channel
        return out


def name_digest(name: str) -> str:
    """Huella corta del nombre de una carpeta rechazada: permite localizarla sin publicar el nombre."""
    return hashlib.sha256(name.encode("utf-8", "surrogateescape")).hexdigest()[:8]


@dataclass
class Rejected:
    """Carpeta de la raíz que no es un estudio. Nunca guarda el nombre en bruto (podría identificar a alguien).

    `level` es `patient` o `timepoint`; `patient` es el ID ya validado de la carpeta padre (solo para `timepoint`).
    """

    level: str
    code: str
    name_sha8: str
    message: str
    patient: str | None = None

    def to_json(self) -> dict[str, str]:
        out = {"level": self.level, "code": self.code, "name_sha8": self.name_sha8, "message": self.message}
        if self.patient is not None:
            out["patient"] = self.patient
        return out


@dataclass
class InventoryResult:
    """Registros por estudio más lo que se descartó antes de llegar a ser estudio."""

    records: list[dict[str, Any]]
    rejected: list[Rejected] = field(default_factory=list)
    ignored_entries: int = 0


def sha256_file(path: Path) -> str:
    """SHA-256 del contenido del archivo, leído en bloques de 1 MiB (nunca entero en memoria)."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_under_root(root: Path, *parts: str) -> Path:
    """Resuelve `root/parts…` siguiendo symlinks y exige que el resultado quede bajo `root` (ya resuelta).

    Lanza `ValueError` si alguna parte está vacía, es `.`/`..` o contiene separadores, o si la ruta resuelta
    (p. ej. vía un symlink) escapa de la raíz. No exige que exista.
    """
    for part in parts:
        if not part or part in (".", "..") or "/" in part or "\\" in part or "\0" in part:
            raise ValueError(f"Componente de ruta no permitido: {part!r}")
    try:
        resolved = root.joinpath(*parts).resolve()
    except (OSError, RuntimeError) as exc:  # bucle de symlinks
        raise ValueError(f"No se pudo resolver la ruta {'/'.join(parts)}") from exc
    if resolved != root and not resolved.is_relative_to(root):
        raise ValueError(f"La ruta {'/'.join(parts)} resuelve fuera de la raíz autorizada")
    return resolved


def study_dir(root: Path, patient: str, timepoint: str) -> Path:
    """Carpeta de un estudio: valida los identificadores **antes** de construir el `Path` y la confina a `root`."""
    validate_patient(patient)
    validate_timepoint(timepoint)
    return resolve_under_root(root, patient, timepoint)


def timepoint_index(timepoint: str) -> int:
    """Número del tiempo (`t0` → 0, `t10` → 10), para ordenar numéricamente."""
    return int(validate_timepoint(timepoint)[1:])


def stratum(timepoint: str) -> str:
    """Estrato descriptivo: `t0` es la línea base; el resto, seguimiento."""
    return "baseline" if timepoint_index(timepoint) == 0 else "follow_up"


def _signature(path: Path) -> tuple[int, int, int, int]:
    st = path.stat()
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)


def _raw_pixdim(path: Path) -> tuple[float, ...]:
    """`pixdim[1:4]` tal como está en el archivo.

    `nib.load` "repara" la cabecera al leerla (spacing 0 → 1, negativo → valor absoluto, solo con un aviso en el
    log); aquí se relee sin `check` para no aceptar en silencio un spacing no positivo.
    """
    with ImageOpener(str(path)) as handle:
        raw = nib.Nifti1Header.from_fileobj(handle, check=False)
    return tuple(float(v) for v in raw["pixdim"][1:4])


def _inspect_header(path: Path, channel: str | None) -> tuple[dict[str, Any] | None, list[_Issue]]:
    """Lee la cabecera de un NIfTI-1 y comprueba 3D, shape, affine, spacing y su coherencia. No toca los vóxeles."""
    try:
        img = load_nifti(path)
        if isinstance(img, nib.Nifti2Image):  # subclase de Nifti1Image: load_nifti la aceptaría
            return None, [_Issue("unreadable", "NIfTI-2 no soportado (se espera NIfTI-1)", channel)]
        hdr = img.header
        shape = tuple(int(s) for s in hdr.get_data_shape())
        affine = np.asarray(img.affine, dtype=np.float64)
        dtype = str(hdr.get_data_dtype())
        spacing = _raw_pixdim(path)
    except Exception as exc:  # nibabel lanza tipos variados ante archivos dañados
        return None, [_Issue("unreadable", f"No se pudo leer la cabecera NIfTI-1: {type(exc).__name__}", channel)]

    issues: list[_Issue] = []
    if len(shape) != 3:
        issues.append(_Issue("not_3d", f"Se esperaba un volumen 3D y tiene {len(shape)} dimensiones {shape}", channel))
    elif any(s <= 0 for s in shape):
        issues.append(_Issue("invalid_shape", f"Dimensiones no positivas: {shape}", channel))
    spacing_ok = len(spacing) == 3 and all(math.isfinite(z) and z > 0 for z in spacing)
    if not spacing_ok:
        issues.append(_Issue("invalid_spacing", f"Spacing no finito o no positivo: {spacing}", channel))
    affine_ok = affine.shape == (4, 4) and bool(np.all(np.isfinite(affine)))
    if not affine_ok:
        issues.append(_Issue("invalid_affine", "El affine contiene valores no finitos", channel))
    elif abs(float(np.linalg.det(affine[:3, :3]))) < MIN_ABS_DET:
        affine_ok = False
        issues.append(_Issue("invalid_affine", "El affine no es invertible (determinante ~0)", channel))
    if spacing_ok and affine_ok:
        # Estricto a propósito: el remuestreo de FT2 no debe adivinar cuál de las dos geometrías es la buena.
        norms = np.linalg.norm(affine[:3, :3], axis=0)
        if not np.allclose(norms, spacing, rtol=SPACING_RTOL, atol=0.0):
            msg = f"pixdim {spacing} no coincide con las normas de columna del affine {tuple(norms.round(6).tolist())}"
            issues.append(_Issue("spacing_affine_mismatch", msg, channel))
    if issues:
        return None, issues

    info: dict[str, Any] = {
        "shape": list(shape),
        "spacing_mm": [round(z, 6) for z in spacing],
        "affine": [[round(float(v), 6) for v in row] for row in affine.tolist()],
        "dtype": dtype,
    }
    return info, []


@dataclass
class _FileCheck:
    info: dict[str, Any] | None
    issues: list[_Issue]
    resolved: Path | None = None
    signature: tuple[int, int, int, int] | None = None


def _changed(channel: str | None) -> _Issue:
    return _Issue("unreadable", "El archivo cambió durante el inventario", channel)


def _inspect_file(
    root: Path, patient: str, timepoint: str, sequence: str, channel: str | None, layout: CerberusLayout
) -> _FileCheck:
    """Resuelve y valida un archivo del estudio: ruta relativa, cabecera y sha256, o los problemas encontrados."""
    name = layout.file_name(patient, timepoint, sequence)
    try:
        resolved = resolve_under_root(root, patient, timepoint, name)
    except ValueError as exc:
        return _FileCheck(None, [_Issue("path_outside_root", str(exc), channel)])
    if not resolved.is_file():
        return _FileCheck(
            None, [_Issue("not_a_file", f"{patient}/{timepoint}/{name} no es un archivo regular", channel)]
        )
    try:
        before = _signature(resolved)
        info, issues = _inspect_header(resolved, channel)
        if info is None:
            return _FileCheck(None, issues)
        digest = sha256_file(resolved)
        if _signature(resolved) != before:
            return _FileCheck(None, [_changed(channel)])
    except OSError as exc:
        return _FileCheck(None, [_Issue("unreadable", f"No se pudo leer el archivo: {exc.strerror or exc}", channel)])
    info = {"sequence": sequence, "path": f"{patient}/{timepoint}/{name}", **info, "sha256": digest}
    return _FileCheck(info, [], resolved, before)


def _label_voxels(check: _FileCheck) -> int:
    """Vóxeles no nulos de la GTV, leída por la ruta ya resuelta y validada (única decodificación de vóxeles).

    Lanza `OSError` si el archivo cambió desde que se validó su cabecera y se calculó su hash.
    """
    assert check.resolved is not None and check.signature is not None
    img = load_nifti(check.resolved)
    nonzero = int(np.count_nonzero(np.asanyarray(img.dataobj)))
    if _signature(check.resolved) != check.signature:
        raise OSError("El archivo cambió durante el inventario")
    return nonzero


def _list_sequences(directory: Path, patient: str, timepoint: str, layout: CerberusLayout) -> tuple[set[str], int]:
    """Secuencias reconocidas (solo archivos) en la carpeta del estudio y número de entradas no reconocidas."""
    found: set[str] = set()
    unrecognized = 0
    with os.scandir(directory) as it:
        for entry in it:
            if entry.name.startswith("."):
                continue
            seq = layout.parse_file(patient, timepoint, entry.name)
            if seq is None or not entry.is_file(follow_symlinks=True):
                unrecognized += 1
            else:
                found.add(seq)
    return found, unrecognized


def _record(
    patient: str,
    timepoint: str,
    layout: CerberusLayout,
    available: set[str],
    unrecognized: int,
    selected: dict[str, dict[str, Any] | None],
    label: dict[str, Any] | None,
    brain_mask: dict[str, Any] | None,
    exclusions: list[_Issue],
    review: list[_Issue],
) -> dict[str, Any]:
    return {
        "schema_version": INVENTORY_SCHEMA_VERSION,
        "study_id": f"{patient}_{timepoint}",
        "patient": patient,
        "timepoint": timepoint,
        "timepoint_index": timepoint_index(timepoint),
        "stratum": stratum(timepoint),
        "layout": layout.name,
        "available_sequences": sorted(available),
        "unrecognized_files": unrecognized,
        "channels": selected,
        "selected_sequences": {c: (info["sequence"] if info else None) for c, info in selected.items()},
        "label": label,
        "brain_mask": brain_mask,
        "eligible": not exclusions,
        "exclusions": [i.to_json() for i in exclusions],
        "review_flags": [i.to_json() for i in review],
    }


def inspect_study(
    root: Path,
    patient: str,
    timepoint: str,
    channels: ChannelsConfig | None = None,
    layout: CerberusLayout = DEFAULT_LAYOUT,
) -> dict[str, Any]:
    """Construye el registro de inventario de un estudio (paciente, tiempo).

    `root` debe estar resuelta. Selección de canales del perfil estricto: por canal se toma la **primera**
    secuencia presente en el orden de preferencia (T1: `t1eg` y luego `t1tse`); si ese archivo es inválido, el
    estudio se excluye en lugar de saltar en silencio a la siguiente preferencia. T2* nunca sustituye a T2.
    Una carpeta que no se puede listar produce un registro excluido (`unreadable`), sin abortar el inventario.
    """
    channels = channels or ChannelsConfig()
    directory = study_dir(root, patient, timepoint)
    empty_selection: dict[str, dict[str, Any] | None] = dict.fromkeys(CHANNEL_ORDER)
    try:
        available, unrecognized = _list_sequences(directory, patient, timepoint, layout)
    except OSError as exc:
        issue = _Issue("unreadable", f"No se pudo listar la carpeta del estudio: {exc.strerror or type(exc).__name__}")
        return _record(patient, timepoint, layout, set(), 0, empty_selection, None, None, [issue], [])
    exclusions: list[_Issue] = []
    review: list[_Issue] = []

    selected: dict[str, dict[str, Any] | None] = {}
    for channel in CHANNEL_ORDER:
        candidates = channels.preferences[channel]
        seq = next((s for s in candidates if s in available), None)
        if seq is None:
            msg = f"Canal {channel}: no hay ninguna de {list(candidates)}"
            if channel == "T2" and T2STAR_SEQUENCE in available:
                msg += "; hay T2*, pero no sustituye a T2 en el perfil estricto"
            exclusions.append(_Issue("missing_channel", msg, channel))
            selected[channel] = None
            continue
        check = _inspect_file(root, patient, timepoint, seq, channel, layout)
        exclusions.extend(check.issues)
        selected[channel] = check.info

    label: dict[str, Any] | None = None
    if LABEL_SEQUENCE not in available:
        # Nunca se sustituye por una máscara vacía: sin GTV no hay etiqueta.
        exclusions.append(_Issue("missing_label", "No existe la máscara GTV del estudio", "label"))
    else:
        check = _inspect_file(root, patient, timepoint, LABEL_SEQUENCE, "label", layout)
        issues = check.issues
        if check.info is not None:
            try:
                nonzero = _label_voxels(check)
            except Exception as exc:  # gzip truncado, datos insuficientes, archivo modificado…
                reason = str(exc) if isinstance(exc, OSError) else type(exc).__name__
                msg = f"No se pudieron leer los vóxeles de la GTV: {reason}"
                issues = [_Issue("unreadable", msg, "label")]
            else:
                label = {**check.info, "name": channels.label, "nonzero_voxels": nonzero, "empty": nonzero == 0}
                if nonzero == 0:
                    review.append(_Issue("empty_label", "La GTV existe pero no tiene vóxeles; requiere revisión"))
        exclusions.extend(issues)

    brain_mask: dict[str, Any] | None = None
    if BRAIN_MASK_SEQUENCE in available:
        check = _inspect_file(root, patient, timepoint, BRAIN_MASK_SEQUENCE, "brain_mask", layout)
        brain_mask = check.info
        if check.issues:
            detail = "; ".join(i.message for i in check.issues)
            review.append(_Issue("invalid_brain_mask", f"Máscara cerebral ignorada: {detail}", "brain_mask"))

    files = [f for f in (*selected.values(), label, brain_mask) if f is not None]
    if len({f["sha256"] for f in files}) != len(files):
        review.append(_Issue("duplicate_within_study", "Hay archivos con contenido idéntico dentro del estudio"))

    return _record(patient, timepoint, layout, available, unrecognized, selected, label, brain_mask, exclusions, review)


def _subdirs(
    directory: Path, root: Path, level: str, result: InventoryResult, patient: str | None = None
) -> list[str] | None:
    """Nombres de subcarpetas (ordenados) que no escapan de la raíz; el resto se cuenta o se rechaza.

    Devuelve `None` si `directory` no se puede listar (el llamador decide si eso aborta o se registra).
    """
    try:
        with os.scandir(directory) as it:
            entries = sorted(it, key=lambda e: e.name)
    except OSError:
        return None
    names: list[str] = []
    for entry in entries:
        if entry.name.startswith("."):
            continue
        if not entry.is_dir(follow_symlinks=True):
            result.ignored_entries += 1
            continue
        try:
            inside = Path(entry.path).resolve().is_relative_to(root)
        except (OSError, RuntimeError):
            inside = False
        if not inside:
            msg = "La carpeta resuelve fuera de la raíz autorizada"
            result.rejected.append(Rejected(level, "path_outside_root", name_digest(entry.name), msg, patient))
            continue
        names.append(entry.name)
    return names


def build_inventory(
    data_root: Path, channels: ChannelsConfig | None = None, layout: CerberusLayout = DEFAULT_LAYOUT
) -> InventoryResult:
    """Recorre `data_root` (solo lectura) y devuelve un registro por estudio, ordenado por (paciente, tiempo).

    Las carpetas con identificadores inválidos no se convierten en estudios: se listan en `rejected` (código
    `invalid_identifier`, sin el nombre). Una carpeta de paciente ilegible se rechaza (`unreadable`) y una de estudio
    ilegible produce un registro excluido; solo una raíz ilegible aborta. Archivos sueltos y entradas ocultas se
    ignoran (se cuentan).
    """
    if not data_root.is_dir():
        raise InventoryError(f"La raíz del dataset no existe o no es una carpeta: {data_root}")
    root = data_root.resolve()
    result = InventoryResult(records=[])
    patients = _subdirs(root, root, "patient", result)
    if patients is None:
        raise InventoryError(f"No se pudo listar la raíz del dataset: {root}")
    for patient in patients:
        try:
            validate_patient(patient)
        except ValueError:
            msg = "Paciente inválido (se esperan 3 dígitos)"
            result.rejected.append(Rejected("patient", "invalid_identifier", name_digest(patient), msg))
            continue
        tps = _subdirs(root / patient, root, "timepoint", result, patient)
        if tps is None:
            msg = "No se pudo listar la carpeta del paciente"
            result.rejected.append(Rejected("patient", "unreadable", name_digest(patient), msg, patient))
            continue
        timepoints: list[str] = []
        for tp in tps:
            try:
                validate_timepoint(tp)
            except ValueError:
                msg = "Tiempo inválido (se espera t + 1-2 dígitos)"
                result.rejected.append(Rejected("timepoint", "invalid_identifier", name_digest(tp), msg, patient))
                continue
            timepoints.append(tp)
        for tp in sorted(timepoints, key=timepoint_index):
            result.records.append(inspect_study(root, patient, tp, channels, layout))
    return result


def summarize(result: InventoryResult) -> dict[str, Any]:
    """Resumen por paciente/tiempo: conteos, motivos de exclusión, estratos, canales elegidos y duplicados."""
    records = result.records
    exclusion_counts: Counter[str] = Counter()
    review_counts: Counter[str] = Counter()
    strata: dict[str, Counter[str]] = {}
    selection: dict[str, Counter[str]] = {c: Counter() for c in CHANNEL_ORDER}
    per_patient: dict[str, dict[str, Any]] = {}
    for r in records:
        codes = sorted({e["code"] for e in r["exclusions"]})
        exclusion_counts.update(codes)
        review_counts.update(sorted({f["code"] for f in r["review_flags"]}))
        strata.setdefault(r["stratum"], Counter())["eligible" if r["eligible"] else "excluded"] += 1
        if r["eligible"]:
            for channel, seq in r["selected_sequences"].items():
                selection[channel][seq] += 1
        entry = per_patient.setdefault(r["patient"], {"timepoints": {}, "eligible_studies": 0})
        entry["timepoints"][r["timepoint"]] = {"eligible": r["eligible"], "exclusions": codes}
        entry["eligible_studies"] += int(r["eligible"])
    eligible = [r for r in records if r["eligible"]]
    return {
        "schema_version": INVENTORY_SCHEMA_VERSION,
        "studies": len(records),
        "eligible_studies": len(eligible),
        "excluded_studies": len(records) - len(eligible),
        "patients": len(per_patient),
        "eligible_patients": len({r["patient"] for r in eligible}),
        "exclusion_counts": dict(sorted(exclusion_counts.items())),
        "review_counts": dict(sorted(review_counts.items())),
        "strata": {k: dict(sorted(v.items())) for k, v in sorted(strata.items())},
        "selected_sequences": {c: dict(sorted(v.items())) for c, v in selection.items()},
        "duplicates": duplicate_groups(records),
        "rejected": [r.to_json() for r in result.rejected],
        "ignored_entries": result.ignored_entries,
        "per_patient": dict(sorted(per_patient.items())),
    }


def format_summary(summary: dict[str, Any]) -> str:
    """Texto legible del resumen para la CLI (las carpetas rechazadas solo por nivel, código y huella)."""
    lines = [
        f"Estudios: {summary['studies']} ({summary['eligible_studies']} elegibles, "
        f"{summary['excluded_studies']} excluidos); pacientes: {summary['patients']} "
        f"({summary['eligible_patients']} con algún estudio elegible)",
    ]
    for code, n in summary["exclusion_counts"].items():
        lines.append(f"  exclusión {code}: {n} estudio(s) — {EXCLUSION_CODES.get(code, code)}")
    for code, n in summary["review_counts"].items():
        lines.append(f"  revisión {code}: {n} estudio(s) — {REVIEW_CODES.get(code, code)}")
    for name, counts in summary["strata"].items():
        lines.append(f"  estrato {name}: {counts}")
    for channel, counts in summary["selected_sequences"].items():
        lines.append(f"  canal {channel} (elegibles): {counts}")
    if summary["duplicates"]:
        lines.append(f"  duplicados exactos entre estudios: {len(summary['duplicates'])} grupo(s)")
    for rej in summary["rejected"]:
        where = f"{rej['patient']}/" if "patient" in rej else ""
        lines.append(
            f"  rechazada carpeta de {rej['level']} {where}#{rej['name_sha8']}: {rej['code']} — {rej['message']}"
        )
    if summary["ignored_entries"]:
        lines.append(f"  entradas ignoradas (no son carpetas): {summary['ignored_entries']}")
    lines.append("Por paciente:")
    for patient, entry in summary["per_patient"].items():
        parts = [
            f"{tp} ok" if info["eligible"] else f"{tp} excluido ({', '.join(info['exclusions'])})"
            for tp, info in entry["timepoints"].items()
        ]
        lines.append(f"  {patient}: {'; '.join(parts)}")
    return "\n".join(lines)


def dump_summary(summary: dict[str, Any]) -> str:
    """JSON del resumen para `--summary`."""
    return json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
