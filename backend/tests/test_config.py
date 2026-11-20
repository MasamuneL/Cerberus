"""Tests de configuración (docs/PLAN_MVP.md §5)."""

from pathlib import Path

import pytest
import uvicorn
from pydantic import ValidationError

from cerberus_api import serve
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
        "APP_ORIGIN",
        "API_HOST",
        "API_PORT",
        "UI_PORT",
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
    assert s.app_origin == "http://localhost:5173"
    assert s.api_host == "127.0.0.1"
    assert s.api_port == 8000
    assert s.ui_port == 5173


def test_ui_port_derives_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CERBERUS_UI_PORT", "5174")
    s = Settings()
    assert s.ui_port == 5174
    assert s.cors_origins == ["http://localhost:5174"]
    assert s.app_origin == "http://localhost:5174"


def test_explicit_origins_win_over_ui_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CERBERUS_UI_PORT", "5174")
    monkeypatch.setenv("CERBERUS_CORS_ORIGINS", '["http://localhost:9999"]')
    monkeypatch.setenv("CERBERUS_APP_ORIGIN", "http://localhost:9999")
    s = Settings()
    assert s.cors_origins == ["http://localhost:9999"]
    assert s.app_origin == "http://localhost:9999"


@pytest.mark.parametrize("var", ["API_PORT", "UI_PORT"])
@pytest.mark.parametrize("value", ["0", "65536", "-1"])
def test_port_out_of_range_is_rejected(monkeypatch: pytest.MonkeyPatch, var: str, value: str) -> None:
    monkeypatch.setenv(f"CERBERUS_{var}", value)
    with pytest.raises(ValidationError):
        Settings()


def test_serve_uses_env_host_and_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CERBERUS_API_HOST", "0.0.0.0")
    monkeypatch.setenv("CERBERUS_API_PORT", "8011")
    get_settings.cache_clear()
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    monkeypatch.setattr(uvicorn, "run", lambda *a, **kw: calls.append((a, kw)))
    try:
        serve.main([])
        serve.main(["--reload"])
    finally:
        get_settings.cache_clear()
    assert calls[0] == (
        ("cerberus_api.main:app",),
        {"host": "0.0.0.0", "port": 8011, "reload": False, "reload_dirs": None},
    )
    assert calls[1][1]["reload"] is True
    assert calls[1][1]["reload_dirs"] == ["backend"]


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
