"""The labelled decision dataset.

Hand built ground truth, loaded into ``application`` and ``instrument`` with ``label_source``
set to ``hand_labelled``. Everything about this module exists to make one rule enforceable: a
row without a citation does not load.

That rule applies to human work for the same reason it applies to language model output. An
unsourced claim in a training set is indistinguishable from a guess, and it gets laundered into
a published probability. The difference between a rating agency and a data vendor is that the
rating agency can show you where every input came from.

The file format is YAML rather than CSV because a citation is a nested object with a quote in
it, and quotes contain commas. It is version controlled, so every change to a label is a diff
with an author and a date.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection

from auspice.db import schema
from auspice.domain import (
    APPROVAL_OUTCOMES,
    TERMINAL_OUTCOMES,
    VOTE_POSITIONS,
    BodyKind,
    InstrumentKind,
    ObjectionGround,
    Outcome,
    Relief,
    UseClass,
)
from auspice.logging import get_logger

log = get_logger(__name__, _stage="labels")

DEFAULT_LABELS_FILE = "decisions.yaml"


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------
class Citation(BaseModel):
    """Where a labelled fact came from.

    ``quote`` is transcribed verbatim from the document at ``url``. ``auspice labels verify``
    fetches the URL, stores it in the content addressed corpus, extracts the text and checks
    the quote appears in it character for character. A quote that does not match marks the row
    unverified, and unverified rows are excluded from training.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    url: HttpUrl
    document_title: str = Field(min_length=3, max_length=300)
    quote: str = Field(min_length=10, max_length=500)
    page: int | None = Field(default=None, ge=1)
    retrieved_on: date
    kind: str = Field(
        default="secondary",
        description="primary for an official record, secondary for contemporary reporting",
    )

    @model_validator(mode="after")
    def _known_kind(self) -> Self:
        if self.kind not in {"primary", "secondary"}:
            raise ValueError("citation kind must be primary or secondary")
        return self


class Labelled(BaseModel):
    """Fields every labelled row carries."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    label_id: str = Field(
        pattern=r"^[a-z0-9][a-z0-9-]{4,80}$",
        description="Our stable key for this row. Never reused, never renumbered.",
    )
    jurisdiction: str = Field(pattern=r"^[a-z]{2}-[a-z]{2}-[a-z0-9-]+$")
    labelled_by: str = Field(min_length=2)
    labelled_on: date
    citations: list[Citation] = Field(min_length=1)
    notes: str | None = None

    @model_validator(mode="after")
    def _at_least_one_primary_or_two_secondary(self) -> Self:
        """One official record, or two independent contemporary reports.

        A single secondary source can be wrong about a vote tally, and a wrong tally in the
        training set teaches the model the opposite of what happened. Two independent reports
        that agree is a weaker guarantee than the minutes, and it is enough to load the row
        while the minutes are being retrieved.
        """
        primaries = [c for c in self.citations if c.kind == "primary"]
        if primaries:
            return self
        hosts = {c.url.host for c in self.citations if c.url.host}
        if len(hosts) < 2:
            raise ValueError(
                f"{self.label_id}: with no primary source, at least two citations from "
                "different hosts are required. Retrieve the official record instead."
            )
        return self


class MemberVote(BaseModel):
    """How one named member of a body voted on one application.

    Three features depend on this and can populate from nothing else: ``board_composition_score``,
    ``swing_seat_count`` and, through the member terms it creates,
    ``turnover_since_last_comparable``. Until this existed the aggregate ``vote_for`` and
    ``vote_against`` were the only tally a label could carry, so those three features returned unknown
    for every row no matter how much labelling was done. They were reachable only through the
    extraction pipeline, which needs a language model key.

    ``name`` is the member's name as the source spells it. Spellings vary between minutes, so the
    loader keeps every spelling it sees in ``decision_maker.name_variants`` and never destroys one,
    per section 6.5.

    Section 8.9 forbids predicting how a named individual will vote, and this does not do that. It
    records how they did vote, from the public record, and the features built on it are aggregates
    only. The distinction is the difference between reading minutes and profiling a person.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=2, max_length=200)
    position: str = Field(description="for, against, abstain, absent or recused")
    seat: str | None = Field(default=None, description="District or seat label, as published")
    term_start: date | None = None
    term_end: date | None = None

    @model_validator(mode="after")
    def _known_position(self) -> Self:
        if self.position not in VOTE_POSITIONS:
            raise ValueError(
                f"vote position must be one of {sorted(VOTE_POSITIONS)}, not {self.position!r}"
            )
        return self

    @model_validator(mode="after")
    def _terms_ordered(self) -> Self:
        if self.term_start and self.term_end and self.term_end < self.term_start:
            raise ValueError(f"{self.name}: term_end precedes term_start")
        return self


