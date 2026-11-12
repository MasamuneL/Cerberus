"""Fallo de paquete o identidad no habilita actualización destructiva."""

import hashlib
import json
from pathlib import Path

import pytest

from cerberus_api import release_state
from cerberus_api.release_state import check_update, verify_package


def test_package_integrity_and_mixed_images(tmp_path: Path) -> None:
    images = {
        "backend": "ghcr.io/example/backend@sha256:" + "a" * 64,
        "frontend": "ghcr.io/example/frontend@sha256:" + "b" * 64,
    }
    manifest = {"format": 1, "revision": "c" * 40, "images": images}
    config = {
        "services": {
            name: {"image": images["frontend" if name == "frontend" else "backend"]}
            for name in ("api", "worker", "setup-secrets", "setup-identity", "frontend")
        }
    }
    (tmp_path / "release.json").write_text(json.dumps(manifest))
    (tmp_path / "compose.yaml").write_text(json.dumps(config))

    def checksums() -> None:
        (tmp_path / "SHA256SUMS").write_text(
            "".join(
                hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() + "  " + name + "\n"
                for name in ("release.json", "compose.yaml")
            )
        )

    checksums()
    assert verify_package(tmp_path) == config
    (tmp_path / "compose.yaml").write_text("corrupt")
    with pytest.raises(ValueError, match="corrupto"):
        verify_package(tmp_path)
    config["services"]["worker"]["image"] = images["frontend"]
    (tmp_path / "compose.yaml").write_text(json.dumps(config))
    checksums()
    with pytest.raises(ValueError, match="mezcladas"):
        verify_package(tmp_path)


@pytest.mark.parametrize("jobs", [1, -1])
def test_update_postpones_jobs(jobs: int) -> None:
    with pytest.raises(ValueError, match="posponer"):
        check_update({}, {}, jobs)


def test_update_preserves_identity() -> None:
    config = {
        "name": "qa",
        "volumes": {"db": {}},
        "services": {
            service: {"image": service + "@sha256:" + "a" * 64} for service in ("redis", "keycloak", "auth-db")
        },
    }
    check_update(config, config, 0)
    changed = json.loads(json.dumps(config))
    changed["services"]["auth-db"]["image"] = "different"
    with pytest.raises(ValueError, match="identidad"):
        check_update(config, changed, 0)


def test_active_job_count() -> None:
    import asyncio

    from cerberus_api.release_state import active_job_count

    class Client:
        async def zcard(self, key: str) -> int:
            assert key == "arq:queue"
            return 2

        async def scan_iter(self, *, match: str):
            assert match == "arq:in-progress:*"
            yield b"job"

    assert asyncio.run(active_job_count(Client())) == 3


def release_fixture(root: Path, revision: str = "a" * 40) -> Path:
    """Crea un paquete mínimo válido con estado de aplicación explícito."""
    root.mkdir(parents=True)
    images = {
        "backend": "ghcr.io/example/backend@sha256:" + "b" * 64,
        "frontend": "ghcr.io/example/frontend@sha256:" + "c" * 64,
    }
    manifest = {"format": 1, "state_format": 1, "version": "candidate", "revision": revision, "images": images}
    config = {
        "name": "cerberus",
        "volumes": {name: {} for name in release_state.VOLUME_NAMES},
        "services": {
            name: {"image": images["frontend" if name == "frontend" else "backend"]}
            for name in ("api", "worker", "frontend", "setup-secrets", "setup-identity", "setup-sample")
        },
    }
    config["services"].update(
        {name: {"image": name + "@sha256:" + "d" * 64} for name in ("redis", "keycloak", "auth-db")}
    )
    (root / "release.json").write_text(json.dumps(manifest))
    (root / "compose.yaml").write_text(json.dumps(config))
    (root / "SHA256SUMS").write_text(
        "".join(
            hashlib.sha256((root / name).read_bytes()).hexdigest() + "  " + name + "\n"
            for name in ("release.json", "compose.yaml")
        )
    )
    return root


