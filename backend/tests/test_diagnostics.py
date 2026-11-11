"""Diagnóstico offline: estados accionables y exportación sin datos privados."""

import importlib
import json
import os
import subprocess
from pathlib import Path
from types import ModuleType

import pytest


def diagnostics() -> ModuleType:
    """Carga la interfaz pendiente sin depender de Docker ni red."""
    try:
        return importlib.import_module("cerberus_api.diagnostics")
    except ModuleNotFoundError:
        pytest.fail("Falta el diagnóstico seguro D3e")


def codes(report: dict) -> set[str]:
    """Extrae los códigos públicos para comprobar decisiones operativas."""
    return {check["code"] for check in report["checks"]}


def test_unavailable_docker_produces_partial_safe_report(tmp_path: Path) -> None:
    report = diagnostics().build_report({"docker": {"status": "unavailable"}}, data_dir=tmp_path)
    assert report["format"] == 1
    assert "DOCKER_UNAVAILABLE" in codes(report)
    assert "SAMPLE_MISSING" in codes(report)
    assert all(set(check) == {"code", "service", "status", "action"} for check in report["checks"])


def test_initializers_are_completed_and_failed_initializer_is_actionable(tmp_path: Path) -> None:
    snapshot = {
        "docker": {"status": "ready"},
        "services": [
            {"service": "setup-secrets", "state": "exited", "exit_code": 0},
            {"service": "setup-identity", "state": "exited", "exit_code": 1},
            {"service": "keycloak", "state": "running", "health": "starting"},
        ],
    }
    report = diagnostics().build_report(snapshot, data_dir=tmp_path)
    assert any(c["code"] == "INITIALIZER_COMPLETED" and c["service"] == "setup-secrets" for c in report["checks"])
    assert any(c["code"] == "INITIALIZER_FAILED" and c["service"] == "setup-identity" for c in report["checks"])
    assert any(c["code"] == "SERVICE_STARTING" and c["service"] == "keycloak" for c in report["checks"])


def test_occupied_ports_and_mixed_images_are_identified(tmp_path: Path) -> None:
    digest = "ghcr.io/example/backend@sha256:" + "a" * 64
    snapshot = {
        "docker": {"status": "ready"},
        "ports": {"http": "busy", "identity": "busy"},
        "release": {"images": {"backend": digest}},
        "services": [{"service": "api", "state": "running", "health": "healthy", "image": "old:local"}],
    }
    report = diagnostics().build_report(snapshot, data_dir=tmp_path)
    assert "PORT_OCCUPIED" in codes(report)
    assert "IMAGE_MISMATCH" in codes(report)


def test_sample_hash_lfs_and_unsafe_manifest_are_distinguished(tmp_path: Path) -> None:
    import hashlib

    data = tmp_path / "Data"
    target = data / "001/t0/1_t0_gtv.nii.gz"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"nifti fixture")
    manifest = {
        "format": 1,
        "files": [
            {"path": "001/t0/1_t0_gtv.nii.gz", "size": 13, "sha256": hashlib.sha256(b"nifti fixture").hexdigest()}
        ],
    }
    module = diagnostics()
    assert "SAMPLE_VERIFIED" in codes(module.build_report({"sample_manifest": manifest}, data_dir=data))
    target.write_bytes(b"corrupt")
    assert "SAMPLE_CORRUPT" in codes(module.build_report({"sample_manifest": manifest}, data_dir=data))
    target.write_text("version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 13\n")
    assert "SAMPLE_LFS_POINTER" in codes(module.build_report({"sample_manifest": manifest}, data_dir=data))
    manifest["files"][0]["path"] = "../private"
    assert "SAMPLE_MANIFEST_INVALID" in codes(module.build_report({"sample_manifest": manifest}, data_dir=data))


