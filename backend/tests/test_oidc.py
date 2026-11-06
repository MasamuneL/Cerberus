"""Proveedor simulado con JWT firmados por claves efímeras; transporte sin red."""

import asyncio
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx2 as httpx
import pytest
from joserfc import jwt
from joserfc.jwk import OctKey, RSAKey
from pydantic import SecretStr

from cerberus_api.config import Settings
from cerberus_api.sessions import LoginTransaction

NOW = 1_800_000_000
ISSUER = "https://identity.example/realms/cerberus"
INTERNAL = "http://keycloak:8080/realms/cerberus"


@pytest.fixture(scope="module")
def signing_key() -> RSAKey:
    return RSAKey.generate_key(auto_kid=True)


class Provider:
    def __init__(self, key: RSAKey) -> None:
        self.key = key
        self.signing_key: RSAKey | OctKey = key
        self.algorithm = "RS256"
        self.header_kid: str | None = None
        self.status = 200
        self.claims: dict[str, Any] = {
            "iss": ISSUER,
            "sub": "subject-1",
            "aud": "cerberus-web",
            "exp": NOW + 300,
            "iat": NOW,
            "nonce": "nonce",
            "cerberus_roles": ["reader"],
        }
        self.metadata: dict[str, Any] = {
            "issuer": ISSUER,
            "authorization_endpoint": ISSUER + "/authorize",
            "token_endpoint": INTERNAL + "/token",
            "jwks_uri": INTERNAL + "/certs",
            "id_token_signing_alg_values_supported": ["RS256"],
        }

    def respond(self, request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith(INTERNAL + "/")
        if request.url.path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(200, json=self.metadata)
        if request.url.path.endswith("/certs"):
            return httpx.Response(200, json={"keys": [self.key.as_dict()]})
        assert request.url.path.endswith("/token")
        body = parse_qs(request.content.decode())
        assert body["code"] == ["code"] and body["code_verifier"] == ["verifier"]
        assert body["redirect_uri"] == ["https://cerberus.example/api/auth/callback"]
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "invalid_grant"})
        signed = jwt.encode(
            {"alg": self.algorithm, "kid": self.header_kid or self.signing_key.as_dict()["kid"]},
            self.claims,
            self.signing_key,
            algorithms=[self.algorithm],
        )
        return httpx.Response(
            200, json={"id_token": signed, "access_token": "opaque-test-token", "token_type": "Bearer"}
        )

    def client(self) -> Any:
        from cerberus_api.oidc import OIDCClient

        settings = Settings(
            auth_mode="oidc",
            app_origin="https://cerberus.example",
            oidc_issuer_url=ISSUER,
            oidc_backchannel_url=INTERNAL,
            oidc_client_secret=SecretStr("secreto-sintetico-para-tests"),
        )
        return OIDCClient(settings, transport=httpx.MockTransport(self.respond), clock=lambda: NOW)


def transaction() -> LoginTransaction:
    return LoginTransaction(
        state="state", nonce="nonce", code_verifier="verifier", browser_token="browser", created_at=NOW
    )


def test_authorization_url_has_pkce_state_nonce_and_fixed_redirect(signing_key: RSAKey) -> None:
    url = asyncio.run(Provider(signing_key).client().authorization_url(transaction()))
    parsed = urlsplit(url)
    assert parsed.scheme == "https" and parsed.netloc == "identity.example"
    params = parse_qs(parsed.query)
    assert params["state"] == ["state"] and params["nonce"] == ["nonce"]
    assert params["response_type"] == ["code"] and params["scope"] == ["openid"]
    assert params["code_challenge_method"] == ["S256"]
    assert params["code_challenge"] != ["verifier"]
    assert params["redirect_uri"] == ["https://cerberus.example/api/auth/callback"]
    assert params["ui_locales"] == ["es"]


def test_validated_identity_ignores_unknown_roles(signing_key: RSAKey) -> None:
    provider = Provider(signing_key)
    provider.claims["cerberus_roles"] = ["admin", "analyst", "analyst"]
    principal = asyncio.run(provider.client().exchange_code("code", transaction()))
    assert principal.issuer == ISSUER and principal.sub == "subject-1"
    assert principal.roles == frozenset({"analyst"})


