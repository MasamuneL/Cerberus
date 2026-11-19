"""Lectura/escritura ligera de `inventory.jsonl` y utilidades de escritura segura (ticket FT1).

Sin numpy ni nibabel: `split` importa solo este módulo, de modo que particionar no carga dependencias pesadas.
`read_inventory` no confía en el archivo: revalida identificadores, rutas relativas y claves mínimas antes de que
cualquier etapa posterior construya un `Path` a partir de él.
"""

import json
import os
import re
import tempfile
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from cerberus_api.sequences import validate_patient, validate_timepoint

# Versión del esquema de cada línea de inventory.jsonl; se incrementa ante cambios incompatibles.
INVENTORY_SCHEMA_VERSION = 1
CHANNELS: tuple[str, ...] = ("T1c", "T1", "T2", "FLAIR")
REQUIRED_KEYS: tuple[str, ...] = (
    "schema_version",
    "study_id",
    "patient",
    "timepoint",
    "stratum",
    "channels",
    "selected_sequences",
    "label",
    "brain_mask",
    "eligible",
    "exclusions",
    "review_flags",
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)


class InventoryError(ValueError):
    """Error de uso o de formato del inventario; mensaje en español."""


def fsync_dir(directory: Path) -> None:
    """`fsync` de la carpeta para que el renombrado/enlace sobreviva a un corte (no disponible en Windows)."""
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _write_temp(path: Path, text: str, mode: int) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return tmp


def atomic_write_text(path: Path, text: str, mode: int = 0o644) -> None:
    """Escritura atómica que reemplaza: temporal en la misma carpeta, `fsync`, `os.replace` y `fsync` de la carpeta."""
    tmp = _write_temp(path, text, mode)
    try:
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    fsync_dir(path.parent)


def publish_exclusive(path: Path, text: str, mode: int = 0o444) -> None:
    """Publica `path` solo si no existe: temporal completo + `os.link` (atómico y exclusivo).

    Lanza `FileExistsError` si otro proceso lo publicó antes. Si el sistema de archivos no admite enlaces duros, se
    recurre a `O_CREAT | O_EXCL` (exclusivo, aunque no atómico frente a un corte a mitad de escritura).
    """
    tmp = _write_temp(path, text, mode)
    try:
        try:
            os.link(tmp, path)
        except FileExistsError:
            raise
        except OSError:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(text)
                    handle.flush()
                    os.fsync(handle.fileno())
            except BaseException:
                path.unlink(missing_ok=True)
                raise
    finally:
        Path(tmp).unlink(missing_ok=True)
    fsync_dir(path.parent)


def ensure_outside_root(output: Path, data_root: Path) -> None:
    """El dataset es de solo lectura: ninguna salida puede quedar dentro de `data_root`."""
    out, root = output.resolve(), data_root.resolve()
    if out == root or root in out.parents:
        raise InventoryError(f"La salida {out} no puede estar dentro del dataset de solo lectura {root}")


def ensure_distinct(first: Path, second: Path, what: str) -> None:
    """Dos rutas de E/S no pueden ser el mismo archivo tras resolverlas (una pisaría a la otra)."""
    if first.resolve() == second.resolve():
        raise InventoryError(f"{what}: las dos rutas apuntan al mismo archivo ({first.resolve()})")


def write_inventory(records: list[dict[str, Any]], output: Path) -> None:
    """Escribe `inventory.jsonl` (un estudio por línea, claves ordenadas) de forma atómica."""
    text = "".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r in records)
    atomic_write_text(output, text)


