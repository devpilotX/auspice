"""The abstention rule and the score object's invariants.

Section 8.4 and section 5.6. These are the rules that let the product refuse to answer, and the rules
that stop a refusal from being quietly converted back into a number somewhere downstream.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

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
