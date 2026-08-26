"""The thresholds that decide whether a verdict may be reported at all.

These live in one module, alone, on purpose. They are the numbers most likely to be quietly
relaxed when a test is close to passing, and section 12 of the specification is explicit that
the test must not be adjusted until it passes. Putting them here makes any change to them a
visible, reviewable, one line diff in a file whose only job is to hold them.

The pass conditions come from sections 6.9 and 16.1. The sample size floors do not: they are
derived below, because the specification does not state them and a verdict on a sample too
small to support one is worse than no verdict.
"""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# Pass conditions. Section 6.9 and section 16.1.
# ---------------------------------------------------------------------------
MIN_BRIER_SKILL: Final = 0.15
"""Brier skill score against the base rate model.

Section 6.9 asks for a 15 percent improvement and section 16.1 asks for 25 percent. The lower
of the two is used as the pass condition and the higher is reported as the target, because a
pass condition that is quietly the more generous of two published numbers is not a pass
condition.
"""

TARGET_BRIER_SKILL: Final = 0.25

MAX_ECE: Final = 0.08
"""Expected calibration error. The published promise, so it is a hard gate."""

COVERAGE_BAND: Final = (0.76, 0.84)
"""Share of outcomes inside the 80 percent credible interval.

Both ends matter. Coverage of 0.95 fails: it means the intervals are too wide, which is a
different kind of dishonesty from being too narrow but is still dishonesty.
"""

MIN_AUC: Final = 0.70
MIN_CONCORDANCE: Final = 0.65
MIN_ABSTENTION_PRECISION: Final = 0.85

# ---------------------------------------------------------------------------
# Sample size floors. Not in the specification. Derived here.
# ---------------------------------------------------------------------------
MIN_LABELLED_DECISIONS: Final = 400
"""Terminal decisions required before a verdict may be reported.

Section 12 day 2 asks for 300 to 800 hand labelled rows. 400 is chosen as the floor for a
reason that can be stated in one line: the standard error of a Brier skill estimate on n held
out decisions is roughly proportional to 1/sqrt(n), and below a few hundred training rows with
sixty held out, the 95 percent interval on the skill score spans both zero and 0.3. A verdict
computed there is a coin flip wearing a number, and someone would quote it.
"""

MIN_HELD_OUT_DECISIONS: Final = 60
"""Decisions after the temporal cutoff required before a verdict may be reported."""

MIN_JURISDICTIONS_WITH_DEPTH: Final = 6
"""Jurisdictions holding at least MIN_DEPTH_FOR_CLUSTER decisions.

Partial pooling borrows strength from similar jurisdictions. With fewer than six jurisdictions
carrying real depth there is nothing to borrow from, and the hierarchical model collapses to
the global mean while reporting cluster level uncertainty it has not earned.
"""

MIN_DEPTH_FOR_CLUSTER: Final = 5

# ---------------------------------------------------------------------------
# Abstention rule. Section 8.4, verbatim.
# ---------------------------------------------------------------------------
ABSTAIN_MAX_COMPARABLES: Final = 3
"""Abstain when fewer than this many comparable decisions exist."""

ABSTAIN_MAX_POOLING_WEIGHT: Final = 0.8
"""Abstain when more than this share of the estimate comes from other jurisdictions."""

ABSTAIN_MAX_INTERVAL_WIDTH: Final = 0.35
"""Abstain when the 80 percent credible interval is wider than this."""

STALENESS_FLAG_DAYS: Final = 14
"""Section 6.12: a jurisdiction more than fourteen days stale is flagged in the UI and the API."""

STALENESS_ABSTAIN_DAYS: Final = 90
"""Beyond three months stale the flag is not enough and the system abstains.

Not in the specification. Added because a flagged number still gets pasted into a credit memo
without the flag, and at three months the ordinance the score assumed may no longer exist.
"""

__all__ = [
    "ABSTAIN_MAX_COMPARABLES",
    "ABSTAIN_MAX_INTERVAL_WIDTH",
    "ABSTAIN_MAX_POOLING_WEIGHT",
    "COVERAGE_BAND",
    "MAX_ECE",
    "MIN_ABSTENTION_PRECISION",
    "MIN_AUC",
    "MIN_BRIER_SKILL",
    "MIN_CONCORDANCE",
    "MIN_DEPTH_FOR_CLUSTER",
    "MIN_HELD_OUT_DECISIONS",
    "MIN_JURISDICTIONS_WITH_DEPTH",
    "MIN_LABELLED_DECISIONS",
    "STALENESS_ABSTAIN_DAYS",
    "STALENESS_FLAG_DAYS",
    "TARGET_BRIER_SKILL",
]
