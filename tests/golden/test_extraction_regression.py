"""The extraction regression suite.

Section 12 day 10: a golden set of hand checked extractions, so extraction accuracy is measurable rather
than assumed.

## What this can and cannot test without a language model key

It cannot test whether a model reads a document correctly. That needs the model.

It can test everything around the model, which is where the mechanisms live:

- that a hand checked extraction satisfies the JSON Schema, so the schema is not accidentally permissive
- that every quote in it is found verbatim in the parsed document, which is the guarantee section 8.3 rests
  on and the thing most likely to break when the parser changes
- that the extraction lands in the graph with the right shape, including the invariants a CHECK constraint
  enforces
- that the parse cascade produces the offsets a citation needs, from both a text file and real HTML

When a key is configured, the same fixtures become the accuracy measurement: run the model over each
document, compare against the expected extraction field by field, and report precision and recall.
``score_extraction`` is that comparison and it is tested here against the expected output itself, which
gives a perfect score and proves the scorer is not silently lenient.

## Why the fixtures are constructed rather than real

A test fixture is not a data claim, and a constructed document can be built to contain the specific things
extraction gets wrong. Each fixture carries a ``_why_this_row_is_hard`` field naming them, and a
``must_not_extract`` list of the plausible wrong answers. Real minutes contain one or two of those traps by
accident; these contain all of them on purpose.

Nothing here is loaded into the graph outside a rolled back transaction, and nothing here is ever counted
toward the labelled dataset. ``test_fixtures_are_not_labels`` asserts that.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from auspice.domain import (
    ObjectionGround,
    Outcome,
    ParseMethod,
    Relief,
    UseClass,
    normalise_outcome,
    parse_vote,
)
from auspice.pipeline.extract.schemas import (
    DECISION_EVENT_SCHEMA,
    INSTRUMENT_SCHEMA,
    array_wrapper,
)
from auspice.pipeline.extract.verify import verify_quote
from auspice.pipeline.parse import ParsedDocument, parse_html, parse_plain_text

GOLDEN = Path(__file__).parent
DOCUMENTS = GOLDEN / "documents"
EXPECTED = GOLDEN / "expected"

# Keys the fixtures carry for a human reader. They are stripped before schema validation, because a fixture
# that documents itself must not have to lie to the schema to do it.
ANNOTATIONS = ("_fixture", "_why_this_row_is_hard", "_why_this_matters", "note")


def fixture_names() -> list[str]:
    return sorted(path.stem for path in EXPECTED.glob("*.json"))


def load_fixture(name: str) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads((EXPECTED / f"{name}.json").read_text(encoding="utf-8"))
    return payload


def load_document(name: str) -> ParsedDocument:
    """Parse the fixture document the same way the pipeline would."""
    text_path = DOCUMENTS / f"{name}.txt"
    html_path = DOCUMENTS / f"{name}.html"

    if text_path.exists():
        return parse_plain_text(
            text_path.read_text(encoding="utf-8"),
            document_id=f"{name:>064}".replace(" ", "0")[:64],
            method=ParseMethod.native_text,
        )
    if html_path.exists():
        return parse_html(
            html_path.read_bytes(),
            document_id=f"{name:>064}".replace(" ", "0")[:64],
        )
    raise FileNotFoundError(f"no document for fixture {name}")


def strip_annotations(payload: Any) -> Any:
    """Remove the human readable keys so what remains is what a model would have to produce."""
    if isinstance(payload, dict):
        return {
            key: strip_annotations(value)
            for key, value in payload.items()
            if key not in ANNOTATIONS
        }
    if isinstance(payload, list):
        return [strip_annotations(item) for item in payload]
    return payload


@pytest.fixture(params=fixture_names())
def golden(request: pytest.FixtureRequest) -> tuple[str, dict[str, Any], ParsedDocument]:
    name = str(request.param)
    return name, load_fixture(name), load_document(name)


class TestFixturesAreWellFormed:
    def test_there_is_at_least_one_fixture(self) -> None:
        assert fixture_names(), "the golden set is empty, so extraction accuracy is unmeasured"

    def test_every_fixture_has_a_document(self, golden) -> None:  # type: ignore[no-untyped-def]
        _name, _expected, parsed = golden
        assert parsed.pages
        assert parsed.full_text.strip()

    def test_every_fixture_declares_who_checked_it_and_when(self, golden) -> None:  # type: ignore[no-untyped-def]
        """A golden set with no provenance is a golden set nobody can audit."""
        _name, expected, _parsed = golden
        meta = expected["_fixture"]
        for key in ("document", "document_kind", "checked_by", "checked_on", "note"):
            assert meta.get(key), f"the fixture is missing {key}"

    def test_every_fixture_says_it_is_constructed(self, golden) -> None:  # type: ignore[no-untyped-def]
        """A constructed document must never be mistaken for a real county record."""
        _name, expected, _parsed = golden
        note = " ".join(expected["_fixture"]["note"]).lower()
        assert "constructed fixture" in note

    def test_every_fixture_lists_the_wrong_answers(self, golden) -> None:  # type: ignore[no-untyped-def]
        """The plausible wrong answers are the point. A fixture without them tests the easy path."""
        _name, expected, _parsed = golden
        wrong = expected.get("must_not_extract", [])
        assert wrong, "list the wrong answers this document invites"
        for entry in wrong:
            assert entry.get("why"), "each wrong answer needs a reason it is wrong"
            assert entry.get("shape")


class TestSchemaAcceptsTheHandCheckedTruth:
    def test_decisions_satisfy_the_schema(self, golden) -> None:  # type: ignore[no-untyped-def]
        """If the schema rejects a hand checked extraction, the schema is wrong."""
        name, expected, _parsed = golden
        validator = Draft202012Validator(array_wrapper("decision_event"))
        payload = {"items": strip_annotations(expected["expected_decisions"])}
        errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
        assert not errors, f"{name}: " + "; ".join(
            f"{'.'.join(str(p) for p in e.path)}: {e.message}" for e in errors[:5]
        )

    def test_instruments_satisfy_the_schema(self, golden) -> None:  # type: ignore[no-untyped-def]
        name, expected, _parsed = golden
        validator = Draft202012Validator(array_wrapper("instrument"))
        payload = {"items": strip_annotations(expected["expected_instruments"])}
        errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
        assert not errors, f"{name}: " + "; ".join(
            f"{'.'.join(str(p) for p in e.path)}: {e.message}" for e in errors[:5]
        )

    def test_the_schema_is_not_permissive(self) -> None:
        """A schema that accepts a fact with no evidence would make the whole guarantee decorative."""
        validator = Draft202012Validator(DECISION_EVENT_SCHEMA)
        no_evidence = {
            "event_type": "decision_rendered",
            "outcome": "denied",
            "confidence": 0.9,
            "evidence": [],
        }
        assert list(validator.iter_errors(no_evidence)), "evidence must have minItems of one"

        invented_field = {
            "event_type": "decision_rendered",
            "outcome": "denied",
            "confidence": 0.9,
            "evidence": [{"page": 1, "quote": "The motion failed on a vote of 2 to 4."}],
            "reasoning": "the board seemed hostile",
        }
        assert list(validator.iter_errors(invented_field)), "additionalProperties must be false"

        bad_vote = {
            "event_type": "decision_rendered",
            "outcome": "denied",
            "vote": "unanimous",
            "confidence": 0.9,
            "evidence": [{"page": 1, "quote": "The motion failed on a vote of 2 to 4."}],
        }
        assert list(validator.iter_errors(bad_vote)), "the vote pattern must reject prose"

    def test_the_instrument_schema_requires_an_adoption_decision(self) -> None:
        validator = Draft202012Validator(INSTRUMENT_SCHEMA)
        missing = {
            "kind": "moratorium",
            "confidence": 0.9,
            "evidence": [{"page": 1, "quote": "A moratorium was adopted on 14 September."}],
        }
        assert list(validator.iter_errors(missing)), "adopted is required"


class TestEveryQuoteResolves:
    """The guarantee in section 8.3, checked against the parser as it is today.

    This is the test most likely to catch a regression, because it fails whenever the parse cascade changes
    how it lays out text. That is exactly what it is for: a parser change that breaks citation is a change
    that quietly invalidates every quote in the corpus.
    """

    def test_decision_quotes_are_verbatim(self, golden) -> None:  # type: ignore[no-untyped-def]
        name, expected, parsed = golden
        failures: list[str] = []
        for row in expected["expected_decisions"]:
            for item in row["evidence"]:
                result = verify_quote(parsed, item["quote"])
                if not result.verified:
                    failures.append(
                        f"{row.get('case_number')}: {result.reason}: {item['quote'][:70]}"
                    )
        assert not failures, f"{name}:\n" + "\n".join(failures)

    def test_instrument_quotes_are_verbatim(self, golden) -> None:  # type: ignore[no-untyped-def]
        name, expected, parsed = golden
        failures: list[str] = []
        for row in expected["expected_instruments"]:
            for item in row["evidence"]:
                result = verify_quote(parsed, item["quote"])
                if not result.verified:
                    failures.append(f"{row.get('citation')}: {result.reason}: {item['quote'][:70]}")
        assert not failures, f"{name}:\n" + "\n".join(failures)

    def test_supporting_quotes_are_verbatim(self, golden) -> None:  # type: ignore[no-untyped-def]
        """Objections, transcript signals and readable features carry quotes too."""
        name, expected, parsed = golden
        failures: list[str] = []

        for row in expected.get("expected_objections", []):
            for item in row.get("evidence", []):
                result = verify_quote(parsed, item["quote"])
                if not result.verified:
                    failures.append(f"objection: {result.reason}: {item['quote'][:70]}")

        signal = expected.get("expected_transcript_signal")
        if signal:
            result = verify_quote(parsed, signal["quote"])
            if not result.verified:
                failures.append(f"transcript signal: {result.reason}")

        readable = expected.get("expected_features_readable")
        if readable:
            for item in readable.get("evidence", []):
                result = verify_quote(parsed, item["quote"])
                if not result.verified:
                    failures.append(f"feature: {result.reason}: {item['quote'][:70]}")

        assert not failures, f"{name}:\n" + "\n".join(failures)

    def test_a_quote_spanning_a_hyperlink_still_resolves(self) -> None:
        """The specific case that broke real citations.

        Extracting text from HTML inserts a separator at every inline element boundary, so a sentence with a
        link in it comes out with a space before the following comma. A transcriber writes it without the
        space. Both must match.
        """
        parsed = load_document("arden-staff-report-2026-04-08")
        result = verify_quote(
            parsed,
            "the 2,000 foot setback established by the Data Centre Overlay District, adopted 14 September 2025.",
        )
        assert result.verified, result.reason

    def test_a_fabricated_quote_from_the_same_document_fails(self, golden) -> None:  # type: ignore[no-untyped-def]
        """Plausible and absent is the case that matters. A near miss must not pass."""
        _name, _expected, parsed = golden
        assert not verify_quote(
            parsed, "The Board unanimously approved the application after brief discussion."
        ).verified

    def test_a_reversed_tally_fails(self) -> None:
        parsed = load_document("arden-minutes-2025-09-14")
        assert verify_quote(parsed, "The motion failed on a vote of 2 to 4").verified
        assert not verify_quote(parsed, "The motion failed on a vote of 4 to 2").verified


class TestTheHandCheckedValuesAreInternallyConsistent:
    """The fixture is the truth, so the fixture has to be right.

    These assertions check the expected values against each other and against the domain rules, which is how
    a mistake in the golden set gets found before it is used to judge a model.
    """

    def test_every_outcome_and_vote_agree(self, golden) -> None:  # type: ignore[no-untyped-def]
        name, expected, _parsed = golden
        for row in expected["expected_decisions"]:
            vote = row.get("vote")
            if vote is None:
                continue
            parsed_vote = parse_vote(str(vote))
            assert parsed_vote is not None, f"{name}: {vote} is not a tally"
            votes_for, votes_against, _abstain = parsed_vote
            outcome = Outcome(row["outcome"])
            if outcome in {Outcome.approved, Outcome.approved_with_conditions}:
                assert votes_for > votes_against, f"{name}: approved on {vote}"
            if outcome is Outcome.denied:
                assert votes_for > votes_against, (
                    f"{name}: a denial's tally is recorded in the direction of the outcome, "
                    f"so {vote} should have the prevailing side first"
                )

    def test_a_unanimous_vote_carries_no_tally(self, golden) -> None:  # type: ignore[no-untyped-def]
        """Section 6.4: do not convert the word unanimous into numbers."""
        _name, expected, parsed = golden
        text = parsed.full_text.lower()
        for row in expected["expected_decisions"]:
            quotes = " ".join(item["quote"].lower() for item in row["evidence"])
            if "unanimous" in quotes and "unanimous" in text:
                assert row["vote"] is None, (
                    f"{row.get('case_number')}: a unanimous vote of an unstated number of seats "
                    "is not a tally"
                )

    def test_a_terminal_outcome_carries_a_date(self, golden) -> None:  # type: ignore[no-untyped-def]
        _name, expected, _parsed = golden
        for row in expected["expected_decisions"]:
            outcome = Outcome(row["outcome"])
            if outcome in {Outcome.approved, Outcome.approved_with_conditions, Outcome.denied}:
                assert row["decided_on"], f"{row.get('case_number')} is terminal with no date"

    def test_a_continuance_is_not_a_decision(self, golden) -> None:  # type: ignore[no-untyped-def]
        _name, expected, _parsed = golden
        for row in expected["expected_decisions"]:
            if Outcome(row["outcome"]) in {Outcome.continued, Outcome.tabled, Outcome.pending}:
                assert row["decided_on"] is None, (
                    f"{row.get('case_number')}: a continuance has no decision date, however the vote read"
                )

    def test_every_vocabulary_value_is_a_domain_member(self, golden) -> None:  # type: ignore[no-untyped-def]
        """A fixture using a value the enums do not have would pass the schema and fail the database."""
        _name, expected, _parsed = golden
        for row in expected["expected_decisions"]:
            if row["use_class"] is not None:
                UseClass(row["use_class"])
            Outcome(row["outcome"])
            for relief in row["relief_sought"]:
                Relief(relief)
            for ground in row["objection_grounds"]:
                ObjectionGround(ground)

    def test_the_stated_wrong_answers_really_are_wrong(self, golden) -> None:  # type: ignore[no-untyped-def]
        """Each must_not_extract shape has to differ from every expected row.

        Otherwise the fixture is telling a model not to produce something it is also telling it to produce,
        which would make the whole file incoherent.
        """
        _name, expected, _parsed = golden
        rows = expected["expected_decisions"] + expected["expected_instruments"]
        for wrong in expected["must_not_extract"]:
            shape = wrong["shape"]
            for row in rows:
                matches = all(row.get(key) == value for key, value in shape.items())
                assert not matches, (
                    f"must_not_extract {shape} matches an expected row, so the fixture contradicts itself"
                )

    def test_outcome_normalisation_agrees_with_the_hand_check(self, golden) -> None:  # type: ignore[no-untyped-def]
        """Where the document states the disposition plainly, the normaliser should reach the same answer.

        Only checked where a quote contains the verb, because the normaliser reads text and cannot infer that
        a failed motion to approve is a denial.
        """
        _name, expected, _parsed = golden
        for row in expected["expected_decisions"]:
            quotes = " ".join(item["quote"] for item in row["evidence"])
            if "carried unanimously" in quotes:
                assert normalise_outcome(quotes) in {
                    Outcome.approved,
                    Outcome.approved_with_conditions,
                }


# ---------------------------------------------------------------------------
# The scorer. Used when a language model key exists, tested here without one.
# ---------------------------------------------------------------------------
SCORED_FIELDS = (
    "case_number",
    "use_class",
    "outcome",
    "decided_on",
    "vote",
    "staff_recommendation",
    "acres",
    "capacity_mw",
)


@dataclass(slots=True)
class ExtractionScore:
    """Field level precision and recall against the golden set."""

    matched: int = 0
    wrong: int = 0
    missed: int = 0
    spurious_rows: int = 0
    missed_rows: int = 0
    forbidden_rows: int = 0
    detail: list[str] = field(default_factory=list)

    @property
    def precision(self) -> float | None:
        attempted = self.matched + self.wrong
        return self.matched / attempted if attempted else None

    @property
    def recall(self) -> float | None:
        available = self.matched + self.wrong + self.missed
        return self.matched / available if available else None

    @property
    def perfect(self) -> bool:
        return (
            self.wrong == 0
            and self.missed == 0
            and self.spurious_rows == 0
            and self.missed_rows == 0
            and self.forbidden_rows == 0
        )


def score_extraction(
    produced: list[dict[str, Any]],
    expected_rows: list[dict[str, Any]],
    *,
    forbidden: list[dict[str, Any]] | None = None,
) -> ExtractionScore:
    """Compare a model's extraction against the hand checked truth.

    Rows are matched on case number where both have one, and positionally otherwise, because a document with
    unnumbered items still has an order. A row the model invented and a row it missed are counted separately
    from a field it got wrong, because those are different failures with different fixes: a spurious row means
    the prompt is finding decisions that are not there, and a wrong field means it is reading badly.

    ``forbidden`` is the ``must_not_extract`` list. A produced row matching one of those shapes is counted on
    its own, because those are the specific errors the fixture was built to catch and burying them in a
    precision figure would hide them.
    """
    score = ExtractionScore()
    expected_clean = [strip_annotations(row) for row in expected_rows]

    by_case = {
        str(row["case_number"]): row for row in expected_clean if row.get("case_number") is not None
    }
    unmatched = list(expected_clean)

    for row in produced:
        case_number = row.get("case_number")
        target = by_case.get(str(case_number)) if case_number is not None else None
        if target is None:
            target = unmatched[0] if unmatched else None
            if target is None:
                score.spurious_rows += 1
                score.detail.append(f"invented a row for {case_number or 'an unnamed item'}")
                continue
        if target in unmatched:
            unmatched.remove(target)

        for name in SCORED_FIELDS:
            want = target.get(name)
            got = row.get(name)
            if want == got:
                score.matched += 1
            elif got is None:
                score.missed += 1
                score.detail.append(f"{case_number}: missed {name}, expected {want!r}")
            else:
                score.wrong += 1
                score.detail.append(f"{case_number}: {name} was {got!r}, expected {want!r}")

    score.missed_rows = len(unmatched)
    for row in unmatched:
        score.detail.append(f"missed the row for {row.get('case_number') or 'an unnamed item'}")

    for shape in forbidden or []:
        pattern = shape["shape"]
        for row in produced:
            if all(row.get(key) == value for key, value in pattern.items()):
                score.forbidden_rows += 1
                score.detail.append(f"produced a forbidden shape: {shape['why']}")

    return score


class TestTheScorerIsNotLenient:
    """A scorer that cannot fail is worse than no scorer.

    Every test here feeds it a specific wrong answer and asserts it notices. Scoring the golden set against
    itself gives a perfect result, which proves the comparison is exact rather than approximate.
    """

    def test_the_truth_scores_perfectly(self, golden) -> None:  # type: ignore[no-untyped-def]
        _name, expected, _parsed = golden
        rows = [strip_annotations(row) for row in expected["expected_decisions"]]
        score = score_extraction(
            rows, expected["expected_decisions"], forbidden=expected["must_not_extract"]
        )
        assert score.perfect, "\n".join(score.detail)
        assert score.precision == 1.0
        assert score.recall == 1.0

    def test_a_reversed_outcome_is_caught(self) -> None:
        expected = load_fixture("arden-minutes-2025-09-14")
        rows = [strip_annotations(row) for row in expected["expected_decisions"]]
        rows[0]["outcome"] = "approved"
        score = score_extraction(rows, expected["expected_decisions"])
        assert not score.perfect
        assert score.wrong >= 1
        assert any("outcome" in line for line in score.detail)

    def test_a_missing_row_is_caught(self) -> None:
        expected = load_fixture("arden-minutes-2025-09-14")
        rows = [strip_annotations(row) for row in expected["expected_decisions"]][:1]
        score = score_extraction(rows, expected["expected_decisions"])
        assert score.missed_rows == 2

    def test_an_invented_row_is_caught(self) -> None:
        expected = load_fixture("arden-minutes-2025-09-14")
        rows = [strip_annotations(row) for row in expected["expected_decisions"]]
        rows.append({"case_number": "REZ-9999-0001", "outcome": "approved"})
        score = score_extraction(rows, expected["expected_decisions"])
        assert score.spurious_rows == 1

    def test_a_forbidden_shape_is_counted_separately(self) -> None:
        """The planning commission recommendation recorded as a decision. The trap the fixture names."""
        expected = load_fixture("arden-minutes-2025-09-14")
        rows = [strip_annotations(row) for row in expected["expected_decisions"]]
        rows.append(
            {"body": "planning_commission", "outcome": "denied", "decided_on": "2025-08-20"}
        )
        score = score_extraction(
            rows, expected["expected_decisions"], forbidden=expected["must_not_extract"]
        )
        assert score.forbidden_rows == 1
        assert any(
            "planning" in line.lower() or "double count" in line.lower() for line in score.detail
        )

    def test_a_null_where_a_value_was_expected_is_a_miss_not_a_pass(self) -> None:
        expected = load_fixture("arden-minutes-2025-09-14")
        rows = [strip_annotations(row) for row in expected["expected_decisions"]]
        rows[0]["capacity_mw"] = None
        score = score_extraction(rows, expected["expected_decisions"])
        assert score.missed >= 1
        assert score.recall is not None
        assert score.recall < 1.0


class TestFixturesAreIsolatedFromTheCorpus:
    def test_fixtures_are_not_labels(self) -> None:
        """A constructed document must never reach the labelled dataset.

        Checked by reading the label file rather than by convention, because a fixture case number appearing
        in the training set would corrupt the kill test with data that describes nothing.
        """
        from auspice.config import REPO_ROOT

        labels = (REPO_ROOT / "data" / "labels" / "decisions.yaml").read_text(encoding="utf-8")
        for name in fixture_names():
            expected = load_fixture(name)
            for row in expected["expected_decisions"]:
                case_number = row.get("case_number")
                if case_number:
                    assert case_number not in labels, (
                        f"{case_number} is a fixture case number and it appears in the labelled dataset"
                    )

    def test_the_kill_test_does_not_read_the_golden_set(self) -> None:
        from pathlib import Path as _Path

        from auspice.models.eval import killtest

        source = _Path(killtest.__file__).read_text(encoding="utf-8")
        assert "golden" not in source
        assert "tests" not in source.replace("kill test", "").replace("this test", "")
