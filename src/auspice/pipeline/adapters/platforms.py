"""CivicPlus, Accela, OpenGov and Municode.

Four adapters in one file because they are short, and they are short for the same reason: each one is a
mapping from a vendor's URL conventions onto ours, and none of them needs state.

The platform probe found CivicPlus on more of the twelve registry counties than anything else, which makes
it the highest value adapter here even though Legistar is the better engineered one.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Final

from auspice.domain import CivicPlatform, DocumentKind
from auspice.logging import get_logger
from auspice.pipeline.adapters.base import (
    MeetingRef,
    SourceRef,
    absolute,
    classify_document,
    parse_iso_datetime,
)

log = get_logger(__name__, _stage="ingest")


# ===========================================================================
# CivicPlus, sold as CivicEngage
# ===========================================================================
class CivicPlusAdapter:
    """CivicPlus AgendaCenter and DocumentCenter.

    No public API. What there is instead is a set of URL conventions that hold across essentially every
    CivicEngage tenant, which is nearly as good:

        /AgendaCenter                            the meeting list
        /AgendaCenter/Search/?term=&CIDs=all     a searchable index across all categories
        /DocumentCenter/View/{id}                a document by identifier
        /ArchiveCenter                           older material, structured differently

    The AgendaCenter list is rendered server side, so no browser is needed. Category identifiers vary per
    tenant, which is why the search endpoint with ``CIDs=all`` is preferred: it avoids having to discover
    and maintain a category map for every county.
    """

    platform = CivicPlatform.civicplus

    def discover(self, *, base_url: str, config: dict[str, Any]) -> list[SourceRef]:
        root = base_url.rstrip("/")
        return [
            SourceRef(
                url=f"{root}/AgendaCenter",
                kind=DocumentKind.agenda,
                platform=self.platform,
                title="CivicPlus AgendaCenter",
                platform_config={"module": "agenda_center"},
            ),
            SourceRef(
                url=f"{root}/AgendaCenter/Search/?term=&CIDs=all&startDate=&endDate=&dateRange=&dateSelector=",
                kind=DocumentKind.agenda,
                platform=self.platform,
                title="CivicPlus AgendaCenter search, all categories",
                platform_config={"module": "agenda_search"},
            ),
            SourceRef(
                url=f"{root}/ArchiveCenter",
                kind=DocumentKind.minutes,
                platform=self.platform,
                title="CivicPlus ArchiveCenter",
                platform_config={"module": "archive_center"},
            ),
        ]

    async def enumerate_meetings(
        self, *, base_url: str, config: dict[str, Any], since: date, client: Any
    ) -> list[MeetingRef]:
        root = base_url.rstrip("/")
        response = await client.get(f"{root}/AgendaCenter")
        if response.status_code != 200:
            log.warning(
                "civicplus agenda center unavailable", base_url=root, status=response.status_code
            )
            return []
        return _parse_agenda_center(response.text, root=root, since=since)

    async def documents_for(
        self, *, meeting: MeetingRef, config: dict[str, Any], client: Any
    ) -> list[SourceRef]:
        # The AgendaCenter row already carries every document link, so this needs no request. That is
        # unusual and worth keeping: a document listing that costs nothing is a document listing that can
        # run daily across every county.
        links: dict[str, str] = meeting.raw.get("links", {})
        return [
            SourceRef(
                url=url,
                kind=classify_document(name),
                platform=self.platform,
                title=f"{meeting.body_name} {name} {meeting.occurred_on.isoformat()}",
                published_on=meeting.occurred_on,
            )
            for name, url in links.items()
        ]

    async def media_url(
        self, *, meeting: MeetingRef, config: dict[str, Any], client: Any
    ) -> str | None:
        # CivicPlus tenants usually delegate video to Granicus, YouTube or Vimeo rather than hosting it.
        # The link is on the meeting row when it exists.
        links: dict[str, str] = meeting.raw.get("links", {})
        for name, url in links.items():
            if any(hint in name for hint in ("video", "media", "watch", "recording")):
                return str(url)
        return None


def _parse_agenda_center(html: str, *, root: str, since: date) -> list[MeetingRef]:
    """Parse an AgendaCenter listing.

    The structure is a set of category panels, each containing rows with a date, a title and links. Rather
    than depending on the exact class names, which do vary between tenant themes, this walks rows and
    accepts any row that yields a parseable date and at least one document link. That survives a theme
    change, and where it does not survive one it fails visibly: a broken theme returns zero meetings, which
    trips the freshness alert rather than quietly halving a county.
    """
    from selectolax.parser import HTMLParser

    tree = HTMLParser(html)
    meetings: list[MeetingRef] = []
    seen: set[str] = set()

    for row in tree.css("tr, div.catAgendaRow, li"):
        text = row.text(separator=" ", strip=True)
        if not text:
            continue

        links = {
            (
                link.text(strip=True) or link.attributes.get("aria-label") or "document"
            ).lower(): absolute(root, link.attributes.get("href") or "")
            for link in row.css("a")
            if link.attributes.get("href")
        }
        if not links:
            continue

        occurred = _first_date(text)
        if occurred is None or occurred < since:
            continue

        body = _body_name(row) or "unknown body"
        external_id = f"{body}:{occurred.isoformat()}"
        if external_id in seen:
            continue
        seen.add(external_id)

        meetings.append(
            MeetingRef(
                external_id=external_id,
                body_name=body,
                occurred_on=occurred,
                platform=CivicPlatform.civicplus,
                title=text[:200],
                canceled="cancel" in text.lower(),
                raw={"links": links},
            )
        )

    return meetings


def _first_date(text: str) -> date | None:
    import re

    for pattern in (
        r"\b(\d{4}-\d{2}-\d{2})\b",
        r"\b(\d{1,2}/\d{1,2}/\d{4})\b",
        r"\b([A-Z][a-z]+ \d{1,2},? \d{4})\b",
    ):
        match = re.search(pattern, text)
        if match:
            parsed = parse_iso_datetime(match.group(1))
            if parsed is not None:
                return parsed
    return None


def _body_name(row: Any) -> str | None:
    # The body name is usually the nearest preceding heading. Walking up is more reliable than guessing a
    # class name, because the heading structure is part of the page's semantics rather than its theme.
    node = row
    for _ in range(6):
        node = getattr(node, "parent", None)
        if node is None:
            return None
        heading = node.css_first("h2, h3, .catTitle, .catAgendaHeader")
        if heading is not None:
            name = str(heading.text(strip=True))
            if name:
                return name
    return None


# ===========================================================================
# Accela Citizen Access
# ===========================================================================
class AccelaAdapter:
    """Accela Citizen Access.

    Accela is a permitting system rather than a legislative one, so it answers a different question: what
    was applied for, and what happened to the permit. That makes it the downstream confirmation source
    described in section 6.1 rather than a source of decisions.

    Two access paths, and which one a jurisdiction offers matters a great deal. Accela's Construct API
    (``apis.accela.com/v4``) is documented and returns JSON, and it requires an agency application
    registration. Citizen Access itself is an ASP.NET application with viewstate driven search, which is
    the case Playwright exists for.

    This adapter implements the API path and reports the HTML path as unavailable rather than attempting
    it, because a viewstate scraper that works today and breaks silently next month is worse than a
    documented gap. Section 6.1 rule 2 applies: these are public records, and behaving like a hostile
    scraper is how access gets cut.
    """

    platform = CivicPlatform.accela
    API_ROOT: Final = "https://apis.accela.com/v4"

    def discover(self, *, base_url: str, config: dict[str, Any]) -> list[SourceRef]:
        agency = config.get("accela_agency")
        if not agency:
            log.info(
                "accela adapter needs an accela_agency and API credentials, and falls back to nothing",
                base_url=base_url,
            )
            return []
        return [
            SourceRef(
                url=f"{self.API_ROOT}/records",
                kind=DocumentKind.application_packet,
                platform=self.platform,
                title=f"Accela records for {agency}",
                platform_config={"accela_agency": agency, "endpoint": "records"},
            )
        ]

    async def enumerate_meetings(
        self, *, base_url: str, config: dict[str, Any], since: date, client: Any
    ) -> list[MeetingRef]:
        # Accela has no concept of a meeting. Returning an empty list is correct rather than an error, and
        # the permit records it does hold are read by documents_for against a record identifier.
        del base_url, config, since, client
        return []

    async def documents_for(
        self, *, meeting: MeetingRef, config: dict[str, Any], client: Any
    ) -> list[SourceRef]:
        agency = config.get("accela_agency")
        token = config.get("accela_token")
        if not agency or not token:
            return []

        response = await client.get(
            f"{self.API_ROOT}/records/{meeting.external_id}/documents",
            headers={
                "x-accela-appid": str(config.get("accela_app_id", "")),
                "Authorization": str(token),
            },
        )
        if response.status_code != 200:
            return []

        return [
            SourceRef(
                url=str(document.get("fileName") or document.get("url") or ""),
                kind=classify_document(str(document.get("type", {}).get("text", "document"))),
                platform=self.platform,
                title=str(document.get("fileName") or "document"),
                published_on=parse_iso_datetime(document.get("uploadedDate")),
            )
            for document in response.json().get("result", [])
            if document.get("fileName") or document.get("url")
        ]

    async def media_url(
        self, *, meeting: MeetingRef, config: dict[str, Any], client: Any
    ) -> str | None:
        del meeting, config, client
        return None


# ===========================================================================
# OpenGov
# ===========================================================================
class OpenGovAdapter:
    """OpenGov, including the Viewpoint and ClearGov meeting products.

    OpenGov exposes a JSON meeting index at a predictable path on its hosted domains. Where a jurisdiction
    runs OpenGov Permitting rather than the meeting product, the meeting list is empty and the permit
    records are the useful output, which mirrors Accela.
    """

    platform = CivicPlatform.opengov

    def discover(self, *, base_url: str, config: dict[str, Any]) -> list[SourceRef]:
        tenant = config.get("opengov_tenant")
        if not tenant:
            return []
        return [
            SourceRef(
                url=f"https://{tenant}.opengov.com/api/meetings",
                kind=DocumentKind.agenda,
                platform=self.platform,
                title=f"OpenGov meetings for {tenant}",
                platform_config={"opengov_tenant": tenant},
            )
        ]

    async def enumerate_meetings(
        self, *, base_url: str, config: dict[str, Any], since: date, client: Any
    ) -> list[MeetingRef]:
        tenant = config.get("opengov_tenant")
        if not tenant:
            return []

        response = await client.get(
            f"https://{tenant}.opengov.com/api/meetings",
            params={"since": since.isoformat()},
        )
        if response.status_code != 200:
            log.warning("opengov meetings unavailable", tenant=tenant, status=response.status_code)
            return []

        payload = response.json()
        records = payload if isinstance(payload, list) else payload.get("meetings", [])

        meetings: list[MeetingRef] = []
        for record in records:
            occurred = parse_iso_datetime(record.get("date") or record.get("startsAt"))
            if occurred is None or occurred < since:
                continue
            meetings.append(
                MeetingRef(
                    external_id=str(record.get("id") or f"{occurred.isoformat()}"),
                    body_name=str(
                        record.get("bodyName") or record.get("committee") or "unknown body"
                    ),
                    occurred_on=occurred,
                    platform=self.platform,
                    title=record.get("title"),
                    canceled=bool(record.get("canceled")),
                    detail_url=record.get("url"),
                    media_hint=record.get("videoUrl"),
                    raw=record,
                )
            )
        return meetings

    async def documents_for(
        self, *, meeting: MeetingRef, config: dict[str, Any], client: Any
    ) -> list[SourceRef]:
        del config, client
        documents: list[SourceRef] = []
        for key, kind in (
            ("agendaUrl", DocumentKind.agenda),
            ("minutesUrl", DocumentKind.minutes),
            ("packetUrl", DocumentKind.agenda),
        ):
            url = meeting.raw.get(key)
            if url:
                documents.append(
                    SourceRef(
                        url=str(url),
                        kind=kind,
                        platform=self.platform,
                        title=f"{meeting.body_name} {kind.value}",
                        published_on=meeting.occurred_on,
                    )
                )
        return documents

    async def media_url(
        self, *, meeting: MeetingRef, config: dict[str, Any], client: Any
    ) -> str | None:
        del config, client
        hint = meeting.media_hint
        return str(hint) if hint else None


# ===========================================================================
# Municode and the other code hosts
# ===========================================================================
class MunicodeAdapter:
    """Municode, American Legal Publishing and eCode360.

    A different shape from the others: a code host publishes the rules rather than the meetings, so there
    are no meetings to enumerate and the useful output is the ordinance text and its amendment history.

    Section 9.2 treats a zoning data vendor as a potential supplier rather than a competitor, and this
    adapter is where that decision lives. The rules layer is a commodity; the political layer is not, so
    the correct move is to buy or read the rules cheaply and spend the effort elsewhere.
    """

    platform = CivicPlatform.municode

    def discover(self, *, base_url: str, config: dict[str, Any]) -> list[SourceRef]:
        client_id = config.get("municode_client_id")
        state = config.get("municode_state")
        sources: list[SourceRef] = []

        if client_id:
            sources.append(
                SourceRef(
                    url=f"https://api.municode.com/codesContent?jobId={client_id}",
                    kind=DocumentKind.ordinance,
                    platform=self.platform,
                    title="Municode code content",
                    platform_config={"municode_client_id": client_id},
                )
            )
            sources.append(
                SourceRef(
                    url=f"https://api.municode.com/CodesToc?jobId={client_id}",
                    kind=DocumentKind.ordinance,
                    platform=self.platform,
                    title="Municode table of contents",
                    platform_config={"municode_client_id": client_id},
                )
            )
        elif state:
            sources.append(
                SourceRef(
                    url=f"https://library.municode.com/{state}",
                    kind=DocumentKind.ordinance,
                    platform=self.platform,
                    title=f"Municode library for {state}",
                    platform_config={"municode_state": state},
                )
            )

        for key, host, kind in (
            ("american_legal_url", None, DocumentKind.ordinance),
            ("ecode360_url", None, DocumentKind.ordinance),
        ):
            url = config.get(key)
            if url:
                sources.append(
                    SourceRef(
                        url=str(url),
                        kind=kind,
                        platform=self.platform,
                        title=key.replace("_", " "),
                    )
                )
            del host

        return sources

    async def enumerate_meetings(
        self, *, base_url: str, config: dict[str, Any], since: date, client: Any
    ) -> list[MeetingRef]:
        # A code host holds no meetings. Empty is the correct answer, and returning it rather than raising
        # keeps the orchestration uniform across adapters.
        del base_url, config, since, client
        return []

    async def documents_for(
        self, *, meeting: MeetingRef, config: dict[str, Any], client: Any
    ) -> list[SourceRef]:
        del meeting, config, client
        return []

    async def media_url(
        self, *, meeting: MeetingRef, config: dict[str, Any], client: Any
    ) -> str | None:
        del meeting, config, client
        return None
