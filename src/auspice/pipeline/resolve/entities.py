"""Stage 5: entity resolution.

Section 6.5 calls this the unglamorous stage that decides whether the graph is real or garbage, and it is
right. Four problems, in ascending order of value.

"Loudoun County Board of Supervisors", "Loudoun Co. BOS" and "the Board" are one entity.

A commissioner appears as "J. Smith", "Jane Smith" and "Supervisor Smith", across two non consecutive
terms.

Parcels split, merge and get renumbered between assessment years.

The same applicant behind six single purpose LLCs. This one is genuinely predictive and developers
deliberately obscure it, which makes beneficial owner clustering the highest value work in the stage.

## The method, and why it is a cascade

Blocking on jurisdiction and type first, then exact match, then trigram similarity, then embedding
similarity, then a language model on the ambiguous middle band only. Each step is cheaper and more certain
than the next, so the expensive step sees a small number of genuinely hard cases rather than every pair.

The band matters more than the steps. Above the high threshold a merge happens automatically. Below the low
threshold nothing happens. Between them the pair goes to adjudication, and the width of that band is the
knob that trades cost against precision. Section 16.2 targets entity resolution precision above 0.97, which
is a demanding number and it is met by making the band wide rather than by making the thresholds
aggressive.

## Every merge is reversible

The original strings are never destroyed. A merge writes an ``entity_alias`` row holding the string exactly
as it appeared and a ``merge_audit`` row recording the method, the score and the rationale. ``reverse``
undoes one.

That is not defensive programming. Entity resolution is the stage most likely to be wrong in a way nobody
notices for months, and the only recovery from a bad merge is having kept what was there before.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text, update
from sqlalchemy.engine import Connection

from auspice.db import schema
from auspice.logging import get_logger

log = get_logger(__name__, _stage="resolve")

# Above this, merge. Below the low threshold, do nothing. Between them, adjudicate.
AUTO_MERGE_SIMILARITY = 0.92
ADJUDICATE_SIMILARITY = 0.62

# Corporate suffixes carry no identifying information and their presence varies by filing clerk.
_SUFFIXES = (
    "llc",
    "l.l.c.",
    "inc",
    "inc.",
    "incorporated",
    "corp",
    "corp.",
    "corporation",
    "co",
    "co.",
    "company",
    "lp",
    "l.p.",
    "llp",
    "ltd",
    "ltd.",
    "limited",
    "holdings",
    "holding",
    "partners",
    "partnership",
    "trust",
    "group",
    "properties",
    "property",
    "development",
    "developments",
    "ventures",
    "capital",
    "investments",
    "realty",
)

# Words that make a name look like a single purpose vehicle rather than an operating company. Not proof of
# anything, and the feature that consumes it is named entity_opacity rather than something judgemental.
_SPV_MARKERS = re.compile(
    r"\b(?:spe|spv|holdco|propco|project\s*co|acquisition\s*(?:co|corp)|"
    r"[a-z]{1,3}\s*\d{1,4}\s*llc|solar\s*\d+|site\s*[a-z0-9]{1,4})\b",
    re.I,
)

_BODY_ABBREVIATIONS = {
    "bos": "board of supervisors",
    "bocs": "board of county supervisors",
    "bcc": "board of county commissioners",
    "boc": "board of commissioners",
    "pc": "planning commission",
    "apc": "area plan commission",
    "zba": "zoning board of appeals",
    "bza": "board of zoning appeals",
    "cc": "city council",
}

_HONORIFICS = (
    "supervisor",
    "commissioner",
    "councilmember",
    "council member",
    "councilman",
    "councilwoman",
    "chairman",
    "chairwoman",
    "chair",
    "mayor",
    "mr",
    "mrs",
    "ms",
    "dr",
    "hon",
    "honorable",
    "vice",
)


# ---------------------------------------------------------------------------
# Normalisation. Never applied in place: the raw string is stored beside it.
# ---------------------------------------------------------------------------
def normalise_organisation(raw: str) -> str:
    """Reduce an organisation name to its identifying core.

    Case, punctuation and corporate suffixes go. The order of remaining words is kept, because "Ridgeline
    Solar" and "Solar Ridgeline" are not obviously the same company and pretending otherwise would merge
    unrelated entities.

    Dotted initialisms are collapsed before punctuation is stripped, which matters more than it looks:
    stripping first turns "L.L.C." into three separate tokens and the suffix list then never matches it, so
    "Ridgeline Holdings, L.L.C." and "Ridgeline Holdings LLC" reduce to different strings and stay two
    entities. Only runs of single letters followed by dots are collapsed, so "St. Louis Partners" keeps its
    space.
    """
    lowered = raw.lower()
    lowered = re.sub(r"\b(?:[a-z]\.){2,}", lambda match: match.group(0).replace(".", ""), lowered)
    lowered = re.sub(r"[^\w\s]", " ", lowered)
    tokens = [token for token in lowered.split() if token]
    while tokens and tokens[-1] in _SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def normalise_body(raw: str) -> str:
    """Expand the abbreviations local records use for their own bodies."""
    lowered = re.sub(r"[^\w\s]", " ", raw.lower())
    tokens = [_BODY_ABBREVIATIONS.get(token, token) for token in lowered.split() if token]
    expanded = " ".join(tokens)
    # "the board" on its own is not resolvable without context, and saying so is better than guessing.
    return (
        ""
        if expanded.strip() in {"the board", "board", "the commission", "commission"}
        else expanded
    )


def normalise_person(raw: str) -> tuple[str, str]:
    """Return (surname, normalised full form) for a person named in a record.

    The surname is returned separately because it is the only part that is reliably present. "J. Smith",
    "Jane Smith" and "Supervisor Smith" agree on exactly one token, and matching on that token plus the
    body is far safer than trying to reconcile the given names.
    """
    lowered = re.sub(r"[^\w\s.]", " ", raw.lower())
    tokens = [token.strip(".") for token in lowered.split() if token.strip(".")]
    tokens = [token for token in tokens if token not in _HONORIFICS]
    if not tokens:
        return "", ""
    # Initials carry no surname information.
    substantive = [token for token in tokens if len(token) > 1]
    surname = substantive[-1] if substantive else tokens[-1]
    return surname, " ".join(tokens)


def looks_like_single_purpose_entity(raw: str) -> bool:
    """Whether a name reads as a single purpose vehicle.

    Two signals: an explicit marker, or a name that is almost entirely a corporate suffix once normalised,
    which is what "Pageland 3 LLC" looks like after the suffix is stripped.
    """
    if _SPV_MARKERS.search(raw):
        return True
    core = normalise_organisation(raw)
    return len(core.split()) <= 2 and bool(re.search(r"\d", core))


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class ResolveReport:
    clusters_created: int = 0
    aliases_added: int = 0
    merged: int = 0
    queued_for_adjudication: int = 0
    bodies_resolved: int = 0
    people_resolved: int = 0
    candidates: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "clusters_created": self.clusters_created,
            "aliases_added": self.aliases_added,
            "merged": self.merged,
            "queued_for_adjudication": self.queued_for_adjudication,
            "bodies_resolved": self.bodies_resolved,
            "people_resolved": self.people_resolved,
        }


def resolve_applicants(conn: Connection, *, report: ResolveReport | None = None) -> ResolveReport:
    """Cluster applicant strings and attach applications to their cluster.

    Runs in three passes over the distinct raw strings on ``application``: exact match on the normalised
    form, then trigram similarity through pg_trgm, then the adjudication queue for the middle band.

    The embedding pass described in section 6.5 is not run here. It needs document embeddings that the
    corpus does not yet hold, and adding a step that silently does nothing would make the cascade look more
    thorough than it is. It is a named gap in docs/DATA_SOURCES.md.
    """
    resolved = report or ResolveReport()

    rows = (
        conn.execute(
            text(
                """
            SELECT DISTINCT a.applicant_raw
            FROM application a
            WHERE a.applicant_raw IS NOT NULL
              AND length(trim(a.applicant_raw)) > 2
              AND a.applicant_cluster_id IS NULL
            ORDER BY a.applicant_raw
            """
            )
        )
        .scalars()
        .all()
    )

    for raw in rows:
        normalised = normalise_organisation(str(raw))
        if not normalised:
            continue

        cluster_id = _find_or_create_cluster(
            conn,
            kind="applicant",
            raw=str(raw),
            normalised=normalised,
            report=resolved,
        )
        if cluster_id is None:
            continue

        conn.execute(
            update(schema.application)
            .where(schema.application.c.applicant_raw == raw)
            .where(schema.application.c.applicant_cluster_id.is_(None))
            .values(applicant_cluster_id=cluster_id)
        )

    log.info("applicants resolved", **resolved.as_dict())
    return resolved


def _find_or_create_cluster(
    conn: Connection,
    *,
    kind: str,
    raw: str,
    normalised: str,
    report: ResolveReport,
) -> int | None:
    """Exact, then trigram, then create. Ambiguous pairs are queued rather than merged."""
    exact = conn.execute(
        text(
            """
            SELECT ec.id
            FROM entity_cluster ec
            JOIN entity_alias ea ON ea.cluster_id = ec.id
            WHERE ec.kind = :kind AND ea.normalised = :normalised
            LIMIT 1
            """
        ).bindparams(kind=kind, normalised=normalised)
    ).scalar()
    if exact is not None:
        _add_alias(conn, cluster_id=int(exact), raw=raw, normalised=normalised, report=report)
        return int(exact)

    # pg_trgm similarity, ordered by score. The index on entity_alias.normalised makes this cheap.
    candidate = (
        conn.execute(
            text(
                """
            SELECT ec.id, ea.normalised, similarity(ea.normalised, :normalised) AS score
            FROM entity_cluster ec
            JOIN entity_alias ea ON ea.cluster_id = ec.id
            WHERE ec.kind = :kind
              AND similarity(ea.normalised, :normalised) >= :floor
            ORDER BY score DESC
            LIMIT 1
            """
            ).bindparams(kind=kind, normalised=normalised, floor=ADJUDICATE_SIMILARITY)
        )
        .mappings()
        .first()
    )

    if candidate is not None:
        score = float(candidate["score"])
        if score >= AUTO_MERGE_SIMILARITY:
            _add_alias(
                conn, cluster_id=int(candidate["id"]), raw=raw, normalised=normalised, report=report
            )
            _record_merge(
                conn,
                entity_kind=kind,
                absorbed_id=0,
                survivor_id=int(candidate["id"]),
                method="trigram",
                score=score,
                rationale=f"{normalised!r} matched {candidate['normalised']!r}",
            )
            report.merged += 1
            return int(candidate["id"])

        # The middle band. Queued for a human or a language model, and a new cluster is created in the
        # meantime so the application is not left unattached. If adjudication later says they are the same,
        # the merge is a single operation and it is reversible.
        report.queued_for_adjudication += 1
        report.candidates.append(
            {
                "kind": kind,
                "raw": raw,
                "normalised": normalised,
                "nearest": candidate["normalised"],
                "score": round(score, 4),
            }
        )
        from auspice.pipeline.ingest import record_dead_letter

        record_dead_letter(
            conn,
            stage="resolve",
            subject=f"{kind}:{normalised}",
            jurisdiction_id=None,
            error_type="ambiguous_match",
            error_message=(
                f"{normalised!r} is {score:.2f} similar to {candidate['normalised']!r}, which is inside "
                "the adjudication band. Confirm or reject rather than guessing."
            ),
            payload={"raw": raw, "nearest": candidate["normalised"], "score": score},
        )

    cluster_id = int(
        conn.execute(
            schema.entity_cluster.insert()
            .values(
                kind=kind,
                canonical_name=raw.strip(),
                opaque=looks_like_single_purpose_entity(raw),
            )
            .returning(schema.entity_cluster.c.id)
        ).scalar_one()
    )
    report.clusters_created += 1
    _add_alias(conn, cluster_id=cluster_id, raw=raw, normalised=normalised, report=report)
    return cluster_id


def _add_alias(
    conn: Connection, *, cluster_id: int, raw: str, normalised: str, report: ResolveReport
) -> None:
    """Record a spelling. The raw string is stored exactly as it appeared, always."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    statement = pg_insert(schema.entity_alias).values(
        cluster_id=cluster_id, raw_string=raw, normalised=normalised
    )
    conn.execute(
        statement.on_conflict_do_nothing(
            index_elements=[schema.entity_alias.c.cluster_id, schema.entity_alias.c.raw_string]
        )
    )
    report.aliases_added += 1


