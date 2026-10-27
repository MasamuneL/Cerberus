"""Ingesta DICOM: extracción segura del ZIP, agrupación por serie y conversión con dcm2niix (ticket B8).

Reglas de datos personales (AGENTS.md, regla 4), obligatorias en todo este módulo:

- El DICOM crudo solo vive en `storage/tmp/`; quien llama lo borra en un `finally`.
- De cada serie solo se conservan `Modality`, `SeriesDescription`, `ProtocolName`, si hay `ContrastBolusAgent`,
  `SeriesNumber` y la lista de archivos. `SeriesInstanceUID` se usa **solo** como clave interna de agrupación y
  nunca sale de `group_series`. Nada de `PatientName`, `PatientID`, fechas, institución ni UIDs.
- dcm2niix siempre con `-b n` (sin sidecar JSON) y `-f series` (el nombre no lleva datos del paciente).
- No se loguean headers ni la salida de dcm2niix.
"""

import re
import shutil
import stat
import subprocess
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import pydicom
from pydicom.errors import InvalidDicomError

# Límites por defecto del ZIP (el worker pasa `max_zip_uncompressed_mb` de la configuración)
MAX_MEMBERS = 20000
MAX_BYTES = 4096 * 1024 * 1024
# Tiempo máximo de dcm2niix por serie (segundos)
DCM2NIIX_TIMEOUT = 600

_COPY_CHUNK = 1024 * 1024


def _member_parts(name: str) -> tuple[str, ...]:
    """Partes de la ruta de un miembro del ZIP; `ValueError` si es absoluta o tiene `..`."""
    normalized = name.replace("\\", "/")
    # Rutas absolutas POSIX ("/etc/x") o con unidad de Windows ("C:/x", "C:x")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise ValueError(f"El ZIP contiene una ruta absoluta: {name!r}")
    parts = tuple(p for p in PurePosixPath(normalized).parts if p not in ("", "."))
    if ".." in parts:
        raise ValueError(f"El ZIP contiene una ruta con '..': {name!r}")
    return parts


def safe_extract(zip_path: Path, dest: Path, max_members: int = MAX_MEMBERS, max_bytes: int = MAX_BYTES) -> list[Path]:
    """Extrae `zip_path` en `dest` validando todo **antes** de escribir nada; devuelve los archivos extraídos.

    Rechaza (con `ValueError`) rutas absolutas, componentes `..`, symlinks, más de `max_members` miembros y
    una suma de `file_size` mayor que `max_bytes`. Durante la copia vuelve a contar los bytes reales, por si
    el ZIP declara tamaños falsos (zip bomb). Un ZIP corrupto lanza `ValueError` también.
    """
    try:
        zf = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise ValueError("El archivo no es un ZIP válido") from exc

    with zf:
        members = zf.infolist()
        if len(members) > max_members:
            raise ValueError(f"El ZIP tiene demasiados archivos ({len(members)} > {max_members})")

        planned: list[tuple[zipfile.ZipInfo, tuple[str, ...]]] = []
        total = 0
        for info in members:
            # Los bits altos de external_attr guardan el modo Unix: S_IFLNK = symlink
            if stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError(f"El ZIP contiene un enlace simbólico: {info.filename!r}")
            parts = _member_parts(info.filename)
            if info.is_dir() or not parts:
                continue
            total += info.file_size
            planned.append((info, parts))
        if total > max_bytes:
            raise ValueError(f"El ZIP descomprimido excede el límite ({max_bytes // _COPY_CHUNK} MB)")

        dest.mkdir(parents=True, exist_ok=True)
        root = dest.resolve()
        extracted: list[Path] = []
        written = 0
        for info, parts in planned:
            target = root.joinpath(*parts)
            if not target.resolve().is_relative_to(root):  # defensa extra (no debería pasar tras _member_parts)
                raise ValueError(f"Ruta fuera del destino: {info.filename!r}")
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                with zf.open(info) as src, target.open("wb") as out:
                    while chunk := src.read(_COPY_CHUNK):
                        written += len(chunk)
                        if written > max_bytes:
                            raise ValueError(f"El ZIP descomprimido excede el límite ({max_bytes // _COPY_CHUNK} MB)")
                        out.write(chunk)
            except (zipfile.BadZipFile, EOFError, OSError, NotImplementedError) as exc:
                raise ValueError("El ZIP está dañado o usa un formato no soportado") from exc
            extracted.append(target)
    return extracted


@dataclass
class SeriesGroup:
    """Serie DICOM sin datos personales: solo los tags que necesita la sugerencia y la lista de archivos."""

    modality: str
    description: str
    protocol: str
    series_number: int | None
    has_contrast_agent: bool
    files: list[Path] = field(default_factory=list)


def _text(value: object) -> str:
    """Valor de un tag como texto limpio ("" si falta)."""
    return "" if value is None else str(value).strip()


