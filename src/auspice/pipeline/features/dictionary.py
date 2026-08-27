"""The feature dictionary.

Section 6.7 lists the features. This module is that list as data, with three fields attached to
every entry that turn the section 6.7 decision into something the code enforces rather than
something a person remembers:

    ``plain_language``   one sentence a customer can read. A driver that cannot be explained in one
                         sentence cannot appear in a memo, and a memo is what gets paid for. So a
                         feature with no plain language sentence is not selectable.
    ``group``            which of the six groups it belongs to, used in the memo and the drivers
                         table.
    ``direction``        whether a higher value is expected to help or hurt, or whether it is not
                         known. This is never used to constrain a fitted coefficient. It is used to
                         catch the case where a model learns a sign that contradicts the domain,
                         which is usually a leakage bug rather than a discovery.

The 80 percent coverage rule from section 6.7 is applied by ``select_usable``, against measured
coverage rather than an assumption.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

FEATURE_SET_VERSION: Final = "1.0.0"

# Section 6.7 decision (a): a feature must be computable for at least this share of the target
# jurisdictions or it is excluded.
MIN_COVERAGE: Final = 0.80


class FeatureGroup(StrEnum):
    base_rates = "base_rates"
    rules = "rules"
    politics = "politics"
    opposition = "opposition"
    physical = "physical"
    applicant = "applicant"


class Direction(StrEnum):
    helps = "helps"
    hurts = "hurts"
    unknown = "unknown"


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    name: str
    group: FeatureGroup
    plain_language: str
    direction: Direction
    dtype: str = "float"
    note: str | None = None

    @property
    def is_binary(self) -> bool:
        return self.dtype == "bool"


def _f(
    name: str,
    group: FeatureGroup,
    plain_language: str,
    direction: Direction = Direction.unknown,
    dtype: str = "float",
    note: str | None = None,
) -> FeatureSpec:
    return FeatureSpec(name, group, plain_language, direction, dtype, note)


# ---------------------------------------------------------------------------
# Group A. Base rates and history. Boring and dominant.
# ---------------------------------------------------------------------------
_GROUP_A = (
    _f(
        "approval_rate_juris_use",
        FeatureGroup.base_rates,
        "This county has approved {value:.0%} of all applications of this type on record.",
        Direction.helps,
        note="The strongest single predictor. Section 6.7 calls it boring and dominant.",
    ),
    _f(
        "approval_rate_juris_use_24m",
        FeatureGroup.base_rates,
        "In the last two years the county has approved {value:.0%} of applications of this type.",
        Direction.helps,
        note="Diverging from the all time rate is itself a signal of regime change.",
    ),
    _f(
        "approval_rate_trend",
        FeatureGroup.base_rates,
        "The county's approval rate for this type is moving at {value:+.2f} per decision across its"
        " last eight.",
        Direction.helps,
        note="Detects a hardening or softening board before it is obvious.",
    ),
    _f(
        "denial_streak",
        FeatureGroup.base_rates,
        "The county has denied its last {value:.0f} applications of this type in a row.",
        Direction.hurts,
        note="Boards behave with momentum.",
    ),
    _f(
        "withdrawal_rate",
        FeatureGroup.base_rates,
        "{value:.0%} of applications of this type are withdrawn before a vote is taken.",
        Direction.hurts,
        note="Hidden denials. A high rate means staff kills projects quietly, so the true denial "
        "rate is much higher than the recorded one.",
    ),
    _f(
        "n_comparable_decisions",
        FeatureGroup.base_rates,
        "The estimate rests on {value:.0f} comparable decisions in this county.",
        Direction.unknown,
        note="Drives the pooling weight and the abstention rule. Not a predictor of the outcome.",
    ),
    _f(
        "months_since_last_comparable",
        FeatureGroup.base_rates,
        "The most recent comparable decision here was {value:.0f} months ago.",
        Direction.unknown,
        note="Precedent decays. A ten year old approval is weak evidence about today's board.",
    ),
)

# ---------------------------------------------------------------------------
# Group B. Rules and discretion.
# ---------------------------------------------------------------------------
_GROUP_B = (
    _f(
        "by_right",
        FeatureGroup.rules,
        "The use is permitted as of right, so approval is ministerial rather than discretionary.",
        Direction.helps,
        dtype="bool",
        note="Binary and enormous. By right sites barely need us, and we say so.",
    ),
    _f(
        "discretion_index",
        FeatureGroup.rules,
        "{value:.0%} of this county's decisions on record turned on relief it could lawfully refuse.",
        Direction.hurts,
    ),
    _f(
        "relief_count",
        FeatureGroup.rules,
        "The project needs {value:.0f} separate approvals, each of which can fail on its own.",
        Direction.hurts,
    ),
    _f(
        "overlay_present",
        FeatureGroup.rules,
        "A use specific overlay district is in force here.",
        Direction.hurts,
        dtype="bool",
        note="Overlays are usually adopted in response to projects like this one.",
    ),
    _f(
        "days_since_rule_change",
        FeatureGroup.rules,
        "The governing rules last changed {value:.0f} days ago.",
        Direction.helps,
        note="A change inside the last 180 days is the single most dangerous condition, and the "
        "one humans miss most often. Higher is safer, hence direction helps.",
    ),
    _f(
        "rule_changed_within_180d",
        FeatureGroup.rules,
        "The governing rules changed within the last 180 days.",
        Direction.hurts,
        dtype="bool",
    ),
    _f(
        "moratorium_active",
        FeatureGroup.rules,
        "A moratorium covering this use is in force.",
        Direction.hurts,
        dtype="bool",
    ),
    _f(
        "months_to_moratorium_expiry",
        FeatureGroup.rules,
        "The moratorium lifts in {value:.0f} months.",
        Direction.unknown,
        note="Turns a hard no into a dated no, which is a completely different commercial fact.",
    ),
    _f(
        "open_rule_process",
        FeatureGroup.rules,
        "The county has an open standards or comprehensive plan process running.",
        Direction.hurts,
        dtype="bool",
        note="Feeds the rule change hazard model more than the approval model.",
    ),
    _f(
        "setback_compliance_margin_ft",
        FeatureGroup.rules,
        "The site clears the binding setback by {value:.0f} feet.",
        Direction.helps,
        note="Converts a legal text into a continuous number. Needs parcel geometry, so it is "
        "missing for most rows until parcel data is loaded.",
    ),
)

# ---------------------------------------------------------------------------
# Group C. Politics and people. Institutions do not vote; people do.
# ---------------------------------------------------------------------------
_GROUP_C = (
    _f(
        "board_seats",
        FeatureGroup.politics,
        "The deciding body has {value:.0f} seats.",
        Direction.unknown,
        note="Smaller boards have higher variance, which widens the interval rather than moving "
        "the point estimate.",
    ),
    _f(
        "board_composition_score",
        FeatureGroup.politics,
        "Weighted by how the sitting members have voted on this use class before, the board leans "
        "{value:+.2f}.",
        Direction.helps,
        note="Aggregate body behaviour only. Section 8.9: never a prediction about a named person.",
    ),
    _f(
        "swing_seat_count",
        FeatureGroup.politics,
        "{value:.0f} sitting members have a mixed voting record on this use class.",
        Direction.unknown,
        note="Determines variance, which is the width of the interval.",
    ),
    _f(
        "months_to_next_election",
        FeatureGroup.politics,
        "The next election for this body is {value:.0f} months away.",
        Direction.helps,
        note="Approvals of unpopular uses fall sharply near elections, so more months is safer.",
    ),
    _f(
        "election_within_12m",
        FeatureGroup.politics,
        "An election for this body falls within twelve months of the filing date.",
        Direction.hurts,
        dtype="bool",
    ),
    _f(
        "turnover_since_last_comparable",
        FeatureGroup.politics,
        "{value:.0%} of the seats have changed hands since the last comparable decision.",
        Direction.unknown,
        note="Precedent decays when the people change. Most models ignore this.",
    ),
    _f(
        "staff_recommended_approval",
        FeatureGroup.politics,
        "Professional staff recommended approval.",
        Direction.helps,
        dtype="bool",
    ),
    _f(
        "staff_recommendation_alignment",
        FeatureGroup.politics,
        "This body follows its own staff's recommendation {value:.0%} of the time.",
        Direction.unknown,
        note="If a board overrules staff 40 percent of the time, a positive staff report means "
        "much less. This is what makes the staff signal conditional rather than absolute.",
    ),
    _f(
        "home_rule",
        FeatureGroup.politics,
        "The state grants this county home rule power, so local politics is decisive and the state "
        "cannot easily pre-empt it.",
        Direction.hurts,
        dtype="bool",
    ),
)

# ---------------------------------------------------------------------------
# Group D. Opposition. Identifies the specific argument that will be used.
# ---------------------------------------------------------------------------
_GROUP_D = (
    _f(
        "objection_density_24m",
        FeatureGroup.opposition,
        "There have been {value:.2f} recorded objection events per decision here over two years.",
        Direction.hurts,
    ),
    _f(
        "organised_group_present",
        FeatureGroup.opposition,
        "A named group with repeat appearances opposes projects of this type here.",
        Direction.hurts,
        dtype="bool",
        note="Organised opposition wins far more often than individual opposition.",
    ),
    _f(
        "salience_water",
        FeatureGroup.opposition,
        "Water was raised as an objection in {value:.0%} of recent comparable hearings.",
        Direction.hurts,
    ),
    _f(
        "salience_power_cost",
        FeatureGroup.opposition,
        "Electricity cost was raised in {value:.0%} of recent comparable hearings.",
        Direction.hurts,
    ),
    _f(
        "salience_noise",
        FeatureGroup.opposition,
        "Noise was raised in {value:.0%} of recent comparable hearings.",
        Direction.hurts,
    ),
    _f(
        "salience_traffic",
        FeatureGroup.opposition,
        "Traffic was raised in {value:.0%} of recent comparable hearings.",
        Direction.hurts,
    ),
    _f(
        "neighbour_contagion",
        FeatureGroup.opposition,
        "{value:.0f} adjacent counties have restricted this use in the last two years.",
        Direction.hurts,
        note="Opposition tactics diffuse geographically faster than policy does.",
    ),
)

# ---------------------------------------------------------------------------
# Group E. Physical and infrastructural.
# ---------------------------------------------------------------------------
_GROUP_E = (
    _f(
        "parcel_acres",
        FeatureGroup.physical,
        "The site is {value:,.0f} acres.",
        Direction.unknown,
    ),
    _f(
        "capacity_mw",
        FeatureGroup.physical,
        "The project is {value:,.0f} megawatts.",
        Direction.hurts,
        note="Scale drives opposition non-linearly.",
    ),
    _f(
        "intensity_mw_per_acre",
        FeatureGroup.physical,
        "The project draws {value:.2f} megawatts per acre.",
        Direction.hurts,
    ),
    _f(
        "prior_industrial_use",
        FeatureGroup.physical,
        "The site was previously in industrial use.",
        Direction.helps,
        dtype="bool",
        note="Brownfield sites are dramatically easier.",
    ),
    _f(
        "distance_to_residential_m",
        FeatureGroup.physical,
        "The nearest residential zone is {value:,.0f} metres away.",
        Direction.helps,
        note="The most common trigger. Needs zoning geometry.",
    ),
)

# ---------------------------------------------------------------------------
# Group F. Applicant.
# ---------------------------------------------------------------------------
_GROUP_F = (
    _f(
        "applicant_track_record",
        FeatureGroup.applicant,
        "This applicant has been approved {value:.0%} of the time across the counties we cover.",
        Direction.helps,
    ),
    _f(
        "applicant_local_experience",
        FeatureGroup.applicant,
        "This applicant has filed {value:.0f} previous applications in this county.",
        Direction.unknown,
        note="Cuts both ways. Measure it, do not assume it.",
    ),
    _f(
        "entity_opacity",
        FeatureGroup.applicant,
        "The applicant is a single purpose entity with no disclosed principal.",
        Direction.hurts,
        dtype="bool",
        note="Opacity correlates with opposition.",
    ),
)


FEATURES: Final[tuple[FeatureSpec, ...]] = (
    *_GROUP_A,
    *_GROUP_B,
    *_GROUP_C,
    *_GROUP_D,
    *_GROUP_E,
    *_GROUP_F,
)

BY_NAME: Final[dict[str, FeatureSpec]] = {f.name: f for f in FEATURES}

# Features that describe how much evidence there is rather than what it says. They drive pooling
# and abstention and are deliberately excluded from the model matrix, because a model that learns
# "more data means approval" has learned something about our coverage, not about permission.
EVIDENCE_FEATURES: Final[frozenset[str]] = frozenset(
    {"n_comparable_decisions", "months_since_last_comparable"}
)


def feature_names(*, include_evidence: bool = False) -> list[str]:
    names = [f.name for f in FEATURES]
    if include_evidence:
        return names
    return [n for n in names if n not in EVIDENCE_FEATURES]


def select_usable(
    coverage: dict[str, float], *, min_coverage: float = MIN_COVERAGE
) -> tuple[list[str], dict[str, str]]:
    """Apply the section 6.7 rule against measured coverage.

    Returns the usable feature names and, for everything excluded, the reason. The reasons are
    printed by ``auspice features build`` and published in docs/METHODOLOGY.md, because a feature
    list with silent exclusions is not a published methodology.
    """
    usable: list[str] = []
    excluded: dict[str, str] = {}

    for spec in FEATURES:
        if spec.name in EVIDENCE_FEATURES:
            excluded[spec.name] = "evidence depth, used for pooling and abstention, not as an input"
            continue
        if not spec.plain_language:
            excluded[spec.name] = "no plain language sentence, so it cannot appear in a memo"
            continue
        measured = coverage.get(spec.name, 0.0)
        if measured < min_coverage:
            excluded[spec.name] = (
                f"computable for only {measured:.0%} of rows, below {min_coverage:.0%}"
            )
            continue
        usable.append(spec.name)

    return usable, excluded


def describe(name: str, value: float | bool | None) -> str:
    """Render a feature's plain language sentence with its value substituted."""
    spec = BY_NAME.get(name)
    if spec is None:
        return f"{name}: {value}"
    if value is None:
        return f"{spec.plain_language.split('{')[0].strip()} This is not known for this site."
    if spec.is_binary:
        if bool(value):
            return spec.plain_language
        return "Not the case here: " + spec.plain_language[0].lower() + spec.plain_language[1:]
    try:
        return spec.plain_language.format(value=float(value))
    except (ValueError, KeyError):
        return f"{name}: {value}"
