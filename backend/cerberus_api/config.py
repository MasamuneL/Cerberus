"""Configuración del backend (docs/PLAN_MVP.md §5).

Todas las variables usan el prefijo `CERBERUS_` (ej. `CERBERUS_DATA_DIR`). Las rutas relativas se resuelven
contra la raíz del repo, no contra el directorio de trabajo, para que API y worker vean las mismas carpetas.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/cerberus_api/config.py → parents[2] = raíz del repo
REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Ajustes leídos del entorno (prefijo `CERBERUS_`)."""

    model_config = SettingsConfigDict(env_prefix="CERBERUS_")

    data_dir: Path = Path("Data")
    storage_dir: Path = Path("storage")
    models_dir: Path = Path("models")
    redis_url: str = "redis://localhost:6379"
    max_upload_mb: int = 2048
    max_zip_uncompressed_mb: int = 4096
    cors_origins: list[str] = ["http://localhost:5173"]

    @field_validator("data_dir", "storage_dir", "models_dir", mode="after")
    @classmethod
    def _resolve_against_repo(cls, value: Path) -> Path:
        """Las rutas relativas cuelgan de la raíz del repo; las absolutas se respetan."""
        return value if value.is_absolute() else REPO_ROOT / value

    # Subcarpetas de storage/ (contrato de §6)
    @property
    def results_dir(self) -> Path:
        """`storage/results/<patient>/<timepoint>/monai_seg.*`."""
        return self.storage_dir / "results"

    @property
    def staging_dir(self) -> Path:
        """`storage/staging/<upload_id>/` (manifest + series convertidas)."""
        return self.storage_dir / "staging"

    @property
    def tmp_dir(self) -> Path:
        """`storage/tmp/<uuid>/`: DICOM crudo, se borra siempre en un `finally`."""
        return self.storage_dir / "tmp"


@lru_cache
def get_settings() -> Settings:
    """Instancia única de `Settings` (cacheada; en tests usa `Settings()` directamente)."""
    return Settings()
