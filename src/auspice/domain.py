"""Controlled vocabularies.

Section 4.1 of the specification names the real problem: one county says "special use
permit", the next says "conditional use", the third says "discretionary review". Those are
the same thing and a model cannot learn from three spellings of one concept.

So every categorical value in the graph comes from a closed set defined here, and the
database enforces it with CHECK constraints generated from these enums. Adding a member is
a migration, which is the point: the vocabulary should be hard to extend by accident and
easy to extend on purpose.

``normalise_relief`` and ``normalise_use_class`` map the wild strings found in source
documents onto these members. Anything unmapped returns ``None`` and the caller records it
for review rather than guessing.
"""

from __future__ import annotations

import re
from enum import StrEnum


def _members(enum_cls: type[StrEnum]) -> tuple[str, ...]:
    return tuple(m.value for m in enum_cls)


# ---------------------------------------------------------------------------
# Who decides
# ---------------------------------------------------------------------------
class JurisdictionKind(StrEnum):
    county = "county"
    municipality = "municipality"
    township = "township"
    special_district = "special_district"
    state_agency = "state_agency"
    federal_agency = "federal_agency"
    utility = "utility"
    grid_operator = "grid_operator"


class BodyKind(StrEnum):
    planning_commission = "planning_commission"
    board_of_supervisors = "board_of_supervisors"
    county_commission = "county_commission"
    city_council = "city_council"
    zoning_board = "zoning_board"
    board_of_adjustment = "board_of_adjustment"
    plan_commission = "plan_commission"
    staff = "staff"
    other = "other"


class JurisdictionRole(StrEnum):
    """The role a jurisdiction plays in one project's permission chain."""

    primary_decider = "primary_decider"
    recommending = "recommending"
    clearance = "clearance"
    load_approval = "load_approval"
    water_approval = "water_approval"
    appellate = "appellate"


class LegalFramework(StrEnum):
    """Section 6.0. Dillon's Rule versus home rule determines how much power a locality has."""

    dillons_rule = "dillons_rule"
    home_rule = "home_rule"
    mixed = "mixed"


# ---------------------------------------------------------------------------
# What is being asked
# ---------------------------------------------------------------------------
class UseClass(StrEnum):
    data_center_hyperscale = "data_center_hyperscale"
    data_center_colocation = "data_center_colocation"
    data_center_edge = "data_center_edge"
    solar_utility = "solar_utility"
    wind_onshore = "wind_onshore"
    battery_storage = "battery_storage"
    substation_transmission = "substation_transmission"
    industrial_general = "industrial_general"
    warehouse_logistics = "warehouse_logistics"
    residential_multifamily = "residential_multifamily"
    other = "other"


class Relief(StrEnum):
    """The instrument being requested. A project usually needs several."""

    rezoning = "rezoning"
    special_use_permit = "special_use_permit"
    conditional_use_permit = "conditional_use_permit"
    variance = "variance"
    site_plan_approval = "site_plan_approval"
    comprehensive_plan_amendment = "comprehensive_plan_amendment"
    text_amendment = "text_amendment"
    annexation = "annexation"
    development_agreement = "development_agreement"
    tax_abatement = "tax_abatement"
    subdivision_plat = "subdivision_plat"
    other = "other"


DISCRETIONARY_RELIEF: frozenset[Relief] = frozenset(
    {
        Relief.rezoning,
        Relief.special_use_permit,
        Relief.conditional_use_permit,
        Relief.variance,
        Relief.comprehensive_plan_amendment,
        Relief.text_amendment,
        Relief.annexation,
        Relief.development_agreement,
        Relief.tax_abatement,
    }
)
"""Relief a body may lawfully refuse even when every technical criterion is satisfied.

Section 19.1: this is where nearly all of the variance lives. Site plan approval and
subdivision plat are largely ministerial and are excluded on purpose.
"""


# ---------------------------------------------------------------------------
# What happened
# ---------------------------------------------------------------------------
class Outcome(StrEnum):
    approved = "approved"
    approved_with_conditions = "approved_with_conditions"
    denied = "denied"
    withdrawn = "withdrawn"
    continued = "continued"
    tabled = "tabled"
    pending = "pending"
    unknown = "unknown"


