"""Muestra D3c: pruebas sin red, datos sintéticos y conservación de archivos."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import shutil
import tarfile
import urllib.error
from dataclasses import dataclass
from http.client import HTTPMessage
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from cerberus_api import sample
from cerberus_api.catalog import get_study
from conftest import MakeStudy


@dataclass
class Bundle:
    """Artefacto íntegro sintetizado localmente."""

    source: Path
    archive: Path
    manifest: Path
    raw: dict[str, Any]

    def save(self) -> None:
        """Persiste alteraciones controladas al manifest."""
        self.manifest.write_text(json.dumps(self.raw), encoding="utf-8")


@pytest.fixture
def bundle(tmp_path: Path, make_study: MakeStudy) -> Bundle:
    """Construye NIfTI reales pequeños y su TAR; nunca utiliza la muestra personal."""
    source = tmp_path / "source"
    make_study(source)
    archive = tmp_path / "sample.tar"
    files = []
    with tarfile.open(archive, "w", format=tarfile.USTAR_FORMAT) as output:
        for seq in sample.SAMPLE_SEQUENCES:
            relative = f"001/t0/1_t0_{seq}.nii.gz"
            path = source / relative
            content = path.read_bytes()
            files.append({"path": relative, "size": len(content), "sha256": hashlib.sha256(content).hexdigest()})
            info = tarfile.TarInfo(relative)
            info.size = len(content)
            output.addfile(info, io.BytesIO(content))
    content = archive.read_bytes()
    raw = {
        "format": 1,
        "version": sample.SAMPLE_VERSION,
        "archive": {
            "url": "https://example.org/sample.tar",
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        },
        "files": files,
    }
    manifest = tmp_path / "manifest.json"
    result = Bundle(source, archive, manifest, raw)
    result.save()
    return result


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Una prueba que olvide instalar transporte local falla antes de acceder a la red."""

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Los tests de muestra nunca usan red.")

    monkeypatch.setattr(sample.urllib.request, "build_opener", forbidden)


def serve(monkeypatch: pytest.MonkeyPatch, content: bytes | BaseException) -> list[str]:
    """Instala una respuesta HTTP en memoria y registra conexiones solicitadas."""
    calls: list[str] = []

    def request(url: str, timeout: int) -> io.BytesIO:
        calls.append(url)
        assert timeout == 60
        if isinstance(content, BaseException):
            raise content
        return io.BytesIO(content)

    monkeypatch.setattr(sample.urllib.request, "build_opener", lambda *args: SimpleNamespace(open=request))
    return calls


