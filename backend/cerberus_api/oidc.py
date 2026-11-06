"""Cliente confidencial OIDC: Authlib para OAuth/PKCE y validación OIDC, joserfc para firma."""

import time
from collections.abc import Callable
from typing import Any, cast
from urllib.parse import unquote, urlsplit

import httpx2 as httpx
from authlib.integrations.base_client.errors import OAuthError
from authlib.integrations.httpx_client import AsyncOAuth2Client
from authlib.oidc.core import CodeIDToken
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet, KeySetSerialization

from cerberus_api.config import Settings, _parse_auth_url
from cerberus_api.identity import Principal, Role
from cerberus_api.sessions import LoginTransaction


class OIDCUnavailable(RuntimeError):
    """Proveedor o metadata no disponibles; no se debe ofrecer acceso anónimo."""


class OIDCInvalid(RuntimeError):
    """Código o ID Token inválido; sin información sensible en el mensaje público."""


class OIDCForbidden(RuntimeError):
    """Identidad válida sin roles de aplicación admitidos."""


class OIDCClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.settings = settings
        self.issuer = settings.oidc_issuer_url or ""
        self.backchannel = settings.oidc_backchannel_url or self.issuer
        self.redirect_uri = settings.app_origin + "/api/auth/callback"
        self.transport = transport
        self.clock = clock

    async def _get_json(self, url: str) -> dict[str, Any]:
        """Sin redirecciones ni tokens: metadata/JWKS solo desde el transporte configurado."""
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=5, follow_redirects=False) as client:
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()
            if not isinstance(data, dict):
                raise ValueError("Respuesta inválida")
            return data
        except (httpx.HTTPError, ValueError) as error:
            raise OIDCUnavailable("Proveedor de identidad no disponible") from error

    def _endpoint(self, endpoint: Any, *, public: bool = False) -> str:
        """El backchannel cambia el transporte del mismo realm, nunca el issuer validado."""
        try:
            if not isinstance(endpoint, str):
                raise ValueError("Endpoint ausente")
            _parse_auth_url(endpoint)
            if any(part in (".", "..") for part in unquote(urlsplit(endpoint).path).split("/")):
                raise ValueError("Ruta no canónica")
            for source in (self.issuer, self.backchannel):
                prefix = source.rstrip("/") + "/"
                if endpoint.startswith(prefix):
                    target = self.issuer if public else self.backchannel
                    return target.rstrip("/") + "/" + endpoint[len(prefix) :]
            raise ValueError("Endpoint ajeno al realm configurado")
        except ValueError as error:
            raise OIDCUnavailable("Metadata de identidad inválida") from error

    async def _metadata(self) -> dict[str, Any]:
        """Comprueba toda la metadata antes de enviar credenciales al endpoint de tokens."""
        metadata = await self._get_json(self.backchannel.rstrip("/") + "/.well-known/openid-configuration")
        if metadata.get("issuer") != self.issuer:
            raise OIDCUnavailable("Metadata de identidad inválida")
        return {
            "authorization_endpoint": self._endpoint(metadata.get("authorization_endpoint"), public=True),
            "token_endpoint": self._endpoint(metadata.get("token_endpoint")),
            "jwks_uri": self._endpoint(metadata.get("jwks_uri")),
        }

    def _oauth_client(self) -> AsyncOAuth2Client:
        """Sin renovación silenciosa ni persistencia de tokens del proveedor."""
        secret = self.settings.oidc_client_secret
        return AsyncOAuth2Client(
            client_id=self.settings.oidc_client_id,
            client_secret=secret.get_secret_value() if secret else None,
            scope="openid",
            redirect_uri=self.redirect_uri,
            code_challenge_method="S256",
            token_endpoint_auth_method="client_secret_basic",
            transport=self.transport,
            timeout=5,
            follow_redirects=False,
        )

    async def authorization_url(self, transaction: LoginTransaction) -> str:
        """Authlib calcula PKCE; callback fijo y proveedor en español, sin return_to arbitrario."""
        metadata = await self._metadata()
        client = self._oauth_client()
        try:
            url, _ = client.create_authorization_url(
                metadata["authorization_endpoint"],
                state=transaction.state,
                nonce=transaction.nonce,
                code_verifier=transaction.code_verifier,
                ui_locales="es",
            )
        finally:
            await cast(httpx.AsyncClient, client).aclose()
        return url

    async def exchange_code(self, code: str, transaction: LoginTransaction) -> Principal:
        """Verifica firma RS256, claims OIDC y roles antes de devolver una identidad utilizable."""
        metadata = await self._metadata()
        try:
            client = self._oauth_client()
            try:
                token = await client.fetch_token(
                    metadata["token_endpoint"],
                    grant_type="authorization_code",
                    code=code,
                    code_verifier=transaction.code_verifier,
                )
            finally:
                await cast(httpx.AsyncClient, client).aclose()
        except httpx.HTTPStatusError as error:
            if error.response.status_code >= 500:
                raise OIDCUnavailable("Proveedor de identidad no disponible") from None
            raise OIDCInvalid("No se pudo completar el inicio de sesión") from None
        except httpx.HTTPError:
            raise OIDCUnavailable("Proveedor de identidad no disponible") from None
        except (OAuthError, ValueError):
            raise OIDCInvalid("No se pudo completar el inicio de sesión") from None

        # Claves nuevas en cada login: admite rotación sin conservar tokens ni una caché obsoleta.
        jwks = await self._get_json(metadata["jwks_uri"])
        try:
            if not isinstance(token.get("id_token"), str):
                raise ValueError("ID Token ausente")
            decoded = jwt.decode(
                token["id_token"], KeySet.import_key_set(cast(KeySetSerialization, jwks)), algorithms=["RS256"]
            )
            claims = CodeIDToken(
                decoded.claims,
                decoded.header,
                {
                    "iss": {"value": self.issuer},
                    "aud": {"value": self.settings.oidc_client_id},
                    "azp": {"value": self.settings.oidc_client_id},
                },
                {
                    "nonce": transaction.nonce,
                    "client_id": self.settings.oidc_client_id,
                    "access_token": token.get("access_token"),
                },
            )
            claims.validate(now=self.clock(), leeway=0)
            # Keycloak omite este claim cuando la cuenta no tiene roles del cliente.
            raw_roles = claims.get("cerberus_roles", [])
            if not isinstance(raw_roles, list) or not all(isinstance(role, str) for role in raw_roles):
                raise ValueError("Claim de roles inválido")
            roles: frozenset[Role] = frozenset(cast(Role, role) for role in raw_roles if role in ("reader", "analyst"))
            if not roles:
                raise OIDCForbidden("La cuenta no tiene permisos de Cerberus")
            return Principal(issuer=self.issuer, sub=claims["sub"], roles=roles)
        except (JoseError, ValueError, TypeError, KeyError):
            raise OIDCInvalid("No se pudo validar el inicio de sesión") from None