TERMINAL_OUTCOMES: frozenset[Outcome] = frozenset(
    {Outcome.approved, Outcome.approved_with_conditions, Outcome.denied, Outcome.withdrawn}
)
"""Outcomes that end the application. Everything else is still in flight.

``continued`` and ``tabled`` are the quiet killers of timelines, per appendix 19.2 group B,
and they are explicitly not terminal.
"""

APPROVAL_OUTCOMES: frozenset[Outcome] = frozenset(
    {Outcome.approved, Outcome.approved_with_conditions}
)
"""What counts as a yes for the binary label.

Approval with conditions counts as approval. That is a real modelling choice with a real
cost: conditions can be onerous enough to destroy the economics, which section 2.2 calls
out. The graph keeps the conditions so a later model can separate them, and the label
dictionary in docs/METHODOLOGY.md states the choice plainly.
"""


class CompetingRisk(StrEnum):
    """Section 6.8 model 2. Three distinct exits, not one event."""

    approval = "approval"
    denial = "denial"
    withdrawal = "withdrawal"
    censored = "censored"


class EventType(StrEnum):
    application_filed = "application_filed"
    hearing_held = "hearing_held"
    hearing_continued = "hearing_continued"
    staff_report_issued = "staff_report_issued"
    decision_rendered = "decision_rendered"
    ordinance_adopted = "ordinance_adopted"
    ordinance_proposed = "ordinance_proposed"
    moratorium_enacted = "moratorium_enacted"
    moratorium_proposed = "moratorium_proposed"
    moratorium_expired = "moratorium_expired"
    appeal_filed = "appeal_filed"
    litigation_filed = "litigation_filed"
    membership_changed = "membership_changed"


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------
class InstrumentKind(StrEnum):
    zoning_ordinance = "zoning_ordinance"
    overlay_district = "overlay_district"
    moratorium = "moratorium"
    comprehensive_plan = "comprehensive_plan"
    text_amendment = "text_amendment"
    resolution = "resolution"
    state_statute = "state_statute"
    interim_control = "interim_control"


# ---------------------------------------------------------------------------
# Opposition
# ---------------------------------------------------------------------------
class ObjectionGround(StrEnum):
    water = "water"
    noise = "noise"
    traffic = "traffic"
    electricity_cost = "electricity_cost"
    property_value = "property_value"
    visual = "visual"
    environmental = "environmental"
    process = "process"
    tax = "tax"
    agricultural_land = "agricultural_land"
    public_safety = "public_safety"
    other = "other"


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------
class DocumentKind(StrEnum):
    agenda = "agenda"
    minutes = "minutes"
    staff_report = "staff_report"
    ordinance = "ordinance"
    resolution = "resolution"
    comprehensive_plan = "comprehensive_plan"
    application_packet = "application_packet"
    transcript = "transcript"
    docket = "docket"
    legal_notice = "legal_notice"
    news_article = "news_article"
    parcel_record = "parcel_record"
    election_record = "election_record"
    other = "other"


class ParseMethod(StrEnum):
    """Which step of the section 6.2 cascade produced the text. Logged per page."""

    pymupdf = "pymupdf"
    pdfplumber = "pdfplumber"
    tesseract = "tesseract"
    vision_model = "vision_model"
    native_text = "native_text"
    transcription = "transcription"


class CivicPlatform(StrEnum):
    """Section 6.1. Five adapters instead of ten thousand scrapers."""

    legistar = "legistar"
    civicplus = "civicplus"
    accela = "accela"
    opengov = "opengov"
    municode = "municode"
    granicus = "granicus"
    unknown = "unknown"


# ---------------------------------------------------------------------------
# Models and output
# ---------------------------------------------------------------------------
class ModelKind(StrEnum):
    base_rate = "base_rate"
    gradient_boosted = "gradient_boosted"
    hierarchical = "hierarchical"
    survival = "survival"
    rule_change = "rule_change"


