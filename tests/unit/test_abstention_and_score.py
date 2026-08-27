"""The abstention rule and the score object's invariants.

Section 8.4 and section 5.6. These are the rules that let the product refuse to answer, and the rules
that stop a refusal from being quietly converted back into a number somewhere downstream.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas import PortfolioResponse, PortfolioRow
from auspice.domain import AbstentionReason, Confidence, JurisdictionRole, Relief, UseClass
from auspice.models.eval.thresholds import (
    ABSTAIN_MAX_COMPARABLES,
    ABSTAIN_MAX_INTERVAL_WIDTH,
    ABSTAIN_MAX_POOLING_WEIGHT,
    STALENESS_ABSTAIN_DAYS,
)
from auspice.score import (
    AbstentionInput,
    Determination,
    Driver,
    Evidence,
    JurisdictionLink,
    Provenance,
    Score,
    Site,
    TimeToDecision,
    confidence_for,
    decide,
    pooling_note,
)


def _thin() -> AbstentionInput:
    """All three section 8.4 conditions satisfied."""
    return AbstentionInput(
        n_comparable_decisions=1,
        pooling_weight=0.92,
        interval_width=0.51,
        staleness_days=2,
    )


class TestAbstentionRule:
    def test_all_three_conditions_abstains(self) -> None:
        decision = decide(_thin())
        assert decision.abstained
        assert AbstentionReason.thin_local_record in decision.reasons
        assert AbstentionReason.dominated_by_pooling in decision.reasons
        assert AbstentionReason.interval_too_wide in decision.reasons

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("n_comparable_decisions", ABSTAIN_MAX_COMPARABLES),
            ("pooling_weight", ABSTAIN_MAX_POOLING_WEIGHT),
            ("interval_width", ABSTAIN_MAX_INTERVAL_WIDTH),
        ],
    )
    def test_any_condition_failing_answers(self, field: str, value: float) -> None:
        """The conditions are joined by AND.

        A rule that fired on any one of them would abstain on most of the corpus, which is not
        intelligence, it is refusing to work. This parametrisation is the guard against someone
        "simplifying" the rule to an OR.
        """
        inputs = _thin()
        relaxed = AbstentionInput(
            n_comparable_decisions=int(value)
            if field == "n_comparable_decisions"
            else inputs.n_comparable_decisions,
            pooling_weight=value if field == "pooling_weight" else inputs.pooling_weight,
            interval_width=value if field == "interval_width" else inputs.interval_width,
            staleness_days=inputs.staleness_days,
        )
        assert not decide(relaxed).abstained


class TestPortfolioCountsAddUp:
    """The summary line above a ranked list, which a reader trusts before they read the rows.

    ``scored`` counted every row including the abstentions, so a portfolio where nothing could be scored
    reported three scored and three abstained out of three sites. It is invisible in the JSON and obvious
    the moment the two numbers sit next to each other on a screen, which is where it was found. A header
    that contradicts itself discredits every number under it.
    """

    @staticmethod
    def _row(*, abstained: bool, probability: float | None, public_id: str) -> PortfolioRow:
        return PortfolioRow(
            label=public_id,
            jurisdiction="Somewhere County",
            approval_probability=probability,
            credible_interval_80=None if probability is None else (0.3, 0.6),
            abstained=abstained,
            months_p50=None,
            rule_change_probability=None,
            data_depth=0,
            stale=False,
            public_id=public_id,
        )

    def test_a_valid_response_constructs(self) -> None:

        response = PortfolioResponse(
            ranked=[
                self._row(abstained=False, probability=0.45, public_id="a"),
                self._row(abstained=True, probability=None, public_id="b"),
            ],
            submitted=2,
            scored=1,
            abstained=1,
        )
        assert response.scored + response.abstained == response.submitted

    def test_the_all_abstained_case_that_exposed_it(self) -> None:

        rows = [self._row(abstained=True, probability=None, public_id=str(n)) for n in range(3)]
        response = PortfolioResponse(ranked=rows, submitted=3, scored=0, abstained=3)
        assert response.scored == 0

        with pytest.raises(ValidationError, match="does not equal"):
            PortfolioResponse(ranked=rows, submitted=3, scored=3, abstained=3)

    def test_a_row_count_that_disagrees_is_refused(self) -> None:

        with pytest.raises(ValidationError, match="Every site gets a row"):
            PortfolioResponse(
                ranked=[self._row(abstained=False, probability=0.5, public_id="a")],
                submitted=2,
                scored=2,
                abstained=0,
            )

    def test_an_abstention_count_that_disagrees_with_the_rows_is_refused(self) -> None:

        with pytest.raises(ValidationError, match="the rows contain"):
            PortfolioResponse(
                ranked=[
                    self._row(abstained=True, probability=None, public_id="a"),
                    self._row(abstained=True, probability=None, public_id="b"),
                ],
                submitted=2,
                scored=1,
                abstained=1,
            )

    def test_an_abstained_row_cannot_carry_a_probability(self) -> None:
        """Asserted on the row rather than the summary, because this is the one that misleads silently.

        Built from a dict so the validator runs on construction, which is the path a response body takes.
        """
        from app.schemas import PortfolioRow

        base = {
            "label": "a",
            "jurisdiction": "Somewhere County",
            "months_p50": None,
            "rule_change_probability": None,
            "data_depth": 0,
            "stale": False,
            "public_id": "a",
        }

        with pytest.raises(ValidationError, match="cannot carry a probability"):
            PortfolioRow.model_validate(
                {
                    **base,
                    "approval_probability": 0.12,
                    "credible_interval_80": (0.0, 0.3),
                    "abstained": True,
                }
            )

        with pytest.raises(ValidationError, match="point estimate posing as a range"):
            PortfolioRow.model_validate(
                {
                    **base,
                    "approval_probability": 0.55,
                    "credible_interval_80": None,
                    "abstained": False,
                }
            )

        with pytest.raises(ValidationError, match="inverted"):
            PortfolioRow.model_validate(
                {
                    **base,
                    "approval_probability": 0.55,
                    "credible_interval_80": (0.8, 0.2),
                    "abstained": False,
                }
            )

    def test_the_router_computes_scored_by_subtraction(self) -> None:
        """Read the source, because the arithmetic is one line and easy to reintroduce.

        The validator catches a wrong count at runtime. This catches the specific wrong expression, so a
        reviewer sees why it is written the way it is.
        """
        from pathlib import Path

        import app.routers.score as score_router

        source = Path(score_router.__file__).read_text(encoding="utf-8")
        assert "scored=len(rows) - abstained" in source
        assert "scored=len(rows)," not in source, (
            "scored must exclude abstentions, or the summary counts a refusal as an answer"
        )


class TestServedVersionIsTheModelVersion:
    """A published prediction has to name a model version that exists.

    The engine hardcoded "0.1.0", which is ``auspice.__version__``, while every model declares
    ``MODEL_VERSION = "1.0.0"``. The two were the same string once and then diverged, so a score in the
    ledger cited a model version no model has ever had. Found by rendering a memo and reading it, and it
    matters more than most typos because a ledger payload cannot be corrected.
    """

    def test_no_version_string_is_hardcoded_in_the_engine(self) -> None:
        from pathlib import Path

        from auspice.score import engine

        source = Path(engine.__file__).read_text(encoding="utf-8")
        assert 'model_version="0.1.0"' not in source
        assert 'model_version="1.0.0"' not in source, (
            "read the version from the serving model rather than repeating it, or the next bump misses here"
        )
        assert "model_version=models.primary_version" in source

    def test_the_package_version_and_the_model_version_are_different_things(self) -> None:
        """Asserted so that making them equal again does not silently make the bug invisible."""
        import auspice
        from auspice.models.baseline.base_rate import MODEL_VERSION

        assert auspice.__version__ != MODEL_VERSION, (
            "if these ever match, the engine reading the wrong one would look correct. Keep the test "
            "and fix the engine, not the versions."
        )

    def test_primary_version_follows_primary_kind(self) -> None:
        from auspice.models.baseline.base_rate import MODEL_VERSION as BASE_RATE
        from auspice.models.baseline.base_rate import BaseRateModel
        from auspice.models.dataset import Dataset
        from auspice.score.engine import ServingModels

        models = ServingModels(dataset=Dataset.__new__(Dataset), base_rate=BaseRateModel())
        assert models.primary_kind == "base_rate"
        assert models.primary_version == BASE_RATE


class TestPublishedMethodologyMatchesTheCode:
    """The published rule and the enforced rule have to be the same rule.

    ``docs/METHODOLOGY.md`` and the `/v1/public/methodology` endpoint are the public claim about how this
    product decides. The endpoint serves the threshold constants directly so the numbers cannot drift, and
    that protects the values while saying nothing about a condition being left out. A fourth abstention
    condition was added and the endpoint kept describing three, which is the more damaging kind of error:
    every number on the page was correct and the page was still wrong.
    """

    def test_every_abstention_reason_is_published(self) -> None:
        import asyncio
        import json

        from app.routers.public import methodology

        published = asyncio.run(methodology())
        text = json.dumps(published["abstention_rule"])

        # Each enum member has to be discoverable in the published rule, by the quantity that triggers it.
        expected = {
            AbstentionReason.thin_local_record: "comparable_decisions_below",
            AbstentionReason.dominated_by_pooling: "pooling_weight_above",
            AbstentionReason.interval_too_wide: "interval_width_above",
            AbstentionReason.stale_jurisdiction_data: "data_older_than_days",
            AbstentionReason.unresolved_jurisdiction_chain: "jurisdiction_chain_unresolved",
            AbstentionReason.degenerate_training_corpus: "distinct_outcomes_in_training_below",
        }
        assert set(expected) == set(AbstentionReason), (
            "a new abstention reason was added without deciding how to publish it. Add it to this map "
            "and to the endpoint, or the published methodology understates when we refuse to answer."
        )
        for reason, key in expected.items():
            assert key in text, f"{reason.value} is enforced but not published"

    def test_the_published_thresholds_are_the_enforced_thresholds(self) -> None:
        import asyncio

        from app.routers.public import methodology
        from auspice.models.eval import thresholds

        published = asyncio.run(methodology())
        conditions = published["abstention_rule"]["abstain_when_all_hold"]
        assert conditions["comparable_decisions_below"] == thresholds.ABSTAIN_MAX_COMPARABLES
        assert conditions["pooling_weight_above"] == thresholds.ABSTAIN_MAX_POOLING_WEIGHT
        assert conditions["interval_width_above"] == thresholds.ABSTAIN_MAX_INTERVAL_WIDTH
        assert (
            published["abstention_rule"]["also_abstain_when"]["distinct_outcomes_in_training_below"]
            == thresholds.MIN_OUTCOME_CLASSES
        )


class TestDegenerateTrainingCorpus:
    """The bug this class exists for.

    Run against the real corpus while it held one approval and nothing else, the scorer reported a 100
    percent chance of approval for a neighbouring county. The shrinkage was arithmetically correct: the
    prior it shrank toward was computed from the same single row, so every level agreed at 1.0. The three
    thin record conditions did not catch it because the base rate's pooling weight came to exactly
    4/(4+1), and 0.8 is not greater than 0.8.

    The primary site abstained and the alternative did not, which is the part that made it a real defect
    rather than a rough edge. An abstention that leaks a number through a side channel has not abstained.
    """

    def test_a_single_outcome_class_abstains_on_its_own(self) -> None:
        """No thin record condition needs to hold. Deep local data does not rescue it."""
        decision = decide(
            AbstentionInput(
                n_comparable_decisions=500,
                pooling_weight=0.0,
                interval_width=0.01,
                staleness_days=0,
                outcome_classes_in_training=1,
            )
        )
        assert decision.abstained
        assert decision.reasons == [AbstentionReason.degenerate_training_corpus]

    def test_the_exact_boundary_that_leaked(self) -> None:
        """The precise inputs from the failure, asserted as a regression."""
        leaked = AbstentionInput(
            n_comparable_decisions=1,
            pooling_weight=0.8,
            interval_width=0.5773502691896258,
            staleness_days=0,
        )
        assert not decide(leaked).abstained, (
            "the thin record rule genuinely does not fire here, which is why a separate condition "
            "was needed rather than a tighter threshold"
        )

        with_knowledge = AbstentionInput(
            n_comparable_decisions=1,
            pooling_weight=0.8,
            interval_width=0.5773502691896258,
            staleness_days=0,
            outcome_classes_in_training=1,
        )
        assert decide(with_knowledge).abstained

    def test_two_classes_does_not_abstain_on_this_ground(self) -> None:
        decision = decide(
            AbstentionInput(
                n_comparable_decisions=40,
                pooling_weight=0.2,
                interval_width=0.15,
                staleness_days=1,
                outcome_classes_in_training=2,
            )
        )
        assert not decision.abstained

    def test_not_supplied_leaves_the_rule_unchanged(self) -> None:
        """Defaulting to None rather than to a passing value keeps old callers honest.

        A caller that has not been taught about outcome classes gets the section 8.4 rule exactly, and
        the two production call sites are asserted separately below.
        """
        assert decide(_thin()).abstained
        assert AbstentionReason.degenerate_training_corpus not in decide(_thin()).reasons

    def test_zero_classes_abstains(self) -> None:
        """An empty training set is the same problem in its most extreme form."""
        assert decide(
            AbstentionInput(
                n_comparable_decisions=0,
                pooling_weight=1.0,
                interval_width=1.0,
                staleness_days=None,
                outcome_classes_in_training=0,
            )
        ).abstained

    def test_the_threshold_cannot_be_relaxed_quietly(self) -> None:
        from auspice.models.eval.thresholds import MIN_OUTCOME_CLASSES

        assert MIN_OUTCOME_CLASSES == 2, (
            "one outcome class means the model has never observed a denial. Lowering this lets it "
            "publish certainties."
        )

    def test_both_engine_call_sites_pass_the_outcome_count(self) -> None:
        """Read the source, because a missed call site is exactly how the leak happened.

        The primary path abstained correctly while the alternatives path did not. Asserting on the text
        catches a third call site added later without the argument, which a behavioural test on the two
        known paths would not.
        """
        import re
        from pathlib import Path

        from auspice.score import engine

        source = Path(engine.__file__).read_text(encoding="utf-8")
        constructions = re.findall(r"AbstentionInput\((.*?)\n    {4,8}\)", source, re.DOTALL)
        assert len(constructions) >= 2, "expected the primary and the alternatives call sites"

        scoring_sites = [c for c in constructions if "models.outcome_classes" in c]
        assert len(scoring_sites) == 2, (
            "every path that turns a model into a probability must pass outcome_classes_in_training. "
            f"Found {len(scoring_sites)} of {len(constructions)} constructions carrying it."
        )

    def test_deep_record_answers(self) -> None:
        decision = decide(
            AbstentionInput(
                n_comparable_decisions=41,
                pooling_weight=0.08,
                interval_width=0.11,
                staleness_days=1,
            )
        )
        assert not decision.abstained
        assert not decision.stale_flag

    def test_very_stale_data_abstains_on_its_own(self) -> None:
        decision = decide(
            AbstentionInput(
                n_comparable_decisions=40,
                pooling_weight=0.05,
                interval_width=0.10,
                staleness_days=STALENESS_ABSTAIN_DAYS + 1,
            )
        )
        assert decision.abstained
        assert decision.reasons == [AbstentionReason.stale_jurisdiction_data]

    def test_moderately_stale_data_flags_but_answers(self) -> None:
        decision = decide(
            AbstentionInput(
                n_comparable_decisions=40,
                pooling_weight=0.05,
                interval_width=0.10,
                staleness_days=30,
            )
        )
        assert not decision.abstained
        assert decision.stale_flag

    def test_unresolved_jurisdiction_abstains_regardless(self) -> None:
        decision = decide(
            AbstentionInput(
                n_comparable_decisions=400,
                pooling_weight=0.0,
                interval_width=0.02,
                staleness_days=0,
                jurisdiction_resolved=False,
            )
        )
        assert decision.abstained
        assert decision.reasons == [AbstentionReason.unresolved_jurisdiction_chain]

    def test_explanation_says_we_do_not_know(self) -> None:
        """The writing rules: when the model abstains the copy says we do not know."""
        text = decide(_thin()).explanation
        assert text.startswith("We do not know")
        assert "insufficient data" not in text.lower()
        assert "\u2014" not in text, "no em dashes anywhere in the product"


class TestConfidenceAndPooling:
    def test_confidence_never_contradicts_a_wide_interval(self) -> None:
        assert (
            confidence_for(interval_width=0.45, pooling_weight=0.1, n_comparable=40)
            is Confidence.low
        )

    def test_confidence_is_high_only_on_a_deep_local_record(self) -> None:
        assert (
            confidence_for(interval_width=0.12, pooling_weight=0.2, n_comparable=20)
            is Confidence.high
        )
        assert (
            confidence_for(interval_width=0.12, pooling_weight=0.2, n_comparable=4)
            is not Confidence.high
        )

    def test_pooling_note_is_silent_when_borrowing_is_immaterial(self) -> None:
        assert pooling_note(pooling_weight=0.05, n_comparable=50, similar_count=6) is None

    def test_pooling_note_discloses_the_share(self) -> None:
        note = pooling_note(pooling_weight=0.74, n_comparable=2, similar_count=6)
        assert note is not None
        assert "74%" in note
        assert "6 similar" in note


# ---------------------------------------------------------------------------
# The score object
# ---------------------------------------------------------------------------
def _site() -> Site:
    return Site(
        jurisdiction_chain=[
            JurisdictionLink(
                level="county",
                name="Loudoun County",
                slug="us-va-loudoun",
                role=JurisdictionRole.primary_decider,
                data_depth=12,
            )
        ],
        use_class=UseClass.data_center_hyperscale,
        requested_relief=[Relief.rezoning],
    )


def _provenance() -> Provenance:
    from datetime import date

    return Provenance(
        model_version="0.1.0",
        model_kind="hierarchical",
        feature_set_version="1.0.0",
        dataset_hash="d" * 64,
        data_as_of=date(2026, 8, 27),
        documents_used=47,
        jurisdiction_data_depth="12 comparable decisions since 2019",
        pooled=True,
        pooling_weight=0.31,
    )


def _score(determination: Determination, **kwargs: object) -> Score:
    return Score(
        public_id="scr_test",
        generated_at=datetime.now(UTC),
        site=_site(),
        determination=determination,
        provenance=_provenance(),
        features_hash="e" * 64,
        **kwargs,  # type: ignore[arg-type]
    )


class TestScoreInvariants:
    def test_a_probability_requires_an_interval(self) -> None:
        """Section 5.6 rule 1: a bare point estimate is a lie."""
        with pytest.raises(ValidationError, match="bare point estimate"):
            Determination(approval_probability=0.34)

    def test_an_estimate_outside_its_own_interval_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="outside its own interval"):
            Determination(approval_probability=0.9, credible_interval_80=(0.2, 0.4))

    def test_an_abstention_cannot_carry_a_probability(self) -> None:
        """A number with a caveat beside it gets pasted into a memo without the caveat."""
        with pytest.raises(ValidationError, match="cannot carry a probability"):
            Determination(
                abstained=True,
                abstention_reasons=[AbstentionReason.thin_local_record],
                approval_probability=0.34,
            )

    def test_an_abstention_must_say_why(self) -> None:
        with pytest.raises(ValidationError, match="must say why"):
            Determination(abstained=True)

    def test_time_quantiles_must_be_ordered(self) -> None:
        with pytest.raises(ValidationError, match="out of order"):
            TimeToDecision(p10=20, p50=10, p90=30)

    def test_a_driver_citing_missing_evidence_is_rejected(self) -> None:
        """Section 5.6 rule 3: no unsourced claim reaches the customer."""
        determination = Determination(approval_probability=0.34, credible_interval_80=(0.25, 0.44))
        with pytest.raises(ValidationError, match="cite evidence that is not attached"):
            _score(
                determination,
                drivers=[
                    Driver(
                        factor="overlay_present",
                        group="rules",
                        direction="negative",
                        weight=0.31,
                        plain_language="A use specific overlay district is in force here.",
                        evidence_id="ord_missing",
                    )
                ],
            )

    def test_unverified_evidence_cannot_be_published(self) -> None:
        determination = Determination(approval_probability=0.34, credible_interval_80=(0.25, 0.44))
        with pytest.raises(ValidationError, match=r"[Uu]nverified quotes"):
            _score(
                determination,
                evidence=[
                    Evidence(
                        evidence_id="ev_1",
                        document_id="f" * 64,
                        source_url="https://example.gov/minutes.pdf",
                        quote="The motion failed on a vote of 1 to 4.",
                        verified=False,
                    )
                ],
            )

    def test_an_abstention_cannot_present_weighted_drivers(self) -> None:
        """A weighted driver table implies a probability underneath it."""
        determination = Determination(
            abstained=True, abstention_reasons=[AbstentionReason.thin_local_record]
        )
        with pytest.raises(ValidationError, match="cannot present weighted drivers"):
            _score(
                determination,
                drivers=[
                    Driver(
                        factor="denial_streak",
                        group="base_rates",
                        direction="negative",
                        weight=0.4,
                        plain_language="The county has denied its last three applications.",
                    )
                ],
            )

    def test_a_valid_score_round_trips(self) -> None:
        determination = Determination(
            approval_probability=0.34,
            credible_interval_80=(0.25, 0.44),
            interval_kind="credible",
            confidence=Confidence.medium,
            time_to_decision_months=TimeToDecision(p10=8, p50=14, p90=27),
            probability_of_rule_change_before_decision=0.22,
            local_base_rate=0.41,
        )
        evidence = Evidence(
            evidence_id="ord_2026_0412",
            document_id="a" * 64,
            source_url="https://example.gov/ordinance.pdf",
            page=7,
            quote="The Board adopted a data centre overlay with a 2,000 foot residential setback.",
            verified=True,
        )
        score = _score(
            determination,
            drivers=[
                Driver(
                    factor="overlay_present",
                    group="rules",
                    direction="negative",
                    weight=0.31,
                    plain_language="A use specific overlay district is in force here.",
                    evidence_id="ord_2026_0412",
                )
            ],
            evidence=[evidence],
        )
        assert score.determination.interval_width == pytest.approx(0.19)
        assert "34%" in score.headline

    def test_the_ledger_payload_is_minimal_and_stable(self) -> None:
        """The ledger commits the prediction, not the essay around it."""
        determination = Determination(approval_probability=0.34, credible_interval_80=(0.25, 0.44))
        payload = _score(determination).ledger_payload()
        assert set(payload) == {
            "public_id",
            "generated_at",
            "jurisdiction",
            "use_class",
            "requested_relief",
            "approval_probability",
            "credible_interval_80",
            "abstained",
            "abstention_reasons",
            "time_to_decision_months",
            "probability_of_rule_change_before_decision",
            "model_version",
            "model_kind",
            "feature_set_version",
            "dataset_hash",
            "features_hash",
            "data_as_of",
        }

    def test_an_abstention_headline_says_we_do_not_know(self) -> None:
        determination = Determination(
            abstained=True, abstention_reasons=[AbstentionReason.interval_too_wide]
        )
        assert _score(determination).headline == "We do not know."
