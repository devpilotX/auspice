"""Stage 1: the CivicAdapter protocol.

Section 6.1 holds the highest leverage engineering observation in the specification. United States local
government does not have 33,000 different websites. It has a small number of software vendors reselling
the same platform to thousands of jurisdictions. So the decision is five to seven excellent platform
adapters rather than ten thousand bad site specific scrapers, and one adapter reaches hundreds of
jurisdictions at once.

The platform probe found that seven of the twelve counties in the registry run one of two vendors, which is
direct support for that claim on real data rather than an assumption about it.

Every adapter implements the same four operations and nothing else:

    discover           what document sources exist for this jurisdiction
    enumerate_meetings what meetings happened or are scheduled since a date
    documents_for      the documents attached to one meeting
    media_url          the recording, if there is one

The protocol is deliberately narrow. An adapter's job is to turn a vendor's idea of a meeting into ours and
stop. It does not fetch bytes, does not parse, does not write to the database, and does not decide what is
relevant. Those belong to the ingest, parse and extract stages, and an adapter that reached into them would
have to be rewritten every time one of them changed.

The consequence worth naming: an adapter can be tested entirely against recorded responses, because it is a
pure transformation. ``tests/golden`` holds those recordings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol, runtime_checkable

from auspice.domain import CivicPlatform, DocumentKind


@dataclass(frozen=True, slots=True)
class SourceRef:
    """A place documents come from, in a form the ingest stage can fetch."""

    url: str
    kind: DocumentKind
    platform: CivicPlatform
    title: str | None = None
    published_on: date | None = None
    platform_config: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.url.startswith(("http://", "https://")):
            raise ValueError(f"a source ref needs an absolute URL, got {self.url!r}")


@dataclass(frozen=True, slots=True)
class MeetingRef:
    """One meeting, normalised across vendors.

    ``external_id`` is whatever the vendor calls it and is kept verbatim, because it is the only handle
    that survives a re-crawl and it is what makes the ingest idempotent.
    """

    external_id: str
    body_name: str
    occurred_on: date
    platform: CivicPlatform
    title: str | None = None
    canceled: bool = False
    detail_url: str | None = None
    media_hint: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_future(self) -> bool:
        return self.occurred_on > date.today()


@runtime_checkable
class CivicAdapter(Protocol):
    """What every platform connector implements.

    A Protocol rather than a base class, so an adapter is a plain object with four methods and no
    inheritance to reason about. ``runtime_checkable`` lets the registry assert that a configured adapter
    actually satisfies the interface before the crawl starts, rather than discovering a missing method
    partway through a jurisdiction.
    """

    platform: CivicPlatform

    def discover(self, *, base_url: str, config: dict[str, Any]) -> list[SourceRef]:
        """Document sources for one jurisdiction, from its configuration alone.

        Must not fetch anything. Discovery that requires a network round trip belongs in
        ``enumerate_meetings``, so that a registry load stays offline and fast.
        """
        ...

    async def enumerate_meetings(
        self, *, base_url: str, config: dict[str, Any], since: date, client: Any
    ) -> list[MeetingRef]:
        """Meetings on or after ``since``.

        Takes the HTTP client rather than making its own, so the politeness, rate limiting and robots
        handling in the ingest stage apply to adapter traffic too. An adapter with its own client would
        route around all of it.
        """
        ...

    async def documents_for(
        self, *, meeting: MeetingRef, config: dict[str, Any], client: Any
    ) -> list[SourceRef]:
        """The agenda, minutes and staff reports attached to one meeting."""
        ...

    async def media_url(
        self, *, meeting: MeetingRef, config: dict[str, Any], client: Any
    ) -> str | None:
        """The recording, if the vendor exposes one.

        Section 6.3: this is the single most underexploited input in the market. The minutes say "motion
        denied, 1 to 4"; the recording says why, and the why generalises to the next four decisions.
        """
        ...


# ---------------------------------------------------------------------------
# Shared helpers. Small and boring on purpose: an adapter should be almost entirely
# vendor specific mapping, with none of the generic plumbing repeated in five places.
# ---------------------------------------------------------------------------
DOCUMENT_KIND_HINTS: tuple[tuple[str, DocumentKind], ...] = (
    ("agenda packet", DocumentKind.agenda),
    ("agenda", DocumentKind.agenda),
    ("minutes", DocumentKind.minutes),
    ("staff report", DocumentKind.staff_report),
    ("staff memo", DocumentKind.staff_report),
    ("ordinance", DocumentKind.ordinance),
    ("resolution", DocumentKind.resolution),
    ("comprehensive plan", DocumentKind.comprehensive_plan),
    ("notice", DocumentKind.legal_notice),
    ("application", DocumentKind.application_packet),
    ("transcript", DocumentKind.transcript),
)


def classify_document(title: str) -> DocumentKind:
    """Guess a document kind from its title.

    A guess, and treated as one: the extraction stage records what the document actually turned out to be
    and the two are compared. Getting this wrong costs a misfiled document, not a wrong fact, because
    nothing downstream trusts the title over the content.
    """
    lowered = title.lower()
    for needle, kind in DOCUMENT_KIND_HINTS:
        if needle in lowered:
            return kind
    return DocumentKind.other


def parse_iso_datetime(value: object) -> date | None:
    """Parse the several date shapes these vendors emit, or return None.

    None rather than today. A meeting with an unparseable date is a meeting we cannot place in time, and
    substituting today would put it in the wrong month for every point in time feature that reads it.
    """
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()

    text = str(value).strip()
    if not text:
        return None

    for pattern in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m/%d/%Y %I:%M %p",
    ):
        try:
            return datetime.strptime(text, pattern).date()  # noqa: DTZ007 - a civic date has no timezone
        except ValueError:
            continue

    # Last resort: dateutil handles the long tail, and returns None rather than raising here.
    try:
        from dateutil.parser import parse as parse_date

        return parse_date(text).date()
    except Exception:
        return None


def absolute(base_url: str, href: str) -> str:
    """Resolve a possibly relative href against a base URL."""
    from urllib.parse import urljoin

    return urljoin(base_url if base_url.endswith("/") else base_url + "/", href)