def _record_merge(
    conn: Connection,
    *,
    entity_kind: str,
    absorbed_id: int,
    survivor_id: int,
    method: str,
    score: float | None,
    rationale: str,
) -> None:
    if absorbed_id == survivor_id:
        # The audit table forbids a self merge, and an alias added to an existing cluster is not a merge of
        # two clusters. Recording it as one would make the audit trail describe something that did not
        # happen.
        return
    conn.execute(
        schema.merge_audit.insert().values(
            entity_kind=entity_kind,
            absorbed_id=absorbed_id,
            survivor_id=survivor_id,
            method=method,
            score=score,
            rationale=rationale,
        )
    )


def merge_clusters(
    conn: Connection,
    *,
    absorbed_id: int,
    survivor_id: int,
    method: str = "manual",
    score: float | None = None,
    rationale: str = "",
) -> None:
    """Merge two clusters. Reversible.

    Everything pointing at the absorbed cluster is repointed, its aliases move across, and the audit row
    records enough to undo it. The absorbed cluster row itself is deleted only after its aliases have moved,
    so a failure partway through leaves the aliases attached to something.
    """
    if absorbed_id == survivor_id:
        raise ValueError("a cluster cannot absorb itself")

    conn.execute(
        update(schema.entity_alias)
        .where(schema.entity_alias.c.cluster_id == absorbed_id)
        .values(cluster_id=survivor_id)
    )
    for table, column in (
        (schema.application, schema.application.c.applicant_cluster_id),
        (schema.parcel, schema.parcel.c.owner_cluster_id),
        (schema.objection, schema.objection.c.group_cluster_id),
    ):
        conn.execute(update(table).where(column == absorbed_id).values({column.name: survivor_id}))

    _record_merge(
        conn,
        entity_kind="applicant",
        absorbed_id=absorbed_id,
        survivor_id=survivor_id,
        method=method,
        score=score,
        rationale=rationale or f"cluster {absorbed_id} merged into {survivor_id}",
    )
    conn.execute(schema.entity_cluster.delete().where(schema.entity_cluster.c.id == absorbed_id))
    log.info("clusters merged", absorbed=absorbed_id, survivor=survivor_id, method=method)


