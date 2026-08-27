"""Quote verification. The mechanism behind section 8.3.

The claim being tested is narrow and absolute: a quote that is not in the source document does not
verify, and no amount of near-ness changes that. The tests are written to try to break it in the ways a
language model actually breaks it, which is by producing text that is plausible and slightly wrong.

The one thing verification is allowed to ignore is how whitespace was laid out, because a line break
inside a PDF is a rendering artefact and never content. Those cases are tested too, in both directions.
"""

from __future__ import annotations

import pytest

from auspice.domain import ParseMethod
from auspice.errors import QuoteVerificationError
from auspice.pipeline.extract.verify import verify_extraction_evidence, verify_quote
from auspice.pipeline.parse import ParsedDocument, ParsedPage, normalise_text, parse_html
from auspice.pipeline.parse.cascade import collapse_whitespace

MINUTES = """\
BOARD OF SUPERVISORS
Regular Meeting, 14 September 2025

ITEM 7. REZ-2025-0081. Application of Ridgeline Holdings LLC for a rezoning of
approximately 340 acres from Agricultural to Planned Development Industrial to
permit a data centre campus.

Staff recommended approval with conditions. The Planning Commission recommended
denial by a vote of 5 to 2.

Supervisor Alvarez stated that she could not support the application until the
county understood what it would do to the aquifer, and noted that she had been
asking the same question for six months.

MOTION: Supervisor Boone moved to approve the rezoning. The motion failed on a
vote of 1 to 4, with Supervisor Kim absent.
"""


def _document(text: str, *, document_id: str = "a" * 64) -> ParsedDocument:
    normalised = normalise_text(text) + "\n"
    document = ParsedDocument(document_id=document_id)
    document.pages.append(
        ParsedPage(
            page=1,
            text=normalised,
            char_start=0,
            char_end=len(normalised),
            method=ParseMethod.native_text,
            legibility=1.0,
            escalated=False,
        )
    )
    return document


class TestExactQuotes:
    def test_a_verbatim_quote_verifies(self) -> None:
        document = _document(MINUTES)
        result = verify_quote(document, "The motion failed on a vote of 1 to 4")
        assert result.verified
        assert result.location is not None
        assert result.location.page == 1

    def test_offsets_point_at_the_quote(self) -> None:
        document = _document(MINUTES)
        quote = "Staff recommended approval with conditions."
        result = verify_quote(document, quote)
        assert result.location is not None
        span = document.full_text[result.location.char_start : result.location.char_end]
        assert collapse_whitespace(span)[0] == collapse_whitespace(normalise_text(quote))[0]

    def test_a_quote_spanning_a_line_break_verifies(self) -> None:
        """The bug that made real citations fail. A PDF breaks lines; a transcriber does not."""
        document = _document(MINUTES)
        result = verify_quote(
            document, "Supervisor Boone moved to approve the rezoning. The motion failed on a vote"
        )
        assert result.verified

    def test_curly_punctuation_is_folded(self) -> None:
        document = _document("The chair said \u201cwe are not ready to decide this tonight\u201d.")
        result = verify_quote(document, "we are not ready to decide this tonight")
        assert result.verified

    def test_an_en_dash_in_a_tally_matches_a_hyphen(self) -> None:
        document = _document("defeating the ordinance 8\u20131 after an hours-long debate")
        assert verify_quote(
            document, "defeating the ordinance 8-1 after an hours-long debate"
        ).verified

    def test_a_stray_space_before_a_comma_is_ignored(self) -> None:
        """HTML inserts one at every inline element boundary. It is markup, not content."""
        document = _document("the moratorium on new developments , defeating the ordinance")
        assert verify_quote(
            document, "the moratorium on new developments, defeating the ordinance"
        ).verified


class TestQuotesThatMustFail:
    def test_a_fabricated_quote_does_not_verify(self) -> None:
        document = _document(MINUTES)
        result = verify_quote(
            document, "The Board unanimously approved the application after brief discussion."
        )
        assert not result.verified
        assert result.reason is not None

    def test_a_reversed_vote_does_not_verify(self) -> None:
        """The most damaging single error, and it has to fail on a character."""
        document = _document(MINUTES)
        assert not verify_quote(document, "The motion failed on a vote of 4 to 1").verified

    def test_a_changed_number_does_not_verify(self) -> None:
        document = _document(MINUTES)
        assert not verify_quote(
            document, "approximately 340 acres from Agricultural to Planned Development Commercial"
        ).verified

    def test_a_paraphrase_does_not_verify(self) -> None:
        document = _document(MINUTES)
        assert not verify_quote(
            document,
            "Supervisor Alvarez said she was unable to back the proposal until the county grasped "
            "the aquifer impact",
        ).verified

    def test_a_dropped_negation_does_not_verify(self) -> None:
        document = _document("The applicant did not provide a groundwater study.")
        assert not verify_quote(document, "The applicant did provide a groundwater study.").verified

    def test_a_quote_shorter_than_the_floor_does_not_verify(self) -> None:
        """Short strings appear in every document and are not evidence of anything."""
        document = _document(MINUTES)
        result = verify_quote(document, "approval")
        assert not result.verified
        assert "shorter than" in (result.reason or "")

    def test_an_empty_quote_does_not_verify(self) -> None:
        assert not verify_quote(_document(MINUTES), "").verified