def test_install_catalog_and_repeat_offline(bundle: Bundle, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = tmp_path / "Data"
    calls = serve(monkeypatch, bundle.archive.read_bytes())
    assert "preparada" in sample.ensure_sample(bundle.manifest, data)
    detail = get_study(data, tmp_path / "results", "001", "t0")
    assert detail is not None and detail.has_gtv and detail.has_brain_mask
    assert detail.sequences == list(sample.SAMPLE_SEQUENCES)
    before = {path.name: (path.stat().st_mtime_ns, path.read_bytes()) for path in (data / "001/t0").iterdir()}
    assert "sin descarga" in sample.ensure_sample(bundle.manifest, data)
    assert len(calls) == 1
    assert before == {path.name: (path.stat().st_mtime_ns, path.read_bytes()) for path in (data / "001/t0").iterdir()}
    assert not list(data.glob(".cerberus-sample-*"))


def test_valid_existing_no_network(bundle: Bundle) -> None:
    assert "sin descarga" in sample.ensure_sample(bundle.manifest, bundle.source)


def test_none_skips_manifest_disk_and_network(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = tmp_path / "Data"
    monkeypatch.setenv("CERBERUS_SAMPLE_MODE", "none")
    assert sample.main(["--manifest", str(tmp_path / "missing.json"), "--data", str(data)]) == 0
    assert not data.exists()
    with pytest.raises(sample.SampleError, match="auto o none"):
        sample.ensure_sample(tmp_path / "missing", data, mode="disabled")


@pytest.mark.parametrize("content", [b"otros datos", b"version https://git-lfs.github.com/spec/v1\noid sha256:test\n"])
def test_existing_conflict_preserved(bundle: Bundle, content: bytes) -> None:
    path = bundle.source / bundle.raw["files"][0]["path"]
    path.write_bytes(content)
    before = {p.name: p.read_bytes() for p in path.parent.iterdir()}
    with pytest.raises(sample.SampleError, match="distinta|LFS"):
        sample.ensure_sample(bundle.manifest, bundle.source)
    assert before == {p.name: p.read_bytes() for p in path.parent.iterdir()}


def test_partial_existing_and_unrelated_preserved(
    bundle: Bundle, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = tmp_path / "Data"
    path = data / bundle.raw["files"][0]["path"]
    path.parent.mkdir(parents=True)
    original = bundle.source / bundle.raw["files"][0]["path"]
    shutil.copyfile(original, path)
    before = path.stat().st_mtime_ns
    unrelated = data / "private.txt"
    unrelated.write_bytes(b"datos propios")
    serve(monkeypatch, bundle.archive.read_bytes())
    sample.ensure_sample(bundle.manifest, data)
    assert path.stat().st_mtime_ns == before
    assert unrelated.read_bytes() == b"datos propios"


@pytest.mark.parametrize(
    "failure",
    [b"truncado", b"x" * 500_000, urllib.error.URLError("private-token"), KeyboardInterrupt()],
    ids=["truncated", "too-large", "network", "cancelled"],
)
def test_download_failure_cleanup_and_safe_retry(
    bundle: Bundle, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: bytes | BaseException
) -> None:
    data = tmp_path / "Data"
    serve(monkeypatch, failure)
    with pytest.raises((sample.SampleError, KeyboardInterrupt)):
        sample.ensure_sample(bundle.manifest, data)
    assert not (data / "001").exists()
    assert not list(data.glob(".cerberus-sample-*"))
    serve(monkeypatch, bundle.archive.read_bytes())
    assert "preparada" in sample.ensure_sample(bundle.manifest, data)


def test_archive_checksum_corruption(bundle: Bundle, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    content = bytearray(bundle.archive.read_bytes())
    content[-1] ^= 1
    serve(monkeypatch, bytes(content))
    with pytest.raises(sample.SampleError, match="corrupto"):
        sample.ensure_sample(bundle.manifest, tmp_path / "Data")


def test_no_space_before_download(bundle: Bundle, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sample.os, "fstatvfs", lambda fd: SimpleNamespace(f_bavail=0, f_frsize=4096))
    with pytest.raises(sample.SampleError, match="Espacio insuficiente"):
        sample.ensure_sample(bundle.manifest, tmp_path / "Data")


@pytest.mark.parametrize("level", ["root", "patient", "timepoint", "file", "lock", "ancestor"])
def test_symlinks_never_followed(bundle: Bundle, tmp_path: Path, level: str) -> None:
    data = tmp_path / "Data"
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "private"
    marker.write_bytes(b"intacto")
    if level == "root":
        data.symlink_to(outside, target_is_directory=True)
    elif level == "ancestor":
        data.symlink_to(outside, target_is_directory=True)
        data = data / "child"
    else:
        data.mkdir()
        if level == "lock":
            (data / ".cerberus-sample.lock").symlink_to(marker)
        elif level == "patient":
            (data / "001").symlink_to(outside, target_is_directory=True)
        elif level == "timepoint":
            (data / "001").mkdir()
            (data / "001/t0").symlink_to(outside, target_is_directory=True)
        else:
            (data / "001/t0").mkdir(parents=True)
            (data / "001/t0/1_t0_brain_mask.nii.gz").symlink_to(marker)
    with pytest.raises((sample.SampleError, OSError)):
        sample.ensure_sample(bundle.manifest, data)
    assert marker.read_bytes() == b"intacto"
    assert list(outside.iterdir()) == [marker]


@pytest.mark.parametrize(
    "value",
    [
        "../escape",
        "/001/t0/x",
        "001/t0/../x",
        "001\\t0\\x",
        "001/t1/1_t1_gtv.nii.gz",
        "002/t0/2_t0_gtv.nii.gz",
        "001/t0/1_t0_unknown.nii.gz",
        "001/t0/1_t0_ct.nii.gz",
        None,
        "001/t0/1_t0_gtv.nii.gz\x00",
    ],
)
def test_manifest_paths_reject_traversal(value: object) -> None:
    with pytest.raises(sample.SampleError):
        sample.validate_sample_path(value)


@pytest.mark.parametrize(
    "field,value", [("format", 2), ("version", "latest"), ("files", []), ("files", [True]), ("archive", None)]
)
def test_invalid_manifest_shapes(bundle: Bundle, field: str, value: object) -> None:
    bundle.raw[field] = value
    bundle.save()
    with pytest.raises(sample.SampleError):
        sample.load_manifest(bundle.manifest)


@pytest.mark.parametrize(
    "field,value",
    [
        ("url", "http://example.org/x"),
        ("url", "https://user:secret@example.org/x"),
        ("url", "https://example.org/x?token=private"),
        ("url", "https://example.org/x#fragment"),
        ("url", "https://example.org:invalid/x"),
        ("url", "https://example.org:8443/x"),
        ("size", True),
        ("size", -1),
        ("sha256", "bad"),
    ],
)
def test_invalid_archive_contract(bundle: Bundle, field: str, value: object) -> None:
    bundle.raw["archive"][field] = value
    bundle.save()
    with pytest.raises(sample.SampleError):
        sample.load_manifest(bundle.manifest)


def test_duplicate_missing_bad_hash_and_json(bundle: Bundle) -> None:
    original = bundle.manifest.read_text()
    bundle.raw["files"][1] = bundle.raw["files"][0]
    bundle.save()
    with pytest.raises(sample.SampleError, match="cuatro"):
        sample.load_manifest(bundle.manifest)
    bundle.manifest.write_text(original)
    raw = json.loads(original)
    raw["files"][0]["sha256"] = "f" * 63
    bundle.manifest.write_text(json.dumps(raw))
    with pytest.raises(sample.SampleError, match="SHA"):
        sample.load_manifest(bundle.manifest)
    bundle.manifest.write_text("{broken")
    with pytest.raises(sample.SampleError, match="leer"):
        sample.load_manifest(bundle.manifest)


@pytest.mark.parametrize(
    "attack",
    [
        "traversal",
        "symlink",
        "hardlink",
        "duplicate",
        "missing",
        "size",
        "sparse",
        "pax",
        "corrupt_file",
        "lfs",
        "directory",
    ],
)
def test_tar_rejects_unsafe_or_incomplete_members(bundle: Bundle, tmp_path: Path, attack: str) -> None:
    archive = tmp_path / "hostile.tar"
    with tarfile.open(archive, "w", format=tarfile.PAX_FORMAT) as output:
        for index, entry in enumerate(bundle.raw["files"]):
            if attack == "missing" and index == 0:
                continue
            content = (bundle.source / entry["path"]).read_bytes()
            info = tarfile.TarInfo(entry["path"])
            info.size = len(content)
            if index == 0:
                if attack == "traversal":
                    info.name = "../../escape"
                elif attack in ("symlink", "hardlink"):
                    info.type = tarfile.SYMTYPE if attack == "symlink" else tarfile.LNKTYPE
                    info.linkname = "../../private"
                    info.size = 0
                elif attack == "directory":
                    info.type, info.size = tarfile.DIRTYPE, 0
                elif attack == "size":
                    info.size -= 1
                elif attack == "sparse":
                    info.type = tarfile.GNUTYPE_SPARSE
                elif attack == "pax":
                    info.pax_headers = {"comment": "no permitido"}
                elif attack == "corrupt_file":
                    content = b"x" * len(content)
                elif attack == "lfs":
                    content = sample.LFS_PREFIX + b"x" * (len(content) - len(sample.LFS_PREFIX))
            output.addfile(info, io.BytesIO(content))
            if attack == "duplicate" and index == 0:
                output.addfile(info, io.BytesIO(content))
    staging = tmp_path / "staging"
    staging.mkdir()
    with pytest.raises(sample.SampleError):
        with archive.open("rb") as stream, sample.secure_directory(staging) as staging_fd:
            sample.extract_archive(stream, staging_fd, sample.load_manifest(bundle.manifest))
    assert not (tmp_path.parent / "escape").exists()


def test_tar_truncated_and_non_nifti(bundle: Bundle, tmp_path: Path) -> None:
    staging = tmp_path / "stage"
    staging.mkdir()
    broken = tmp_path / "broken.tar"
    broken.write_bytes(bundle.archive.read_bytes()[:800])
    with pytest.raises(sample.SampleError):
        with broken.open("rb") as stream, sample.secure_directory(staging) as staging_fd:
            sample.extract_archive(stream, staging_fd, sample.load_manifest(bundle.manifest))
    content = b"not a nifti"
    entry = sample.SampleFile("001/t0/1_t0_gtv.nii.gz", len(content), hashlib.sha256(content).hexdigest())
    with pytest.raises(sample.SampleError, match="NIfTI"):
        sample.verify_file(io.BytesIO(content), entry)


def test_concurrent_preparation_rejected(bundle: Bundle) -> None:
    with sample.secure_directory(bundle.source) as data_fd:
        fd = os.open(".cerberus-sample.lock", os.O_CREAT | os.O_RDWR, 0o600, dir_fd=data_fd)
        with os.fdopen(fd, "rb+") as lock:
            sample.fcntl.flock(lock, sample.fcntl.LOCK_EX)
            with pytest.raises(sample.SampleError, match="Otra preparación"):
                sample.ensure_sample(bundle.manifest, bundle.source)


def test_no_overwrite_if_file_appears_during_publish(
    bundle: Bundle, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = tmp_path / "Data"
    serve(monkeypatch, bundle.archive.read_bytes())
    original_link = sample.os.link

    def racing_link(source: Path, target: str, **kwargs: Any) -> None:
        fd = os.open(target, os.O_CREAT | os.O_WRONLY, 0o644, dir_fd=kwargs["dst_dir_fd"])
        with os.fdopen(fd, "wb") as stream:
            stream.write(b"datos propios nuevos")
        original_link(source, target, **kwargs)

    monkeypatch.setattr(sample.os, "link", racing_link)
    with pytest.raises(sample.SampleError, match="Apareció"):
        sample.ensure_sample(bundle.manifest, data)
    assert (data / bundle.raw["files"][0]["path"]).read_bytes() == b"datos propios nuevos"


def test_main_errors_hide_transport_secrets(
    bundle: Bundle, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    serve(monkeypatch, urllib.error.URLError("token=private /Users/secret/patient"))
    args = ["--manifest", str(bundle.manifest), "--data", str(tmp_path / "Data")]
    assert sample.main(args) == 1
    captured = capsys.readouterr()
    assert "Revise red" in captured.err
    assert "private" not in captured.err and "/Users" not in captured.err
    serve(monkeypatch, KeyboardInterrupt())
    assert sample.main(args) == 130


def test_release_builder_reproducible_pinned_and_allowlisted(bundle: Bundle, tmp_path: Path) -> None:
    location = Path(__file__).resolve().parents[2] / "tools/release/sample-build.py"
    spec = importlib.util.spec_from_file_location("sample_build", location)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (bundle.source / "private.dcm").write_bytes(b"no distribuir")
    first = tmp_path / "first.tar"
    second = tmp_path / "second.tar"
    module.build_sample(bundle.source, first, bundle.manifest)
    module.build_sample(bundle.source, second, bundle.manifest)
    assert first.read_bytes() == second.read_bytes()
    with tarfile.open(first) as archive:
        assert archive.getnames() == [entry["path"] for entry in bundle.raw["files"]]
        assert all(entry.uid == entry.gid == entry.mtime == 0 and not entry.uname for entry in archive)
    with pytest.raises(sample.SampleError, match="ya existe"):
        module.build_sample(bundle.source, first, bundle.manifest)
    (bundle.source / bundle.raw["files"][0]["path"]).write_bytes(b"version https://git-lfs.github.com/spec/v1")
    with pytest.raises(sample.SampleError, match="LFS"):
        module.build_sample(bundle.source, tmp_path / "third.tar", bundle.manifest)
    assert not (tmp_path / "third.tar").exists()


def test_committed_manifest_public_four_files() -> None:
    path = Path(__file__).resolve().parents[2] / "tools/release/sample-manifest.json"
    manifest = sample.load_manifest(path)
    assert len(manifest.files) == 4
    raw = path.read_text()
    assert "PatientName" not in raw and "PatientID" not in raw and "/Users/" not in raw
    assert "CC-BY-4.0" in raw and "10.7937/v9pn-2f72" in raw


def test_redirect_requires_https() -> None:
    handler = sample._HTTPSRedirect()
    with pytest.raises(sample.SampleError, match="HTTPS"):
        handler.redirect_request(
            sample.urllib.request.Request("https://example.org"),
            io.BytesIO(),
            302,
            "Found",
            HTTPMessage(),
            "http://example.org/x",
        )


def test_secure_directory_rejects_parent_and_fifo(bundle: Bundle, tmp_path: Path) -> None:
    with pytest.raises(sample.SampleError):
        with sample.secure_directory(tmp_path / ".." / "Data"):
            pass
    fifo = bundle.source / bundle.raw["files"][0]["path"]
    fifo.unlink()
    os.mkfifo(fifo)
    with pytest.raises(sample.SampleError, match="regular"):
        sample.ensure_sample(bundle.manifest, bundle.source)