def _check_file_entry(entry: Any, patient: str, timepoint: str, where: str) -> None:
    """Ficha de archivo: ruta relativa `<paciente>/<tiempo>/<archivo>` coherente con los ids y sha256 válido."""
    if not isinstance(entry, Mapping):
        raise InventoryError(f"{where}: se esperaba un objeto")
    raw = entry.get("path")
    if not isinstance(raw, str) or "\\" in raw or "\0" in raw:
        raise InventoryError(f"{where}: ruta ausente o no válida")
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts or "." in raw.split("/"):
        raise InventoryError(f"{where}: la ruta debe ser relativa y sin '..'")
    if len(path.parts) != 3 or path.parts[0] != patient or path.parts[1] != timepoint:
        raise InventoryError(f"{where}: la ruta no corresponde a {patient}/{timepoint}")
    if not isinstance(entry.get("sha256"), str) or not _SHA256_RE.fullmatch(entry["sha256"]):
        raise InventoryError(f"{where}: sha256 ausente o mal formado")


def validate_record(record: Any, where: str) -> dict[str, Any]:
    """Valida un registro leído del disco (no se confía en él aunque lo haya escrito este código)."""
    if not isinstance(record, dict):
        raise InventoryError(f"{where}: se esperaba un objeto JSON")
    if record.get("schema_version") != INVENTORY_SCHEMA_VERSION:
        raise InventoryError(f"{where}: esquema no soportado (se espera {INVENTORY_SCHEMA_VERSION})")
    missing = [key for key in REQUIRED_KEYS if key not in record]
    if missing:
        raise InventoryError(f"{where}: faltan claves {missing}")
    patient, timepoint = record["patient"], record["timepoint"]
    try:
        validate_patient(patient if isinstance(patient, str) else "")
        validate_timepoint(timepoint if isinstance(timepoint, str) else "")
    except ValueError as exc:
        raise InventoryError(f"{where}: identificador inválido ({exc})") from exc
    if record["study_id"] != f"{patient}_{timepoint}":
        raise InventoryError(f"{where}: study_id no coincide con paciente y tiempo")
    if not isinstance(record["eligible"], bool):
        raise InventoryError(f"{where}: `eligible` debe ser booleano")
    channels = record["channels"]
    if not isinstance(channels, Mapping) or set(channels) != set(CHANNELS):
        raise InventoryError(f"{where}: `channels` debe tener exactamente {list(CHANNELS)}")
    if not isinstance(record["selected_sequences"], Mapping) or set(record["selected_sequences"]) != set(CHANNELS):
        raise InventoryError(f"{where}: `selected_sequences` debe tener exactamente {list(CHANNELS)}")
    for name in (*CHANNELS, "label", "brain_mask"):
        entry = channels[name] if name in CHANNELS else record[name]
        if entry is not None:
            _check_file_entry(entry, patient, timepoint, f"{where} ({name})")
    if record["eligible"] and (any(channels[c] is None for c in CHANNELS) or record["label"] is None):
        raise InventoryError(f"{where}: estudio elegible sin todos los canales o sin GTV")
    if not isinstance(record["exclusions"], list) or record["eligible"] == bool(record["exclusions"]):
        raise InventoryError(f"{where}: `eligible` incoherente con `exclusions`")
    return record


def read_inventory(path: Path) -> list[dict[str, Any]]:
    """Lee `inventory.jsonl` y valida cada línea; cualquier manipulación es un `InventoryError` claro."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise InventoryError(f"No se pudo leer el inventario {path}: {exc}") from exc
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        where = f"{path}:{number}"
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise InventoryError(f"{where}: JSON inválido ({exc.msg})") from exc
        validate_record(record, where)
        if record["study_id"] in seen:
            raise InventoryError(f"{where}: study_id repetido {record['study_id']}")
        seen.add(record["study_id"])
        records.append(record)
    return records


def duplicate_groups(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Archivos de imagen (canales) con el mismo SHA-256 en estudios distintos.

    Solo cuentan los canales de imagen: GTV o máscaras vacías de igual shape coincidirían sin ser duplicados.
    """
    by_hash: dict[str, set[str]] = {}
    for record in records:
        for info in (record.get("channels") or {}).values():
            if info:
                by_hash.setdefault(info["sha256"], set()).add(record["study_id"])
    groups = sorted(by_hash.items())
    return [{"sha256": digest, "studies": sorted(studies)} for digest, studies in groups if len(studies) > 1]
