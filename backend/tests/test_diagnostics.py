"""Diagnóstico offline: estados accionables y exportación sin datos privados."""

import hashlib
import io
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import UID, ExplicitVRLittleEndian, MRImageStorage

from cerberus_api import diagnostics


def codes(report: dict[str, Any]) -> set[str]:
    """Extrae los códigos públicos para comprobar decisiones operativas."""
    return {check["code"] for check in report["checks"]}


def test_unavailable_docker_produces_partial_safe_report(tmp_path: Path) -> None:
    report = diagnostics.build_report({"docker": {"status": "unavailable"}}, data_dir=tmp_path)
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
    report = diagnostics.build_report(snapshot, data_dir=tmp_path)
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
    report = diagnostics.build_report(snapshot, data_dir=tmp_path)
    assert "PORT_OCCUPIED" in codes(report)
    assert "IMAGE_MISMATCH" in codes(report)


def test_sample_hash_lfs_and_unsafe_manifest_are_distinguished(tmp_path: Path) -> None:
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
    assert "SAMPLE_VERIFIED" in codes(diagnostics.build_report({"sample_manifest": manifest}, data_dir=data))
    target.write_bytes(b"corrupt")
    assert "SAMPLE_CORRUPT" in codes(diagnostics.build_report({"sample_manifest": manifest}, data_dir=data))
    target.write_text("version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 13\n")
    assert "SAMPLE_LFS_POINTER" in codes(diagnostics.build_report({"sample_manifest": manifest}, data_dir=data))
    manifest["files"][0]["path"] = "../private"
    assert "SAMPLE_MANIFEST_INVALID" in codes(diagnostics.build_report({"sample_manifest": manifest}, data_dir=data))


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
    report = diagnostics.build_report(snapshot, data_dir=tmp_path)
    assert marker not in json.dumps(report)
    export = tmp_path / "report.json"
    diagnostics.export_report(report, export)
    assert json.loads(export.read_text()) == report
    assert export.stat().st_mode & 0o077 == 0
    with pytest.raises(FileExistsError):
        diagnostics.export_report(report, export)
    assert marker not in capsys.readouterr().out


def test_cli_invalid_json_and_export_failure_never_echo_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(diagnostics.sys, "stdin", io.StringIO("secret invalid JSON"))
    assert diagnostics.main(["--snapshot-stdin", "--data-dir", str(tmp_path)]) == 1
    output = capsys.readouterr()
    assert "secret invalid JSON" not in output.out + output.err
    assert "SNAPSHOT_INVALID" in codes(json.loads(output.out))
    monkeypatch.setattr(diagnostics.sys, "stdin", io.StringIO("{}"))
    assert diagnostics.main(["--snapshot-stdin", "--data-dir", str(tmp_path), "--export", str(tmp_path)]) == 1
    assert "EXPORT_FAILED" in codes(json.loads(capsys.readouterr().out))


def test_storage_permission_error_is_redacted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(diagnostics.os, "access", lambda *args: False)
    report = diagnostics.build_report({}, data_dir=tmp_path, storage_dir=tmp_path, models_dir=tmp_path)
    assert "STORAGE_PERMISSIONS" in codes(report)


def test_resource_failure_and_malformed_snapshot_are_safe(tmp_path: Path) -> None:
    report = diagnostics.build_report(
        {"docker": {"status": "ready"}, "services": [{"service": "worker", "state": "exited", "oom_killed": True}]},
        data_dir=tmp_path,
    )
    assert "RESOURCE_OOM" in codes(report)
    report = diagnostics.build_report({"docker": {"status": []}, "services": [False]}, data_dir=tmp_path)
    assert "DOCKER_UNKNOWN" in codes(report)


def test_export_reconstructs_allowlist_and_rejects_symlink(tmp_path: Path) -> None:
    report = {
        "format": 42,
        "secret": "private",
        "checks": [{"code": "DOCKER_UNKNOWN", "service": "docker", "status": "private", "action": "private"}],
    }
    target = tmp_path / "target"
    diagnostics.export_report(report, target)
    assert "private" not in target.read_text()
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(FileExistsError):
        diagnostics.export_report(report, link)


def test_sample_symlink_cannot_read_external_file(tmp_path: Path) -> None:
    data = tmp_path / "Data"
    (data / "001").mkdir(parents=True)
    private = tmp_path / "private"
    private.mkdir()
    (private / "1_t0_gtv.nii.gz").write_text("PatientName private")
    (data / "001/t0").symlink_to(private, target_is_directory=True)
    report = diagnostics.build_report({}, data_dir=data)
    assert "SAMPLE_CORRUPT" in codes(report)


def test_check_rejects_untrusted_codes_and_services() -> None:
    with pytest.raises(ValueError):
        diagnostics.check("PatientName", "docker")
    with pytest.raises(ValueError):
        diagnostics.check("DOCKER_READY", "/Users/private")


def test_sample_missing_and_insufficient_disk_have_distinct_actions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = {"format": 1, "files": [{"path": "001/t0/1_t0_gtv.nii.gz", "size": 100, "sha256": "a" * 64}]}
    monkeypatch.setattr(shutil, "disk_usage", lambda _: shutil._ntuple_diskusage(100, 100, 0))
    assert "DISK_INSUFFICIENT" in codes(diagnostics.build_report({"sample_manifest": manifest}, data_dir=tmp_path))


