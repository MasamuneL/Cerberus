"""Detección de recursos y autoajuste de hilos (docs/PLAN_MVP.md §16, ticket D2e-back).

El worker llama a `configure_threads()` al arrancar, **antes** de importar torch o ANTs: OpenMP, MKL e ITK leen
sus variables de entorno al inicializarse, así que fijarlas después no tiene efecto.

Precedencia de hilos:
1. `CERBERUS_CPU_THREADS` numérico (≥ 1) manda (`threads_source="env"`).
2. `CERBERUS_CPU_THREADS=auto`, vacío o inválido → `max(1, min(CPUs − 1, 8))` (`threads_source="auto"`).
3. El valor resuelto **sobrescribe** `OMP_NUM_THREADS`, `MKL_NUM_THREADS`, `OPENBLAS_NUM_THREADS` e
   `ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS` aunque ya existan: la única perilla es `CERBERUS_CPU_THREADS`.

Todas las funciones de detección aceptan rutas inyectables para probarlas con un cgroup simulado en `tmp_path`.
"""

import logging
import math
import os
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from cerberus_api.schemas import SystemInfo

logger = logging.getLogger(__name__)

ENV_THREADS = "CERBERUS_CPU_THREADS"
# Clave de Redis donde el worker publica su `SystemInfo`; la lee `GET /api/system`
SYSTEM_INFO_KEY = "cerberus:system:worker"
THREAD_ENV_VARS = ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS")
MAX_AUTO_THREADS = 8
# Pico medido del worker con 001/t0: ~4.2 GiB (MONAI en CPU + registro ANTs SyN)
LOW_MEMORY_GB = 5.0

CGROUP_ROOT = Path("/sys/fs/cgroup")
MEMINFO = Path("/proc/meminfo")
CPUINFO = Path("/proc/cpuinfo")
# Rosetta para Linux registra este intérprete binfmt en la VM (no siempre visible desde el contenedor)
ROSETTA_BINFMT = Path("/proc/sys/fs/binfmt_misc/rosetta")
_GIB = 1024**3
# cgroup v1 usa un número enorme (≈ 2^63) en vez de "max" para "sin límite"
_UNLIMITED_BYTES = 1 << 60

Device = Literal["cuda", "mps", "cpu"]
ThreadsSource = Literal["auto", "env"]


def _read(path: Path) -> str | None:
    """Contenido de un archivo sin espacios extremos, o `None` si no existe o no se puede leer."""
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None


def _cgroup_cpu_quota(cgroup_root: Path) -> float | None:
    """CPUs de la cuota del cgroup (v2 `cpu.max`, v1 `cpu.cfs_quota_us`); `None` si no hay límite."""
    v2 = _read(cgroup_root / "cpu.max")
    if v2 is not None:
        parts = v2.split()
        if len(parts) == 2 and parts[0] != "max":
            try:
                quota, period = int(parts[0]), int(parts[1])
            except ValueError:
                return None
            return quota / period if quota > 0 and period > 0 else None
        return None
    quota_v1 = _read(cgroup_root / "cpu" / "cpu.cfs_quota_us")
    period_v1 = _read(cgroup_root / "cpu" / "cpu.cfs_period_us")
    if quota_v1 is None or period_v1 is None:
        return None
    try:
        quota, period = int(quota_v1), int(period_v1)
    except ValueError:
        return None
    return quota / period if quota > 0 and period > 0 else None


def _affinity_cpus() -> int:
    """CPUs en la afinidad del proceso (Linux, respeta `--cpuset-cpus`) o `os.cpu_count()` (macOS); mínimo 1."""
    if sys.platform == "linux":
        try:
            return max(1, len(os.sched_getaffinity(0)))
        except OSError:
            pass
    return max(1, os.cpu_count() or 1)


def detect_cpus(cgroup_root: Path = CGROUP_ROOT) -> float:
    """CPUs disponibles: cuota cgroup (`--cpus`) → afinidad → `cpu_count`. Nunca supera la afinidad."""
    affinity = _affinity_cpus()
    quota = _cgroup_cpu_quota(cgroup_root)
    return min(quota, float(affinity)) if quota is not None else float(affinity)


