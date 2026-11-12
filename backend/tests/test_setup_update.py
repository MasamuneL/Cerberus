"""Actualización y recuperación con Docker simulado: nunca toca el daemon ni usa red."""

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FAKE_DOCKER = r"""
import json,os,sys,time
from pathlib import Path
a=sys.argv[1:]
log=Path(os.environ["UPDATE_DOCKER_LOG"])
with log.open("a") as output: output.write(json.dumps(a)+"\n")
stage=os.environ.get("UPDATE_FAIL","")
helper="ghcr.io/example/backend@sha256:"+"a"*64
if a[0]=="info": pass
elif a[0]=="context": print(os.environ.get("UPDATE_ENDPOINT","unix:///fake/docker.sock"))
elif a[0]=="ps": print("a"*64 if os.environ.get("UPDATE_FOREIGN") else "")
elif a[:2]==["image","inspect"]:
    if "--format" in a:
        print(json.dumps(dict(version="candidate",revision="b"*40,architecture="amd64",os="linux")))
elif a[:2]==["volume","inspect"]: sys.exit(0 if os.environ.get("UPDATE_EXISTING_VOLUME") else 1)
elif a[0]=="inspect":
    if "working_dir" in a[2]: print(os.environ.get("UPDATE_FOREIGN",os.environ["CERBERUS_INSTALL_DIR"]))
    else: print("private_persistent_volume")
elif a[0]=="cp": Path(a[-1]).write_bytes(b"PGDMPprivate-binary")
elif a[0]=="run":
    operation=a[a.index("--operation")+1]
    if stage==operation: sys.exit(1)
elif a[0]=="compose":
    if "--images" in a: print(helper+"\nredis@sha256:"+"b"*64+"\npostgres@sha256:"+"c"*64)
    elif "pull" in a:
        if stage=="sleep-pull":
            Path(os.environ["UPDATE_DOCKER_LOG"]+".sleep").touch()
            time.sleep(10)
        sys.exit(1 if stage=="pull" else 0)
    elif "ps" in a: print("a"*64)
    elif "run" in a:
        if "--operation" in a:
            if stage==a[a.index("--operation")+1]: sys.exit(1)
        else:
            count=sum(1 for line in log.read_text().splitlines()
                      if '"/release/current"' in line and '"--operation"' not in line)
            if stage==("guard-first" if count==1 else "guard-second"): sys.exit(1)
    elif "up" in a: sys.exit(1 if stage=="up" else 0)
    elif "stop" in a or "exec" in a: pass
    else: sys.exit("unexpected compose command")
else: sys.exit("unexpected docker command")
"""


@pytest.fixture(params=["bash", "powershell"])
def updater(request: pytest.FixtureRequest, tmp_path: Path) -> tuple[Path, list[str], dict[str, str]]:
    root = tmp_path / "Instalación ñ con espacios"
    root.mkdir()
    candidate = tmp_path / "candidato"
    candidate.mkdir()
    (root / ".env").write_text("PRIVATE_STATE='unchanged'\n")
    (root / "compose.yaml").write_text("{}")
    manifest = {
        "images": {
            "backend": "ghcr.io/example/backend@sha256:" + "a" * 64,
            "frontend": "ghcr.io/example/frontend@sha256:" + "d" * 64,
        }
    }
    for directory in (root, candidate):
        (directory / "release.json").write_text(json.dumps(manifest))
    binary = tmp_path / "bin"
    binary.mkdir()
    docker = binary / "docker"
    docker.write_text(f"#!{sys.executable}\n" + FAKE_DOCKER)
    docker.chmod(0o755)
    env = {key: value for key, value in os.environ.items() if not key.startswith(("CERBERUS_", "COMPOSE_", "UPDATE_"))}
    env.update(
        PATH=str(binary) + os.pathsep + env["PATH"],
        CERBERUS_INSTALL_DIR=str(root),
        UPDATE_DOCKER_LOG=str(tmp_path / "commands.jsonl"),
    )
    if request.param == "bash":
        command = ["bash", str(ROOT / "tools/setup/update.sh")]
    else:
        pwsh = os.environ.get("CERBERUS_TEST_PWSH") or shutil.which("pwsh")
        if not pwsh:
            pytest.skip("PowerShell no instalado: usar CERBERUS_TEST_PWSH para verificar paridad")
        command = [pwsh, "-NoLogo", "-NoProfile", "-File", str(ROOT / "tools/setup/update.ps1")]
    return root, command, env


def run_update(updater: tuple[Path, list[str], dict[str, str]], *arguments: str) -> subprocess.CompletedProcess[str]:
    root, command, env = updater
    return subprocess.run(
        command + list(arguments or (str(root.parent / "candidato"),)),
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )


def commands(updater: tuple[Path, list[str], dict[str, str]]) -> list[list[str]]:
    log = Path(updater[2]["UPDATE_DOCKER_LOG"])
    return [json.loads(line) for line in log.read_text().splitlines()]


