"""Tests de configuración (docs/PLAN_MVP.md §5)."""

from pathlib import Path

import pytest

from cerberus_api.config import REPO_ROOT, Settings, get_settings


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Aísla los tests de cualquier `CERBERUS_*` del entorno real."""
    for var in (
        "DATA_DIR",
        "STORAGE_DIR",
        "MODELS_DIR",
        "REDIS_URL",
        "MAX_UPLOAD_MB",
        "MAX_ZIP_UNCOMPRESSED_MB",
        "CORS_ORIGINS",
    ):
        monkeypatch.delenv(f"CERBERUS_{var}", raising=False)


def test_repo_root_contains_backend() -> None:
    assert (REPO_ROOT / "backend" / "cerberus_api" / "config.py").is_file()


def test_defaults() -> None:
    s = Settings()
    assert s.data_dir == REPO_ROOT / "Data"
    assert s.storage_dir == REPO_ROOT / "storage"
    assert s.models_dir == REPO_ROOT / "models"
    assert s.redis_url == "redis://localhost:6379"
    assert s.max_upload_mb == 2048
    assert s.max_zip_uncompressed_mb == 4096
    assert s.cors_origins == ["http://localhost:5173"]


def test_storage_subdirs() -> None:
    s = Settings()
    assert s.results_dir == REPO_ROOT / "storage" / "results"
    assert s.staging_dir == REPO_ROOT / "storage" / "staging"
    assert s.tmp_dir == REPO_ROOT / "storage" / "tmp"


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CERBERUS_REDIS_URL", "redis://otro:6380")
    monkeypatch.setenv("CERBERUS_MAX_UPLOAD_MB", "10")
    monkeypatch.setenv("CERBERUS_CORS_ORIGINS", '["http://a.test", "http://b.test"]')
    s = Settings()
    assert s.redis_url == "redis://otro:6380"
    assert s.max_upload_mb == 10
    assert s.cors_origins == ["http://a.test", "http://b.test"]


def test_relative_path_resolves_under_repo_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CERBERUS_DATA_DIR", "otros/datos")
    assert Settings().data_dir == REPO_ROOT / "otros" / "datos"


def test_absolute_path_kept(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CERBERUS_STORAGE_DIR", str(tmp_path))
    s = Settings()
    assert s.storage_dir == tmp_path
    assert s.tmp_dir == tmp_path / "tmp"


def test_get_settings_is_cached() -> None:
    get_settings.cache_clear()
    assert get_settings() is get_settings()
    get_settings.cache_clear()