def test_update_requires_explicit_state_compatibility(tmp_path: Path) -> None:
    current = release_fixture(tmp_path / "current")
    candidate = release_fixture(tmp_path / "candidate", "e" * 40)
    release_state.validate_release_pair(current, candidate)
    manifest = json.loads((candidate / "release.json").read_text())
    manifest.pop("state_format")
    (candidate / "release.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        release_state.validate_release_pair(current, candidate)


def test_cold_backup_restore_preserves_state_and_rewrites_new_identity(tmp_path: Path) -> None:
    current = release_fixture(tmp_path / "current")
    (current / ".env").write_text("CERBERUS_DATA_PATH='/old/private/Data'\nCOMPOSE_PROJECT_NAME='old'\n")
    (current / ".env.auth").write_text("CERBERUS_AUTH_DB_PASSWORD='private-secret'\n")
    sources = {
        name: tmp_path / ("source-" + name) for name in ("Data", "storage", "models", *release_state.VOLUME_NAMES)
    }
    for source in sources.values():
        source.mkdir()
        (source / "preserved").write_text("private-state")
    (sources["storage"] / "tmp").mkdir()
    (sources["storage"] / "tmp/raw.dcm").write_text("PatientName")
    (sources["storage"] / "worker.log").write_text("private-log")
    backup = tmp_path / "backup"
    backup.mkdir(mode=0o700)
    (backup / "database.dump").write_bytes(b"PGDMPprivate-database")
    release_state.create_backup(current, backup, sources, helper_image="ghcr.io/example/backend@sha256:" + "b" * 64)
    target = tmp_path / "restore"
    destinations = {name: tmp_path / ("destination-" + name) for name in release_state.VOLUME_NAMES}
    release_state.restore_backup(backup, target, destinations, project="cerberus-restore-test")
    assert (target / "Data/preserved").read_text() == "private-state"
    assert (target / ".env.auth").read_text() == "CERBERUS_AUTH_DB_PASSWORD='private-secret'\n"
    assert "old/private" not in (target / ".env").read_text()
    assert "cerberus-restore-test" in (target / ".env").read_text()
    assert not (target / "storage/tmp/raw.dcm").exists()
    assert not (target / "storage/worker.log").exists()
    assert all((destination / "preserved").read_text() == "private-state" for destination in destinations.values())
    assert (backup / "backup.json").stat().st_mode & 0o077 == 0
    with pytest.raises(ValueError, match="vacío"):
        release_state.restore_backup(backup, target, destinations, project="cerberus-restore-test")


def test_restore_rejects_corruption_before_writing(tmp_path: Path) -> None:
    backup = tmp_path / "backup"
    backup.mkdir()
    (backup / "backup.json").write_text('{"format":1,"archive_sha256":"' + "a" * 64 + '"}')
    (backup / "state.tar").write_bytes(b"corrupt")
    target = tmp_path / "target"
    with pytest.raises(ValueError):
        release_state.restore_backup(backup, target, {}, project="cerberus-restore-test")
    assert not target.exists()


def test_activation_retains_previous_package_and_configuration(tmp_path: Path) -> None:
    current = release_fixture(tmp_path / "current")
    candidate = release_fixture(tmp_path / "candidate", "e" * 40)
    (current / ".env").write_text("CERBERUS_HTTP_PORT=8082\n")
    (current / "Data").mkdir()
    (current / "Data/untouched").write_bytes(b"private")
    release_state.activate_package(current, candidate)
    assert json.loads((current / "release.json").read_text())["revision"] == "e" * 40
    assert (current / ".cerberus-versions" / ("a" * 40) / "release.json").is_file()
    assert (current / ".env").read_text() == "CERBERUS_HTTP_PORT=8082\n"
    assert (current / "Data/untouched").read_bytes() == b"private"


def test_pulled_image_labels_must_match_release_before_activation(tmp_path: Path) -> None:
    candidate = release_fixture(tmp_path / "candidate")
    labels = {
        name: {"version": "candidate", "revision": "a" * 40, "architecture": "amd64", "os": "linux"}
        for name in ("backend", "frontend")
    }
    release_state.validate_image_labels(candidate, labels)
    labels["backend"]["revision"] = "e" * 40
    with pytest.raises(ValueError):
        release_state.validate_image_labels(candidate, labels)


@pytest.mark.parametrize("service", release_state.IDENTITY_SERVICES)
def test_update_rejects_identity_configuration_changes(service: str) -> None:
    config = {
        "services": {name: {"image": name, "environment": {"SAFE": "old"}} for name in release_state.IDENTITY_SERVICES}
    }
    changed = json.loads(json.dumps(config))
    changed["services"][service]["environment"]["SAFE"] = "changed"
    with pytest.raises(ValueError, match="identidad"):
        check_update(config, changed, 0)


def test_verify_package_accepts_symlinked_ancestor_but_not_linked_resource(tmp_path: Path) -> None:
    current = release_fixture(tmp_path / "current")
    alias = tmp_path / "alias"
    alias.symlink_to(tmp_path, target_is_directory=True)
    assert verify_package(alias / "current") == verify_package(current)
    target = current / "compose.yaml"
    target.rename(current / "actual-compose")
    target.symlink_to(current / "actual-compose")
    with pytest.raises(ValueError, match="enlazado"):
        verify_package(current)


def test_verify_package_checks_setup_sample_image(tmp_path: Path) -> None:
    current = release_fixture(tmp_path / "current")
    config = json.loads((current / "compose.yaml").read_text())
    config["services"]["setup-sample"]["image"] = config["services"]["frontend"]["image"]
    (current / "compose.yaml").write_text(json.dumps(config))
    (current / "SHA256SUMS").write_text(
        "".join(
            release_state.digest_file(current / name) + "  " + name + "\n" for name in ("release.json", "compose.yaml")
        )
    )
    with pytest.raises(ValueError, match="mezcladas"):
        verify_package(current)


def test_activation_restores_previous_package_if_copy_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    current = release_fixture(tmp_path / "current")
    candidate = release_fixture(tmp_path / "candidate", "e" * 40)
    copy = release_state.copy_package

    def failing_copy(source: Path, destination: Path) -> None:
        if source == candidate:
            (destination / "compose.yaml").write_text("partial")
            raise OSError("Disco lleno")
        copy(source, destination)

    monkeypatch.setattr(release_state, "copy_package", failing_copy)
    with pytest.raises(OSError, match="Disco lleno"):
        release_state.activate_package(current, candidate)
    assert verify_package(current)
    assert json.loads((current / "release.json").read_text())["revision"] == "a" * 40


@pytest.mark.parametrize("name", ["storage/tmp/patient.dcm", "storage/logs/private.txt", "storage/private.log"])
def test_backup_filter_excludes_raw_dicom_and_logs(name: str) -> None:
    import tarfile

    assert release_state.backup_filter(tarfile.TarInfo(name)) is None


def test_backup_filter_rejects_links() -> None:
    import tarfile

    member = tarfile.TarInfo("Data/link")
    member.type = tarfile.SYMTYPE
    with pytest.raises(ValueError, match="enlaces"):
        release_state.backup_filter(member)


def test_main_invalid_input_is_redacted(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr("sys.argv", ["release_state", "--operation", "verify-backup", "--backup", "/private-secret"])
    assert release_state.main() == 1
    assert "private-secret" not in capsys.readouterr().out


def test_incomplete_archive_is_rejected_before_destination_creation(tmp_path: Path) -> None:
    import tarfile

    backup = tmp_path / "backup"
    backup.mkdir()
    with tarfile.open(backup / "state.tar", "w") as archive:
        member = tarfile.TarInfo("Data")
        member.type = tarfile.DIRTYPE
        archive.addfile(member)
    helper = "ghcr.io/example/backend@sha256:" + "a" * 64
    (backup / "helper-image.txt").write_text(helper + "\n")
    (backup / "database.dump").write_bytes(b"PGDMPprivate")
    (backup / "backup.json").write_text(
        json.dumps(
            {
                "format": 1,
                "state_format": 1,
                "volumes": list(release_state.VOLUME_NAMES),
                "helper_image": helper,
                "archive_sha256": release_state.digest_file(backup / "state.tar"),
                "database_sha256": release_state.digest_file(backup / "database.dump"),
            }
        )
    )
    destination = tmp_path / "restore"
    with pytest.raises(ValueError, match="incompleto"):
        release_state.restore_backup(backup, destination, {}, project="cerberus-restore-test")
    assert not destination.exists()
