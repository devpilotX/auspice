"""The abstention rule. Section 8.4.

    abstain if:
        n_comparable_decisions < 3
        AND cluster_pooling_weight > 0.8
        AND credible_interval_width > 0.35

All three conditions, joined by AND, exactly as written. A rule that fired on any one of them would
abstain on most of the corpus, which is not intelligence, it is refusing to work.

Two additions to the specification, both deliberate and both stated in docs/METHODOLOGY.md.

**Staleness.** A jurisdiction whose data is more than ninety days old triggers an abstention on its
own. Section 6.12 flags a score at fourteen days, and a flag is right at that horizon. At three months
the ordinance the score assumed may no longer exist, and a flagged number still gets pasted into a
credit memo without the flag.

**Unresolved jurisdiction chain.** If the spatial join cannot say who decides, there is nothing to
score. This is an abstention rather than an error because "we cannot tell which body has authority
over this parcel" is a real and useful answer, and it is the honest one for a site outside the covered
counties.

**Degenerate training corpus.** If every decision the model trained on has the same outcome, the model
has never seen the other kind of event and cannot assign a probability to it. Found by running the
scorer against the real corpus while it held a single approval: every level of shrinkage agreed at
1.0, because the prior being shrunk toward was itself 1.0, and the three thin record conditions did
not fire because the pooling weight landed exactly on its threshold. The result was a published claim
that a data centre had a 100 percent chance of approval, from one decision.

This one deserves its own condition rather than a tighter threshold. A base rate of 1.0 means "always
approves", which is the same unearned certainty as the base rate of 0.0 that section 7.7 forbids, and
no amount of interval arithmetic makes it defensible. The fitting code already knew: it declines to
fit a classifier on a single outcome class and says so. It then let the base rate answer anyway. This
closes that gap.

> A system that always answers is trusted exactly once.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from auspice.domain import AbstentionReason, Confidence
from auspice.models.eval.thresholds import (
    ABSTAIN_MAX_COMPARABLES,
    ABSTAIN_MAX_INTERVAL_WIDTH,
    ABSTAIN_MAX_POOLING_WEIGHT,
    MIN_OUTCOME_CLASSES,
    STALENESS_ABSTAIN_DAYS,
    STALENESS_FLAG_DAYS,
)


@dataclass(frozen=True, slots=True)
class AbstentionInput:
    n_comparable_decisions: int
    pooling_weight: float
    interval_width: float
    staleness_days: int | None
    jurisdiction_resolved: bool = True
    outcome_classes_in_training: int | None = None
    """How many distinct outcomes the serving model was trained on. None when not known.

    Below two, the model has only ever seen one kind of event. Defaults to None rather than to a
    passing value so that a caller which forgets to supply it does not silently get the old behaviour.
    """


@dataclass(frozen=True, slots=True)
class AbstentionDecision:
    abstained: bool
    reasons: list[AbstentionReason] = field(default_factory=list)
    stale_flag: bool = False
    explanation: str = ""


THIN_RECORD_CONDITIONS = (
    AbstentionReason.thin_local_record,
    AbstentionReason.dominated_by_pooling,
    AbstentionReason.interval_too_wide,
)


def decide(inputs: AbstentionInput) -> AbstentionDecision:
    """Apply the rule. Returns the decision and the reasons, in the order they are shown."""
    reasons: list[AbstentionReason] = []

    if not inputs.jurisdiction_resolved:
        return AbstentionDecision(
            abstained=True,
            reasons=[AbstentionReason.unresolved_jurisdiction_chain],
            explanation=(
                "We cannot say who decides for this parcel. Until the jurisdiction chain resolves, "
                "any probability would be a guess about the wrong body."
            ),
        )

    stale_flag = inputs.staleness_days is not None and inputs.staleness_days > STALENESS_FLAG_DAYS

    if (
        inputs.outcome_classes_in_training is not None
        and inputs.outcome_classes_in_training < MIN_OUTCOME_CLASSES
    ):
        return AbstentionDecision(
            abstained=True,
            reasons=[AbstentionReason.degenerate_training_corpus],
            stale_flag=stale_flag,
            explanation=(
                "Every decision we hold has the same outcome, so the model has never seen an "
                "application go the other way. It cannot tell you the odds of something it has no "
                "example of. This is a gap in our corpus, not a finding about your site."
            ),
        )

    if inputs.staleness_days is not None and inputs.staleness_days > STALENESS_ABSTAIN_DAYS:
        return AbstentionDecision(
            abstained=True,
            reasons=[AbstentionReason.stale_jurisdiction_data],
            stale_flag=True,
            explanation=(
                f"Our data for this jurisdiction is {inputs.staleness_days} days old. The rules may "
                "have changed since, and a score computed on rules that no longer exist is worse "
                "than no score."
            ),
        )

    # The three conditions from section 8.4. All must hold.
    thin = inputs.n_comparable_decisions < ABSTAIN_MAX_COMPARABLES
    pooled = inputs.pooling_weight > ABSTAIN_MAX_POOLING_WEIGHT
    wide = inputs.interval_width > ABSTAIN_MAX_INTERVAL_WIDTH

    if thin and pooled and wide:
        reasons = list(THIN_RECORD_CONDITIONS)
        return AbstentionDecision(
            abstained=True,
            reasons=reasons,
            stale_flag=stale_flag,
            explanation=explain(inputs),
        )

    return AbstentionDecision(abstained=False, reasons=[], stale_flag=stale_flag)


def explain(inputs: AbstentionInput) -> str:
    """The abstention notice text. Bordered, plain, unapologetic.

    It states the three conditions and says we would rather show nothing than a number we cannot
    stand behind. Written to be read out loud without sounding like a press release.
    """
    return (
        f"We do not know. This jurisdiction has {inputs.n_comparable_decisions} comparable decisions "
        f"on record, {inputs.pooling_weight:.0%} of any estimate would come from other "
        f"jurisdictions, and the interval would be {inputs.interval_width:.2f} wide. All three of "
        "those are past the point where a probability means anything. We would rather show you "
        "nothing than a number we cannot stand behind."
    )


def confidence_for(
    *, interval_width: float, pooling_weight: float, n_comparable: int
) -> Confidence:
    """Map the same three quantities onto a confidence tag.

    The tag is a summary of the interval, not an independent judgement. It exists because a partner
    reading a memo wants one word before they read three numbers, and it must never disagree with the
    numbers beside it.
    """
    if interval_width <= 0.18 and pooling_weight <= 0.4 and n_comparable >= 8:
        return Confidence.high
    if interval_width <= 0.30 and pooling_weight <= 0.7 and n_comparable >= 3:
        return Confidence.medium
    return Confidence.low


def pooling_note(*, pooling_weight: float, n_comparable: int, similar_count: int) -> str | None:
    """Section 5.6 rule 5. Disclose it when the answer partly comes from elsewhere.

    Returns None below a fifth, where the borrowing is immaterial and a note would be noise.
    """
    if pooling_weight < 0.2:
        return None
    return (
        f"Local data is thin: {n_comparable} comparable decisions. About "
        f"{pooling_weight:.0%} of this estimate is borrowed from {similar_count} similar "
        "jurisdictions, which is why the interval is as wide as it is."
    )