class TestElidedQuotes:
    def test_fragments_in_order_verify(self) -> None:
        document = _document(MINUTES)
        result = verify_quote(
            document,
            "Supervisor Alvarez stated that she could not support the application ... "
            "she had been asking the same question for six months",
        )
        assert result.verified

    def test_fragments_out_of_order_do_not_verify(self) -> None:
        """Order matters. Reordering fragments changes what a document says."""
        document = _document(MINUTES)
        assert not verify_quote(
            document,
            "she had been asking the same question for six months ... "
            "Supervisor Alvarez stated that she could not support the application",
        ).verified

    def test_a_short_fragment_does_not_carry_a_quote(self) -> None:
        document = _document(MINUTES)
        assert not verify_quote(
            document, "The motion failed on a vote of 1 to 4 ... absent"
        ).verified


class TestExtractionEvidence:
    def test_all_quotes_must_verify(self) -> None:
        document = _document(MINUTES)
        evidence = [
            {"page": 1, "quote": "The motion failed on a vote of 1 to 4"},
            {"page": 1, "quote": "The Planning Commission recommended denial"},
        ]
        locations = verify_extraction_evidence(document, evidence)
        assert len(locations) == 2

    def test_one_bad_quote_discards_the_whole_extraction(self) -> None:
        """Section 6.4 rule 1 gives evidence a minimum of one item.

        An extraction whose quote fails has no evidence, and a fact with no evidence does not exist. It
        is discarded rather than kept with the good quotes, because a model that fabricated one citation
        has demonstrated that its reading of the document is not trustworthy.
        """
        document = _document(MINUTES)
        evidence = [
            {"page": 1, "quote": "The motion failed on a vote of 1 to 4"},
            {"page": 1, "quote": "The Board approved the application unanimously"},
        ]
        with pytest.raises(QuoteVerificationError):
            verify_extraction_evidence(document, evidence)

    def test_no_evidence_at_all_raises(self) -> None:
        with pytest.raises(QuoteVerificationError):
            verify_extraction_evidence(_document(MINUTES), [])


class TestPageAttribution:
    def test_a_quote_is_attributed_to_the_right_page(self) -> None:
        document = ParsedDocument(document_id="b" * 64)
        cursor = 0
        for page_number, body in enumerate(
            ["First page about drainage.\n", "Second page about the aquifer study.\n"], start=1
        ):
            document.pages.append(
                ParsedPage(
                    page=page_number,
                    text=body,
                    char_start=cursor,
                    char_end=cursor + len(body),
                    method=ParseMethod.pymupdf,
                    legibility=1.0,
                    escalated=False,
                )
            )
            cursor += len(body)

        result = verify_quote(document, "Second page about the aquifer study")
        assert result.location is not None
        assert result.location.page == 2

    def test_a_page_marker_is_not_part_of_the_source(self) -> None:
        """The extraction prompt inserts page markers. Quoting one must not verify."""
        from auspice.pipeline.extract.pipeline import render_for_model

        document = _document(MINUTES)
        rendered = render_for_model(document)
        assert "[page 1]" in rendered
        assert not verify_quote(document, "[page 1] BOARD OF SUPERVISORS").verified


class TestHtmlExtraction:
    def test_script_and_navigation_are_stripped(self) -> None:
        html = b"""<html><head><style>.a{color:red}</style></head><body>
        <nav>Home Contact</nav>
        <script>var tracking = 1;</script>
        <p>The board voted 4 to 1 to deny the rezoning.</p>
        <footer>Copyright</footer></body></html>"""
        document = parse_html(html, document_id="c" * 64)
        assert verify_quote(document, "The board voted 4 to 1 to deny the rezoning").verified
        assert "var tracking" not in document.full_text
        assert "color:red" not in document.full_text
