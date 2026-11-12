"""Pruebas sin red del artefacto de distribución, su identidad y exclusión de archivos privados."""

import hashlib
import importlib.util
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/release"))
spec = importlib.util.spec_from_file_location("release_build", ROOT / "tools/release/build.py")
assert spec and spec.loader
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)

BACKEND = "ghcr.io/masamunel/cerberus-backend@sha256:" + "a" * 64
FRONTEND = "ghcr.io/masamunel/cerberus-frontend@sha256:" + "b" * 64
REVISION = "c" * 40


@pytest.fixture
def source() -> dict[str, Any]:
    return {
        "services": {
            "api": {"build": ".", "image": "local", "environment": {"MODE": "oidc"}},
            "worker": {"build": ".", "depends_on": {}},
            "setup-secrets": {"volumes": [], "environment": {}},
            "setup-identity": {},
            "frontend": {"build": "."},
            "redis": {"image": "redis@sha256:" + "d" * 64},
        },
        "volumes": {"sessions": {}},
        "networks": {"internal": {"internal": True}},
    }


@pytest.fixture
def resources() -> dict[str, bytes]:
    return {
        "docker/keycloak/realm.json": b'{"realm":"cerberus"}',
        "docker/keycloak/themes/cerberus/login/theme.properties": b"parent=keycloak",
        "docker/keycloak/themes/cerberus/login/resources/fonts/OFL.txt": b"SIL OPEN FONT LICENSE",
        "tools/setup/start.py": b'print("inicio")\n',
        "start.sh": b"#!/bin/sh\n",
        "start.command": b"#!/bin/sh\n",
        "start.ps1": b"# inicio\n",
    }


def test_archive_is_reproducible_complete_and_pinned(
    tmp_path: Path,
    source: dict[str, Any],
    resources: dict[str, bytes],
) -> None:
    manifest = build.release_manifest("candidate-123", REVISION, BACKEND, FRONTEND)
    first, second = tmp_path / "primero.zip", tmp_path / "segundo.zip"
    digest = build.build_archive(first, source, manifest, resources)
    assert digest == build.build_archive(second, source, manifest, dict(reversed(list(resources.items()))))
    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as archive:
        assert set(archive.namelist()) == set(resources) | {"compose.yaml", "release.json", "SHA256SUMS", "LEEME.md"}
        assert json.loads(archive.read("release.json")) == manifest
        checksums = archive.read("SHA256SUMS").decode().splitlines()
        assert len(checksums) == len(archive.namelist()) - 1
        for line in checksums:
            expected, name = line.split("  ", 1)
            assert hashlib.sha256(archive.read(name)).hexdigest() == expected
        config = json.loads(archive.read("compose.yaml"))
        assert config["services"]["api"]["image"] == config["services"]["worker"]["image"] == BACKEND
        assert config["services"]["frontend"]["image"] == FRONTEND
        assert config["services"]["redis"] == source["services"]["redis"]
        assert all("build" not in service for service in config["services"].values())
        assert archive.getinfo("start.sh").external_attr >> 16 & 0o777 == 0o755
        assert archive.getinfo("start.command").external_attr >> 16 & 0o777 == 0o755


@pytest.mark.parametrize(
    "version,revision,image",
    [
        ("latest", REVISION, BACKEND),
        ("dev", REVISION, BACKEND),
        ("../escape", REVISION, BACKEND),
        ("v1", "abc123", BACKEND),
        ("v1", REVISION, "image:latest"),
        ("v1", REVISION, "image:latest@sha256:" + "a" * 64),
        ("v1", REVISION, "https://token@registry/image@sha256:" + "a" * 64),
    ],
)
def test_manifest_rejects_mutable_or_unsafe_identity(version: str, revision: str, image: str) -> None:
    with pytest.raises(ValueError):
        build.release_manifest(version, revision, image, FRONTEND)


@pytest.mark.parametrize(
    "name",
    [
        "../start.sh",
        "/start.sh",
        "tools/setup/../../.env.auth",
        "tools/setup/.env.auth",
        "tools/setup/__pycache__/start.pyc",
        "Data/001/t0/GTV.nii.gz",
        "storage/results/result.json",
        "tools/setup/credentials.json",
        "models/weights.pt",
        "docker/keycloak/themes/cerberus/secret.key",
        "tools\\setup\\start.py",
        "tools/setup/.git/config",
    ],
)
def test_allowlist_excludes_private_paths(name: str) -> None:
    assert not build.allowed_resource(name)


def test_allowlist_rejects_checksum_line_injection() -> None:
    assert not build.allowed_resource("tools/setup/file\ninjected.py")


def test_failed_package_preserves_previous_output(
    tmp_path: Path,
    source: dict[str, Any],
    resources: dict[str, bytes],
) -> None:
    output = tmp_path / "release.zip"
    output.write_bytes(b"previous version")
    manifest = build.release_manifest("v1", REVISION, BACKEND, FRONTEND)
    resources[".env.auth"] = b"private synthetic secret"
    with pytest.raises(ValueError, match="lista permitida"):
        build.build_archive(output, source, manifest, resources)
    assert output.read_bytes() == b"previous version"
    assert list(tmp_path.iterdir()) == [output]


def test_missing_identity_license_fails(
    tmp_path: Path,
    source: dict[str, Any],
    resources: dict[str, bytes],
) -> None:
    del resources["docker/keycloak/themes/cerberus/login/resources/fonts/OFL.txt"]
    with pytest.raises(ValueError, match="licencia"):
        build.build_archive(
            tmp_path / "release.zip", source, build.release_manifest("v1", REVISION, BACKEND, FRONTEND), resources
        )


def test_commit_resources_ignore_local_files_and_reject_symlinks(tmp_path: Path) -> None:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True, text=True).stdout.strip()

    git("init", "-q")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Test")
    (tmp_path / "start.sh").write_text("committed\n")
    git("add", "start.sh")
    git("commit", "-qm", "fixture")
    revision = git("rev-parse", "HEAD")
    (tmp_path / "start.sh").write_text("private local content\n")
    (tmp_path / ".env.auth").write_text("synthetic secret\n")
    assert build.committed_resources(tmp_path, revision) == {"start.sh": b"committed\n"}
    (tmp_path / "start.command").symlink_to(".env.auth")
    git("add", "start.command")
    git("commit", "-qm", "symlink fixture")
    with pytest.raises(ValueError, match="no regular"):
        build.committed_resources(tmp_path, git("rev-parse", "HEAD"))


def test_workflows_pin_actions_and_never_publish_pr_images() -> None:
    import re

    workflows = ROOT / ".github/workflows"
    for workflow in workflows.glob("*.yml"):
        for action in re.findall(r"uses: ([^\s#]+)", workflow.read_text()):
            assert re.fullmatch(r"[a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+@[a-f0-9]{40}", action)
    ci = (workflows / "ci.yml").read_text()
    assert "push: false" in ci and "push: true" not in ci and "packages: write" not in ci
    candidate = (workflows / "candidate.yml").read_text()
    assert "workflow_dispatch:" in candidate and "default: false" in candidate
    assert "release:" not in candidate and "contents: write" not in candidate
    assert "DOCKER_CONFIG=$(mktemp -d)" in candidate
