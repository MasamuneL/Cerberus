"""Lanzador `tools/launch/up.sh` (HW2): `--dry-run` con la detección simulada (sin hardware, red ni daemon)."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from cerberus_api.config import REPO_ROOT

pytestmark = [
    pytest.mark.launcher,
    pytest.mark.skipif(shutil.which("bash") is None, reason="requiere bash"),
]

UP_SH = REPO_ROOT / "tools" / "launch" / "up.sh"
GIB = 1024**3
DOCKER_8GB = f"8 {8_214_257_664}"  # Docker Desktop con 8 GB reporta ~7.65 GiB
RTX_3060 = "NVIDIA GeForce RTX 3060, 8.6, 550.54.14, 12288 MiB"
RTX_5090_580 = "NVIDIA GeForce RTX 5090, 12.0, 580.65.06, 32607 MiB"
RTX_5090_550 = "NVIDIA GeForce RTX 5090, 12.0, 550.54.14, 32607 MiB"


def _launch(
    tmp_path: Path,
    *args: str,
    os_name: str,
    arch: str = "x86_64",
    docker_info: str | None = DOCKER_8GB,
    nvidia: str = "none",
    runtimes: str = "runc",
    env_file: str = "",
    extra_env: dict[str, str] | None = None,
    shell: str = "bash",
) -> subprocess.CompletedProcess[str]:
    """Ejecuta up.sh con un entorno limpio de `CERBERUS_*` y un `.env` propio en `tmp_path`."""
    dotenv = tmp_path / ".env"
    dotenv.write_text(env_file, encoding="utf-8")
    environment = {name: value for name, value in os.environ.items() if not name.startswith("CERBERUS_")}
    environment |= {
        "CERBERUS_LAUNCH_ENV_FILE": str(dotenv),
        "CERBERUS_LAUNCH_FAKE_OS": os_name,
        "CERBERUS_LAUNCH_FAKE_ARCH": arch,
        "CERBERUS_LAUNCH_FAKE_NVIDIA_SMI": nvidia,
        "CERBERUS_LAUNCH_FAKE_DOCKER_RUNTIMES": runtimes,
        "CERBERUS_UV": "uv",
    }
    if docker_info is not None:
        environment["CERBERUS_LAUNCH_FAKE_DOCKER_INFO"] = docker_info
    environment |= extra_env or {}
    return subprocess.run(
        [shell, str(UP_SH), *args],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _dry_run(tmp_path: Path, *args: str, **kwargs: object) -> str:
    result = _launch(tmp_path, "--dry-run", *args, **kwargs)  # type: ignore[arg-type]
    assert result.returncode == 0, result.stderr
    return result.stdout


def _line(output: str, prefix: str) -> str:
    """Primera línea del informe que empieza (sin sangría) por `prefix`."""
    return next(line.strip() for line in output.splitlines() if line.strip().startswith(prefix))


def test_bash_syntax() -> None:
    result = subprocess.run(["bash", "-n", str(UP_SH)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck no está instalado")
def test_shellcheck() -> None:
    result = subprocess.run(["shellcheck", str(UP_SH)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout


def test_mac_arm_uses_hybrid_mode_with_native_worker(tmp_path: Path) -> None:
    out = _dry_run(tmp_path, os_name="darwin", arch="arm64", docker_info=f"14 {8 * GIB}")
    assert _line(out, "Sistema:") == "Sistema:  darwin/arm64"
    assert _line(out, "Modo:").startswith("Modo:     híbrido")
    assert _line(out, "Compose:") == "Compose:  -f compose.yaml -f compose.hybrid.yaml"
    assert "docker compose -f compose.yaml -f compose.hybrid.yaml up -d --build" in out
    worker = _line(out, "env CERBERUS_REDIS_URL=")
    assert "CERBERUS_REDIS_URL=redis://127.0.0.1:6379/0" in worker
    assert "CERBERUS_DATA_DIR=./Data CERBERUS_STORAGE_DIR=./storage CERBERUS_MODELS_DIR=./models" in worker
    assert "run --no-sync python -m cerberus_api.worker > ./storage/launch/worker.log" in worker
    # Sin worker de Docker no hay límite de memoria que fijar, ni emulación que avise
    assert "CERBERUS_WORKER_MEM_LIMIT" not in out
    assert "CERBERUS_REGISTRATION" not in out


def test_mac_arm_foreground_runs_worker_without_pid(tmp_path: Path) -> None:
    out = _dry_run(tmp_path, "--foreground", os_name="darwin", arch="arm64")
    assert "worker.pid" not in out
    assert _line(out, "env CERBERUS_REDIS_URL=").endswith("python -m cerberus_api.worker")


def test_mac_arm_hybrid_worker_follows_dotenv_paths(tmp_path: Path) -> None:
    dotenv = 'CERBERUS_STORAGE_PATH="./storage-docker"\nCERBERUS_REDIS_PORT=6390 # otro redis\nCERBERUS_CPU_THREADS=6\n'
    out = _dry_run(tmp_path, os_name="darwin", arch="arm64", env_file=dotenv)
    worker = _line(out, "env CERBERUS_REDIS_URL=")
    assert "CERBERUS_REDIS_URL=redis://127.0.0.1:6390/0" in worker
    assert "CERBERUS_STORAGE_DIR=./storage-docker" in worker
    assert "CERBERUS_CPU_THREADS=6" in worker
    assert "./storage-docker/launch/worker.pid" in out


def test_mac_arm_no_hybrid_is_emulated_and_suggests_fast(tmp_path: Path) -> None:
    out = _dry_run(tmp_path, "--no-hybrid", os_name="darwin", arch="arm64", docker_info=f"14 {8 * GIB}")
    assert _line(out, "Modo:") == "Modo:     cpu (backend linux/amd64 emulado en arm64)"
    assert _line(out, "Compose:") == "Compose:  -f compose.yaml"
    assert "sugerencia (emulación arm64 → amd64)" in out
    assert "--fast" in out


def test_mac_intel_uses_plain_compose(tmp_path: Path) -> None:
    out = _dry_run(tmp_path, os_name="darwin", arch="x86_64")
    assert _line(out, "Modo:") == "Modo:     cpu"
    assert _line(out, "Compose:") == "Compose:  -f compose.yaml"
    # 7.65 GiB − 2 = 5.65 → 5 GB
    assert "CERBERUS_WORKER_MEM_LIMIT=5g  (lanzador" in out
    assert "CERBERUS_UID" not in out
    assert "Avisos:" not in out


def test_linux_without_nvidia_uses_cpu_and_host_uid(tmp_path: Path) -> None:
    out = _dry_run(tmp_path, os_name="linux", docker_info=f"16 {32 * GIB}")
    assert _line(out, "Modo:") == "Modo:     cpu"
    assert _line(out, "GPU:") == "GPU:      no detectada"
    assert "CERBERUS_WORKER_MEM_LIMIT=12g" in out
    assert f"CERBERUS_UID={os.getuid()}" in out
    assert f"CERBERUS_GID={os.getgid()}" in out


def test_linux_ampere_uses_cu126(tmp_path: Path) -> None:
    out = _dry_run(tmp_path, os_name="linux", nvidia=RTX_3060, runtimes="io.containerd.runc.v2 nvidia runc")
    assert _line(out, "Modo:") == "Modo:     gpu NVIDIA (torch cu126)"
    assert _line(out, "Compose:") == "Compose:  -f compose.yaml -f compose.gpu.yaml"
    assert "CERBERUS_TORCH_VARIANT=cu126  (lanzador" in out
    # Con GPU el mínimo sube 1 GB por el contexto CUDA
    assert "CERBERUS_WORKER_MEM_LIMIT=6g" in out
    assert "docker compose -f compose.yaml -f compose.gpu.yaml up -d --build" in out


def test_linux_blackwell_with_driver_580_uses_cu130(tmp_path: Path) -> None:
    out = _dry_run(tmp_path, os_name="linux", nvidia=RTX_5090_580, runtimes="runc nvidia")
    assert _line(out, "Modo:") == "Modo:     gpu NVIDIA (torch cu130)"
    assert "CERBERUS_TORCH_VARIANT=cu130  (lanzador: cc 12.0, driver 580.65.06)" in out


def test_linux_blackwell_with_old_driver_falls_back_to_cpu(tmp_path: Path) -> None:
    out = _dry_run(tmp_path, os_name="linux", nvidia=RTX_5090_550, runtimes="runc nvidia")
    assert _line(out, "Modo:") == "Modo:     cpu"
    assert _line(out, "Compose:") == "Compose:  -f compose.yaml"
    assert "driver ≥ 580 (tienes 550.54.14)" in out
    assert "CERBERUS_TORCH_VARIANT" not in out


def test_linux_nvidia_without_container_toolkit_falls_back_to_cpu(tmp_path: Path) -> None:
    out = _dry_run(tmp_path, os_name="linux", nvidia=RTX_3060, runtimes="io.containerd.runc.v2 runc")
    assert _line(out, "Modo:") == "Modo:     cpu"
    assert "NVIDIA Container Toolkit" in out


def test_wsl2_with_nvidia_needs_only_nvidia_smi(tmp_path: Path) -> None:
    # Docker Desktop + WSL2 expone la GPU sin listar el runtime nvidia
    out = _dry_run(tmp_path, os_name="wsl", nvidia=RTX_3060, runtimes="")
    assert _line(out, "Sistema:") == "Sistema:  wsl/x86_64"
    assert _line(out, "Modo:") == "Modo:     gpu NVIDIA (torch cu126)"
    assert "CERBERUS_UID=" in out


def test_windows_with_nvidia_uses_gpu_profile(tmp_path: Path) -> None:
    out = _dry_run(tmp_path, os_name="windows", nvidia=RTX_5090_580, runtimes="")
    assert _line(out, "Modo:") == "Modo:     gpu NVIDIA (torch cu130)"
    assert "CERBERUS_UID" not in out


def test_cpu_flag_ignores_gpu(tmp_path: Path) -> None:
    out = _dry_run(tmp_path, "--cpu", os_name="linux", nvidia=RTX_3060, runtimes="nvidia")
    assert _line(out, "Modo:") == "Modo:     cpu"
    assert "ignorada por --cpu" in out
    assert "CERBERUS_WORKER_MEM_LIMIT=5g" in out


def test_low_memory_warns_and_clamps_to_minimum(tmp_path: Path) -> None:
    out = _dry_run(tmp_path, os_name="linux", docker_info=f"8 {4 * GIB}")
    assert "CERBERUS_WORKER_MEM_LIMIT=5g" in out
    assert "Docker tiene 4.0 GB" in out


def test_few_cpus_suggest_fast_and_flag_applies_it(tmp_path: Path) -> None:
    suggested = _dry_run(tmp_path, os_name="linux", docker_info=f"4 {16 * GIB}")
    assert "sugerencia (4 CPU en Docker)" in suggested
    assert "  CERBERUS_REGISTRATION=" not in suggested  # sin fijarla en «Variables:»
    applied = _dry_run(tmp_path, "--fast", os_name="linux", docker_info=f"4 {16 * GIB}")
    assert "CERBERUS_REGISTRATION=fast  (lanzador: --fast (4 CPU en Docker))" in applied
    assert "sugerencia" not in applied


def test_user_variables_are_never_overwritten(tmp_path: Path) -> None:
    out = _dry_run(
        tmp_path,
        "--fast",
        os_name="linux",
        nvidia=RTX_5090_580,
        runtimes="nvidia",
        docker_info=f"2 {16 * GIB}",
        env_file="CERBERUS_REGISTRATION=full\nexport CERBERUS_TORCH_VARIANT='cu126'\n",
        extra_env={"CERBERUS_WORKER_MEM_LIMIT": "9g", "CERBERUS_UID": "1234"},
    )
    assert "CERBERUS_WORKER_MEM_LIMIT=9g  (tuya, entorno; el lanzador proponía 12g)" in out
    assert "CERBERUS_UID=1234  (tuya, entorno" in out
    assert "CERBERUS_REGISTRATION=full  (tuya, .env; el lanzador proponía fast)" in out
    assert "CERBERUS_TORCH_VARIANT=cu126  (tuya, .env; el lanzador proponía cu130)" in out
    assert "difiere de la detectada (cu130)" in out


def test_docker_not_running_is_a_clear_error(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    docker.chmod(0o755)
    result = _launch(
        tmp_path,
        "--dry-run",
        os_name="linux",
        docker_info=None,
        extra_env={"PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"},
    )
    assert result.returncode == 1
    assert "Docker no responde" in result.stderr


def test_down_dry_run_uses_hybrid_files_and_profile(tmp_path: Path) -> None:
    # storage propio: un compose-files real del repo no debe influir
    out = _dry_run(
        tmp_path, "down", os_name="darwin", arch="arm64", extra_env={"CERBERUS_STORAGE_PATH": str(tmp_path / "st")}
    )
    assert "docker compose -f compose.yaml -f compose.hybrid.yaml --profile docker-worker down" in out


def test_down_reuses_compose_files_of_last_up(tmp_path: Path) -> None:
    launch_dir = tmp_path / "st" / "launch"
    launch_dir.mkdir(parents=True)
    (launch_dir / "compose-files").write_text("-f compose.yaml -f compose.gpu.yaml\n", encoding="utf-8")
    out = _dry_run(tmp_path, "down", os_name="linux", extra_env={"CERBERUS_STORAGE_PATH": str(tmp_path / "st")})
    assert "docker compose -f compose.yaml -f compose.gpu.yaml down" in out


def test_help_and_unknown_option(tmp_path: Path) -> None:
    help_result = _launch(tmp_path, "--help", os_name="linux")
    assert help_result.returncode == 0
    assert "--dry-run" in help_result.stdout
    bad = _launch(tmp_path, "--turbo", os_name="linux")
    assert bad.returncode == 1
    assert "opción desconocida: --turbo" in bad.stderr


# --- correcciones tras la revisión del PR #39 -----------------------------------------------------------------------
UP_PS1 = REPO_ROOT / "tools" / "launch" / "up.ps1"
GB10 = "NVIDIA GB10, 12.1, 580.95.05, [N/A]"
# bash 3.2 de macOS en locale UTF-8 toma el primer byte de «»» como parte de `$VAR»`; con bash 5 no pasa
BASH_32 = Path("/bin/bash")
UTF8 = {"LC_ALL": "en_US.UTF-8"}


@pytest.mark.parametrize("shell", ["bash", str(BASH_32)])
def test_gpu_without_compute_capability_warns_in_utf8_locale(tmp_path: Path, shell: str) -> None:
    if not Path(shell).exists() and shutil.which(shell) is None:
        pytest.skip(f"{shell} no existe")
    result = _launch(
        tmp_path,
        "--dry-run",
        os_name="linux",
        nvidia="NVIDIA-SMI has failed",
        runtimes="nvidia",
        extra_env=UTF8,
        shell=shell,
    )
    assert result.returncode == 0, result.stderr
    assert "nvidia-smi no informó la compute capability («»): driver demasiado viejo. Se usa CPU." in result.stdout
    assert _line(result.stdout, "Modo:") == "Modo:     cpu"


@pytest.mark.parametrize("shell", ["bash", str(BASH_32)])
def test_non_numeric_docker_info_is_a_clear_error_in_utf8_locale(tmp_path: Path, shell: str) -> None:
    if not Path(shell).exists() and shutil.which(shell) is None:
        pytest.skip(f"{shell} no existe")
    result = _launch(tmp_path, "--dry-run", os_name="linux", docker_info="abc 123", extra_env=UTF8, shell=shell)
    assert result.returncode == 1
    assert "docker info devolvió CPUs no numéricas: «abc 123»" in result.stderr


def test_failing_nvidia_smi_is_treated_as_no_gpu(tmp_path: Path) -> None:
    # nvidia-smi escribe «NVIDIA-SMI has failed…» en stdout con código ≠ 0: no es el nombre de una GPU
    out = _dry_run(
        tmp_path,
        os_name="linux",
        nvidia="NVIDIA-SMI has failed because it couldn't communicate with the NVIDIA driver.",
        runtimes="nvidia",
        extra_env={"CERBERUS_LAUNCH_FAKE_NVIDIA_SMI_EXIT": "9"},
    )
    assert _line(out, "GPU:") == "GPU:      no detectada"
    assert "driver demasiado viejo" not in out
    assert _line(out, "Modo:") == "Modo:     cpu"


@pytest.mark.parametrize("os_name", ["linux", "wsl", "windows"])
def test_arm64_with_nvidia_ignores_gpu(tmp_path: Path, os_name: str) -> None:
    # GB10/DGX Spark: la imagen linux/amd64 corre emulada y CUDA no funciona bajo qemu
    out = _dry_run(tmp_path, os_name=os_name, arch="arm64", nvidia=GB10, runtimes="nvidia")
    assert _line(out, "Modo:") == "Modo:     cpu (backend linux/amd64 emulado en arm64)"
    assert _line(out, "Compose:") == "Compose:  -f compose.yaml"
    assert "ignorada en arm64" in _line(out, "GPU:")
    assert "CUDA no funciona" in out
    assert "CERBERUS_TORCH_VARIANT" not in out
    assert "CERBERUS_WORKER_MEM_LIMIT=5g" in out  # sin el +1 GB de GPU


def test_hybrid_worker_gets_upload_limits_from_dotenv(tmp_path: Path) -> None:
    dotenv = "CERBERUS_MAX_UPLOAD_MB=512\nCERBERUS_MAX_ZIP_UNCOMPRESSED_MB='1024'\n"
    out = _dry_run(tmp_path, os_name="darwin", arch="arm64", env_file=dotenv)
    worker = _line(out, "env CERBERUS_REDIS_URL=")
    assert "CERBERUS_MAX_UPLOAD_MB=512" in worker
    assert "CERBERUS_MAX_ZIP_UNCOMPRESSED_MB=1024" in worker


def test_hybrid_dry_run_syncs_with_locked(tmp_path: Path) -> None:
    out = _dry_run(tmp_path, os_name="darwin", arch="arm64")
    assert "  uv sync --locked" in out


def _fake_tools(tmp_path: Path, uv_exit: int) -> dict[str, str]:
    """`docker` que siempre responde 0 y `uv` con el código pedido; storage propio en `tmp_path`."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for name, code in (("docker", 0), ("uv", uv_exit)):
        tool = fake_bin / name
        tool.write_text(f"#!/bin/sh\nexit {code}\n", encoding="utf-8")
        tool.chmod(0o755)
    return {
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "CERBERUS_UV": str(fake_bin / "uv"),
        "CERBERUS_STORAGE_PATH": str(tmp_path / "st"),
        "CERBERUS_REDIS_PORT": "6",  # puerto privilegiado: nada escucha ahí
    }


