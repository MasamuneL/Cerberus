"""Configuración del backend (docs/PLAN_MVP.md §5).

Todas las variables usan el prefijo `CERBERUS_` (ej. `CERBERUS_DATA_DIR`). Las rutas relativas se resuelven
contra la raíz del repo, no contra el directorio de trabajo, para que API y worker vean las mismas carpetas.
"""

from functools import lru_cache
from ipaddress import ip_address
from pathlib import Path
from typing import Self
from urllib.parse import SplitResult, urlsplit

from pydantic import AnyHttpUrl, Field, SecretStr, TypeAdapter, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from cerberus_api.identity import AuthMode

# backend/cerberus_api/config.py → parents[2] = raíz del repo
REPO_ROOT = Path(__file__).resolve().parents[2]
_HTTP_URL = TypeAdapter(AnyHttpUrl)


def _parse_auth_url(value: str) -> SplitResult:
    """Valida sin normalizar: issuer, origen y backchannel no llevan credenciales ni query."""
    if not value or "\\" in value or any(char.isspace() or ord(char) < 32 for char in value):
        raise ValueError("URL de autenticación inválida")
    parsed = urlsplit(value)
    _HTTP_URL.validate_python(value)
    if (
        not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or "?" in value
        or "#" in value
    ):
        raise ValueError("La URL de autenticación requiere host y no admite credenciales, query ni fragmento")
    # Acceder a port valida también el rango y rechaza puertos no numéricos.
    if parsed.port == 0:
        raise ValueError("El puerto de autenticación debe ser positivo")
    return parsed


def _is_loopback(host: str) -> bool:
    """Sin DNS: solo localhost exacto y direcciones IP de loopback canónicas."""
    if host == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


class Settings(BaseSettings):
    """Ajustes leídos del entorno (prefijo `CERBERUS_`)."""

    model_config = SettingsConfigDict(env_prefix="CERBERUS_", hide_input_in_errors=True)

    data_dir: Path = Path("Data")
    storage_dir: Path = Path("storage")
    models_dir: Path = Path("models")
    redis_url: str = "redis://localhost:6379"
    max_upload_mb: int = 2048
    max_zip_uncompressed_mb: int = 4096
    cors_origins: list[str] = ["http://localhost:5173"]
    auth_mode: AuthMode = "off"
    app_origin: str = "http://localhost:5173"
    oidc_issuer_url: str | None = None
    oidc_backchannel_url: str | None = None
    oidc_client_id: str = "cerberus-web"
    oidc_client_secret: SecretStr | None = None
    auth_cookie_secure: bool = True
    auth_idle_timeout_seconds: int = Field(default=1800, gt=0)
    auth_absolute_timeout_seconds: int = Field(default=3600, gt=0)

    @model_validator(mode="after")
    def _validate_auth(self) -> Self:
        """Configuración OIDC explícita; nunca degrada automáticamente al modo sin auth."""
        origin = _parse_auth_url(self.app_origin)
        if origin.path:
            raise ValueError("CERBERUS_APP_ORIGIN debe ser un origen sin ruta ni barra final")
        loopback_http = origin.scheme == "http" and _is_loopback(origin.hostname or "")
        if origin.scheme == "http" and not loopback_http:
            raise ValueError("CERBERUS_APP_ORIGIN requiere HTTPS salvo HTTP de loopback")
        if not self.auth_cookie_secure and not loopback_http:
            raise ValueError("Una cookie insegura solo se admite con origen HTTP de loopback")
        if self.auth_absolute_timeout_seconds < self.auth_idle_timeout_seconds:
            raise ValueError("El timeout absoluto no puede ser menor que el de inactividad")

        if self.oidc_issuer_url is not None:
            issuer = _parse_auth_url(self.oidc_issuer_url)
            if issuer.scheme == "http" and not _is_loopback(issuer.hostname or ""):
                raise ValueError("El issuer público requiere HTTPS salvo HTTP de loopback")
        if self.oidc_backchannel_url is not None:
            _parse_auth_url(self.oidc_backchannel_url)
        else:
            self.oidc_backchannel_url = self.oidc_issuer_url

        if self.auth_mode == "oidc":
            if self.oidc_issuer_url is None:
                raise ValueError("CERBERUS_OIDC_ISSUER_URL es obligatorio en modo oidc")
            if self.oidc_client_secret is None or not self.oidc_client_secret.get_secret_value().strip():
                raise ValueError("CERBERUS_OIDC_CLIENT_SECRET es obligatorio en modo oidc")
            if not self.oidc_client_id.strip():
                raise ValueError("CERBERUS_OIDC_CLIENT_ID no puede estar vacío en modo oidc")
            if any("*" in origin for origin in self.cors_origins):
                raise ValueError("CORS no admite comodines en modo oidc")
        return self

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