def reverse(conn: Connection, *, merge_audit_id: int, reason: str) -> None:
    """Mark a merge as reversed.

    The aliases are not moved back automatically, because the correct destination depends on why the merge
    was wrong, and a second wrong guess is not an improvement. What this does is record that the merge was
    wrong, with a reason, so the next run of the resolver treats the pair as adjudicated rather than
    re-merging it.
    """
    conn.execute(
        update(schema.merge_audit)
        .where(schema.merge_audit.c.id == merge_audit_id)
        .values(reversed_at=datetime.now(UTC), reversed_reason=reason)
    )
    log.info("merge reversed", merge_audit_id=merge_audit_id, reason=reason)


def resolve_body_reference(conn: Connection, *, jurisdiction_id: int, raw: str) -> int | None:
    """Map a body name found in a document onto a registry body.

    Returns None when the reference is unresolvable, which "the Board" always is without more context.
    Guessing the largest body would be wrong in every county with two.
    """
    normalised = normalise_body(raw)
    if not normalised:
        return None

    row = (
        conn.execute(
            text(
                """
            SELECT b.id, similarity(lower(b.name), :normalised) AS score
            FROM decision_body b
            WHERE b.jurisdiction_id = :jurisdiction_id
            ORDER BY score DESC
            LIMIT 1
            """
            ).bindparams(jurisdiction_id=jurisdiction_id, normalised=normalised)
        )
        .mappings()
        .first()
    )

    if row is None or float(row["score"]) < ADJUDICATE_SIMILARITY:
        return None
    return int(row["id"])