class DecisionLabel(Labelled):
    """One application to one body."""

    case_number: str | None = Field(
        default=None,
        description="The case number as the jurisdiction publishes it, or null when the cited "
        "sources do not give one.",
    )
    body: BodyKind
    applicant: str | None = None
    project_name: str | None = None
    use_class: UseClass
    relief_sought: list[Relief] = Field(min_length=1)
    by_right: bool | None = None
    acres: float | None = Field(default=None, gt=0)
    capacity_mw: float | None = Field(default=None, gt=0)
    filed_on: date | None = None
    decided_on: date | None = None
    outcome: Outcome
    vote_for: int | None = Field(default=None, ge=0)
    vote_against: int | None = Field(default=None, ge=0)
    vote_abstain: int | None = Field(default=None, ge=0)
    member_votes: list[MemberVote] = Field(
        default_factory=list,
        description="Per member votes, when the minutes name who voted which way. Optional, and the "
        "only route by which the board composition features can populate from hand labelling.",
    )
    staff_recommendation: str | None = None
    conditions: list[str] = Field(default_factory=list)
    objection_grounds: list[ObjectionGround] = Field(default_factory=list)
    organised_opposition: bool | None = None

    @model_validator(mode="after")
    def _terminal_needs_date(self) -> Self:
        if (
            self.outcome in TERMINAL_OUTCOMES
            and self.outcome is not Outcome.withdrawn
            and self.decided_on is None
        ):
            raise ValueError(
                f"{self.label_id}: outcome is {self.outcome.value} but decided_on is missing. "
                "A decision with no date is unusable for the survival model."
            )
        return self

    @model_validator(mode="after")
    def _dates_ordered(self) -> Self:
        if self.filed_on and self.decided_on and self.decided_on < self.filed_on:
            raise ValueError(f"{self.label_id}: decided_on precedes filed_on")
        return self

    @model_validator(mode="after")
    def _pending_has_no_decision(self) -> Self:
        if self.outcome is Outcome.pending and self.decided_on is not None:
            raise ValueError(f"{self.label_id}: outcome is pending but a decision date is set")
        return self

    @model_validator(mode="after")
    def _member_votes_agree_with_the_tally(self) -> Self:
        """Two records of the same vote have to say the same thing.

        A label can carry an aggregate tally, a per member list, or both. When it carries both they are
        two transcriptions of one event, and a disagreement means one of them is wrong. Loading both
        without checking would put a contradiction into the training set and into the evidence a
        customer reads, which is worse than carrying only one of them.
        """
        if not self.member_votes:
            return self

        names = [vote.name.strip().casefold() for vote in self.member_votes]
        duplicates = {name for name in names if names.count(name) > 1}
        if duplicates:
            raise ValueError(
                f"{self.label_id}: the same member appears twice in member_votes: "
                f"{sorted(duplicates)}. One person casts one vote."
            )

        counted = {
            position: sum(1 for vote in self.member_votes if vote.position == position)
            for position in ("for", "against", "abstain")
        }
        for field_name, position in (
            ("vote_for", "for"),
            ("vote_against", "against"),
            ("vote_abstain", "abstain"),
        ):
            declared = getattr(self, field_name)
            if declared is not None and declared != counted[position]:
                raise ValueError(
                    f"{self.label_id}: {field_name} is {declared} and member_votes contains "
                    f"{counted[position]} {position!r} vote(s). Two transcriptions of one vote "
                    "disagree, so one is wrong."
                )
        return self

    @model_validator(mode="after")
    def _member_terms_cover_the_decision(self) -> Self:
        """A member cannot vote on a decision made outside their term.

        Feature queries filter members by term against the as-of date, so a term that does not cover
        the decision date silently removes that member from every feature computed for it. The row
        would load, look complete, and quietly contribute less than it appears to.
        """
        if self.decided_on is None:
            return self
        for vote in self.member_votes:
            if vote.term_start and vote.term_start > self.decided_on:
                raise ValueError(
                    f"{self.label_id}: {vote.name} has a term starting {vote.term_start}, after the "
                    f"decision on {self.decided_on}. They cannot have voted on it."
                )
            if vote.term_end and vote.term_end < self.decided_on:
                raise ValueError(
                    f"{self.label_id}: {vote.name} has a term ending {vote.term_end}, before the "
                    f"decision on {self.decided_on}. They cannot have voted on it."
                )
        return self

    @model_validator(mode="after")
    def _vote_agrees_with_outcome(self) -> Self:
        """A recorded tally has to agree with the recorded outcome.

        This catches the single most damaging labelling error: transcribing a vote the right way
        round and the outcome the wrong way round, which flips the label on a row the model will
        then treat as a strong example.
        """
        if self.vote_for is None or self.vote_against is None:
            return self
        approved = self.outcome in APPROVAL_OUTCOMES
        if approved and self.vote_for <= self.vote_against:
            raise ValueError(
                f"{self.label_id}: outcome is {self.outcome.value} but the tally is "
                f"{self.vote_for}-{self.vote_against}. One of the two is transcribed wrong."
            )
        if self.outcome is Outcome.denied and self.vote_for > self.vote_against:
            raise ValueError(
                f"{self.label_id}: outcome is denied but the tally is "
                f"{self.vote_for}-{self.vote_against}. Some bodies vote on a motion to approve "
                "and some on a motion to deny, so record the tally in the direction of the "
                "outcome and put the motion wording in notes."
            )
        return self

    @model_validator(mode="after")
    def _staff_recommendation_vocabulary(self) -> Self:
        allowed = {"approve", "approve_with_conditions", "deny", "none"}
        if self.staff_recommendation is not None and self.staff_recommendation not in allowed:
            raise ValueError(f"staff_recommendation must be one of {sorted(allowed)}")
        return self

    @property
    def external_id(self) -> str:
        """What goes into the database. The published case number where one exists."""
        return self.case_number or f"label:{self.label_id}"

    @property
    def is_terminal(self) -> bool:
        return self.outcome in TERMINAL_OUTCOMES

    @property
    def is_censored(self) -> bool:
        return self.outcome in {Outcome.pending, Outcome.continued, Outcome.tabled, Outcome.unknown}


