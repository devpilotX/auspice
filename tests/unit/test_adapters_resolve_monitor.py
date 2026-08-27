"""Adapters, entity resolution, monitoring materiality, and the transcript citation.

These are the stages where a subtle error is invisible for months. An adapter that returns nothing looks like
a quiet county. A resolver that over merges turns two applicants into one and inflates a track record. An
alert threshold set slightly wrong gets the whole channel muted. So each of them is tested against the
specific way it goes wrong rather than only against the happy path.
"""

from __future__ import annotations

from datetime import date

import pytest

from auspice.domain import AlertTrigger, CivicPlatform, DocumentKind
from auspice.monitor import Change, materiality
from auspice.monitor.watcher import SCORE_NOISE_FLOOR, SEND_THRESHOLD
from auspice.pipeline.adapters import (
    ADAPTERS,
    CivicAdapter,
    for_platform,
    supported_platforms,
)
from auspice.pipeline.adapters.base import classify_document, parse_iso_datetime
from auspice.pipeline.adapters.legistar import (
    _extract_granicus_media,
    _is_canceled,
    _parse_granicus_archive,
)
from auspice.pipeline.adapters.platforms import _parse_agenda_center
from auspice.pipeline.resolve import (
    ADJUDICATE_SIMILARITY,
    AUTO_MERGE_SIMILARITY,
    looks_like_single_purpose_entity,
    normalise_body,
    normalise_organisation,
    normalise_person,
)
from auspice.pipeline.transcribe import Segment, Transcript


class TestAdapterRegistry:
    def test_every_adapter_satisfies_the_protocol(self) -> None:
        """Checked at runtime, so a missing method fails here rather than partway through a crawl."""
        for platform, adapter in ADAPTERS.items():
            assert isinstance(adapter, CivicAdapter), platform.value

    def test_an_unknown_platform_returns_nothing(self) -> None:
        """None rather than a permissive default.

        A generic fallback scraper would make an unreadable jurisdiction look covered. Returning None means
        it shows as never fetched on the public freshness page, which is the honest state.
        """
        assert for_platform(CivicPlatform.unknown) is None

    def test_five_platforms_at_minimum(self) -> None:
        """Section 6.1 asks for five to seven adapters, not ten thousand scrapers."""
        assert len(supported_platforms()) >= 5

    def test_discovery_makes_no_network_call(self) -> None:
        """Discovery has to work offline so a registry load stays fast and deterministic.

        Passing no client at all is the strongest way to assert it: any request would raise.
        """
        for adapter in ADAPTERS.values():
            refs = adapter.discover(
                base_url="https://example.gov",
                config={
                    "legistar_client": "demo",
                    "opengov_tenant": "demo",
                    "accela_agency": "DEMO",
                    "municode_state": "va",
                },
            )
            for ref in refs:
                assert ref.url.startswith("https://")

    def test_a_source_ref_rejects_a_relative_url(self) -> None:
        from auspice.pipeline.adapters.base import SourceRef

        with pytest.raises(ValueError, match="absolute URL"):
            SourceRef(
                url="/AgendaCenter", kind=DocumentKind.agenda, platform=CivicPlatform.civicplus
            )


class TestDateParsing:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("2025-09-14T19:00:00", date(2025, 9, 14)),
            ("2025-09-14", date(2025, 9, 14)),
            ("09/14/2025", date(2025, 9, 14)),
            ("9/14/2025 7:00 PM", date(2025, 9, 14)),
            ("September 14, 2025", date(2025, 9, 14)),
        ],
    )
    def test_the_shapes_these_vendors_emit(self, raw: str, expected: date) -> None:
        assert parse_iso_datetime(raw) == expected

    def test_an_unparseable_date_is_none_not_today(self) -> None:
        """Substituting today would put a meeting in the wrong month for every history feature."""
        assert parse_iso_datetime("to be determined") is None
        assert parse_iso_datetime("") is None
        assert parse_iso_datetime(None) is None