def _cgroup_memory_bytes(cgroup_root: Path) -> int | None:
    """Límite de memoria del cgroup (v2 `memory.max`, v1 `memory.limit_in_bytes`); `None` si no hay."""
    raw = _read(cgroup_root / "memory.max")
    if raw is None:
        raw = _read(cgroup_root / "memory" / "memory.limit_in_bytes")
    if raw is None or raw == "max":
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if 0 < value < _UNLIMITED_BYTES else None


def _meminfo_bytes(meminfo: Path) -> int | None:
    """`MemTotal` de `/proc/meminfo` en bytes."""
    text = _read(meminfo)
    if text is None:
        return None
    for line in text.splitlines():
        if line.startswith("MemTotal:"):
            parts = line.split()
            try:
                return int(parts[1]) * 1024  # viene en kB
            except (IndexError, ValueError):
                return None
    return None


def _sysctl(name: str) -> str | None:
    """Valor de `sysctl -n <name>` (macOS); `None` si no existe o falla."""
    if sys.platform != "darwin":
        return None
    try:
        out = subprocess.run(["sysctl", "-n", name], capture_output=True, text=True, timeout=2, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else None


def detect_memory_gb(cgroup_root: Path = CGROUP_ROOT, meminfo: Path = MEMINFO) -> float | None:
    """Memoria disponible en GiB: límite cgroup (acotado por la RAM) → `MemTotal` → `sysctl hw.memsize`."""
    total = _meminfo_bytes(meminfo)
    if total is None:
        raw = _sysctl("hw.memsize")
        total = int(raw) if raw is not None and raw.isdigit() else None
    limit = _cgroup_memory_bytes(cgroup_root)
    if limit is not None:
        total = min(limit, total) if total is not None else limit
    return round(total / _GIB, 1) if total is not None else None


def detect_device(allow_import: bool = True) -> Device:
    """Dispositivo de cálculo: cuda → mps → cpu (mismo orden que `segmentation._monai_predictor`).

    Importa torch solo si `allow_import` (el worker lo hace **después** de `configure_threads`); la API no
    lo importa para no cargar ~400 MB, y si torch no está en memoria responde `"cpu"`.
    """
    if not allow_import and "torch" not in sys.modules:
        return "cpu"
    try:
        import torch
    except ImportError:
        return "cpu"
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def in_container(root: Path = Path("/")) -> bool:
    """`True` dentro de Docker/Podman/Kubernetes (marcas `/.dockerenv`, `/run/.containerenv` o cgroup de PID 1)."""
    if (root / ".dockerenv").exists() or (root / "run" / ".containerenv").exists():
        return True
    cgroup = _read(root / "proc" / "1" / "cgroup") or ""
    return any(hint in cgroup for hint in ("docker", "kubepods", "containerd", "libpod"))


def _is_emulated(machine: str, cpuinfo: Path) -> str | None:
    """Arquitectura anfitriona si el proceso corre emulado (Rosetta / QEMU), si no `None`. Best-effort."""
    if sys.platform == "darwin":
        # Proceso x86_64 traducido por Rosetta 2 en Apple Silicon
        return "arm64" if _sysctl("sysctl.proc_translated") == "1" else None
    if machine not in ("x86_64", "amd64"):
        return None
    host = os.environ.get("CERBERUS_HOST_ARCH", "").strip()
    if host and host not in ("x86_64", "amd64"):
        return host
    # Rosetta para Linux (Docker Desktop en Apple Silicon) se anuncia como "VirtualApple"
    if "VirtualApple" in (_read(cpuinfo) or "") or ROSETTA_BINFMT.exists():
        return "arm64"
    return None


def platform_str(cpuinfo: Path = CPUINFO) -> str:
    """`sistema/arquitectura`, ej. `"darwin/arm64"` o `"linux/x86_64 (emulado en arm64)"`."""
    system = platform.system().lower() or sys.platform
    machine = platform.machine().lower() or "desconocida"
    host = _is_emulated(machine, cpuinfo)
    return f"{system}/{machine} (emulado en {host})" if host else f"{system}/{machine}"


def _parse_env_threads(env_value: str | None) -> int | None:
    """Hilos de `CERBERUS_CPU_THREADS` si es un entero ≥ 1; `None` si es auto, vacío o inválido."""
    if env_value is None:
        return None
    value = env_value.strip()
    if value.isdigit() and int(value) >= 1:
        return int(value)
    return None


def _is_invalid_env(env_value: str | None) -> bool:
    """`True` si la variable trae algo que no es `auto`, vacío ni un entero ≥ 1."""
    if env_value is None or env_value.strip().lower() in ("", "auto"):
        return False
    return _parse_env_threads(env_value) is None


def resolve_threads(env_value: str | None, cpus: float) -> tuple[int, ThreadsSource]:
    """Hilos a usar: entero ≥ 1 de la variable (`"env"`) o `max(1, min(floor(cpus) − 1, 8))` (`"auto"`).

    Un valor inválido (`"abc"`, `"0"`) cae en auto y deja un warning en el log.
    """
    explicit = _parse_env_threads(env_value)
    if explicit is not None:
        return explicit, "env"
    if _is_invalid_env(env_value):
        logger.warning("%s=%r no es válido; se usa auto", ENV_THREADS, env_value)
    return max(1, min(math.floor(cpus) - 1, MAX_AUTO_THREADS)), "auto"


def apply_threads(n: int) -> None:
    """Fija los hilos de OpenMP/MKL/OpenBLAS/ITK (sobrescribe) y, si torch ya está importado, `set_num_threads`.

    Es barato: el worker la vuelve a llamar al empezar cada job, ya en el hilo que hará el cálculo.
    """
    for var in THREAD_ENV_VARS:
        os.environ[var] = str(n)
    torch = sys.modules.get("torch")
    if torch is not None and torch.get_num_threads() != n:
        torch.set_num_threads(n)


def configure_threads(cgroup_root: Path = CGROUP_ROOT) -> tuple[int, ThreadsSource]:
    """Detecta CPUs, resuelve `CERBERUS_CPU_THREADS` y aplica los hilos. Llamar antes de importar torch/ANTs."""
    threads, source = resolve_threads(os.environ.get(ENV_THREADS), detect_cpus(cgroup_root))
    apply_threads(threads)
    return threads, source


def build_system_info(
    source: Literal["worker", "api"],
    *,
    cgroup_root: Path = CGROUP_ROOT,
    meminfo: Path = MEMINFO,
    cpuinfo: Path = CPUINFO,
    container_root: Path = Path("/"),
    device: Device | None = None,
) -> SystemInfo:
    """`SystemInfo` del proceso actual con warnings en español (memoria baja, plataforma emulada, env inválido).

    No aplica hilos (usa `configure_threads` para eso). `device=None` lo detecta: el worker importa torch, la API
    no (ver `detect_device`).
    """
    env_value = os.environ.get(ENV_THREADS)
    cpus = detect_cpus(cgroup_root)
    threads, threads_source = resolve_threads(env_value, cpus)
    memory_gb = detect_memory_gb(cgroup_root, meminfo)
    plat = platform_str(cpuinfo)
    if device is None:
        device = detect_device(allow_import=source == "worker")

    warnings: list[str] = []
    if _is_invalid_env(env_value):
        warnings.append(f"{ENV_THREADS}={env_value!r} no es válido: se usa auto ({threads} hilos)")
    if memory_gb is not None and memory_gb < LOW_MEMORY_GB:
        warnings.append(
            f"Memoria baja ({memory_gb:g} GB): el registro ANTs puede fallar; asigna ≥ 8 GB en Docker Desktop"
        )
    if "(emulado" in plat:
        warnings.append("Plataforma emulada: el cálculo será más lento")

    return SystemInfo(
        source=source,
        reported_at=datetime.now(UTC),
        in_container=in_container(container_root),
        platform=plat,
        cpus_available=round(cpus, 2),
        threads=threads,
        threads_source=threads_source,
        memory_gb=memory_gb,
        device=device,
        warnings=warnings,
    )
