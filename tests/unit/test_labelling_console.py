"""The labelling console has to be safe on the one file that cannot be regenerated.

`data/labels/decisions.yaml` is the asset. Its value is partly the rows and partly the diff history:
every row has an author and a date because it is version controlled. Two properties therefore have to
hold, and neither is obvious from reading the code.

**Inserting a row changes only that row.** If the writer ever loaded and re-dumped the file, one added
row would reformat all of it, drop every comment and reflow every quote, and the audit trail would be
gone. The tests here assert the original bytes survive an insertion.

**A selected quote verifies.** The point of selecting a quote out of the parsed document instead of
retyping it is that the verifier cannot then reject it. That claim is tested by running the real
verifier on the real candidates, not by inspection. Three citations in the repository fail
verification today, all of them transcription errors, which is why this matters.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from auspice.domain import ParseMethod
from auspice.pipeline.extract.verify import verify_quote
from auspice.pipeline.graph import labelling
from auspice.pipeline.graph.labelling import LabellingError
from auspice.pipeline.parse import ParsedDocument, ParsedPage

MINUTES = (
    "BOARD OF SUPERVISORS REGULAR MEETING\n"
    "Tuesday, 12 March 2024\n"
    "\n"
    "Item 7. REZ-2024-0014, Northgate Technology Park. The applicant requests rezoning of 412 "
    "acres from A-1 Agricultural to PD-IP Planned Development Industrial Park to permit a "
    "hyperscale data centre campus with a connected load of 300 megawatts.\n"
    "\n"
    "Staff recommended approval subject to the proffers dated 4 March 2024.\n"
    "\n"
    "Forty one citizens spoke. Objections addressed groundwater withdrawal, transmission line "
    "routing and night time noise from the cooling plant.\n"
    "\n"
    "Supervisor Ellery moved to approve REZ-2024-0014 with the proffers as amended. The motion "
    "carried on a vote of five to three, with Supervisor Nakamura absent.\n"
    "\n"
    "Item 8. SUP-2024-0031 was continued to the meeting of 9 April 2024 at the request of the "
    "applicant.\n"
)


def _parsed(text: str = MINUTES, *, document_id: str = "a" * 64) -> ParsedDocument:
    """One page, which is what a scraped HTML minutes page parses to."""
    return ParsedDocument(
        document_id=document_id,
        pages=[
            ParsedPage(
                page=1,
                text=text,
                char_start=0,
                char_end=len(text),
                method=ParseMethod.native_text,
                legibility=1.0,
                escalated=False,
            )
        ],
        methods_used={ParseMethod.native_text},
    )


# ---------------------------------------------------------------------------
# Quote selection
# ---------------------------------------------------------------------------
class TestQuoteSelection:
    def test_a_phrase_returns_the_sentence_that_contains_it(self) -> None:
        """The sentence, not the surrounding paragraph. A citation is one quotation."""
        candidates = labelling.find_quote_candidates(_parsed(), "five to three")
        assert len(candidates) == 1
        assert candidates[0].text == (
            "The motion carried on a vote of five to three, with Supervisor Nakamura absent."
        )

    def test_the_motion_and_the_tally_are_reachable_as_separate_citations(self) -> None:
        """Two sentences, two candidates, because they support different fields.

        The motion sentence supports the relief and the outcome. The tally sentence supports the
        vote. Offering the paragraph as one quote would blur which sentence evidences which field.
        """
        motion = labelling.find_quote_candidates(_parsed(), "moved to approve")
        tally = labelling.find_quote_candidates(_parsed(), "five to three")
        assert motion[0].text.startswith("Supervisor Ellery moved to approve")
        assert tally[0].text.startswith("The motion carried")
        assert motion[0].text != tally[0].text

    def test_every_candidate_verifies_against_the_same_document(self) -> None:
        """The whole reason this module exists. A selected quote cannot fail verification."""
        parsed = _parsed()
        for phrase in ("five to three", "412", "Staff recommended", "groundwater", "continued to"):
            for candidate in labelling.find_quote_candidates(parsed, phrase):
                result = verify_quote(parsed, candidate.text)
                assert result.verified, (
                    f"{phrase!r} produced a candidate that fails: {result.reason}"
                )

    def test_the_recorded_offsets_are_the_verifiers_own(self) -> None:
        """Offsets come from parsed.locate, so the evidence row points where the verifier looks."""
        parsed = _parsed()
        candidate = labelling.find_quote_candidates(parsed, "five to three")[0]
        result = verify_quote(parsed, candidate.text)
        assert result.location is not None
        assert (result.location.page, result.location.char_start, result.location.char_end) == (
            candidate.page,
            candidate.char_start,
            candidate.char_end,
        )

    def test_the_search_is_case_insensitive_but_the_quote_is_not_altered(self) -> None:
        candidate = labelling.find_quote_candidates(_parsed(), "SUPERVISOR ELLERY")[0]
        assert "Supervisor Ellery" in candidate.text
        assert verify_quote(_parsed(), candidate.text).verified

    def test_context_is_returned_so_relevance_can_be_judged(self) -> None:
        candidate = labelling.find_quote_candidates(_parsed(), "five to three")[0]
        assert candidate.context_before
        assert "Item 8" in candidate.context_after

    def test_several_matches_are_all_offered(self) -> None:
        candidates = labelling.find_quote_candidates(_parsed(), "2024")
        assert len(candidates) >= 3
        assert len({c.text for c in candidates}) == len(candidates)

    def test_a_phrase_that_is_absent_returns_nothing_rather_than_a_guess(self) -> None:
        assert labelling.find_quote_candidates(_parsed(), "unanimously denied") == []

    def test_an_empty_phrase_is_refused(self) -> None:
        with pytest.raises(LabellingError, match="search phrase is required"):
            labelling.find_quote_candidates(_parsed(), "   ")

    def test_a_document_that_parsed_to_nothing_is_refused_with_the_reason(self) -> None:
        with pytest.raises(LabellingError, match="parsed to no text"):
            labelling.find_quote_candidates(_parsed(""), "anything")

    def test_a_runaway_sentence_is_trimmed_to_a_quotable_length(self) -> None:
        """A badly parsed page can produce one sentence of thousands of characters.

        The schema ceiling is 500. Offering a candidate that validation would then reject wastes the
        labeller's time, so the trim happens here.
        """
        wall = "the board considered the matter at length " * 60 + "and the vote was five to three."
        candidates = labelling.find_quote_candidates(_parsed(wall), "five to three")
        assert candidates, "a long sentence must still yield a candidate"
        for candidate in candidates:
            assert candidate.quotable
            assert len(candidate.text) <= labelling.MAX_QUOTE_CHARS
            assert verify_quote(_parsed(wall), candidate.text).verified

    def test_candidates_are_bounded(self) -> None:
        many = "the vote was five to three. " * 50
        assert len(labelling.find_quote_candidates(_parsed(many), "five to three", limit=4)) == 4


# ---------------------------------------------------------------------------
# Identifiers
# ---------------------------------------------------------------------------
class TestLabelIds:
    def test_an_id_is_readable_and_matches_the_schema_pattern(self) -> None:
        import re

        from auspice.pipeline.graph.labels import DecisionLabel

        pattern = DecisionLabel.model_fields["label_id"].metadata[0].pattern
        generated = labelling.suggest_label_id(
            jurisdiction="us-va-loudoun",
            subject="Northgate Technology Park rezoning",
            on=date(2024, 3, 12),
        )
        assert generated == "loudoun-northgate-technology-park-rezoning-2024"
        assert re.match(pattern, generated)

    def test_a_taken_id_is_not_reused(self) -> None:
        taken = ["loudoun-northgate-2024"]
        generated = labelling.suggest_label_id(
            jurisdiction="us-va-loudoun", subject="Northgate", on=date(2024, 3, 12), taken=taken
        )
        assert generated == "loudoun-northgate-2024-2"
        assert generated not in taken

    def test_an_undated_row_is_still_given_an_id(self) -> None:
        generated = labelling.suggest_label_id(
            jurisdiction="us-tx-tarrant", subject="Pending application", on=None
        )
        assert generated.endswith("-undated")

    def test_ids_already_in_the_real_corpus_are_found(self) -> None:
        from auspice.config import get_settings

        path = get_settings().labels_path / "decisions.yaml"
        ids = labelling.existing_label_ids(path)
        assert "pwc-digital-gateway-rezoning-2023" in ids
        assert len(ids) >= 4


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------
def _corpus(tmp_path: Path) -> Path:
    """A copy of the real corpus, so the tests exercise the real structure and comments."""
    from auspice.config import get_settings

    source = get_settings().labels_path / "decisions.yaml"
    destination = tmp_path / "decisions.yaml"
    destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8", newline="")
    return destination


def _decision_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "label_id": "loudoun-northgate-rezoning-2024",
        "jurisdiction": "us-va-loudoun",
        "labelled_by": "Test Labeller",
        "labelled_on": date(2026, 8, 31),
        "body": "board_of_supervisors",
        "use_class": "data_center_hyperscale",
        "relief_sought": ["rezoning"],
        "acres": 412.0,
        "capacity_mw": 300.0,
        "filed_on": date(2023, 11, 1),
        "decided_on": date(2024, 3, 12),
        "outcome": "approved",
        "vote_for": 5,
        "vote_against": 3,
        "citations": [
            {
                "url": "https://www.loudoun.gov/minutes/2024-03-12",
                "document_title": "Board of Supervisors minutes, 12 March 2024",
                "quote": (
                    "Supervisor Ellery moved to approve REZ-2024-0014 with the proffers as "
                    "amended. The motion carried on a vote of five to three, with Supervisor "
                    "Nakamura absent."
                ),
                "retrieved_on": date(2026, 8, 31),
                "kind": "primary",
            }
        ],
    }
    payload.update(overrides)
    return payload


class TestInsertionIsNonDestructive:
    def test_the_original_text_survives_byte_for_byte(self, tmp_path: Path) -> None:
        path = _corpus(tmp_path)
        before = path.read_text(encoding="utf-8")

        labelling.append_decision(path, _decision_payload())

        after = path.read_text(encoding="utf-8")
        # Every original line is still present, in order, with nothing rewritten.
        original_lines = before.splitlines()
        new_lines = after.splitlines()
        cursor = 0
        for line in original_lines:
            assert line in new_lines[cursor:], f"insertion removed or rewrote: {line!r}"
            cursor = new_lines.index(line, cursor) + 1

    def test_the_comments_survive(self, tmp_path: Path) -> None:
        path = _corpus(tmp_path)
        labelling.append_decision(path, _decision_payload())
        after = path.read_text(encoding="utf-8")
        assert "# The labelled decision dataset." in after
        assert "# INSTRUMENTS" in after
        assert after.count("# ===") >= 4

    def test_the_row_lands_in_the_decisions_sequence(self, tmp_path: Path) -> None:
        path = _corpus(tmp_path)
        before = yaml.safe_load(path.read_text(encoding="utf-8"))
        labelling.append_decision(path, _decision_payload())
        after = yaml.safe_load(path.read_text(encoding="utf-8"))

        assert len(after["decisions"]) == len(before["decisions"]) + 1
        assert len(after["instruments"]) == len(before["instruments"])
        assert after["decisions"][-1]["label_id"] == "loudoun-northgate-rezoning-2024"

    def test_the_file_still_validates_and_the_row_is_typed(self, tmp_path: Path) -> None:
        path = _corpus(tmp_path)
        label_set = labelling.append_decision(path, _decision_payload())
        row = next(
            d for d in label_set.decisions if d.label_id == "loudoun-northgate-rezoning-2024"
        )
        assert row.outcome.value == "approved"
        assert row.citations[0].kind == "primary"
        assert row.acres == 412.0

    def test_two_rows_can_be_added_in_sequence(self, tmp_path: Path) -> None:
        path = _corpus(tmp_path)
        labelling.append_decision(path, _decision_payload())
        labelling.append_decision(
            path, _decision_payload(label_id="loudoun-southgate-rezoning-2024")
        )
        after = yaml.safe_load(path.read_text(encoding="utf-8"))
        ids = [d["label_id"] for d in after["decisions"]]
        assert ids[-2:] == ["loudoun-northgate-rezoning-2024", "loudoun-southgate-rezoning-2024"]

    def test_an_instrument_lands_in_the_instruments_sequence(self, tmp_path: Path) -> None:
        path = _corpus(tmp_path)
        before = yaml.safe_load(path.read_text(encoding="utf-8"))
        labelling.append_instrument(
            path,
            {
                "label_id": "tarrant-moratorium-2026",
                "jurisdiction": "us-tx-tarrant",
                "labelled_by": "Test Labeller",
                "labelled_on": date(2026, 8, 31),
                "kind": "moratorium",
                "title": "Six month moratorium on data centre applications",
                "adopted_on": date(2026, 5, 4),
                "citations": [
                    {
                        "url": "https://www.tarrantcountytx.gov/minutes/2026-05-04",
                        "document_title": "Commissioners Court minutes, 4 May 2026",
                        "quote": "The Court adopted a six month moratorium on new data centre applications.",
                        "retrieved_on": date(2026, 8, 31),
                        "kind": "primary",
                    }
                ],
            },
        )
        after = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert len(after["instruments"]) == len(before["instruments"]) + 1
        assert len(after["decisions"]) == len(before["decisions"])
        assert after["instruments"][-1]["label_id"] == "tarrant-moratorium-2026"


class TestInsertionRefusesRatherThanCorrupts:
    def test_a_duplicate_id_is_refused_and_the_file_is_left_alone(self, tmp_path: Path) -> None:
        path = _corpus(tmp_path)
        before = path.read_text(encoding="utf-8")
        with pytest.raises(ValidationError, match="duplicate label_id"):
            labelling.append_decision(
                path, _decision_payload(label_id="pwc-digital-gateway-rezoning-2023")
            )
        assert path.read_text(encoding="utf-8") == before

    def test_an_invalid_row_is_refused_before_the_file_is_touched(self, tmp_path: Path) -> None:
        path = _corpus(tmp_path)
        before = path.read_text(encoding="utf-8")
        with pytest.raises(ValidationError, match="decided_on"):
            # A terminal outcome with no decision date, which the schema forbids.
            labelling.append_decision(path, _decision_payload(decided_on=None))
        assert path.read_text(encoding="utf-8") == before

    def test_a_row_with_no_citation_is_refused(self, tmp_path: Path) -> None:
        path = _corpus(tmp_path)
        before = path.read_text(encoding="utf-8")
        with pytest.raises(ValidationError, match="at least 1 item"):
            labelling.append_decision(path, _decision_payload(citations=[]))
        assert path.read_text(encoding="utf-8") == before

    def test_one_secondary_citation_alone_is_refused(self, tmp_path: Path) -> None:
        """The corpus rule: one official record, or two reports from different hosts."""
        path = _corpus(tmp_path)
        payload = _decision_payload()
        citations = payload["citations"]
        assert isinstance(citations, list)
        citations[0]["kind"] = "secondary"
        with pytest.raises(ValidationError, match="two citations from different hosts"):
            labelling.append_decision(path, payload)

    def test_a_missing_file_is_refused_rather_than_created(self, tmp_path: Path) -> None:
        with pytest.raises(LabellingError, match="does not exist"):
            labelling.insert_row(
                tmp_path / "absent.yaml", section="decisions", row_text="  - label_id: x\n"
            )

    def test_a_file_without_both_sections_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "partial.yaml"
        path.write_text("version: '0.1.0'\ndecisions: []\n", encoding="utf-8", newline="")
        with pytest.raises(LabellingError, match="top level"):
            labelling.insert_row(path, section="decisions", row_text="  - label_id: x\n")

    def test_an_unknown_section_is_refused(self, tmp_path: Path) -> None:
        path = _corpus(tmp_path)
        with pytest.raises(LabellingError, match="unknown section"):
            labelling.insert_row(path, section="votes", row_text="  - label_id: x\n")


class TestRenderedRows:
    def test_a_quote_with_awkward_characters_round_trips(self) -> None:
        """Quotes contain colons, hashes, quotation marks and dashes. YAML has opinions about all of them."""
        awkward = (
            'The chair stated: "the application is denied" -- see #7 of the agenda, '
            "and the record reflects a 4-3 vote."
        )
        text = labelling.render_row({"label_id": "x-1", "quote": awkward})
        # Wrap in a mapping so the two space indent the row carries is valid in context, which is
        # exactly how it sits in the real file.
        loaded = yaml.safe_load("root:\n" + text)
        assert loaded["root"][0]["quote"] == awkward

    def test_rows_are_indented_to_sit_inside_a_sequence(self) -> None:
        text = labelling.render_row({"label_id": "x-1"})
        assert text.startswith("  - label_id: x-1")

    def test_key_order_is_preserved_rather_than_sorted(self) -> None:
        text = labelling.render_row({"zebra": 1, "apple": 2})
        assert text.index("zebra") < text.index("apple")