@pytest.mark.parametrize(
    "patch",
    [
        {"iss": "https://other.example"},
        {"aud": "wrong"},
        {"aud": ["wrong", "other"]},
        {"exp": NOW},
        {"exp": None},
        {"nonce": "wrong"},
        {"nonce": None},
        {"sub": ""},
        {"sub": 123},
        {"iat": NOW + 100},
        {"aud": ["cerberus-web", "other"]},
        {"azp": "wrong"},
        {"azp": False},
        {"azp": ""},
        {"azp": None},
        {"azp": 0},
    ],
)
def test_invalid_claims_rejected(signing_key: RSAKey, patch: dict[str, Any]) -> None:
    from cerberus_api.oidc import OIDCInvalid

    provider = Provider(signing_key)
    provider.claims.update(patch)
    with pytest.raises(OIDCInvalid):
        asyncio.run(provider.client().exchange_code("code", transaction()))


def test_multi_audience_with_valid_azp(signing_key: RSAKey) -> None:
    provider = Provider(signing_key)
    provider.claims.update(aud=["cerberus-web", "other"], azp="cerberus-web")
    assert asyncio.run(provider.client().exchange_code("code", transaction())).sub == "subject-1"


@pytest.mark.parametrize("roles", [[], ["admin"]])
def test_identity_without_application_role_has_no_access(signing_key: RSAKey, roles: list[str]) -> None:
    from cerberus_api.oidc import OIDCForbidden

    provider = Provider(signing_key)
    provider.claims["cerberus_roles"] = roles
    with pytest.raises(OIDCForbidden):
        asyncio.run(provider.client().exchange_code("code", transaction()))


@pytest.mark.parametrize("roles", ["reader", ["reader", 1], None])
def test_role_claim_must_be_list_of_strings(signing_key: RSAKey, roles: Any) -> None:
    from cerberus_api.oidc import OIDCInvalid

    provider = Provider(signing_key)
    provider.claims["cerberus_roles"] = roles
    with pytest.raises(OIDCInvalid):
        asyncio.run(provider.client().exchange_code("code", transaction()))


@pytest.mark.parametrize("algorithm", ["RS256", "HS256"])
def test_wrong_signature_and_unapproved_algorithm(signing_key: RSAKey, algorithm: str) -> None:
    from cerberus_api.oidc import OIDCInvalid

    provider = Provider(signing_key)
    provider.signing_key = (
        RSAKey.generate_key(auto_kid=True) if algorithm == "RS256" else OctKey.generate_key(256, auto_kid=True)
    )
    provider.algorithm = algorithm
    kid = signing_key.as_dict()["kid"]
    assert isinstance(kid, str)
    provider.header_kid = kid
    with pytest.raises(OIDCInvalid):
        asyncio.run(provider.client().exchange_code("code", transaction()))


@pytest.mark.parametrize("claim", ["iss", "aud", "exp", "iat", "nonce", "sub"])
def test_required_claim_must_be_present(signing_key: RSAKey, claim: str) -> None:
    from cerberus_api.oidc import OIDCInvalid

    provider = Provider(signing_key)
    provider.claims.pop(claim)
    with pytest.raises(OIDCInvalid):
        asyncio.run(provider.client().exchange_code("code", transaction()))


def test_provider_key_rotation(signing_key: RSAKey) -> None:
    provider = Provider(signing_key)
    client = provider.client()
    assert asyncio.run(client.exchange_code("code", transaction())).sub == "subject-1"
    provider.key = RSAKey.generate_key(auto_kid=True)
    provider.signing_key = provider.key
    assert asyncio.run(client.exchange_code("code", transaction())).sub == "subject-1"


@pytest.mark.parametrize(
    "patch",
    [
        {"issuer": "https://wrong.example"},
        {"token_endpoint": "https://attacker.example/token"},
        {"jwks_uri": INTERNAL + "/../../master/certs"},
        {"authorization_endpoint": "javascript:alert(1)"},
    ],
)
def test_invalid_metadata_never_receives_credentials(signing_key: RSAKey, patch: dict[str, Any]) -> None:
    from cerberus_api.oidc import OIDCUnavailable

    provider = Provider(signing_key)
    provider.metadata.update(patch)
    with pytest.raises(OIDCUnavailable):
        asyncio.run(provider.client().exchange_code("code", transaction()))


@pytest.mark.parametrize("status", [400, 503])
def test_provider_token_errors_are_generic(signing_key: RSAKey, status: int) -> None:
    from cerberus_api.oidc import OIDCInvalid, OIDCUnavailable

    provider = Provider(signing_key)
    provider.status = status
    with pytest.raises(OIDCUnavailable if status == 503 else OIDCInvalid):
        asyncio.run(provider.client().exchange_code("code", transaction()))