class InstrumentLabel(Labelled):
    """A rule, and when it changed.

    Section 6.6: knowing the current ordinance is a commodity. Knowing that it changed 90 days
    ago is the product. So moratoria and overlays are labelled with the same discipline as
    decisions, and they feed both ``days_since_rule_change`` and the rule change hazard model.
    """

    kind: InstrumentKind
    citation_ref: str | None = Field(
        default=None, description="The instrument's own citation, e.g. Resolution R-040726b"
    )
    title: str | None = None
    body: BodyKind | None = None
    adopted_on: date | None = None
    effective_on: date | None = None
    expires_on: date | None = None
    applies_to_use_classes: list[UseClass] = Field(default_factory=list)
    restrictions: dict[str, Any] = Field(default_factory=dict)
    vote_for: int | None = Field(default=None, ge=0)
    vote_against: int | None = Field(default=None, ge=0)
    vote_abstain: int | None = Field(default=None, ge=0)
    proposed_but_not_adopted: bool = Field(
        default=False,
        description="A moratorium that reached an agenda and failed. The negative cases matter: "
        "a model trained only on counties that restricted the use class will over predict "
        "restriction everywhere.",
    )

    @property
    def margin(self) -> float | None:
        """Share of the vote in favour, or None when no tally was recorded.

        A rule adopted seven to two is a different object from one adopted three to two. The
        first is durable; the second is one election away from reversal. The rule change hazard
        model uses this, so it is worth carrying even though the instrument table has no vote
        columns of its own.
        """
        if self.vote_for is None or self.vote_against is None:
            return None
        total = self.vote_for + self.vote_against
        if total == 0:
            return None
        return self.vote_for / total

    @model_validator(mode="after")
    def _adopted_or_explicitly_not(self) -> Self:
        if self.proposed_but_not_adopted and self.adopted_on is not None:
            raise ValueError(f"{self.label_id}: marked as not adopted but carries an adoption date")
        if not self.proposed_but_not_adopted and self.adopted_on is None:
            raise ValueError(
                f"{self.label_id}: an adopted instrument needs adopted_on. If it failed, set "
                "proposed_but_not_adopted to true."
            )
        return self

    @model_validator(mode="after")
    def _dates_ordered(self) -> Self:
        if self.effective_on and self.expires_on and self.expires_on < self.effective_on:
            raise ValueError(f"{self.label_id}: expires_on precedes effective_on")
        return self