def test_update_full_order_and_trusted_backup_helper(updater: tuple[Path, list[str], dict[str, str]]) -> None:
    result = run_update(updater)
    assert result.returncode == 0, result.stdout + result.stderr
    calls = commands(updater)
    pull = next(index for index, call in enumerate(calls) if "pull" in call)
    guards = [
        index for index, call in enumerate(calls) if "run" in call and "--current" in call and "--operation" not in call
    ]
    stop_app = next(index for index, call in enumerate(calls) if "stop" in call and "frontend" in call)
    dump = next(index for index, call in enumerate(calls) if any("pg_dump" in item for item in call))
    stop_db = next(index for index, call in enumerate(calls) if "stop" in call and "auth-db" in call)
    backup = next(index for index, call in enumerate(calls) if "--operation" in call and "backup" in call)
    activation = next(index for index, call in enumerate(calls) if "--operation" in call and "activate" in call)
    initial_verification = next(index for index, call in enumerate(calls) if "verify-images" in call)
    assert initial_verification < guards[0]
    assert not any("--images" in call for call in calls)
    inspected = [call[-1] for call in calls if call[:2] == ["image", "inspect"] and "--format" in call]
    assert "ghcr.io/example/backend@sha256:" + "a" * 64 in inspected
    assert "ghcr.io/example/frontend@sha256:" + "d" * 64 in inspected
    assert all("\n" not in reference for reference in inspected)
    assert guards[0] < pull < stop_app < guards[1] < dump < stop_db < backup < activation
    assert "--volumes-from" in calls[backup] and calls[backup][0] == "run"
    assert len([item for item in calls[backup] if ":/run/cerberus-backup/" in item]) == 6
    assert calls[activation][0] == "run" and "--network" in calls[activation]
    assert not any("down" in call or "prune" in call for call in calls)
    assert (updater[0] / ".env").read_text() == "PRIVATE_STATE='unchanged'\n"
    assert not (updater[0] / ".cerberus-setup.lock").exists()


@pytest.mark.parametrize("stage", ["guard-first", "pull", "verify-images"])
def test_failure_before_pause_never_stops_installation(
    updater: tuple[Path, list[str], dict[str, str]], stage: str
) -> None:
    updater[2]["UPDATE_FAIL"] = stage
    result = run_update(updater)
    assert result.returncode != 0
    assert not any("stop" in call or "up" in call for call in commands(updater))
    assert not (updater[0] / ".cerberus-setup.lock").exists()


@pytest.mark.parametrize("stage", ["guard-second", "backup", "activate", "up"])
def test_failure_recovery_depends_on_activation_boundary(
    updater: tuple[Path, list[str], dict[str, str]], stage: str
) -> None:
    updater[2]["UPDATE_FAIL"] = stage
    result = run_update(updater)
    assert result.returncode != 0, result.stdout + result.stderr
    calls = commands(updater)
    if stage in {"guard-second", "backup"}:
        assert "up" in calls[-1]
    else:
        assert "stop" in calls[-1] and "frontend" in calls[-1]
        assert "recuperación" in result.stdout + result.stderr or "restauración" in result.stdout + result.stderr
    assert not (updater[0] / ".cerberus-setup.lock").exists()


def test_restore_is_new_project_only_and_never_starts(updater: tuple[Path, list[str], dict[str, str]]) -> None:
    root, command, _ = updater
    backup = root.parent / "backup"
    backup.mkdir()
    (backup / "helper-image.txt").write_text("ghcr.io/example/backend@sha256:" + "a" * 64 + "\n")
    destination = root.parent / "restauración"
    arguments = (
        ["--restore", str(backup), str(destination), "cerberus-restore-test"]
        if command[0] == "bash"
        else ["-Restore", str(backup), "-Destination", str(destination), "-Project", "cerberus-restore-test"]
    )
    result = run_update(updater, *arguments)
    assert result.returncode == 0, result.stdout + result.stderr
    calls = commands(updater)
    assert not any(call[0] == "compose" for call in calls)
    assert not any("up" in call or "stop" in call for call in calls)
    assert len([call for call in calls if call[:2] == ["volume", "inspect"]]) == 6
    assert "--operation" in calls[-1] and "restore" in calls[-1]
    assert not (destination / ".cerberus-setup.lock").exists()


def test_existing_lock_is_preserved(updater: tuple[Path, list[str], dict[str, str]]) -> None:
    lock = updater[0] / ".cerberus-setup.lock"
    lock.mkdir()
    (lock / "other-owner").touch()
    result = run_update(updater)
    assert result.returncode != 0
    assert (lock / "other-owner").exists()
    assert not any("pull" in call or "stop" in call for call in commands(updater))


def test_cancel_releases_own_lock_and_returns_failure(updater: tuple[Path, list[str], dict[str, str]]) -> None:
    root, command, env = updater
    env["UPDATE_FAIL"] = "sleep-pull"
    child = subprocess.Popen(
        command + [str(root.parent / "candidato")], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    marker = Path(env["UPDATE_DOCKER_LOG"] + ".sleep")
    try:
        deadline = time.monotonic() + 10
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert marker.exists()
        child.send_signal(signal.SIGTERM if command[0] == "bash" else signal.SIGINT)
        child.communicate(timeout=15)
        # pwsh -File puede devolver 0 por Ctrl+C pese a ejecutar finally.
        if command[0] == "bash":
            assert child.returncode != 0
        assert not (root / ".cerberus-setup.lock").exists()
        assert not any("stop" in call or "up" in call for call in commands(updater))
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=5)


@pytest.mark.parametrize("failure", ["foreign", "remote", "context-precedence"])
def test_foreign_project_and_remote_context_are_blocked_before_mutation(
    updater: tuple[Path, list[str], dict[str, str]], failure: str
) -> None:
    root, _, env = updater
    if failure == "foreign":
        other = root.parent / "otra-instalación"
        other.mkdir()
        env["UPDATE_FOREIGN"] = str(other)
    else:
        env["UPDATE_ENDPOINT"] = "ssh://remote"
        if failure == "context-precedence":
            env["DOCKER_CONTEXT"] = "remote-context"
            env["DOCKER_HOST"] = "unix:///local.sock"
    result = run_update(updater)
    assert result.returncode != 0
    assert not any(
        call[0] == "run"
        or (call[0] == "compose" and any(item in call for item in ("run", "up", "stop", "pull", "exec")))
        for call in commands(updater)
    )
    assert not (root / ".cerberus-setup.lock").exists()