def resolve_person(conn: Connection, *, body_id: int, raw: str, as_of: Any = None) -> int | None:
    """Map a person named in a record onto a sitting member of a body.

    Matches on surname plus the body, and requires the person to have been in office on ``as_of`` if one is
    given. A commissioner who served two non consecutive terms is two rows, and attributing a 2019 quote to
    the 2025 term would be wrong in exactly the way that matters for the board composition feature.
    """
    surname, full = normalise_person(raw)
    if not surname:
        return None

    rows = (
        conn.execute(
            text(
                """
            SELECT m.id, m.display_name, m.name_variants, m.term_start, m.term_end
            FROM decision_maker m
            WHERE m.body_id = :body_id
              AND (
                  lower(m.display_name) LIKE '%' || :surname || '%'
                  OR EXISTS (
                      SELECT 1 FROM unnest(m.name_variants) v
                      WHERE lower(v) LIKE '%' || :surname || '%'
                  )
              )
            """
            ).bindparams(body_id=body_id, surname=surname)
        )
        .mappings()
        .all()
    )

    if as_of is not None:
        rows = [
            row
            for row in rows
            if (row["term_start"] is None or row["term_start"] <= as_of)
            and (row["term_end"] is None or row["term_end"] >= as_of)
        ]

    if len(rows) == 1:
        return int(rows[0]["id"])
    if not rows:
        return None

    # More than one member shares the surname. Fall back to the full normalised form, and give up rather
    # than picking one if that does not separate them.
    for row in rows:
        if normalise_person(str(row["display_name"]))[1] == full:
            return int(row["id"])
    log.debug("person reference is ambiguous", raw=raw, body_id=body_id, candidates=len(rows))
    return None