class LabelSet(BaseModel):
    """The whole file."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str
    protocol: str = Field(description="Path to the labelling protocol this file follows")
    compiled_on: date
    decisions: list[DecisionLabel] = Field(default_factory=list)
    instruments: list[InstrumentLabel] = Field(default_factory=list)

    @model_validator(mode="after")
    def _label_ids_unique(self) -> Self:
        seen: set[str] = set()
        for row in [*self.decisions, *self.instruments]:
            if row.label_id in seen:
                raise ValueError(f"duplicate label_id: {row.label_id}")
            seen.add(row.label_id)
        return self

    @property
    def terminal_decisions(self) -> list[DecisionLabel]:
        return [d for d in self.decisions if d.is_terminal]

    @property
    def pending_decisions(self) -> list[DecisionLabel]:
        return [d for d in self.decisions if d.is_censored]

    def content_hash(self) -> str:
        """A hash over the labels, so a model run can record exactly which labels it saw."""
        digest = hashlib.sha256()
        for row in sorted([*self.decisions, *self.instruments], key=lambda r: r.label_id):
            digest.update(row.model_dump_json(exclude_none=False).encode("utf-8"))
        return digest.hexdigest()


def load_label_set(path: Path | None = None) -> LabelSet:
    from auspice.config import get_settings

    resolved = path or (get_settings().labels_path / DEFAULT_LABELS_FILE)
    if not resolved.exists():
        raise FileNotFoundError(
            f"labels file not found: {resolved}. See data/labels/README.md for the format."
        )
    raw = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    return LabelSet.model_validate(raw)


# ---------------------------------------------------------------------------
# Loading into the graph
# ---------------------------------------------------------------------------
class LabelLoadReport:
    def __init__(self) -> None:
        self.decisions = 0
        self.instruments = 0
        self.objections = 0
        self.votes = 0
        self.events = 0
        self.citations = 0
        self.unknown_jurisdictions: list[str] = []
        self.unmatched_bodies: list[str] = []

    def as_dict(self) -> dict[str, object]:
        return {
            "decisions": self.decisions,
            "instruments": self.instruments,
            "objections": self.objections,
            "votes": self.votes,
            "events": self.events,
            "citations": self.citations,
            "unknown_jurisdictions": sorted(set(self.unknown_jurisdictions)),
            "unmatched_bodies": sorted(set(self.unmatched_bodies)),
        }


def _jurisdiction_index(conn: Connection) -> dict[str, int]:
    rows = conn.execute(select(schema.jurisdiction.c.slug, schema.jurisdiction.c.id)).all()
    return {str(row[0]): int(row[1]) for row in rows}


def _body_index(conn: Connection) -> dict[tuple[int, str], int]:
    rows = conn.execute(
        select(
            schema.decision_body.c.jurisdiction_id,
            schema.decision_body.c.kind,
            schema.decision_body.c.id,
        )
    ).all()
    return {(jid, kind): bid for jid, kind, bid in rows}


def _record_citations(
    conn: Connection,
    *,
    subject_table: str,
    subject_id: int,
    citations: Sequence[Citation],
    extractor_version: str,
) -> int:
    """Store citations as ``fact_evidence`` rows.

    ``verified`` stays false until ``auspice labels verify`` fetches the document and confirms
    the quote appears verbatim. A false here means unverified, not wrong, and the training query
    filters on it.
    """
    written = 0
    for citation in citations:
        # A hand label's citation points at a URL we have not yet fetched, so there is no
        # document row to reference. The document id is the hash of the URL until the fetch
        # happens, at which point verify() replaces it with the hash of the bytes.
        placeholder_id = hashlib.sha256(str(citation.url).encode("utf-8")).hexdigest()
        conn.execute(
            pg_insert(schema.document)
            .values(
                id=placeholder_id,
                kind="news_article" if citation.kind == "secondary" else "minutes",
                source_url=str(citation.url),
                title=citation.document_title,
                byte_size=1,
                fetched_at=text("now()"),
                published_on=citation.retrieved_on,
                storage_key=f"pending/{placeholder_id}",
                response_headers={"_auspice_note": "citation placeholder, bytes not yet fetched"},
            )
            .on_conflict_do_nothing(index_elements=[schema.document.c.id])
        )
        conn.execute(
            schema.fact_evidence.insert().values(
                subject_table=subject_table,
                subject_id=subject_id,
                field="outcome" if subject_table == "application" else "adopted_on",
                document_id=placeholder_id,
                page=citation.page,
                quote=citation.quote,
                extractor_version=extractor_version,
                verified=False,
            )
        )
        written += 1
    return written


def load(
    conn: Connection,
    *,
    label_set: LabelSet | None = None,
    labels_path: Path | None = None,
) -> LabelLoadReport:
    """Load hand labels into the graph. Idempotent on ``label_id``."""
    from auspice.config import get_settings

    resolved_path = labels_path or (get_settings().labels_path / DEFAULT_LABELS_FILE)
    labels = label_set or load_label_set(resolved_path)
    report = LabelLoadReport()
    extractor_version = f"hand:{labels.version}"

    jurisdictions = _jurisdiction_index(conn)
    bodies = _body_index(conn)

    # Reload cleanly: hand labelled rows are replaced wholesale so a corrected label does not
    # leave the old version behind. Extracted rows are untouched.
    conn.execute(
        text(
            """
            DELETE FROM fact_evidence
            WHERE extractor_version LIKE 'hand:%'
            """
        )
    )
    conn.execute(text("DELETE FROM application WHERE label_source = 'hand_labelled'"))

    for row in labels.decisions:
        jurisdiction_id = jurisdictions.get(row.jurisdiction)
        if jurisdiction_id is None:
            report.unknown_jurisdictions.append(row.jurisdiction)
            log.warning(
                "label references an unknown jurisdiction",
                label_id=row.label_id,
                slug=row.jurisdiction,
            )
            continue

        body_id = bodies.get((jurisdiction_id, row.body.value))
        if body_id is None:
            report.unmatched_bodies.append(f"{row.jurisdiction}:{row.body.value}")

        application_id = int(
            conn.execute(
                schema.application.insert()
                .values(
                    jurisdiction_id=jurisdiction_id,
                    body_id=body_id,
                    external_id=row.external_id,
                    applicant_raw=row.applicant,
                    use_class=row.use_class.value,
                    relief_sought=[r.value for r in row.relief_sought],
                    by_right=row.by_right,
                    capacity_mw=row.capacity_mw,
                    acres=row.acres,
                    filed_on=row.filed_on,
                    decided_on=row.decided_on,
                    outcome=row.outcome.value,
                    vote_for=row.vote_for,
                    vote_against=row.vote_against,
                    vote_abstain=row.vote_abstain,
                    conditions={"list": row.conditions} if row.conditions else None,
                    staff_recommendation=row.staff_recommendation,
                    censored=row.is_censored,
                    label_source="hand_labelled",
                    notes=_decision_notes(row),
                )
                .returning(schema.application.c.id)
            ).scalar_one()
        )
        report.decisions += 1
        report.citations += _record_citations(
            conn,
            subject_table="application",
            subject_id=application_id,
            citations=row.citations,
            extractor_version=extractor_version,
        )

        if row.objection_grounds or row.organised_opposition is not None:
            conn.execute(
                schema.objection.insert().values(
                    application_id=application_id,
                    jurisdiction_id=jurisdiction_id,
                    observed_on=row.decided_on or row.filed_on,
                    organised=row.organised_opposition,
                    grounds=[g.value for g in row.objection_grounds],
                )
            )
            report.objections += 1

        report.votes += _record_member_votes(
            conn, application_id=application_id, body_id=body_id, row=row
        )

        report.events += _write_decision_events(conn, jurisdiction_id, application_id, body_id, row)

    for instrument_row in labels.instruments:
        jurisdiction_id = jurisdictions.get(instrument_row.jurisdiction)
        if jurisdiction_id is None:
            report.unknown_jurisdictions.append(instrument_row.jurisdiction)
            continue

        if instrument_row.proposed_but_not_adopted:
            # Nothing was adopted, so there is no instrument. What there is, is an event: a
            # moratorium reached an agenda and failed. That is a real and useful observation.
            conn.execute(
                schema.event.insert().values(
                    jurisdiction_id=jurisdiction_id,
                    event_type="moratorium_proposed",
                    occurred_on=instrument_row.effective_on or instrument_row.labelled_on,
                    known_from=instrument_row.effective_on or instrument_row.labelled_on,
                    detail={
                        "label_id": instrument_row.label_id,
                        "outcome": "not_adopted",
                        "title": instrument_row.title,
                        "vote": _vote_string(instrument_row),
                        "margin": instrument_row.margin,
                    },
                )
            )
            report.events += 1
            report.citations += _record_citations(
                conn,
                subject_table="jurisdiction",
                subject_id=jurisdiction_id,
                citations=instrument_row.citations,
                extractor_version=extractor_version,
            )
            continue

        instrument_id = int(
            conn.execute(
                schema.instrument.insert()
                .values(
                    jurisdiction_id=jurisdiction_id,
                    kind=instrument_row.kind.value,
                    citation=instrument_row.citation_ref,
                    title=instrument_row.title,
                    adopted_on=instrument_row.adopted_on,
                    effective_on=instrument_row.effective_on or instrument_row.adopted_on,
                    expires_on=instrument_row.expires_on,
                    applies_to_use_classes=[u.value for u in instrument_row.applies_to_use_classes],
                    restrictions=instrument_row.restrictions,
                )
                .returning(schema.instrument.c.id)
            ).scalar_one()
        )
        report.instruments += 1
        report.citations += _record_citations(
            conn,
            subject_table="instrument",
            subject_id=instrument_id,
            citations=instrument_row.citations,
            extractor_version=extractor_version,
        )

        event_type = (
            "moratorium_enacted"
            if instrument_row.kind is InstrumentKind.moratorium
            else "ordinance_adopted"
        )
        adopted = instrument_row.adopted_on
        assert adopted is not None  # guaranteed by the validator
        conn.execute(
            schema.event.insert().values(
                jurisdiction_id=jurisdiction_id,
                instrument_id=instrument_id,
                event_type=event_type,
                occurred_on=adopted,
                known_from=adopted,
                detail={
                    "label_id": instrument_row.label_id,
                    "citation": instrument_row.citation_ref,
                    "vote": _vote_string(instrument_row),
                    "margin": instrument_row.margin,
                },
            )
        )
        report.events += 1

    log.info("labels loaded", **report.as_dict())
    return report


def _record_member_votes(
    conn: Connection, *, application_id: int, body_id: int | None, row: DecisionLabel
) -> int:
    """Write ``decision_maker`` and ``vote`` rows for a decision that names who voted how.

    Members are matched by name within the body, case insensitively and ignoring surrounding
    whitespace, because minutes spell the same person several ways. Every spelling seen is kept in
    ``name_variants`` and none is ever destroyed, per section 6.5. Matching on the normalised name
    rather than creating a new member per spelling is what makes the vote history features work at all:
    two spellings of one supervisor would otherwise look like two members with half the record each.

    Term dates are widened, never narrowed. A later label that shows the same person voting earlier
    than their recorded term started means the recorded term was incomplete, and the earlier date is
    the better one. Narrowing would let one badly transcribed label hide a member from every feature
    computed for the decisions they actually sat on.
    """
    if not row.member_votes or body_id is None:
        return 0

    written = 0
    for member in row.member_votes:
        display = member.name.strip()
        normalised = display.casefold()

        existing = conn.execute(
            select(
                schema.decision_maker.c.id,
                schema.decision_maker.c.name_variants,
                schema.decision_maker.c.term_start,
                schema.decision_maker.c.term_end,
            ).where(
                schema.decision_maker.c.body_id == body_id,
                func.lower(schema.decision_maker.c.display_name) == normalised,
            )
        ).first()

        if existing is None:
            maker_id = int(
                conn.execute(
                    schema.decision_maker.insert()
                    .values(
                        body_id=body_id,
                        display_name=display,
                        name_variants=[display],
                        seat_label=member.seat,
                        term_start=member.term_start,
                        term_end=member.term_end,
                    )
                    .returning(schema.decision_maker.c.id)
                ).scalar_one()
            )
        else:
            maker_id = int(existing.id)
            variants = list(existing.name_variants or [])
            if display not in variants:
                variants.append(display)
            updates: dict[str, Any] = {"name_variants": variants}
            if member.term_start is not None and (
                existing.term_start is None or member.term_start < existing.term_start
            ):
                updates["term_start"] = member.term_start
            if member.term_end is not None and (
                existing.term_end is None or member.term_end > existing.term_end
            ):
                updates["term_end"] = member.term_end
            if member.seat:
                updates["seat_label"] = member.seat
            conn.execute(
                schema.decision_maker.update()
                .where(schema.decision_maker.c.id == maker_id)
                .values(**updates)
            )

        statement = pg_insert(schema.vote).values(
            application_id=application_id,
            maker_id=maker_id,
            position=member.position,
            voted_on=row.decided_on,
        )
        conn.execute(
            statement.on_conflict_do_update(
                index_elements=[schema.vote.c.application_id, schema.vote.c.maker_id],
                set_={
                    "position": statement.excluded.position,
                    "voted_on": statement.excluded.voted_on,
                },
            )
        )
        written += 1

    return written


def _vote_string(row: InstrumentLabel) -> str | None:
    if row.vote_for is None or row.vote_against is None:
        return None
    if row.vote_abstain:
        return f"{row.vote_for}-{row.vote_against}-{row.vote_abstain}"
    return f"{row.vote_for}-{row.vote_against}"


def _decision_notes(row: DecisionLabel) -> str | None:
    parts = [row.notes] if row.notes else []
    if row.project_name:
        parts.append(f"Project: {row.project_name}")
    return " | ".join(parts) if parts else None


def _write_decision_events(
    conn: Connection,
    jurisdiction_id: int,
    application_id: int,
    body_id: int | None,
    row: DecisionLabel,
) -> int:
    """Filing and decision as dated events.

    ``known_from`` equals ``occurred_on`` for hand labels: a filing and a decision both enter
    the public record on the day they happen, through an agenda or a minute. Where a source
    proves otherwise the labeller records it in notes and the event is corrected.
    """
    written = 0
    if row.filed_on is not None:
        conn.execute(
            schema.event.insert().values(
                jurisdiction_id=jurisdiction_id,
                application_id=application_id,
                body_id=body_id,
                event_type="application_filed",
                occurred_on=row.filed_on,
                known_from=row.filed_on,
                detail={"label_id": row.label_id},
            )
        )
        written += 1
    if row.decided_on is not None:
        conn.execute(
            schema.event.insert().values(
                jurisdiction_id=jurisdiction_id,
                application_id=application_id,
                body_id=body_id,
                event_type="decision_rendered",
                occurred_on=row.decided_on,
                known_from=row.decided_on,
                detail={
                    "label_id": row.label_id,
                    "outcome": row.outcome.value,
                    "vote": (
                        f"{row.vote_for}-{row.vote_against}"
                        if row.vote_for is not None and row.vote_against is not None
                        else None
                    ),
                },
            )
        )
        written += 1
    return written