def test_explicit_own_data_mode_does_not_report_missing_sample(tmp_path: Path) -> None:
    report = diagnostics.build_report({"sample_mode": "none"}, data_dir=tmp_path)
    assert "SAMPLE_DISABLED" in codes(report)
    assert "SAMPLE_MISSING" not in codes(report)


@pytest.mark.parametrize("json_lines", [False, True])
def test_cli_accepts_compose_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], json_lines: bool
) -> None:
    services = [
        {"Service": "api", "State": "running", "Health": "healthy", "Command": "private command"},
        {"Service": "frontend", "State": "exited", "ExitCode": 1},
        {"Service": "setup-identity", "State": "exited", "ExitCode": 0},
    ]
    raw = "\n".join(map(json.dumps, services)) if json_lines else json.dumps(services)
    monkeypatch.setattr(diagnostics.sys, "stdin", io.StringIO(raw))
    assert diagnostics.main(["--compose-stdin", "--data-dir", str(tmp_path)]) == 1
    output = capsys.readouterr().out
    assert "private command" not in output
    checks = {(item["service"], item["code"]) for item in json.loads(output)["checks"]}
    assert ("api", "SERVICE_HEALTHY") in checks
    assert ("frontend", "SERVICE_FAILED") in checks
    assert ("setup-identity", "INITIALIZER_COMPLETED") in checks


def test_empty_compose_input_is_not_reported_as_ready() -> None:
    assert diagnostics.compose_snapshot("") == {}


def test_cli_ignores_dicom_manifest_and_auth_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    data = tmp_path / "datos-privados"
    storage = tmp_path / "storage-privado"
    dicom_tags = {
        "PatientName": "Persona^Centinela",
        "PatientID": "ID-CENTINELA-419",
        "PatientBirthDate": "19750419",
        "InstitutionName": "Institucion-Centinela",
        "AccessionNumber": "ACC-CENTINELA-1",
        "StudyDate": "20310419",
        "StudyInstanceUID": "1.2.826.0.1.3680043.10.543.4191",
        "SeriesInstanceUID": "1.2.826.0.1.3680043.10.543.4192",
        "SOPInstanceUID": "1.2.826.0.1.3680043.10.543.4193",
    }
    dicom_path = storage / "tmp" / "centinela.dcm"
    dicom_path.parent.mkdir(parents=True)
    metadata = FileMetaDataset()
    metadata.TransferSyntaxUID = ExplicitVRLittleEndian
    metadata.MediaStorageSOPClassUID = MRImageStorage
    metadata.MediaStorageSOPInstanceUID = UID(dicom_tags["SOPInstanceUID"])
    dicom = FileDataset(dicom_path, {}, file_meta=metadata, preamble=bytes(128))
    dicom.SOPClassUID = MRImageStorage
    for tag, value in dicom_tags.items():
        setattr(dicom, tag, value)
    dicom.save_as(dicom_path, enforce_file_format=True)

    token = "token-centinela-privado"
    (tmp_path / ".env.auth").write_text(f"CERBERUS_OIDC_CLIENT_SECRET={token}\n")
    monkeypatch.setenv("CERBERUS_OIDC_CLIENT_SECRET", token)
    monkeypatch.setenv("CERBERUS_DATA_DIR", str(data))
    monkeypatch.setenv("CERBERUS_STORAGE_DIR", str(storage))

    fixture = b"nifti fixture"
    sample_path = data / "001/t0/1_t0_gtv.nii.gz"
    sample_path.parent.mkdir(parents=True)
    sample_path.write_bytes(fixture)
    manifest = {
        "format": 1,
        **dicom_tags,
        "token": token,
        "files": [
            {"path": "001/t0/1_t0_gtv.nii.gz", "size": len(fixture), "sha256": hashlib.sha256(fixture).hexdigest()}
        ],
    }
    manifest_path = storage / "staging" / "fixture" / "manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps(manifest))
    snapshot = {
        "sample_manifest": json.loads(manifest_path.read_text()),
        "release": {"version": "1.2.419", "revision": "a" * 40},
        "logs": {**dicom_tags, "token": token},
    }
    monkeypatch.setattr(diagnostics.sys, "stdin", io.StringIO(json.dumps(snapshot)))
    destination = tmp_path / "diagnostico.json"
    try:
        assert diagnostics.main(["--snapshot-stdin", "--export", str(destination)]) == 0
    finally:
        dicom_path.unlink()
    output = capsys.readouterr()
    exported = destination.read_text()
    assert json.loads(exported) == json.loads(output.out)
    assert "SAMPLE_VERIFIED" in codes(json.loads(exported))
    assert "STORAGE_ACCESSIBLE" in codes(json.loads(exported))
    sentinels = [*dicom_tags, *dicom_tags.values(), token, ".env.auth", "1.2.419", "a" * 40, str(data), str(storage)]
    for sentinel in sentinels:
        assert sentinel not in exported + output.out + output.err
