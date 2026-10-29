"""Tests de `cerberus_api.runtime` (§16, D2e-back) con un cgroup simulado en `tmp_path`."""

import logging
import os
import sys
import types
from pathlib import Path

import pytest

from cerberus_api import runtime


def _cgroup(tmp_path: Path, cpu_max: str | None = None, memory_max: str | None = None) -> Path:
    root = tmp_path / "cgroup"
    root.mkdir()
    if cpu_max is not None:
        (root / "cpu.max").write_text(cpu_max + "\n")
    if memory_max is not None:
        (root / "memory.max").write_text(memory_max + "\n")
    return root


def _meminfo(tmp_path: Path, kb: int) -> Path:
    path = tmp_path / "meminfo"
    path.write_text(f"MemTotal:       {kb} kB\nMemFree:        1234 kB\n")
    return path


@pytest.fixture
def affinity_14(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime, "_affinity_cpus", lambda: 14)


# --- CPUs ---------------------------------------------------------------------------------------


@pytest.mark.usefixtures("affinity_14")
@pytest.mark.parametrize(
    ("cpu_max", "expected"),
    [("max 100000", 14.0), ("200000 100000", 2.0), ("150000 100000", 1.5), ("4000000 100000", 14.0), (None, 14.0)],
)
def test_detect_cpus_cgroup_v2(tmp_path: Path, cpu_max: str | None, expected: float) -> None:
    assert runtime.detect_cpus(_cgroup(tmp_path, cpu_max=cpu_max)) == expected


@pytest.mark.usefixtures("affinity_14")
def test_detect_cpus_cgroup_v1(tmp_path: Path) -> None:
    cpu = tmp_path / "cpu"
    cpu.mkdir()
    (cpu / "cpu.cfs_quota_us").write_text("300000")
    (cpu / "cpu.cfs_period_us").write_text("100000")
    assert runtime.detect_cpus(tmp_path) == 3.0
    (cpu / "cpu.cfs_quota_us").write_text("-1")
    assert runtime.detect_cpus(tmp_path) == 14.0


def test_detect_cpus_without_cgroup_uses_affinity(tmp_path: Path) -> None:
    assert runtime.detect_cpus(tmp_path / "missing") >= 1.0


# --- Memoria ------------------------------------------------------------------------------------


def test_memory_cgroup_limit(tmp_path: Path) -> None:
    root = _cgroup(tmp_path, memory_max=str(6 * 1024**3))
    assert runtime.detect_memory_gb(root, _meminfo(tmp_path, 16 * 1024**2)) == 6.0


def test_memory_unlimited_falls_back_to_meminfo(tmp_path: Path) -> None:
    root = _cgroup(tmp_path, memory_max="max")
    assert runtime.detect_memory_gb(root, _meminfo(tmp_path, 8 * 1024**2)) == 8.0


def test_memory_limit_capped_by_host_ram(tmp_path: Path) -> None:
    root = _cgroup(tmp_path, memory_max=str(64 * 1024**3))
    assert runtime.detect_memory_gb(root, _meminfo(tmp_path, 8 * 1024**2)) == 8.0


def test_memory_cgroup_v1_huge_value_is_unlimited(tmp_path: Path) -> None:
    mem = tmp_path / "memory"
    mem.mkdir()
    (mem / "memory.limit_in_bytes").write_text("9223372036854771712")
    assert runtime.detect_memory_gb(tmp_path, _meminfo(tmp_path, 4 * 1024**2)) == 4.0


def test_memory_macos_sysctl_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime, "_sysctl", lambda name: str(32 * 1024**3) if name == "hw.memsize" else None)
    assert runtime.detect_memory_gb(tmp_path / "nope", tmp_path / "nope") == 32.0


def test_memory_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime, "_sysctl", lambda name: None)
    assert runtime.detect_memory_gb(tmp_path / "nope", tmp_path / "nope") is None


# --- Hilos --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("env", "cpus", "expected"),
    [
        (None, 14.0, (8, "auto")),
        ("auto", 4.0, (3, "auto")),
        ("", 1.0, (1, "auto")),
        ("auto", 2.5, (1, "auto")),
        ("auto", 2.0, (1, "auto")),
        ("6", 14.0, (6, "env")),
        (" 12 ", 2.0, (12, "env")),
        ("abc", 14.0, (8, "auto")),
        ("0", 4.0, (3, "auto")),
        ("-2", 4.0, (3, "auto")),
    ],
)
def test_resolve_threads(env: str | None, cpus: float, expected: tuple[int, str]) -> None:
    assert runtime.resolve_threads(env, cpus) == expected


def test_resolve_threads_invalid_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="cerberus_api.runtime"):
        assert runtime.resolve_threads("abc", 14.0) == (8, "auto")
    assert "no es válido" in caplog.text


def test_apply_threads_sets_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in runtime.THREAD_ENV_VARS:
        monkeypatch.setenv(var, "99")  # se sobrescribe
    monkeypatch.delitem(sys.modules, "torch", raising=False)
    runtime.apply_threads(3)
    assert all(os.environ[var] == "3" for var in runtime.THREAD_ENV_VARS)