class TestDocumentClassification:
    @pytest.mark.parametrize(
        ("title", "kind"),
        [
            ("Board of Supervisors Agenda 2025-09-14", DocumentKind.agenda),
            ("Regular Meeting Minutes", DocumentKind.minutes),
            ("Staff Report REZ-2025-0081", DocumentKind.staff_report),
            ("Ordinance 2025-14 Data Center Overlay", DocumentKind.ordinance),
            ("Agenda Packet", DocumentKind.agenda),
            ("Something else entirely", DocumentKind.other),
        ],
    )
    def test_titles_map_to_kinds(self, title: str, kind: DocumentKind) -> None:
        assert classify_document(title) is kind


class TestLegistarParsing:
    def test_cancellation_is_detected_in_either_field(self) -> None:
        assert _is_canceled({"EventComment": "CANCELLED due to weather"})
        assert _is_canceled({"EventAgendaStatusName": "Cancelled"})
        assert not _is_canceled({"EventComment": "Regular meeting"})

    @pytest.mark.parametrize(
        "html",
        [
            '<a href="https://county.granicus.com/MediaPlayer.php?view_id=2&amp;clip_id=1234">Video</a>',
            '<iframe src="https://county.granicus.com/player/clip/1234?view_id=2"></iframe>',
            '<source src="https://archive-video.granicus.com/county/county_abc.mp4" />',
        ],
    )
    def test_granicus_media_is_found_in_each_shape(self, html: str) -> None:
        found = _extract_granicus_media(html)
        assert found is not None
        assert "granicus.com" in found
        assert "&amp;" not in found, "html entities must be decoded or ffmpeg cannot fetch it"

    def test_no_media_returns_none(self) -> None:
        assert _extract_granicus_media("<p>No recording of this meeting.</p>") is None

    def test_granicus_archive_rows_become_meetings(self) -> None:
        html = """
        <table>
          <tr><th>Name</th><th>Date</th></tr>
          <tr><td>Board of Supervisors</td><td>09/14/2025</td>
              <td><a href="/agenda.pdf">Agenda</a><a href="/MediaPlayer.php?clip_id=9">Video</a></td></tr>
          <tr><td>Planning Commission</td><td>01/02/2020</td>
              <td><a href="/old.pdf">Agenda</a></td></tr>
        </table>
        """
        meetings = _parse_granicus_archive(
            html, since=date(2025, 1, 1), host="https://county.granicus.com"
        )
        assert len(meetings) == 1, "the 2020 row is before the since date and must be excluded"
        meeting = meetings[0]
        assert meeting.body_name == "Board of Supervisors"
        assert meeting.occurred_on == date(2025, 9, 14)
        assert meeting.external_id == "Board of Supervisors:2025-09-14"
        assert meeting.media_hint is not None


class TestCivicPlusParsing:
    def test_agenda_center_rows_become_meetings_with_documents(self) -> None:
        html = """
        <div>
          <h2>Board of Supervisors</h2>
          <table>
            <tr>
              <td>September 14, 2025</td>
              <td><a href="/AgendaCenter/ViewFile/Agenda/_09142025-123">Agenda</a>
                  <a href="/AgendaCenter/ViewFile/Minutes/_09142025-124">Minutes</a></td>
            </tr>
          </table>
        </div>
        """
        meetings = _parse_agenda_center(html, root="https://county.gov", since=date(2025, 1, 1))
        assert len(meetings) == 1
        meeting = meetings[0]
        assert meeting.occurred_on == date(2025, 9, 14)
        assert meeting.body_name == "Board of Supervisors"
        links = meeting.raw["links"]
        assert all(url.startswith("https://county.gov/") for url in links.values())

    def test_rows_before_the_since_date_are_dropped(self) -> None:
        html = """<table><tr><td>January 2, 2019</td><td><a href="/a.pdf">Agenda</a></td></tr></table>"""
        assert _parse_agenda_center(html, root="https://county.gov", since=date(2025, 1, 1)) == []

    def test_a_row_with_no_links_is_not_a_meeting(self) -> None:
        html = """<table><tr><td>September 14, 2025</td><td>No documents posted</td></tr></table>"""
        assert _parse_agenda_center(html, root="https://county.gov", since=date(2025, 1, 1)) == []

    def test_cancellation_is_carried_through(self) -> None:
        html = """
        <table><tr><td>September 14, 2025 CANCELLED</td>
        <td><a href="/a.pdf">Agenda</a></td></tr></table>
        """
        meetings = _parse_agenda_center(html, root="https://county.gov", since=date(2025, 1, 1))
        assert meetings[0].canceled