def test_hybrid_locked_sync_failure_is_a_clear_error(tmp_path: Path) -> None:
    result = _launch(tmp_path, os_name="darwin", arch="arm64", extra_env=_fake_tools(tmp_path, uv_exit=2))
    assert result.returncode == 1
    assert "uv sync --locked falló: uv.lock no coincide con pyproject.toml" in result.stderr


def test_hybrid_running_worker_suggests_down_and_up(tmp_path: Path) -> None:
    extra = _fake_tools(tmp_path, uv_exit=0)
    # Proceso vivo cuya línea de comandos contiene cerberus_api.worker, como el worker real
    worker = subprocess.Popen(["python3", "-c", "import time; time.sleep(30)", "cerberus_api.worker"])
    try:
        launch_dir = tmp_path / "st" / "launch"
        launch_dir.mkdir(parents=True)
        (launch_dir / "worker.pid").write_text(f"{worker.pid}\n", encoding="utf-8")
        result = _launch(tmp_path, os_name="darwin", arch="arm64", extra_env=extra)
    finally:
        worker.kill()
        worker.wait()
    assert result.returncode == 0, result.stderr
    assert f"El worker nativo ya corre (PID {worker.pid}" in result.stdout
    assert "tools/launch/up.sh down y luego tools/launch/up.sh" in result.stdout


