"""Fallo de paquete o identidad no habilita actualización destructiva."""

import hashlib
import json
from pathlib import Path

import pytest

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