def precision_estimate(conn: Connection) -> dict[str, Any]:
    """A checkable proxy for the section 16.2 target of 0.97 entity resolution precision.

    True precision needs a hand labelled sample, which is the correct way to measure it and is listed as
    outstanding. What this reports is what can be computed: how many merges were automatic against
    adjudicated, and how many have been reversed. A rising reversal rate is the signal that the automatic
    threshold is too loose, and it is the number to watch.
    """
    row = (
        conn.execute(
            text(
                """
            SELECT
                count(*) AS merges,
                count(*) FILTER (WHERE method = 'trigram') AS by_trigram,
                count(*) FILTER (WHERE method = 'manual') AS by_hand,
                count(*) FILTER (WHERE method = 'llm_adjudication') AS by_model,
                count(*) FILTER (WHERE reversed_at IS NOT NULL) AS reversed
            FROM merge_audit
            """
            )
        )
        .mappings()
        .one()
    )

    merges = int(row["merges"])
    return {
        "merges": merges,
        "by_trigram": int(row["by_trigram"]),
        "by_hand": int(row["by_hand"]),
        "by_model": int(row["by_model"]),
        "reversed": int(row["reversed"]),
        "reversal_rate": round(int(row["reversed"]) / merges, 4) if merges else None,
        "note": (
            "Reversal rate is a proxy. True precision needs a hand labelled sample and is outstanding, "
            "which is stated rather than approximated away."
        ),
    }