def test_up_ps1_keeps_parity_with_up_sh() -> None:
    # Sin pwsh en el equipo de desarrollo: comprobación estática de las correcciones R2–R10 en up.ps1
    text = UP_PS1.read_text(encoding="utf-8-sig")
    assert "«${Info}»" in text and "«${GpuCC}»" in text
    assert "[int]::TryParse($text, [ref]$id)" in text
    assert "-notmatch 'cerberus_api\\.worker'" in text
    assert "& (Get-NativeTool 'kill') -TERM $workerPid" in text
    assert "ignorada en arm64" in text
    assert "'CERBERUS_MAX_UPLOAD_MB', 'CERBERUS_MAX_ZIP_UNCOMPRESSED_MB'" in text
    assert "@($UvBin, 'sync', '--locked')" in text
    assert "tools/launch/up.ps1 down y luego tools/launch/up.ps1" in text


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="pwsh no está instalado")
def test_up_ps1_arm64_with_nvidia_ignores_gpu(tmp_path: Path) -> None:
    environment = {name: value for name, value in os.environ.items() if not name.startswith("CERBERUS_")}
    environment |= {
        "CERBERUS_LAUNCH_ENV_FILE": str(tmp_path / ".env"),
        "CERBERUS_LAUNCH_FAKE_OS": "linux",
        "CERBERUS_LAUNCH_FAKE_ARCH": "arm64",
        "CERBERUS_LAUNCH_FAKE_NVIDIA_SMI": GB10,
        "CERBERUS_LAUNCH_FAKE_DOCKER_RUNTIMES": "nvidia",
        "CERBERUS_LAUNCH_FAKE_DOCKER_INFO": DOCKER_8GB,
    }
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-File", str(UP_PS1), "--dry-run"],
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "ignorada en arm64" in result.stdout
    assert "Modo:     cpu (backend linux/amd64 emulado en arm64)" in result.stdout