def _series_number(value: object) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def group_series(root: Path) -> list[SeriesGroup]:
    """Agrupa los DICOM bajo `root` por `SeriesInstanceUID` (solo como clave interna) y ordena por `SeriesNumber`.

    Lee solo el header (`stop_before_pixels=True`); omite lo que no es DICOM o no tiene `SeriesInstanceUID`
    (ej. `DICOMDIR`). El UID no se guarda en el `SeriesGroup`.
    """
    groups: dict[str, SeriesGroup] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            ds = pydicom.dcmread(path, stop_before_pixels=True)
        except InvalidDicomError:
            continue
        except Exception:
            # DICOM truncado o raro: se ignora sin loguear su contenido
            continue
        uid = _text(ds.get("SeriesInstanceUID"))
        if not uid:
            continue
        group = groups.get(uid)
        if group is None:
            group = SeriesGroup(
                modality=_text(ds.get("Modality")).upper(),
                description=_text(ds.get("SeriesDescription")),
                protocol=_text(ds.get("ProtocolName")),
                series_number=_series_number(ds.get("SeriesNumber")),
                has_contrast_agent=bool(_text(ds.get("ContrastBolusAgent"))),
            )
            groups[uid] = group
        group.files.append(path)
    return sorted(
        groups.values(),
        key=lambda g: (g.series_number is None, g.series_number or 0, g.description, g.protocol),
    )


# Patrones de `suggest_sequence` sobre `description + protocol` en minúsculas.
# Los límites `(?<![a-z])` / `(?![a-z])` evitan falsos positivos como "ce" en "space" o "gre" en "progress".
_T1 = re.compile(r"t1(?!\d)")
_T2 = re.compile(r"t2(?!\d)")
_FLAIR = re.compile(r"flair")
_ADC = re.compile(r"(?<![a-z])adc(?![a-z])|apparent")
_T2STAR = re.compile(r"t2\*|t2star|t2_star|(?<![a-z])swi(?![a-z])")
_GRE = re.compile(r"(?<![a-z])gre(?![a-z])")
_CONTRAST = re.compile(r"(?<![a-z])(gd|gad\w*|post\w*|contrast|ce)(?![a-z])|\+c")
_T1_GRADIENT = re.compile(r"mprage|(?<![a-z])(gre|tfe|spgr)(?![a-z])")


def suggest_sequence(modality: str, description: str, protocol: str, has_contrast_agent: bool) -> str | None:
    """Sugiere la secuencia de `SEQ_INFO` de una serie, o `None` si no hay una clara.

    Reglas en orden (ticket B8) sobre `description + protocol` en minúsculas:
    `CT`→`ct`; otra modalidad que no sea MR (RTDOSE, RTSTRUCT…)→`None`; `flair`→`flair`; `adc|apparent`→`adc`;
    `t2*|t2star|swi`, o `gre` sin `t1`, sin `flair`→`t2star`; `t2`→`t2tse`; `t1` con
    (`gd|gad|post|+c|contrast|ce` o `ContrastBolusAgent`)→`t1gd`; `mprage|gre|tfe|spgr` con `t1`→`t1eg`;
    `t1`→`t1tse`; si nada coincide→`None`.

    `gre` solo cuenta para `t2star` si no aparece `t1`: así "T1 GRE" llega a la regla de `t1eg`, que de otro
    modo sería inalcanzable.
    """
    mod = modality.strip().upper()
    if mod == "CT":
        return "ct"
    if mod != "MR":
        return None
    text = f"{description} {protocol}".lower()
    has_t1 = bool(_T1.search(text))
    if _FLAIR.search(text):
        return "flair"
    if _ADC.search(text):
        return "adc"
    if _T2STAR.search(text) or (_GRE.search(text) and not has_t1):
        return "t2star"
    if _T2.search(text):
        return "t2tse"
    if has_t1 and (has_contrast_agent or _CONTRAST.search(text)):
        return "t1gd"
    if has_t1 and _T1_GRADIENT.search(text):
        return "t1eg"
    if has_t1:
        return "t1tse"
    return None


def dcm2niix_path() -> Path:
    """Binario de dcm2niix: junto al intérprete (`.venv/bin`) o, si no, en el `PATH`."""
    local = Path(sys.executable).parent / "dcm2niix"
    if local.is_file():
        return local
    found = shutil.which("dcm2niix")
    if found is None:
        raise RuntimeError("No se encontró dcm2niix (instálalo con `uv sync`)")
    return Path(found)


def convert_series(files: list[Path], work_dir: Path, out_path: Path) -> bool:
    """Convierte una serie a `.nii.gz` con dcm2niix y la deja en `out_path`; `False` si no salió ningún NIfTI.

    Copia los archivos (con nombres neutros) a `work_dir/dicom/` para que dcm2niix solo vea esta serie y escribe
    en `work_dir/nifti/` con `-z y -b n -i y -f series`. Toma `series.nii.gz` o, si no existe, el primer
    `*.nii.gz` en orden alfabético. La salida de dcm2niix se captura y se descarta (puede citar tags).
    """
    dicom_dir = work_dir / "dicom"
    nifti_dir = work_dir / "nifti"
    dicom_dir.mkdir(parents=True, exist_ok=True)
    nifti_dir.mkdir(parents=True, exist_ok=True)
    for i, f in enumerate(files):
        shutil.copyfile(f, dicom_dir / f"{i:05d}.dcm")

    cmd = [str(dcm2niix_path()), "-z", "y", "-b", "n", "-i", "y", "-f", "series", "-o", str(nifti_dir), str(dicom_dir)]
    try:
        subprocess.run(cmd, capture_output=True, timeout=DCM2NIIX_TIMEOUT, check=False)
    except subprocess.TimeoutExpired:
        return False

    preferred = nifti_dir / "series.nii.gz"
    if preferred.is_file():
        chosen = preferred
    else:
        candidates = sorted(nifti_dir.glob("*.nii.gz"))
        if not candidates:
            return False
        chosen = candidates[0]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(chosen, out_path)
    return True
