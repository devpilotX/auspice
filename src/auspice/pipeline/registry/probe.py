"""Detect which civic platform a jurisdiction runs.

Section 6.1 is the highest leverage observation in the specification: US local government does
not have 33,000 different websites, it has a handful of software vendors reselling the same
platform to thousands of jurisdictions. Five good adapters beat ten thousand bad scrapers.

That only works if you know which vendor each jurisdiction uses, and asking a model to guess
is exactly the wrong way to find out. So this probes the live site and matches fingerprints:
host names, well known URL paths, and markup that each platform emits.

Detection is deliberately conservative. A wrong platform assignment sends an adapter at a site
it cannot read, and the failure looks like "this county publishes nothing". Where the evidence
is weak the answer is ``unknown``, and ``unknown`` means a human looks at it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from auspice.config import get_settings
from auspice.domain import CivicPlatform
from auspice.logging import get_logger
from auspice.pipeline.registry.models import Registry

log = get_logger(__name__, _stage="registry")


@dataclass(frozen=True, slots=True)
class ProbeResult:
    platform: CivicPlatform
    confidence: float
    evidence: str
    url: str
    checked_at: datetime


# Fingerprints, ordered by how specific they are. A host match beats a markup match, because
# a county site can mention a vendor in a footer without running on it.
_HOST_FINGERPRINTS: tuple[tuple[re.Pattern[str], CivicPlatform, str], ...] = (
    (re.compile(r"\.legistar\.com", re.I), CivicPlatform.legistar, "legistar host"),
    (re.compile(r"\.granicus\.com", re.I), CivicPlatform.granicus, "granicus host"),
    (re.compile(r"\.civicplus\.com", re.I), CivicPlatform.civicplus, "civicplus host"),
    (re.compile(r"\.civicweb\.net", re.I), CivicPlatform.civicplus, "civicweb host"),
    (re.compile(r"\.accela\.com|aca-prod\.accela\.com", re.I), CivicPlatform.accela, "accela host"),
    (re.compile(r"\.opengov\.com", re.I), CivicPlatform.opengov, "opengov host"),
    (
        re.compile(r"library\.municode\.com|\.municode\.com", re.I),
        CivicPlatform.municode,
        "municode host",
    ),
)

_MARKUP_FINGERPRINTS: tuple[tuple[re.Pattern[str], CivicPlatform, str], ...] = (
    (re.compile(r"InSite|Legistar", re.I), CivicPlatform.legistar, "legistar markup"),
    (re.compile(r"granicus", re.I), CivicPlatform.granicus, "granicus reference"),
    # CivicPlus powers CivicEngage, which is the giveaway in the path structure.
    (
        re.compile(r"CivicEngage|/civicax/|civicplus", re.I),
        CivicPlatform.civicplus,
        "civicengage markup",
    ),
    (re.compile(r"citizenaccess|/CAP/|accela", re.I), CivicPlatform.accela, "accela reference"),
    (re.compile(r"opengov", re.I), CivicPlatform.opengov, "opengov reference"),
    (
        re.compile(r"municode|american legal publishing|ecode360", re.I),
        CivicPlatform.municode,
        "code host reference",
    ),
)

# Well known paths each platform serves. Probed only when the landing page was inconclusive.
_PATH_PROBES: tuple[tuple[str, CivicPlatform, str], ...] = (
    ("/AgendaCenter", CivicPlatform.civicplus, "CivicPlus AgendaCenter"),
    ("/Calendar.aspx", CivicPlatform.civicplus, "CivicPlus calendar"),
    ("/DocumentCenter", CivicPlatform.civicplus, "CivicPlus DocumentCenter"),
)


def probe_one(spec_url: str, *, client: httpx.Client) -> ProbeResult:
    checked_at = datetime.now(UTC)

    try:
        response = client.get(spec_url)
    except httpx.HTTPError as exc:
        log.warning("probe failed", url=spec_url, error=str(exc))
        return ProbeResult(
            CivicPlatform.unknown, 0.0, f"unreachable: {type(exc).__name__}", spec_url, checked_at
        )

    final_url = str(response.url)
    # Every host the page redirected through or links to in a script or iframe source.
    body = response.text if response.headers.get("content-type", "").startswith("text/") else ""

    for pattern, platform, evidence in _HOST_FINGERPRINTS:
        if pattern.search(final_url):
            return ProbeResult(platform, 0.95, evidence, final_url, checked_at)

    linked_hosts = set(re.findall(r'(?:href|src|action)="https?://([^/"]+)', body, re.I))
    for pattern, platform, evidence in _HOST_FINGERPRINTS:
        matched = [h for h in linked_hosts if pattern.search(h)]
        if matched:
            return ProbeResult(platform, 0.85, f"{evidence}: {matched[0]}", final_url, checked_at)

    for pattern, platform, evidence in _MARKUP_FINGERPRINTS:
        if pattern.search(body):
            return ProbeResult(platform, 0.6, evidence, final_url, checked_at)

    base = final_url.rstrip("/")
    for path, platform, evidence in _PATH_PROBES:
        try:
            probe_response = client.head(f"{base}{path}", follow_redirects=True)
        except httpx.HTTPError:
            continue
        if probe_response.status_code == 200:
            return ProbeResult(platform, 0.7, evidence, f"{base}{path}", checked_at)

    if response.status_code != 200:
        return ProbeResult(
            CivicPlatform.unknown,
            0.0,
            f"landing page returned {response.status_code}",
            final_url,
            checked_at,
        )

    return ProbeResult(CivicPlatform.unknown, 0.0, "no fingerprint matched", final_url, checked_at)


def probe_all(registry: Registry, *, timeout: float = 30.0) -> dict[str, ProbeResult]:
    """Probe every jurisdiction's landing page.

    Identifies honestly with the configured user agent and contact address. Section 15.2: the
    goal is to be the least burdensome consumer of these systems, because access is the
    business and burning it is unrecoverable.
    """
    settings = get_settings()
    headers = {
        "User-Agent": settings.crawler_user_agent,
        "Accept": "text/html,application/xhtml+xml",
    }
    if settings.crawler_contact:
        headers["From"] = settings.crawler_contact

    results: dict[str, ProbeResult] = {}
    with httpx.Client(
        timeout=timeout, follow_redirects=True, headers=headers, http2=True
    ) as client:
        for spec in registry.jurisdictions:
            target = str(spec.sources[0].url) if spec.sources else None
            if target is None:
                results[spec.slug] = ProbeResult(
                    CivicPlatform.unknown,
                    0.0,
                    "no source url in the registry",
                    "",
                    datetime.now(UTC),
                )
                continue
            result = probe_one(target, client=client)
            results[spec.slug] = result
            log.info(
                "platform probed",
                slug=spec.slug,
                platform=result.platform.value,
                confidence=result.confidence,
                evidence=result.evidence,
            )
    return results
