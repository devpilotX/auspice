"""Legistar and Granicus.

Legistar is Granicus's legislative management product and it publishes a documented REST API at
``webapi.legistar.com/v1/{client}``. That makes it the best adapter in the set by a wide margin: no HTML
parsing, stable field names, and a client identifier that is the only per jurisdiction configuration
needed.

Granicus also runs a separate media platform, and the two are related but not the same. A jurisdiction can
run Legistar for its agendas and Granicus for its video, or either alone. This adapter handles both,
because splitting them would mean two adapters that share ninety percent of their code and disagree about
which one owns a jurisdiction that uses both.

The one field worth calling out is ``EventInSiteURL``. It is the human facing meeting page, and it is where
the video player lives when the API's own media fields are empty, which is often.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Final

from auspice.domain import CivicPlatform, DocumentKind
from auspice.logging import get_logger
from auspice.pipeline.adapters.base import (
    MeetingRef,
    SourceRef,
    classify_document,
    parse_iso_datetime,
)

log = get_logger(__name__, _stage="ingest")

API_ROOT: Final = "https://webapi.legistar.com/v1"

# The API pages at 1000 by default and will happily return every meeting a client has ever held, which for
# a large city is tens of thousands. Ordering by date descending and taking a window keeps a daily crawl
# proportional to what changed.
PAGE_SIZE: Final = 500


class LegistarAdapter:
    """Legistar, and Granicus media where the two are used together."""

    platform = CivicPlatform.legistar

    def __init__(self, *, granicus_media: bool = True) -> None:
        self.granicus_media = granicus_media

    # -- discovery ---------------------------------------------------------
    def discover(self, *, base_url: str, config: dict[str, Any]) -> list[SourceRef]:
        client = config.get("legistar_client")
        if not client:
            log.warning(
                "legistar adapter needs a legistar_client in platform_config", base_url=base_url
            )
            return []

        return [
            SourceRef(
                url=f"{API_ROOT}/{client}/Events",
                kind=DocumentKind.agenda,
                platform=self.platform,
                title=f"Legistar events for {client}",
                platform_config={"legistar_client": client, "endpoint": "Events"},
            ),
            SourceRef(
                url=f"{API_ROOT}/{client}/Matters",
                kind=DocumentKind.application_packet,
                platform=self.platform,
                title=f"Legistar matters for {client}",
                platform_config={"legistar_client": client, "endpoint": "Matters"},
            ),
            SourceRef(
                url=f"{API_ROOT}/{client}/Bodies",
                kind=DocumentKind.other,
                platform=self.platform,
                title=f"Legistar bodies for {client}",
                platform_config={"legistar_client": client, "endpoint": "Bodies"},
            ),
        ]

    # -- meetings ----------------------------------------------------------
    async def enumerate_meetings(
        self, *, base_url: str, config: dict[str, Any], since: date, client: Any
    ) -> list[MeetingRef]:
        legistar_client = config.get("legistar_client")
        if not legistar_client:
            return []

        # OData filter. Legistar accepts $filter on EventDate and it is the difference between fetching a
        # month and fetching a decade.
        params = {
            "$filter": f"EventDate ge datetime'{since.isoformat()}'",
            "$orderby": "EventDate desc",
            "$top": str(PAGE_SIZE),
        }

        response = await client.get(f"{API_ROOT}/{legistar_client}/Events", params=params)
        if response.status_code != 200:
            log.warning(
                "legistar events request failed",
                client=legistar_client,
                status=response.status_code,
            )
            return []

        meetings: list[MeetingRef] = []
        for event in response.json():
            occurred = parse_iso_datetime(event.get("EventDate"))
            if occurred is None:
                # A meeting we cannot place in time is not usable. Recorded and skipped rather than
                # given today's date, which would put it in the wrong month for every history feature.
                log.debug("legistar event with an unparseable date", event_id=event.get("EventId"))
                continue

            meetings.append(
                MeetingRef(
                    external_id=str(event.get("EventId")),
                    body_name=str(event.get("EventBodyName") or "unknown body"),
                    occurred_on=occurred,
                    platform=self.platform,
                    title=event.get("EventComment") or event.get("EventBodyName"),
                    # Legistar spells cancellation several ways depending on the client's conventions.
                    canceled=_is_canceled(event),
                    detail_url=event.get("EventInSiteURL"),
                    media_hint=event.get("EventVideoPath") or event.get("EventInSiteURL"),
                    raw=event,
                )
            )

        log.info(
            "legistar meetings enumerated", client=legistar_client, count=len(meetings), since=since
        )
        return meetings

    # -- documents ---------------------------------------------------------
    async def documents_for(
        self, *, meeting: MeetingRef, config: dict[str, Any], client: Any
    ) -> list[SourceRef]:
        legistar_client = config.get("legistar_client")
        if not legistar_client:
            return []

        documents: list[SourceRef] = []

        # The agenda and minutes are direct fields on the event.
        for field_name, kind in (
            ("EventAgendaFile", DocumentKind.agenda),
            ("EventMinutesFile", DocumentKind.minutes),
        ):
            url = meeting.raw.get(field_name)
            if url:
                documents.append(
                    SourceRef(
                        url=str(url),
                        kind=kind,
                        platform=self.platform,
                        title=f"{meeting.body_name} {kind.value} {meeting.occurred_on.isoformat()}",
                        published_on=meeting.occurred_on,
                    )
                )

        # Everything else hangs off the event's items, one per agenda item, each of which may carry
        # attachments. This is where staff reports live.
        response = await client.get(
            f"{API_ROOT}/{legistar_client}/Events/{meeting.external_id}/EventItems",
            params={"AgendaNote": "1", "MinutesNote": "1", "Attachments": "1"},
        )
        if response.status_code != 200:
            log.debug(
                "legistar event items unavailable",
                event_id=meeting.external_id,
                status=response.status_code,
            )
            return documents

        for item in response.json():
            for attachment in item.get("EventItemMatterAttachments") or []:
                url = attachment.get("MatterAttachmentHyperlink")
                name = str(attachment.get("MatterAttachmentName") or "attachment")
                if not url:
                    continue
                documents.append(
                    SourceRef(
                        url=str(url),
                        kind=classify_document(name),
                        platform=self.platform,
                        title=name,
                        published_on=meeting.occurred_on,
                        platform_config={
                            "matter_file": item.get("EventItemMatterFile"),
                            "agenda_number": item.get("EventItemAgendaNumber"),
                        },
                    )
                )

        return documents

    # -- media -------------------------------------------------------------
    async def media_url(
        self, *, meeting: MeetingRef, config: dict[str, Any], client: Any
    ) -> str | None:
        direct = meeting.raw.get("EventVideoPath")
        if direct:
            return str(direct)

        if not self.granicus_media or not meeting.detail_url:
            return None

        # The API's video field is frequently empty even when a recording exists, because the recording
        # lives on the Granicus media platform and only the meeting page links to it. One extra request
        # per meeting recovers the highest value input in the corpus, which is worth it.
        response = await client.get(meeting.detail_url)
        if response.status_code != 200:
            return None

        return _extract_granicus_media(response.text)


class GranicusAdapter(LegistarAdapter):
    """Granicus without Legistar.

    Some jurisdictions run Granicus for video and meeting minutes with no Legistar tenancy at all. The
    meeting list then comes from the ViewPublisher page rather than the API, and everything else is the
    same, which is why this subclasses rather than duplicates.
    """

    platform = CivicPlatform.granicus

    def discover(self, *, base_url: str, config: dict[str, Any]) -> list[SourceRef]:
        if config.get("legistar_client"):
            return super().discover(base_url=base_url, config=config)

        view_id = config.get("granicus_view_id", "2")
        host = config.get("granicus_host") or base_url.rstrip("/")
        return [
            SourceRef(
                url=f"{host}/ViewPublisher.php?view_id={view_id}",
                kind=DocumentKind.agenda,
                platform=self.platform,
                title="Granicus meeting archive",
                platform_config={"granicus_view_id": view_id},
            )
        ]

    async def enumerate_meetings(
        self, *, base_url: str, config: dict[str, Any], since: date, client: Any
    ) -> list[MeetingRef]:
        if config.get("legistar_client"):
            return await super().enumerate_meetings(
                base_url=base_url, config=config, since=since, client=client
            )

        view_id = config.get("granicus_view_id", "2")
        host = config.get("granicus_host") or base_url.rstrip("/")
        response = await client.get(f"{host}/ViewPublisher.php?view_id={view_id}")
        if response.status_code != 200:
            log.warning("granicus archive unavailable", host=host, status=response.status_code)
            return []

        return _parse_granicus_archive(response.text, since=since, host=host)


# ---------------------------------------------------------------------------
# Vendor specific parsing, kept out of the methods so it can be tested against a
# recorded page with no client and no network.
# ---------------------------------------------------------------------------
def _is_canceled(event: dict[str, Any]) -> bool:
    comment = str(event.get("EventComment") or "").lower()
    agenda_status = str(event.get("EventAgendaStatusName") or "").lower()
    return "cancel" in comment or "cancel" in agenda_status


def _extract_granicus_media(html: str) -> str | None:
    """Find a Granicus player link in a meeting page.

    Granicus emits several shapes depending on the tenant's vintage. All of them contain either a
    MediaPlayer URL or a clip identifier, and both are enough for ffmpeg to reach the audio.
    """
    import re

    for pattern in (
        r'https?://[^"\']*?MediaPlayer\.php\?[^"\']+',
        r'https?://[^"\']*?/player/clip/\d+[^"\']*',
        r'https?://[^"\']*?\.granicus\.com/[^"\']*?\.mp4',
    ):
        match = re.search(pattern, html)
        if match:
            return match.group(0).replace("&amp;", "&")
    return None


def _parse_granicus_archive(html: str, *, since: date, host: str) -> list[MeetingRef]:
    """Parse the ViewPublisher meeting table.

    Granicus renders this server side with a stable row structure: a body name, a date, and links to the
    agenda, minutes and video. selectolax is used rather than a browser because the page needs no
    JavaScript to be readable.
    """
    from selectolax.parser import HTMLParser

    from auspice.pipeline.adapters.base import absolute

    tree = HTMLParser(html)
    meetings: list[MeetingRef] = []

    for row in tree.css("tr"):
        cells = row.css("td")
        if len(cells) < 2:
            continue

        body = cells[0].text(strip=True)
        occurred = parse_iso_datetime(cells[1].text(strip=True))
        if occurred is None or occurred < since or not body:
            continue

        links = {
            link.text(strip=True).lower(): absolute(host, link.attributes.get("href") or "")
            for link in row.css("a")
            if link.attributes.get("href")
        }

        meetings.append(
            MeetingRef(
                # Granicus archive rows carry no stable identifier, so one is composed from the two fields
                # that do identify the meeting. It is stable across re-crawls, which is what matters.
                external_id=f"{body}:{occurred.isoformat()}",
                body_name=body,
                occurred_on=occurred,
                platform=CivicPlatform.granicus,
                detail_url=next((url for name, url in links.items() if "video" in name), None),
                media_hint=next((url for name, url in links.items() if "video" in name), None),
                raw={"links": links},
            )
        )

    return meetings
