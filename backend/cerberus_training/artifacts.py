"""Artefactos de un run de entrenamiento (docs/PLAN_PIPELINE_FINETUNING.md §3 y §6, ticket FT3).

```text
<paths.work_dir>/runs/<run_id>/
  config.resolved.json     # configuración con rutas absolutas (publicación exclusiva, nunca se pisa)
  provenance.json          # commit git, versiones, hashes de dataset/split/pesos/caché, dispositivo, semillas
  metrics.jsonl            # una línea JSON por época
  checkpoints/last.pt      # estado completo para reanudar en límite de época
  checkpoints/best.pt      # mejor época según Dice macro por paciente de validación
```

Un run existente nunca se sobrescribe: la carpeta se crea con `mkdir(exist_ok=False)`. Los checkpoints se escriben
de forma atómica (temporal en la misma carpeta, `fsync`, `os.replace`, `fsync` de la carpeta), con permisos 0644: un
fallo a mitad deja intacta la versión anterior y no deja archivos parciales. Un candado `.lock` (`O_EXCL`) impide dos
procesos sobre el mismo run. torch se importa dentro de las funciones.
"""

import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from cerberus_training.config import REPO_ROOT
from cerberus_training.manifest import atomic_write_text, fsync_dir, publish_exclusive

RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$", re.ASCII)
PROVENANCE_SCHEMA_VERSION = 1
# Bibliotecas cuya versión se registra en la procedencia.
PROVENANCE_LIBRARIES: tuple[str, ...] = ("torch", "monai", "numpy", "scipy", "nibabel", "pydantic", "cerberus")


class RunExistsError(FileExistsError):
    """El directorio del run ya existe: nunca se sobrescribe."""


class RunLockedError(RuntimeError):
    """Otro `train`/`--resume` tiene el candado del run (o quedó un candado huérfano de un proceso muerto)."""


@dataclass(frozen=True)
class RunPaths:
    """Rutas de un run (no crea nada)."""

    root: Path

    @property
    def config(self) -> Path:
        return self.root / "config.resolved.json"

    @property
    def provenance(self) -> Path:
        return self.root / "provenance.json"

    @property
    def metrics(self) -> Path:
        return self.root / "metrics.jsonl"

    @property
    def checkpoints(self) -> Path:
        return self.root / "checkpoints"

    @property
    def last(self) -> Path:
        return self.checkpoints / "last.pt"

    @property
    def best(self) -> Path:
        return self.checkpoints / "best.pt"

    @property
    def lock(self) -> Path:
        return self.root / ".lock"


def validate_run_id(run_id: str) -> str:
    """`run_id` es un nombre de carpeta simple (sin separadores, sin `..`, máx. 64 caracteres)."""
    if not RUN_ID_RE.fullmatch(run_id) or ".." in run_id:
        raise ValueError(f"run_id inválido: {run_id!r} (letras, dígitos, '.', '_' o '-', máx. 64; sin '..')")
    return run_id


def create_run_dir(work_dir: Path, run_id: str) -> RunPaths:
    """Crea `runs/<run_id>/checkpoints/`. Lanza `RunExistsError` si el run ya existe (nunca lo pisa)."""
    validate_run_id(run_id)
    runs = work_dir / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    root = runs / run_id
    try:
        root.mkdir()
    except FileExistsError as exc:
        raise RunExistsError(f"El run {root} ya existe: no se sobrescribe (use otro --run-id o --resume)") from exc
    paths = RunPaths(root)
    paths.checkpoints.mkdir()
    fsync_dir(runs)
    return paths


def remove_run_dir(paths: RunPaths) -> None:
    """Borra un run a medias (solo se usa si falla su creación inicial, antes de entrenar)."""
    shutil.rmtree(paths.root, ignore_errors=True)


@contextmanager
def run_lock(paths: RunPaths) -> Iterator[None]:
    """Candado simple del run: `.lock` creado con `O_EXCL` (con el PID) y borrado al terminar.

    Impide dos `train`/`--resume` simultáneos sobre el mismo run. Si un proceso murió sin liberarlo, el candado queda
    y hay que borrarlo a mano tras comprobar que no hay otro proceso activo.
    """
    try:
        fd = os.open(paths.lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError as exc:
        raise RunLockedError(
            f"El run {paths.root} está en uso ({paths.lock} existe). Si ningún proceso lo está usando, "
            "borre el candado a mano y repita."
        ) from exc
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(f"{os.getpid()}\n")
    try:
        yield
    finally:
        paths.lock.unlink(missing_ok=True)


def write_json_once(path: Path, payload: Any) -> None:
    """Publica un JSON de forma exclusiva (falla si ya existe), con permisos 0644."""
    publish_exclusive(path, json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", mode=0o644)


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    """Añade una línea JSON y hace `fsync` (una época registrada sobrevive a un corte)."""
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def rewrite_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    """Reescribe un JSONL de forma atómica (al reanudar se restaura el historial del checkpoint)."""
    atomic_write_text(path, "".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r in records))


def atomic_torch_save(obj: Any, path: Path) -> None:
    """`torch.save` atómico: temporal en la misma carpeta, `fsync`, `os.replace`, `fsync` de la carpeta."""
    import torch

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            torch.save(obj, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o644)  # mkstemp crea 0600
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    fsync_dir(path.parent)


def git_state(repo: Path = REPO_ROOT) -> dict[str, Any]:
    """Commit y estado del árbol leídos sin modificar el repo (`--no-optional-locks`: no reescribe el índice).

    `dirty` solo considera archivos versionados modificados: **ignora los no versionados** (untracked), que en un
    clon de trabajo suelen ser artefactos locales.
    """
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}

    def run(*args: str) -> str | None:
        try:
            result = subprocess.run(
                ["git", "--no-optional-locks", "-C", str(repo), *args],
                capture_output=True,
                text=True,
                check=False,
                env=env,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return result.stdout.strip() if result.returncode == 0 else None

    commit = run("rev-parse", "HEAD")
    status = run("status", "--porcelain", "--untracked-files=no") if commit else None
    return {"commit": commit, "dirty": bool(status) if status is not None else None}


def library_versions() -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for name in PROVENANCE_LIBRARIES:
        try:
            out[name] = version(name)
        except PackageNotFoundError:
            out[name] = None
    return out


def environment() -> dict[str, Any]:
    """Python, plataforma y versiones de bibliotecas."""
    return {"python": platform.python_version(), "platform": platform.platform(), "libraries": library_versions()}
