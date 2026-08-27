"""Request authentication.

Section 7.2 defers real auth to WorkOS for the web application, because enterprise buyers demand SAML
and nobody should build that. The API is a different surface: partner engineering teams want a key in a
header, and that is what this implements.

Two decisions worth stating plainly.

**Keys are hashed, never compared in plain text.** They arrive from the environment, are hashed at
startup, and a request's key is hashed before comparison with ``compare_digest``. A plain string
comparison leaks length and position through timing, which is a small hole and an unnecessary one.

**The accuracy endpoints are deliberately unauthenticated.** Section 5.3 makes the public accuracy
record free and open with no login, because it is simultaneously the product proof, the marketing
engine and the moat. Everything else requires a key. That split is intentional rather than an
oversight, and it is asserted in the tests so nobody closes it by accident and nobody opens the rest by
accident either.

There is no user model, no session, and no password anywhere in this service. Adding one would mean
owning a credential store, and section 7.2 is right that rolling your own auth is a security incident
waiting to happen.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from auspice.config import Settings, get_settings


class Tier(StrEnum):
    """What a key is allowed to do, and what it is charged for. Section 10.3."""

    screen = "screen"
    team = "team"
    enterprise = "enterprise"
    county = "county"
    """Counties and community groups, at zero cost. Section 5.5, and non-negotiable: it is the defence
    against the largest reputational risk in this business and it produces the best data quality
    feedback in the system, for free."""


TIER_SITE_LIMITS: dict[Tier, int] = {
    Tier.screen: 50,
    Tier.team: 1000,
    Tier.enterprise: 100_000,
    Tier.county: 1000,
}


@dataclass(frozen=True, slots=True)
class Principal:
    label: str
    tier: Tier

    @property
    def portfolio_limit(self) -> int:
        return TIER_SITE_LIMITS[self.tier]


def _digest(key: str) -> str:
    return hashlib.sha256(key.strip().encode("utf-8")).hexdigest()


def parse_api_keys(raw: str) -> dict[str, Principal]:
    """Parse ``key:label:tier`` triples into a hash to principal map.

    Malformed entries raise rather than being skipped. A silently ignored key means an operator thinks
    a customer has access when they do not, and they find out from the customer.
    """
    principals: dict[str, Principal] = {}
    for entry in (e.strip() for e in raw.split(",")):
        if not entry:
            continue
        parts = entry.split(":")
        if len(parts) != 3:
            raise ValueError(
                f"malformed AUSPICE_API_KEYS entry: expected key:label:tier, got {len(parts)} fields"
            )
        key, label, tier = (p.strip() for p in parts)
        if not key or not label:
            raise ValueError("an API key entry needs both a key and a label")
        principals[_digest(key)] = Principal(label=label, tier=Tier(tier))
    return principals


class KeyRing:
    def __init__(self, settings: Settings) -> None:
        self._principals = parse_api_keys(settings.api_keys)
        self._open = not self._principals

    @property
    def is_open(self) -> bool:
        """True when no keys are configured, which is only allowed outside production.

        ``Settings`` refuses to construct in production without keys, so this can only be true in
        development, and the startup log says so loudly.
        """
        return self._open

    def resolve(self, presented: str | None) -> Principal | None:
        if self._open:
            return Principal(label="development", tier=Tier.enterprise)
        if not presented:
            return None
        candidate = _digest(presented)
        for stored, principal in self._principals.items():
            if hmac.compare_digest(candidate, stored):
                return principal
        return None


def get_key_ring() -> KeyRing:
    return KeyRing(get_settings())


async def require_principal(
    request: Request,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    key_ring: Annotated[KeyRing, Depends(get_key_ring)] = None,  # type: ignore[assignment]
) -> Principal:
    principal = key_ring.resolve(x_api_key)
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="An API key is required. Send it in the X-API-Key header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    # Recorded so the rate limiter charges a customer's own allowance rather than the address they share
    # with everyone else behind the same office network.
    request.state.principal_label = principal.label
    return principal


CurrentPrincipal = Annotated[Principal, Depends(require_principal)]