class TestNormalisation:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Ridgeline Holdings LLC", "ridgeline"),
            ("Ridgeline Holdings, L.L.C.", "ridgeline"),
            ("RIDGELINE HOLDINGS INC.", "ridgeline"),
            ("Compass Datacenters, LLC", "compass datacenters"),
        ],
    )
    def test_corporate_suffixes_are_stripped(self, raw: str, expected: str) -> None:
        assert normalise_organisation(raw) == expected

    def test_word_order_is_preserved(self) -> None:
        """Reordering would merge unrelated companies that share a vocabulary."""
        assert normalise_organisation("Ridgeline Solar") != normalise_organisation(
            "Solar Ridgeline"
        )

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("BOS", "board of supervisors"),
            ("Loudoun Co. BOS", "loudoun co board of supervisors"),
            ("Planning Commission", "planning commission"),
            ("PC", "planning commission"),
        ],
    )
    def test_body_abbreviations_expand(self, raw: str, expected: str) -> None:
        assert normalise_body(raw) == expected

    def test_the_board_alone_is_not_resolvable(self) -> None:
        """Guessing the largest body would be wrong in every county with two."""
        assert normalise_body("the Board") == ""
        assert normalise_body("Board") == ""

    @pytest.mark.parametrize(
        "raw",
        ["J. Smith", "Jane Smith", "Supervisor Smith", "Commissioner Jane Smith", "Chairman Smith"],
    )
    def test_every_spelling_agrees_on_the_surname(self, raw: str) -> None:
        """The surname is the only part reliably present, which is why matching keys on it."""
        surname, _full = normalise_person(raw)
        assert surname == "smith"

    def test_honorifics_do_not_become_the_surname(self) -> None:
        surname, _full = normalise_person("Supervisor Alvarez")
        assert surname == "alvarez"

    @pytest.mark.parametrize(
        "raw",
        ["Pageland 3 LLC", "SPE Holdings LLC", "Project Co LLC", "Solar 12 LLC", "Site A4 LLC"],
    )
    def test_single_purpose_vehicles_are_flagged(self, raw: str) -> None:
        assert looks_like_single_purpose_entity(raw)

    @pytest.mark.parametrize(
        "raw", ["Compass Datacenters LLC", "QTS Realty Trust", "Dominion Energy"]
    )
    def test_operating_companies_are_not_flagged(self, raw: str) -> None:
        assert not looks_like_single_purpose_entity(raw)

    def test_the_adjudication_band_is_wide(self) -> None:
        """Precision above 0.97 is met by making the band wide, not by making thresholds aggressive."""
        assert AUTO_MERGE_SIMILARITY - ADJUDICATE_SIMILARITY >= 0.25


class TestMateriality:
    def _change(self, trigger: AlertTrigger) -> Change:
        return Change(
            jurisdiction_id=1,
            jurisdiction_slug="us-va-loudoun",
            trigger=trigger,
            detected_on=date(2026, 8, 27),
            summary="A moratorium took effect.",
        )

    def test_a_moratorium_always_reaches_the_customer(self) -> None:
        score, suppressed = materiality(
            self._change(AlertTrigger.moratorium_enacted),
            score_before=None,
            score_after=None,
            site_count=1,
        )
        assert suppressed is None
        assert score >= SEND_THRESHOLD

    def test_our_own_data_going_stale_is_below_the_threshold_on_its_own(self) -> None:
        """Worth recording and visible on demand. Not worth interrupting someone for by itself."""
        score, suppressed = materiality(
            self._change(AlertTrigger.source_stale),
            score_before=None,
            score_after=None,
            site_count=1,
        )
        assert suppressed is not None
        assert score < SEND_THRESHOLD

    def test_a_large_score_movement_lifts_a_weak_trigger(self) -> None:
        weak, _ = materiality(
            self._change(AlertTrigger.use_class_on_agenda),
            score_before=None,
            score_after=None,
            site_count=1,
        )
        lifted, suppressed = materiality(
            self._change(AlertTrigger.use_class_on_agenda),
            score_before=0.62,
            score_after=0.31,
            site_count=1,
        )
        assert lifted > weak
        assert suppressed is None

    def test_movement_below_the_noise_floor_is_refitting_not_news(self) -> None:
        change = self._change(AlertTrigger.score_moved)
        _score, suppressed = materiality(
            change,
            score_before=0.500,
            score_after=0.500 + SCORE_NOISE_FLOOR / 2,
            site_count=1,
        )
        assert suppressed is not None
        assert "noise floor" in suppressed

    def test_suppression_always_carries_a_reason(self) -> None:
        """So that 'why did I not hear about this' has an answer."""
        _score, suppressed = materiality(
            self._change(AlertTrigger.source_stale),
            score_before=None,
            score_after=None,
            site_count=1,
        )
        assert suppressed
        assert len(suppressed) > 20

    def test_materiality_never_exceeds_one(self) -> None:
        score, _ = materiality(
            self._change(AlertTrigger.moratorium_enacted),
            score_before=0.9,
            score_after=0.05,
            site_count=50,
        )
        assert score <= 1.0