def test_apply_threads_sets_torch_if_imported(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    fake = types.SimpleNamespace(get_num_threads=lambda: 14, set_num_threads=calls.append)
    monkeypatch.setitem(sys.modules, "torch", fake)
    for var in runtime.THREAD_ENV_VARS:
        monkeypatch.setenv(var, "1")
    runtime.apply_threads(5)
    assert calls == [5]


def test_configure_threads_uses_cgroup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for var in runtime.THREAD_ENV_VARS:
        monkeypatch.setenv(var, "1")
    monkeypatch.delitem(sys.modules, "torch", raising=False)
    monkeypatch.setenv("CERBERUS_CPU_THREADS", "auto")
    monkeypatch.setattr(runtime, "_affinity_cpus", lambda: 14)
    assert runtime.configure_threads(_cgroup(tmp_path, cpu_max="400000 100000")) == (3, "auto")
    assert os.environ["OMP_NUM_THREADS"] == "3"


# --- Plataforma y contenedor -------------------------------------------------------------------------


def test_in_container(tmp_path: Path) -> None:
    assert runtime.in_container(tmp_path) is False
    (tmp_path / ".dockerenv").touch()
    assert runtime.in_container(tmp_path) is True


def test_in_container_cgroup_hint(tmp_path: Path) -> None:
    proc1 = tmp_path / "proc" / "1"
    proc1.mkdir(parents=True)
    (proc1 / "cgroup").write_text("12:cpu:/kubepods/besteffort/pod1\n")
    assert runtime.in_container(tmp_path) is True


@pytest.fixture
def linux_x86(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime.sys, "platform", "linux")
    monkeypatch.setattr(runtime.platform, "system", lambda: "Linux")
    monkeypatch.setattr(runtime.platform, "machine", lambda: "x86_64")
    monkeypatch.delenv("CERBERUS_HOST_ARCH", raising=False)
    monkeypatch.setattr(runtime, "ROSETTA_BINFMT", Path("/nonexistent/rosetta"))


@pytest.mark.usefixtures("linux_x86")
def test_platform_emulated_rosetta_linux(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cpuinfo = tmp_path / "cpuinfo"
    cpuinfo.write_text("vendor_id\t: VirtualApple\n")
    assert runtime.platform_str(cpuinfo) == "linux/x86_64 (emulado en arm64)"
    cpuinfo.write_text("vendor_id\t: GenuineIntel\n")
    assert runtime.platform_str(cpuinfo) == "linux/x86_64"
    monkeypatch.setenv("CERBERUS_HOST_ARCH", "aarch64")
    assert runtime.platform_str(cpuinfo) == "linux/x86_64 (emulado en aarch64)"


def test_platform_native_arm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime.sys, "platform", "linux")
    monkeypatch.setattr(runtime.platform, "system", lambda: "Linux")
    monkeypatch.setattr(runtime.platform, "machine", lambda: "aarch64")
    assert runtime.platform_str(tmp_path / "nope") == "linux/aarch64"


def test_detect_device_without_import(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(sys.modules, "torch", raising=False)
    assert runtime.detect_device(allow_import=False) == "cpu"
    assert "torch" not in sys.modules


# --- SystemInfo -----------------------------------------------------------------------------------


def test_build_system_info_constrained(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CERBERUS_CPU_THREADS", "auto")
    monkeypatch.setattr(runtime, "_affinity_cpus", lambda: 14)
    monkeypatch.setattr(runtime, "platform_str", lambda cpuinfo: "linux/x86_64 (emulado en arm64)")
    root = _cgroup(tmp_path, cpu_max="200000 100000", memory_max=str(4 * 1024**3))
    (tmp_path / ".dockerenv").touch()
    info = runtime.build_system_info(
        "worker", cgroup_root=root, meminfo=_meminfo(tmp_path, 16 * 1024**2), container_root=tmp_path, device="cpu"
    )
    assert info.source == "worker"
    assert info.in_container is True
    assert (info.cpus_available, info.threads, info.threads_source) == (2.0, 1, "auto")
    assert info.memory_gb == 4.0
    assert info.warnings == [
        "Memoria baja (4 GB): el registro ANTs puede fallar; asigna ≥ 8 GB en Docker Desktop",
        "Plataforma emulada: el cálculo será más lento",
    ]


def test_build_system_info_env_and_invalid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime, "_affinity_cpus", lambda: 14)
    monkeypatch.setattr(runtime, "platform_str", lambda cpuinfo: "darwin/arm64")
    root = _cgroup(tmp_path, cpu_max="max 100000", memory_max="max")
    meminfo = _meminfo(tmp_path, 16 * 1024**2)
    monkeypatch.setenv("CERBERUS_CPU_THREADS", "6")
    info = runtime.build_system_info("api", cgroup_root=root, meminfo=meminfo, container_root=tmp_path, device="mps")
    assert (info.threads, info.threads_source, info.memory_gb, info.warnings) == (6, "env", 16.0, [])
    monkeypatch.setenv("CERBERUS_CPU_THREADS", "abc")
    info = runtime.build_system_info("api", cgroup_root=root, meminfo=meminfo, container_root=tmp_path, device="mps")
    assert (info.threads, info.threads_source) == (8, "auto")
    assert info.warnings == ["CERBERUS_CPU_THREADS='abc' no es válido: se usa auto (8 hilos)"]