def test_no_untrusted_field_can_reach_report_or_export(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    marker = "PatientName_secret_cookie_token_/Users/private?access_token=private"
    snapshot = {
        "docker": {"status": marker, "stderr": marker},
        "services": [
            {"service": marker, "state": marker, "image": marker},
            {"service": "api", "state": marker, "health": marker},
        ],
        "release": {"version": marker},
        "logs": marker,
    }
    module = diagnostics()
    report = module.build_report(snapshot, data_dir=tmp_path)
    assert marker not in json.dumps(report)
    export = tmp_path / "report.json"
    module.export_report(report, export)
    assert json.loads(export.read_text()) == report
    assert export.stat().st_mode & 0o077 == 0
    with pytest.raises(FileExistsError):
        module.export_report(report, export)
    assert marker not in capsys.readouterr().out


def test_cli_invalid_json_and_export_failure_never_echo_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import io

    module = diagnostics()
    monkeypatch.setattr(module.sys, "stdin", io.StringIO("secret invalid JSON"))
    assert module.main(["--snapshot-stdin", "--data-dir", str(tmp_path)]) == 1
    output = capsys.readouterr()
    assert "secret invalid JSON" not in output.out + output.err
    assert "SNAPSHOT_INVALID" in codes(json.loads(output.out))
    monkeypatch.setattr(module.sys, "stdin", io.StringIO("{}"))
    assert module.main(["--snapshot-stdin", "--data-dir", str(tmp_path), "--export", str(tmp_path)]) == 1
    assert "EXPORT_FAILED" in codes(json.loads(capsys.readouterr().out))


def test_storage_permission_error_is_redacted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = diagnostics()
    monkeypatch.setattr(module.os, "access", lambda *args: False)
    report = module.build_report({}, data_dir=tmp_path, storage_dir=tmp_path, models_dir=tmp_path)
    assert "STORAGE_PERMISSIONS" in codes(report)


def test_resource_failure_and_malformed_snapshot_are_safe(tmp_path: Path) -> None:
    module = diagnostics()
    report = module.build_report(
        {"docker": {"status": "ready"}, "services": [{"service": "worker", "state": "exited", "oom_killed": True}]},
        data_dir=tmp_path,
    )
    assert "RESOURCE_OOM" in codes(report)
    report = module.build_report({"docker": {"status": []}, "services": [False]}, data_dir=tmp_path)
    assert "DOCKER_UNKNOWN" in codes(report)


def test_export_reconstructs_allowlist_and_rejects_symlink(tmp_path: Path) -> None:
    module = diagnostics()
    report = {
        "format": 42,
        "secret": "private",
        "checks": [{"code": "DOCKER_UNKNOWN", "service": "docker", "status": "private", "action": "private"}],
    }
    target = tmp_path / "target"
    module.export_report(report, target)
    assert "private" not in target.read_text()
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(FileExistsError):
        module.export_report(report, link)


def test_sample_symlink_cannot_read_external_file(tmp_path: Path) -> None:
    data = tmp_path / "Data"
    (data / "001").mkdir(parents=True)
    private = tmp_path / "private"
    private.mkdir()
    (private / "1_t0_gtv.nii.gz").write_text("PatientName private")
    (data / "001/t0").symlink_to(private, target_is_directory=True)
    report = diagnostics().build_report({}, data_dir=data)
    assert "SAMPLE_CORRUPT" in codes(report)


def test_check_rejects_untrusted_codes_and_services() -> None:
    module = diagnostics()
    with pytest.raises(ValueError):
        module.check("PatientName", "docker")
    with pytest.raises(ValueError):
        module.check("DOCKER_READY", "/Users/private")


def test_sample_missing_and_insufficient_disk_have_distinct_actions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil

    module = diagnostics()
    manifest = {"format": 1, "files": [{"path": "001/t0/1_t0_gtv.nii.gz", "size": 100, "sha256": "a" * 64}]}
    monkeypatch.setattr(shutil, "disk_usage", lambda _: shutil._ntuple_diskusage(100, 100, 0))
    assert "DISK_INSUFFICIENT" in codes(module.build_report({"sample_manifest": manifest}, data_dir=tmp_path))


def test_shell_wrapper_handles_missing_docker_without_leaking_errors(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    docker = tmp_path / "docker"
    docker.write_text('#!/bin/sh\necho "secret PatientName /Users/private" >&2\nexit 1\n')
    docker.chmod(0o755)
    result = subprocess.run(
        ["/bin/bash", str(root / "tools/setup/diagnose.sh")],
        env={**os.environ, "PATH": str(tmp_path) + ":/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert "DOCKER_UNAVAILABLE" in codes(json.loads(result.stdout))
    assert "secret" not in result.stdout + result.stderr


def test_explicit_own_data_mode_does_not_report_missing_sample(tmp_path: Path) -> None:
    report = diagnostics().build_report({"sample_mode": "none"}, data_dir=tmp_path)
    assert "SAMPLE_DISABLED" in codes(report)
    assert "SAMPLE_MISSING" not in codes(report)