class Confidence(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"


class AbstentionReason(StrEnum):
    thin_local_record = "thin_local_record"
    dominated_by_pooling = "dominated_by_pooling"
    interval_too_wide = "interval_too_wide"
    stale_jurisdiction_data = "stale_jurisdiction_data"
    unresolved_jurisdiction_chain = "unresolved_jurisdiction_chain"
    degenerate_training_corpus = "degenerate_training_corpus"


class AlertTrigger(StrEnum):
    """Section 6.11. Ordered roughly by value to the customer."""

    rule_changed = "rule_changed"
    moratorium_on_agenda = "moratorium_on_agenda"
    moratorium_enacted = "moratorium_enacted"
    comparable_denied_nearby = "comparable_denied_nearby"
    board_composition_changed = "board_composition_changed"
    litigation_filed = "litigation_filed"
    use_class_on_agenda = "use_class_on_agenda"
    score_moved = "score_moved"
    source_stale = "source_stale"


# ---------------------------------------------------------------------------
# CHECK constraint helpers
# ---------------------------------------------------------------------------
JURISDICTION_KINDS = _members(JurisdictionKind)
BODY_KINDS = _members(BodyKind)
JURISDICTION_ROLES = _members(JurisdictionRole)
LEGAL_FRAMEWORKS = _members(LegalFramework)
USE_CLASSES = _members(UseClass)
RELIEFS = _members(Relief)
OUTCOMES = _members(Outcome)
COMPETING_RISKS = _members(CompetingRisk)
EVENT_TYPES = _members(EventType)
INSTRUMENT_KINDS = _members(InstrumentKind)
OBJECTION_GROUNDS = _members(ObjectionGround)
DOCUMENT_KINDS = _members(DocumentKind)
PARSE_METHODS = _members(ParseMethod)
CIVIC_PLATFORMS = _members(CivicPlatform)
MODEL_KINDS = _members(ModelKind)
CONFIDENCES = _members(Confidence)
ABSTENTION_REASONS = _members(AbstentionReason)
ALERT_TRIGGERS = _members(AlertTrigger)
VOTE_POSITIONS = ("for", "against", "abstain", "absent", "recused")


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------
_RELIEF_PATTERNS: tuple[tuple[re.Pattern[str], Relief], ...] = (
    (
        re.compile(r"\brezon|\bzoning\s+map\s+amend|\bmap\s+amend|\bzone\s+chang", re.I),
        Relief.rezoning,
    ),
    (
        re.compile(r"\bspecial\s+(use|exception)|\bSUP\b|\bspecial\s+permit", re.I),
        Relief.special_use_permit,
    ),
    (re.compile(r"\bconditional\s+use|\bCUP\b", re.I), Relief.conditional_use_permit),
    (re.compile(r"\bvarianc", re.I), Relief.variance),
    (re.compile(r"\bsite\s+plan|\bdevelopment\s+plan\s+review", re.I), Relief.site_plan_approval),
    (
        re.compile(r"\bcomprehensive\s+plan|\bcomp\s+plan|\bfuture\s+land\s+use", re.I),
        Relief.comprehensive_plan_amendment,
    ),
    (re.compile(r"\btext\s+amend|\bordinance\s+amend|\bcode\s+amend", re.I), Relief.text_amendment),
    (re.compile(r"\bannex", re.I), Relief.annexation),
    (
        re.compile(r"\bdevelopment\s+agreement|\bhost\s+agreement|\bcommunity\s+benefit", re.I),
        Relief.development_agreement,
    ),
    (
        re.compile(r"\babatement|\btax\s+increment|\bTIF\b|\bincentive\s+agreement", re.I),
        Relief.tax_abatement,
    ),
    (re.compile(r"\bplat\b|\bsubdivi", re.I), Relief.subdivision_plat),
)

_USE_CLASS_PATTERNS: tuple[tuple[re.Pattern[str], UseClass], ...] = (
    (
        re.compile(r"\bhyperscale|\bAI\s+campus|\bcomputing?\s+campus", re.I),
        UseClass.data_center_hyperscale,
    ),
    (
        re.compile(r"\bcolocation|\bcolo\b|\bmulti[- ]?tenant\s+data", re.I),
        UseClass.data_center_colocation,
    ),
    (re.compile(r"\bedge\s+data\s*cent", re.I), UseClass.data_center_edge),
    (
        re.compile(r"\bdata\s*cent|\bdata\s*centre|\bserver\s+farm", re.I),
        UseClass.data_center_hyperscale,
    ),
    (re.compile(r"\bsolar\b", re.I), UseClass.solar_utility),
    (re.compile(r"\bwind\s+(farm|energy|turbine)", re.I), UseClass.wind_onshore),
    (re.compile(r"\bbattery|\bBESS\b|\benergy\s+storage", re.I), UseClass.battery_storage),
    (re.compile(r"\bsubstation|\btransmission\s+line", re.I), UseClass.substation_transmission),
    (
        re.compile(r"\bwarehouse|\bdistribution\s+cent|\blogistics", re.I),
        UseClass.warehouse_logistics,
    ),
    (
        re.compile(r"\bapartment|\bmultifamily|\bmulti[- ]family", re.I),
        UseClass.residential_multifamily,
    ),
    (re.compile(r"\bindustrial|\bmanufactur", re.I), UseClass.industrial_general),
)

_OUTCOME_PATTERNS: tuple[tuple[re.Pattern[str], Outcome], ...] = (
    (
        re.compile(r"\bdenied?\b|\brejected?\b|\bfailed\b|\bdefeated\b|\bvoted\s+down", re.I),
        Outcome.denied,
    ),
    (
        re.compile(r"\bapproved?\s+with\s+condition|\bapproved?\s+subject\s+to", re.I),
        Outcome.approved_with_conditions,
    ),
    (re.compile(r"\bapproved?\b|\bgranted\b|\badopted\b|\bpassed\b", re.I), Outcome.approved),
    (re.compile(r"\bwithdrew?n?\b|\bwithdraw", re.I), Outcome.withdrawn),
    (re.compile(r"\bcontinued\b|\bdeferred\b|\bpostponed\b", re.I), Outcome.continued),
    (re.compile(r"\btabled\b|\bheld\s+in\s+committee", re.I), Outcome.tabled),
)


def normalise_relief(raw: str) -> list[Relief]:
    """Map a free text relief description onto zero or more members.

    Returns every match, because "rezoning and special use permit" is two reliefs and the
    ``relief_count`` feature depends on getting that right.
    """
    found: list[Relief] = []
    for pattern, relief in _RELIEF_PATTERNS:
        if pattern.search(raw) and relief not in found:
            found.append(relief)
    return found


def normalise_use_class(raw: str) -> UseClass | None:
    """Map a free text use description onto one member, or None if nothing matched.

    None is a real answer. Section 6.4 rule 4: guessing is a failure.
    """
    for pattern, use_class in _USE_CLASS_PATTERNS:
        if pattern.search(raw):
            return use_class
    return None


def normalise_outcome(raw: str) -> Outcome | None:
    """Map a free text disposition onto one member, or None if nothing matched."""
    for pattern, outcome in _OUTCOME_PATTERNS:
        if pattern.search(raw):
            return outcome
    return None


def parse_vote(raw: str) -> tuple[int, int, int] | None:
    """Parse "4-1", "4-1-0" or "4 to 1" into (for, against, abstain).

    Returns None on anything else, including the empty string and "unanimous", because a
    unanimous vote of an unknown number of seats is not a tally.
    """
    match = re.fullmatch(r"\s*(\d+)\s*(?:-|to|:)\s*(\d+)(?:\s*(?:-|to|:)\s*(\d+))?\s*", raw)
    if match is None:
        return None
    votes_for = int(match.group(1))
    votes_against = int(match.group(2))
    abstain = int(match.group(3)) if match.group(3) is not None else 0
    return votes_for, votes_against, abstain


def is_approval(outcome: Outcome | str) -> bool:
    """The binary label. See APPROVAL_OUTCOMES for the choice made about conditions."""
    return Outcome(outcome) in APPROVAL_OUTCOMES


def competing_risk_for(outcome: Outcome | str) -> CompetingRisk:
    """Map a terminal outcome onto its competing risk arm."""
    resolved = Outcome(outcome)
    if resolved in APPROVAL_OUTCOMES:
        return CompetingRisk.approval
    if resolved is Outcome.denied:
        return CompetingRisk.denial
    if resolved is Outcome.withdrawn:
        return CompetingRisk.withdrawal
    return CompetingRisk.censored
