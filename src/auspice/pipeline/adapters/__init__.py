"""Stage 1: five platform adapters, not ten thousand scrapers.

Section 6.1: US local government has a small number of software vendors reselling the same platform to
thousands of jurisdictions, so one good adapter reaches hundreds of jurisdictions at once. That single
decision is what makes covering a real number of counties physically possible for one person.

The registry records which platform each jurisdiction runs, detected from the live site rather than
assumed. ``for_platform`` maps that to an adapter, and returns None for ``unknown`` rather than guessing,
because pointing an adapter at a site it cannot read produces a jurisdiction that looks empty.
"""

from __future__ import annotations

from auspice.domain import CivicPlatform
from auspice.pipeline.adapters.base import (
    CivicAdapter,
    MeetingRef,
    SourceRef,
    absolute,
    classify_document,
    parse_iso_datetime,
)
from auspice.pipeline.adapters.legistar import GranicusAdapter, LegistarAdapter
from auspice.pipeline.adapters.platforms import (
    AccelaAdapter,
    CivicPlusAdapter,
    MunicodeAdapter,
    OpenGovAdapter,
)

ADAPTERS: dict[CivicPlatform, CivicAdapter] = {
    CivicPlatform.legistar: LegistarAdapter(),
    CivicPlatform.granicus: GranicusAdapter(),
    CivicPlatform.civicplus: CivicPlusAdapter(),
    CivicPlatform.accela: AccelaAdapter(),
    CivicPlatform.opengov: OpenGovAdapter(),
    CivicPlatform.municode: MunicodeAdapter(),
}


def for_platform(platform: CivicPlatform | str) -> CivicAdapter | None:
    """The adapter for a platform, or None for one we cannot read.

    None rather than a permissive default. A jurisdiction whose platform is unknown produces no documents
    and shows as never fetched on the public freshness page, which is the honest state and is visible.
    Falling back to a generic scraper would produce a jurisdiction that looks covered and is not.
    """
    resolved = CivicPlatform(platform)
    return ADAPTERS.get(resolved)


def supported_platforms() -> list[str]:
    return sorted(platform.value for platform in ADAPTERS)


__all__ = [
    "ADAPTERS",
    "AccelaAdapter",
    "CivicAdapter",
    "CivicPlusAdapter",
    "GranicusAdapter",
    "LegistarAdapter",
    "MeetingRef",
    "MunicodeAdapter",
    "OpenGovAdapter",
    "SourceRef",
    "absolute",
    "classify_document",
    "for_platform",
    "parse_iso_datetime",
    "supported_platforms",
]
