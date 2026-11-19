"""Tests de FT5: `smoke --synthetic` (docs/PLAN_PIPELINE_FINETUNING.md §8). Todo es sintético; sin red ni GPU.

El recorrido completo (13 pasos con SegResNet real, parches 16³ y volúmenes 32³) tarda unos segundos en CPU,
así que no se marca `slow`.
"""

import json
import socket
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

import pytest

from cerberus_training.__main__ import EXIT_CONFIG_ERROR, EXIT_NOT_IMPLEMENTED, EXIT_SMOKE, PENDING, main
from cerberus_training.config import REPO_ROOT
from cerberus_training.smoke import (
    BANNER,
    MARKER_NAME,
    REPORT_NAME,
    STEP_NAMES,
    network_blocked,
    run_smoke,
)


def _repo_state() -> tuple[str, tuple[str, ...]]:
    """`git status` del repo y listado de `storage/` y `models/`: el smoke no debe modificar nada de esto."""
    git = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    listing = tuple(
        sorted(str(p.relative_to(REPO_ROOT)) for top in ("storage", "models") for p in (REPO_ROOT / top).rglob("*"))
    )
    return git, listing


def test_smoke_runs_everything_offline_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sandbox = tmp_path / "tmp"
    sandbox.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(sandbox))
    attempts: list[object] = []
    monkeypatch.setattr(socket.socket, "connect", lambda self, address: attempts.append(address))
    before = _repo_state()

    assert main(["smoke", "--synthetic"]) == 0

    out = capsys.readouterr().out
    assert out.startswith(BANNER) and out.count("✓") == len(STEP_NAMES) and "✗" not in out
    assert f"{len(STEP_NAMES)}/{len(STEP_NAMES)} pasos correctos" in out and "No es un experimento" in out
    for name in STEP_NAMES:
        assert name in out
    assert "borrado" in out
    assert not attempts  # el smoke bloquea `connect` antes de que llegue al socket parcheado por la prueba
    assert [p for p in sandbox.iterdir() if p.name.startswith("cerberus-smoke-")] == []  # el temporal se borró
    assert _repo_state() == before  # nada escrito en el repo (git, storage/ y models/)