class TestTranscriptCitation:
    def _transcript(self) -> Transcript:
        return Transcript(
            document_id="a" * 64,
            segments=[
                Segment(
                    ordinal=0,
                    start_ms=6_442_000,
                    end_ms=6_455_000,
                    text="I can't support this until we understand what it does to the aquifer.",
                    speaker_label="SPEAKER_03",
                ),
            ],
            duration_ms=6_455_000,
        )

    def test_the_timestamp_reads_as_a_person_would_write_it(self) -> None:
        segment = self._transcript().segments[0]
        assert segment.timestamp == "1:47:22"

    def test_a_citation_defaults_to_the_diarisation_label(self) -> None:
        """Guessing who spoke is worse than admitting we do not know."""
        transcript = self._transcript()
        citation = transcript.citation_for(transcript.segments[0], hearing_date=date(2025, 9, 14))
        assert "SPEAKER_03" in citation
        assert "1:47:22" in citation
        assert "2025-09-14" in citation

    def test_a_name_is_used_only_when_supplied(self) -> None:
        transcript = self._transcript()
        citation = transcript.citation_for(
            transcript.segments[0],
            hearing_date=date(2025, 9, 14),
            speaker_name="Supervisor Alvarez",
        )
        assert citation.startswith("Supervisor Alvarez, 1:47:22")

    def test_the_full_text_carries_timestamps_so_a_quote_can_be_located(self) -> None:
        text = self._transcript().full_text
        assert "[1:47:22]" in text
        assert "aquifer" in text

    def test_relevant_windows_are_padded_generously(self) -> None:
        """The sentence naming the aquifer often follows the one naming the project by minutes."""
        from auspice.pipeline.transcribe import relevant_windows

        transcript = Transcript(
            document_id="b" * 64,
            segments=[
                Segment(
                    ordinal=0,
                    start_ms=600_000,
                    end_ms=610_000,
                    text="Item 7, the data centre rezoning.",
                ),
                Segment(
                    ordinal=1, start_ms=3_000_000, end_ms=3_010_000, text="Unrelated business."
                ),
            ],
        )
        windows = relevant_windows(transcript, use_class_terms=["data centre", "data center"])
        assert len(windows) == 1
        start, end = windows[0]
        assert start < 600_000, "the window must open before the mention"
        assert end > 610_000, "and close after it"

    def test_no_terms_means_no_windows(self) -> None:
        from auspice.pipeline.transcribe import relevant_windows

        assert relevant_windows(self._transcript(), use_class_terms=[]) == []

    def test_agenda_alignment_leaves_the_opening_unlabelled(self) -> None:
        """Procedural discussion before item one must not be filed under someone's rezoning."""
        from auspice.pipeline.transcribe import align_to_agenda

        transcript = Transcript(
            document_id="c" * 64,
            segments=[
                Segment(ordinal=0, start_ms=0, end_ms=1000, text="Call to order."),
                Segment(ordinal=1, start_ms=600_000, end_ms=601_000, text="Item 7."),
            ],
        )
        aligned = align_to_agenda(transcript, [("Item 7", 500_000)])
        assert aligned.segments[0].agenda_item is None
        assert aligned.segments[1].agenda_item == "Item 7"
