"""Trusted identity extraction for requests proxied through API Get Away."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


class AuthenticationRequiredError(RuntimeError):
    """Raised when a request does not include gateway-injected identity."""


@dataclass(frozen=True)
class GatewayIdentity:
    """Normalized identity extracted from trusted proxy headers."""

    identity_key: str
    sub: str | None
    email: str | None
    name: str | None
    raw_headers: dict[str, str]


_IDENTITY_HEADER_NAMES = {
    "x-user-sub",
    "x-user-email",
    "x-user-name",
    "x-authentik-uid",
    "x-authentik-username",
    "x-authentik-email",
    "x-authentik-name",
    "x-forwarded-user",
    "x-forwarded-email",
    "remote-user",
    "remote-email",
}

_IDENTITY_HEADER_PREFIXES = (
    "x-user-",
    "x-authentik-",
)


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _collect_identity_headers(headers: Mapping[str, str]) -> dict[str, str]:
    safe_headers: dict[str, str] = {}

    for key, value in headers.items():
        lower_key = key.lower()
        if lower_key in _IDENTITY_HEADER_NAMES or lower_key.startswith(_IDENTITY_HEADER_PREFIXES):
            clean_value = _clean(value)
            if clean_value:
                safe_headers[lower_key] = clean_value

    return safe_headers


def extract_gateway_identity(headers: Mapping[str, str]) -> GatewayIdentity:
    """Extract the authenticated user from API-gateway-injected headers."""
    identity_headers = _collect_identity_headers(headers)

    sub = _clean(
        identity_headers.get("x-user-sub")
        or identity_headers.get("x-authentik-uid")
        or identity_headers.get("x-authentik-username")
    )
    email = _clean(
        identity_headers.get("x-user-email")
        or identity_headers.get("x-authentik-email")
        or identity_headers.get("x-forwarded-email")
        or identity_headers.get("remote-email")
    )
    name = _clean(
        identity_headers.get("x-user-name")
        or identity_headers.get("x-authentik-name")
        or identity_headers.get("x-forwarded-user")
        or identity_headers.get("remote-user")
    )

    identity_key = sub or email
    if not identity_key:
        raise AuthenticationRequiredError("Authenticated gateway user headers are required.")

    return GatewayIdentity(
        identity_key=identity_key,
        sub=sub,
        email=email,
        name=name,
        raw_headers=identity_headers,
    )