def test_smoke_keep_work_dir_has_report_and_markers(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    work = tmp_path / "smoke-work"
    assert main(["smoke", "--synthetic", "--work-dir", str(work)]) == 0
    out = capsys.readouterr().out
    assert f"Artefactos conservados en {work.resolve()}" in out

    report = json.loads((work / REPORT_NAME).read_text(encoding="utf-8"))
    assert report["synthetic"] is True and report["real_finetuning"] is False and report["ok"] is True
    assert report["banner"] == BANNER and report["network_attempts_blocked"] == 0
    assert [s["name"] for s in report["steps"]] == list(STEP_NAMES) and all(s["ok"] for s in report["steps"])
    assert report["facts"]["eligible"] == 9
    assert report["facts"]["exclusions"] == {"missing_channel": 1, "missing_label": 1}
    assert BANNER in (work / MARKER_NAME).read_text(encoding="utf-8")
    runs = sorted((work / "training" / "runs").iterdir())
    assert [r.name for r in runs] == ["smoke-sintetico-continuo", "smoke-sintetico-interrumpido"]
    assert all((r / MARKER_NAME).is_file() for r in runs)
    # Dos pasos de optimización reales y el modelo exportado
    lines = (runs[0] / "metrics.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["step"] for line in lines] == [1, 2]
    assert (runs[0] / "export" / "model.pt").is_file() and (runs[0] / "evaluation" / "test" / "summary.json").is_file()
    # Todo quedó fuera del repo y la configuración derivada es de CPU sin AMP
    assert REPO_ROOT.resolve() not in work.resolve().parents
    config = json.loads((work / "config.json").read_text(encoding="utf-8"))
    assert config["training"]["device"] == "cpu" and config["training"]["amp"] is False
    assert Path(config["paths"]["data_root"]).is_relative_to(work)
    assert Path(config["paths"]["work_dir"]).is_relative_to(work)


def test_smoke_rejects_bad_work_dirs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["smoke", "--synthetic", "--work-dir", str(REPO_ROOT / "storage" / "smoke-no")]) == EXIT_CONFIG_ERROR
    assert "dentro del repo" in capsys.readouterr().out
    assert not (REPO_ROOT / "storage" / "smoke-no").exists()
    busy = tmp_path / "busy"
    busy.mkdir()
    (busy / "ajeno.txt").write_text("no tocar", encoding="utf-8")
    assert main(["smoke", "--synthetic", "--work-dir", str(busy)]) == EXIT_CONFIG_ERROR
    assert "vacío" in capsys.readouterr().out
    assert (busy / "ajeno.txt").read_text(encoding="utf-8") == "no tocar"


def test_smoke_reports_failed_step_and_stops(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Un código de salida inesperado de la CLI marca ese paso con ✗, omite el resto y devuelve 9."""

    def failing_cli(argv: Sequence[str]) -> int:
        if argv[0] == "split":
            print("Error simulado", file=sys.stderr)
            return 4
        return main(argv)

    work = tmp_path / "fail"
    assert run_smoke(failing_cli, work_dir=work) == EXIT_SMOKE
    out = capsys.readouterr().out
    assert "✗ split" in out and "terminó con código 4" in out and "Error simulado" in out
    assert out.count("✓") == 3 and "preflight: omitido" in out and "FALLÓ" in out
    report = json.loads((work / REPORT_NAME).read_text(encoding="utf-8"))
    assert report["ok"] is False and report["synthetic"] is True and len(report["steps"]) == 4


def test_network_attempt_during_a_step_fails_the_smoke(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Aunque el código bajo prueba capture el `OSError`, el intento queda contado y el smoke devuelve 9."""

    def sneaky_cli(argv: Sequence[str]) -> int:
        if argv[0] == "validate":
            try:
                socket.create_connection(("203.0.113.1", 80), timeout=0.1)
            except OSError:
                pass  # el intento ya se registró
        return main(argv)

    work = tmp_path / "net"
    assert run_smoke(sneaky_cli, work_dir=work) == EXIT_SMOKE
    out = capsys.readouterr().out
    assert "intento(s) de red" in out and "FALLÓ" in out and out.count("✓") == len(STEP_NAMES)
    report = json.loads((work / REPORT_NAME).read_text(encoding="utf-8"))
    assert report["ok"] is False and report["network_attempts_blocked"] == 1


def test_temporary_dir_is_removed_on_interrupt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sandbox = tmp_path / "tmp"
    sandbox.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(sandbox))

    def interrupted_cli(argv: Sequence[str]) -> int:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_smoke(interrupted_cli)
    assert [p for p in sandbox.iterdir() if p.name.startswith("cerberus-smoke-")] == []


def test_pending_subcommands_exit_3(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """El camino `PENDING` sigue operativo para subcomandos declarados pero sin implementar."""
    monkeypatch.setitem(PENDING, "smoke", "FT9")
    assert main(["smoke", "--synthetic"]) == EXIT_NOT_IMPLEMENTED
    err = capsys.readouterr().err
    assert "aún no está implementado" in err and "pendiente de FT9" in err


def test_network_guard_blocks_and_restores() -> None:
    original = (socket.socket.connect, socket.getaddrinfo, socket.create_connection)
    with network_blocked() as attempts:
        with pytest.raises(OSError, match="Red bloqueada"):
            socket.getaddrinfo("example.com", 443)
        with pytest.raises(OSError, match="Red bloqueada"):
            socket.create_connection(("203.0.113.1", 80), timeout=0.1)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with pytest.raises(OSError, match="Red bloqueada"):
                sock.connect(("203.0.113.1", 80))
        finally:
            sock.close()
    assert len(attempts) == 3
    assert (socket.socket.connect, socket.getaddrinfo, socket.create_connection) == original
