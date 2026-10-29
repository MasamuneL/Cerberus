"""Secuencias del dataset y validación de identificadores (docs/PLAN_MVP.md §6).

`SEQ_INFO` y `MRI_SEQS` están portados de `cerberus_eda.py:83-96`. Toda entrada del usuario (`patient`,
`timepoint`, `sequence`, nombre de archivo) pasa por aquí **antes** de construir cualquier `Path`,
para evitar path traversal.
"""

import re

SEQ_INFO: dict[str, str] = {
    "t1gd": "T1 con gadolinio (realce)",
    "t1eg": "T1 gradiente-eco",
    "t1tse": "T1 turbo spin-eco",
    "t2tse": "T2 turbo spin-eco",
    "t2star": "T2* (sangre / calcio)",
    "flair": "T2-FLAIR (edema)",
    "adc": "Mapa ADC (difusión)",
    "ct": "Tomografía (planeación RT)",
    "rtdose": "Dosis de radioterapia (Gy)",
    "brain_mask": "Máscara cerebral (skull-strip)",
    "gtv": "GTV de radioterapia (etiqueta)",
}
MRI_SEQS: list[str] = ["t1gd", "t1eg", "t1tse", "t2tse", "t2star", "flair", "adc"]

# Archivos derivados que la API también sirve (storage/results/<patient>/<timepoint>/)
SERVABLE_DERIVED: tuple[str, ...] = ("monai_seg", "brodmann")

# re.ASCII: `\d` solo acepta 0-9 (sin dígitos Unicode como "٠٠١")
PATIENT_RE = re.compile(r"^\d{3}$", re.ASCII)
TIMEPOINT_RE = re.compile(r"^t\d{1,2}$", re.ASCII)


def validate_patient(s: str) -> str:
    """Devuelve `s` si es un paciente válido (3 dígitos, ej. "001"); si no, lanza `ValueError`."""
    if not PATIENT_RE.fullmatch(s):
        raise ValueError(f"Paciente inválido: {s!r}")
    return s


def validate_timepoint(s: str) -> str:
    """Devuelve `s` si es un tiempo válido ("t" + 1-2 dígitos, ej. "t0", "t10"); si no, lanza `ValueError`."""
    if not TIMEPOINT_RE.fullmatch(s):
        raise ValueError(f"Tiempo inválido: {s!r}")
    return s


def validate_sequence(s: str) -> str:
    """Devuelve `s` si es una clave de `SEQ_INFO`; si no, lanza `ValueError`."""
    if s not in SEQ_INFO:
        raise ValueError(f"Secuencia inválida: {s!r}")
    return s


def validate_file_name(name: str) -> str:
    """Nombre servible (sin `.nii.gz`): secuencia válida o derivado (`monai_seg`); si no, `ValueError`."""
    if name not in SEQ_INFO and name not in SERVABLE_DERIVED:
        raise ValueError(f"Archivo no servible: {name!r}")
    return name
