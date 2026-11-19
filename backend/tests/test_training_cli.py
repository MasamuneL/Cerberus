"""Tests de la CLI del pipeline de fine-tuning (docs/PLAN_PIPELINE_FINETUNING.md §8, ticket FT0). Sin red ni GPU."""

import builtins
import json
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from cerberus_training.__main__ import EXIT_CONFIG_ERROR, EXIT_NOT_IMPLEMENTED, PENDING, build_parser, main
from cerberus_training.config import REPO_ROOT, load_config
from cerberus_training.device import format_report, probe_device

EXAMPLE = str(REPO_ROOT / "configs" / "training" / "gtv_binary.json")
SUBCOMMANDS = [
    "validate",
    "device",
    "inventory",
    "prepare",
    "split",
    "preflight",
    "train",
    "evaluate",
    "export",
    "smoke",
]


def test_plan_subcommands_are_declared() -> None:
    parser = build_parser()
    choices = next(a for a in parser._actions if a.dest == "command").choices  # pyright: ignore[reportAttributeAccessIssue]
    assert choices is not None and sorted(choices) == sorted(SUBCOMMANDS)
    assert set(PENDING) == set(SUBCOMMANDS) - {"validate", "device", "inventory", "split"}


@pytest.mark.parametrize("argv", [["--help"], *[[name, "--help"] for name in SUBCOMMANDS]])
def test_help_exits_zero(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(argv)
    assert exc_info.value.code == 0
    assert "usage:" in capsys.readouterr().out


def test_python_m_train_help_exits_zero() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "cerberus_training", "train", "--help"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert "--dry-run" in result.stdout and "--resume" in result.stdout


def test_no_subcommand_is_an_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == EXIT_CONFIG_ERROR
    assert "usage:" in capsys.readouterr().err


def test_validate_example(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate", "--config", EXAMPLE]) == 0
    assert "Configuración válida" in capsys.readouterr().out


def test_validate_writes_resolved_config(tmp_path: Path) -> None:
    out = tmp_path / "resolved.json"
    assert main(["validate", "--config", EXAMPLE, "--write-resolved", str(out)]) == 0
    assert load_config(out).paths.work_dir.is_absolute()
    assert main(["validate", "--config", EXAMPLE, "--write-resolved", str(out)]) == EXIT_CONFIG_ERROR  # no pisa


def test_invalid_config_reports_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data = json.loads(Path(EXAMPLE).read_text(encoding="utf-8"))
    data["split"]["train"] = 0.9
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(data), encoding="utf-8")
    assert main(["train", "--config", str(bad), "--dry-run"]) == EXIT_CONFIG_ERROR
    assert "Configuración inválida" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("argv", "ticket"),
    [
        (["prepare", "--config", EXAMPLE], "FT2"),
        (["preflight", "--config", EXAMPLE], "FT2"),
        (["train", "--config", EXAMPLE, "--dry-run"], "FT3"),
        (["train", "--config", EXAMPLE, "--resume", "/x/last.pt"], "FT3"),
        (["evaluate", "--run", "/x", "--split", "test"], "FT4"),
        (["export", "--run", "/x"], "FT4"),
        (["smoke", "--synthetic"], "FT5"),
    ],
)
def test_unimplemented_subcommands_fail_clearly(
    argv: list[str], ticket: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(argv) == EXIT_NOT_IMPLEMENTED
    err = capsys.readouterr().err
    assert "aún no está implementado" in err and f"pendiente de {ticket}" in err


def test_required_arguments_enforced() -> None:
    for argv in (["train"], ["evaluate", "--run", "/x"], ["evaluate", "--run", "/x", "--split", "train"], ["smoke"]):
        with pytest.raises(SystemExit) as exc_info:
            main(argv)
        assert exc_info.value.code == 2


def test_device_never_fails_on_cpu(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["device"]) == 0
    assert "CUDA disponible:" in capsys.readouterr().out
    assert main(["device", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert isinstance(report["cuda_available"], bool)


def _fake_torch(
    *,
    cuda: bool,
    caps: tuple[tuple[int, int], ...] = ((8, 9),),
    arch_list: tuple[str, ...] = ("sm_80", "sm_89", "sm_90"),
) -> types.SimpleNamespace:
    """torch falso mínimo: solo las funciones que usa `probe_device`."""
    cuda_ns = types.SimpleNamespace(
        is_available=lambda: cuda,
        device_count=lambda: len(caps) if cuda else 0,
        get_device_name=lambda i: f"GPU falsa {i}",
        get_device_capability=lambda i: caps[i],
        get_arch_list=lambda: list(arch_list),
        is_bf16_supported=lambda: True,
    )
    return types.SimpleNamespace(
        __version__="2.14.1+cu126" if cuda else "2.14.1",
        version=types.SimpleNamespace(cuda="12.6" if cuda else None),
        cuda=cuda_ns,
        backends=types.SimpleNamespace(cudnn=types.SimpleNamespace(version=lambda: 91000)),
    )


def test_device_report_cuda_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "torch", _fake_torch(cuda=True, caps=((8, 9), (9, 0))))
    report = probe_device()
    assert report.cuda_available and report.torch_cuda_build == "12.6" and report.cudnn_version == 91000
    assert report.gpus == ["GPU falsa 0", "GPU falsa 1"] and report.gpu_archs == ["sm_89", "sm_90"]
    assert report.compiled_archs == ["sm_80", "sm_89", "sm_90"] and report.warnings == []
    text = format_report(report)
    assert "GPU 0:" in text and "sm_89" in text and "AVISO" not in text


def test_device_warns_when_gpu_arch_not_compiled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "torch", _fake_torch(cuda=True, caps=((12, 0),)))
    report = probe_device()
    assert len(report.warnings) == 1 and "sm_120" in report.warnings[0]
    assert "AVISO" in format_report(report)
    assert json.loads(format_report(report, as_json=True))["warnings"] == report.warnings


def test_device_cpu_fake_has_no_gpu_info(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "torch", _fake_torch(cuda=False))
    report = probe_device()
    assert not report.cuda_available and report.gpus == [] and report.compiled_archs == []
    assert "ruedas CPU" in report.note


def test_require_cuda_exit_codes(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setitem(sys.modules, "torch", _fake_torch(cuda=False))
    assert main(["device", "--require-cuda"]) == 1
    assert "--require-cuda" in capsys.readouterr().err
    monkeypatch.setitem(sys.modules, "torch", _fake_torch(cuda=True))
    assert main(["device", "--require-cuda"]) == 0


def test_device_report_without_torch_is_graceful(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "torch", None)  # fuerza ImportError en `import torch`
    report = probe_device()
    assert report.torch_version is None and report.cuda_available is False
    assert "torch no está instalado" in format_report(report)


def test_device_report_with_broken_torch_install_is_graceful(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def failing_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "torch":
            raise OSError("libcudart.so: no se puede abrir el archivo")  # rueda CUDA con bibliotecas ilegibles
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "torch", raising=False)
    monkeypatch.setattr(builtins, "__import__", failing_import)
    report = probe_device()
    assert report.torch_version is None and report.cuda_available is False and "torch no cargó" in report.note
