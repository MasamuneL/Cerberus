"""Paridad del paquete sin depender del daemon ni de imágenes publicadas."""

import copy
import importlib.util

import pytest

from cerberus_api.config import REPO_ROOT

spec = importlib.util.spec_from_file_location("release_package", REPO_ROOT / "tools/release/package.py")
assert spec and spec.loader
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


def test_distribution_preserves_contract() -> None:
    source = package.source_config()
    original = copy.deepcopy(source)
    backend = "ghcr.io/masamunel/cerberus-backend@sha256:" + "a" * 64
    frontend = "ghcr.io/masamunel/cerberus-frontend@sha256:" + "b" * 64
    config = package.distribution_config(source, backend, frontend)
    assert source == original
    assert config["networks"] == source["networks"]
    assert config["volumes"] == source["volumes"]
    for name, service in config["services"].items():
        if name == "setup-sample":
            assert service["user"] == "${CERBERUS_UID:-1000}:${CERBERUS_GID:-1000}"
            continue
        assert "build" not in service
        if name not in {"setup-secrets", "api", "worker"}:
            assert service.get("environment") == source["services"][name].get("environment")
    assert config["services"]["api"]["image"] == config["services"]["worker"]["image"] == backend
    assert config["services"]["worker"]["depends_on"]["setup-secrets"]["condition"] == "service_completed_successfully"


@pytest.mark.parametrize("image", ["latest", "image:1", "image@sha256:abcd", "secret?x=y"])
def test_distribution_rejects_unpinned_images(image: str) -> None:
    with pytest.raises(ValueError):
        package.distribution_config({}, image, image)


def test_distribution_generation_ignores_packager_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", "personal-project-name")
    monkeypatch.setenv("CERBERUS_HTTP_PORT", "19999")
    source = package.source_config()
    assert source["name"] == "cerberus"
    assert "19999" not in str(source)
    assert "personal-project-name" not in str(source)
