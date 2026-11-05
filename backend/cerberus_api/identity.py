"""Identidad interna estable; no contiene tokens ni representa el modo local sin auth."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AuthMode = Literal["off", "oidc"]
Role = Literal["reader", "analyst"]


class Principal(BaseModel):
    """Identidad autenticada por (`issuer`, `sub`); solo admite roles de Cerberus."""

    model_config = ConfigDict(frozen=True)

    issuer: str = Field(min_length=1)
    sub: str = Field(min_length=1)
    roles: frozenset[Role] = Field(min_length=1)
