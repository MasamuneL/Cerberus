"""Staging de subidas DICOM: `storage/staging/<upload_id>/` (docs/PLAN_MVP.md §6, ticket B8).

```
storage/staging/<upload_id>/manifest.json         # UploadManifest
storage/staging/<upload_id>/series/<index>.nii.gz # series ya convertidas
```

`upload_id` es un uuid4 en hex (32 caracteres). Se valida con `validate_upload_id` **antes** de construir
cualquier `Path` (AGENTS.md, regla 9). El manifest nunca guarda datos personales ni UIDs DICOM.
"""

import os
import re
import uuid
from pathlib import Path

from pydantic import ValidationError

from cerberus_api.schemas import UploadManifest

MANIFEST_NAME = "manifest.json"
SERIES_DIR = "series"

UPLOAD_ID_RE = re.compile(r"^[0-9a-f]{32}$", re.ASCII)


def new_upload_id() -> str:
    """Nuevo identificador de subida (uuid4 en hex)."""
    return uuid.uuid4().hex


def validate_upload_id(s: str) -> str:
    """Devuelve `s` si son 32 caracteres hex en minúscula; si no, lanza `ValueError`."""
    if not UPLOAD_ID_RE.fullmatch(s):
        raise ValueError(f"Identificador de subida inválido: {s!r}")
    return s


def upload_dir(staging_dir: Path, upload_id: str) -> Path:
    """`storage/staging/<upload_id>/` (valida el id)."""
    return staging_dir / validate_upload_id(upload_id)


def manifest_path(staging_dir: Path, upload_id: str) -> Path:
    """`storage/staging/<upload_id>/manifest.json` (valida el id)."""
    return upload_dir(staging_dir, upload_id) / MANIFEST_NAME


def series_path(staging_dir: Path, upload_id: str, index: int) -> Path:
    """`storage/staging/<upload_id>/series/<index>.nii.gz` (valida el id; `index` ≥ 0)."""
    if index < 0:
        raise ValueError(f"Índice de serie inválido: {index}")
    return upload_dir(staging_dir, upload_id) / SERIES_DIR / f"{index}.nii.gz"


def read_manifest(staging_dir: Path, upload_id: str) -> UploadManifest | None:
    """Lee el manifest de la subida; `None` si no existe o está dañado. `ValueError` si el id es inválido."""
    path = manifest_path(staging_dir, upload_id)
    try:
        return UploadManifest.model_validate_json(path.read_bytes())
    except (OSError, ValidationError):
        return None


def write_manifest(staging_dir: Path, manifest: UploadManifest) -> Path:
    """Escribe el manifest de forma atómica (archivo temporal + `os.replace`) y devuelve su ruta."""
    path = manifest_path(staging_dir, manifest.upload_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{MANIFEST_NAME}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return path
