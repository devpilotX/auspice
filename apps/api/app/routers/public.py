"""Public endpoints: the accuracy record, jurisdiction profiles, freshness.

No API key on any route in this module, deliberately. Section 5.3: the single most important page on the
website is public and free, because it is the product proof, the marketing engine and the moat at the
same time. Section 10.4 adds the jurisdiction profiles, which exist to capture the search a developer
actually performs.

Publishing the freshness table is the uncomfortable one and it stays. Section 6.12 makes freshness a
published commitment rather than an internal metric, and a bureau that hides how stale its own data is
has already decided what kind of company it is.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import Connection, text

from app.deps import Db
from app.schemas import (
    AccuracyResponse,
    FreshnessRow,
    JurisdictionProfile,
    JurisdictionSummary,
    LocateLink,
    LocateResponse,
)

router = APIRouter(prefix="/v1/public", tags=["public"])

NO_RECORD_YET = (
    "No prediction has resolved yet, so there is no accuracy record to publish. This page will show a "
    "Brier score, a reliability curve and every miss as soon as there is one. It will not show a number "
    "before then."
)


def _freshness(conn: Connection, slug: str | None = None) -> list[dict[str, Any]]:
    from auspice.pipeline.ingest import freshness_report

    rows = freshness_report(conn)
    if slug is None:
        return rows
    return [r for r in rows if r["slug"] == slug]


@router.get("/accuracy", response_model=AccuracyResponse, summary="The published accuracy record")
def accuracy(conn: Db, response: Response) -> AccuracyResponse:
    from auspice import ledger

    record = ledger.public_record(conn)

    # Keyed to the chain head, which is the only thing that changes this page. A conditional request from
    # a browser or a CDN then costs the head lookup rather than a verification, and the ledger only ever
    # appends, so a matching head means a byte identical answer. No max-age: the page must be able to show
    # a newly published prediction immediately, and revalidation is cheap once there is a validator.
    head_seq, head_hash = ledger.head(conn)
    response.headers["ETag"] = f'W/"ledger-{head_seq}-{head_hash[:16]}"'
    response.headers["Cache-Control"] = "public, no-cache"

    kill_test = (
        conn.execute(
            text(
                """
            SELECT metrics, n_train, n_test, train_cutoff, trained_at, dataset_hash
            FROM model_run
            WHERE metrics ? 'brier_skill_vs_base_rate'
            ORDER BY trained_at DESC
            LIMIT 1
            """
            )
        )
        .mappings()
        .first()
    )

    statement = (
        NO_RECORD_YET
        if record["resolved"] == 0
        else (
            f"{record['answered']} predictions have resolved and been graded. The Brier score below "
            "counts every one of them, including the ones we got wrong, which are listed in full."
        )
    )

    anchor_status = ledger.anchor_status(conn, limit=5)

    return AccuracyResponse(
        published=record["published"],
        resolved=record["resolved"],
        pending=record["pending"],
        answered=record["answered"],
        abstained=record["abstained"],
        brier_score=record["brier_score"],
        chain=record["chain"],
        anchor={**anchor_status.as_dict(), "statement": anchor_status.statement()},
        misses=record["misses"],
        reliability=None,
        kill_test=dict(kill_test) if kill_test else None,
        statement=statement,
    )


@router.get("/ledger", summary="The full prediction ledger, newline delimited JSON")
def ledger_export(
    conn: Db,
    after: Annotated[int, Query(ge=0, description="Return entries after this sequence number")] = 0,
    limit: Annotated[
        int | None, Query(ge=1, le=100_000, description="Maximum entries to return")
    ] = None,
) -> Any:
    """The whole ledger, so anyone can verify it without using our interface.

    A record that can only be checked through the publisher's own tooling is not a public record, so this
    defaults to everything and there is no page size the caller cannot turn off. What changed is how it is
    sent: streamed a line at a time rather than assembled into one string first. The record grows forever
    by design, and an endpoint that materialises all of it to serve it is an endpoint whose memory cost
    grows with the thing the company is trying to accumulate.

    ``after`` and ``limit`` exist for a consumer fetching in slices, not for us deciding how much of our
    own record to show. Both are optional and neither is applied unless asked for.
    """
    from fastapi.responses import StreamingResponse

    from auspice import ledger

    head_seq, head_hash = ledger.head(conn)

    return StreamingResponse(
        ledger.iter_jsonl(conn, after_seq=after, limit=limit),
        media_type="application/x-ndjson",
        headers={
            "Content-Disposition": 'attachment; filename="auspice-ledger.ndjson"',
            "ETag": f'W/"ledger-{head_seq}-{head_hash[:16]}-{after}-{limit}"',
            "Cache-Control": "public, no-cache",
        },
    )


@router.get("/jurisdictions", response_model=list[JurisdictionSummary], summary="Coverage")
def jurisdictions(conn: Db) -> list[JurisdictionSummary]:
    from auspice.pipeline.registry.loader import registry_summary

    freshness_by_slug = {row["slug"]: row for row in _freshness(conn)}
    summaries: list[JurisdictionSummary] = []

    for row in registry_summary(conn):
        fresh = freshness_by_slug.get(row["slug"], {})
        summaries.append(
            JurisdictionSummary(
                slug=row["slug"],
                name=row["name"],
                kind="county",
                region=row["region"],
                legal_framework=row["legal_framework"],
                civic_platform=row["civic_platform"],
                data_depth=int(row["data_depth"] or 0),
                discretion_index=(
                    float(row["discretion_index"]) if row["discretion_index"] is not None else None
                ),
                bodies=int(row["bodies"] or 0),
                elections_known=int(row["elections"] or 0),
                has_boundary=bool(row["has_boundary"]),
                freshness=fresh.get("status", "never"),
                hours_since_refresh=(
                    float(fresh["hours_since_success"])
                    if fresh.get("hours_since_success") is not None
                    else None
                ),
            )
        )
    return summaries


@router.get(
    "/jurisdictions/{slug}",
    response_model=JurisdictionProfile,
    summary="A jurisdiction profile",
)
def jurisdiction_profile(slug: str, conn: Db) -> JurisdictionProfile:
    summaries = jurisdictions(conn)
    summary = next((s for s in summaries if s.slug == slug), None)
    if summary is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{slug} is not in the registry. Twelve counties are covered; the rest abstain.",
        )

    rates = (
        conn.execute(
            text(
                """
            SELECT
                a.use_class,
                count(*) FILTER (
                    WHERE a.outcome IN ('approved','approved_with_conditions','denied')
                ) AS decided,
                count(*) FILTER (WHERE a.outcome IN ('approved','approved_with_conditions')) AS approved
            FROM application a
            JOIN jurisdiction j ON j.id = a.jurisdiction_id
            WHERE j.slug = :slug
              AND EXISTS (
                  SELECT 1 FROM fact_evidence fe
                  WHERE fe.subject_table = 'application' AND fe.subject_id = a.id AND fe.verified
              )
            GROUP BY a.use_class
            """
            ).bindparams(slug=slug)
        )
        .mappings()
        .all()
    )

    instruments = (
        conn.execute(
            text(
                """
            SELECT i.kind, i.citation, i.title, i.adopted_on, i.expires_on, i.restrictions,
                   i.applies_to_use_classes
            FROM instrument i JOIN jurisdiction j ON j.id = i.jurisdiction_id
            WHERE j.slug = :slug
            ORDER BY i.adopted_on DESC NULLS LAST
            """
            ).bindparams(slug=slug)
        )
        .mappings()
        .all()
    )

    bodies = (
        conn.execute(
            text(
                """
            SELECT b.name, b.kind, b.seats, b.quorum, b.vote_threshold, b.recommendation_is_binding
            FROM decision_body b JOIN jurisdiction j ON j.id = b.jurisdiction_id
            WHERE j.slug = :slug
            ORDER BY b.seats DESC NULLS LAST
            """
            ).bindparams(slug=slug)
        )
        .mappings()
        .all()
    )

    elections = (
        conn.execute(
            text(
                """
            SELECT b.name AS body, e.election_date, e.seats_contested
            FROM election e
            JOIN decision_body b ON b.id = e.body_id
            JOIN jurisdiction j ON j.id = b.jurisdiction_id
            WHERE j.slug = :slug AND e.election_date >= current_date
            ORDER BY e.election_date
            LIMIT 4
            """
            ).bindparams(slug=slug)
        )
        .mappings()
        .all()
    )

    return JurisdictionProfile(
        summary=summary,
        approval_rate_by_use_class={
            row["use_class"]: (
                round(float(row["approved"]) / float(row["decided"]), 4) if row["decided"] else None
            )
            for row in rates
        },
        decisions=sum(int(row["decided"]) for row in rates),
        instruments=[dict(row) for row in instruments],
        bodies=[dict(row) for row in bodies],
        next_elections=[dict(row) for row in elections],
    )


@router.get("/locate", response_model=LocateResponse, summary="Who decides for this coordinate")
def locate(
    conn: Db,
    longitude: Annotated[float, Query(ge=-180, le=180)],
    latitude: Annotated[float, Query(ge=-90, le=90)],
) -> LocateResponse:
    """Stage 0 on its own: the chain of bodies that can refuse a project at this point.

    Public and unauthenticated like the rest of this router, and safe to be: it reads the boundary index
    that `auspice registry load` built from published county shapefiles, and returns nothing a visitor
    could not get from the counties themselves. It is a spatial join with no model fit behind it.

    A point outside the covered counties returns ``covered: false`` with an empty chain rather than a 404,
    because "we do not cover this place" is a real answer to a reasonable question and a 404 reads as a
    broken endpoint.
    """
    from auspice.pipeline.registry.loader import resolve_chain

    chain = resolve_chain(conn, longitude=longitude, latitude=latitude)

    return LocateResponse(
        longitude=longitude,
        latitude=latitude,
        covered=len(chain) > 0,
        chain=[
            LocateLink(
                slug=str(link["slug"]),
                name=str(link["name"]),
                kind=str(link["kind"]),
                role=str(link["role"]),
                region=None if link["region"] is None else str(link["region"]),
                legal_framework=(
                    None if link["legal_framework"] is None else str(link["legal_framework"])
                ),
                data_depth=int(link["data_depth"]),
                discretion_index=(
                    None if link["discretion_index"] is None else float(link["discretion_index"])
                ),
            )
            for link in chain
        ],
        note=(
            "The smallest containing jurisdiction decides. The rest can withhold a clearance."
            if chain
            else "This point is outside the twelve counties we cover. We hold no decision record for it."
        ),
    )


@router.get("/freshness", response_model=list[FreshnessRow], summary="How stale our data is")
def freshness(conn: Db) -> list[FreshnessRow]:
    return [
        FreshnessRow(
            jurisdiction=row["slug"],
            kind=row["kind"],
            platform=row["platform"],
            refresh_hours=int(row["refresh_hours"]),
            hours_since_success=(
                float(row["hours_since_success"])
                if row["hours_since_success"] is not None
                else None
            ),
            consecutive_failures=int(row["consecutive_failures"]),
            status=row["status"],
        )
        for row in _freshness(conn)
    ]


@router.get("/methodology", summary="The published method")
def methodology() -> dict[str, Any]:
    """The thresholds and rules the product commits to, served as data.

    Published from the same constants the code enforces rather than transcribed into prose, so the
    published methodology cannot drift from the implemented one.
    """
    from auspice.models.eval import thresholds
    from auspice.pipeline.features import FEATURES, MIN_COVERAGE

    return {
        "pass_conditions": {
            "brier_skill_vs_base_rate": thresholds.MIN_BRIER_SKILL,
            "brier_skill_target": thresholds.TARGET_BRIER_SKILL,
            "max_expected_calibration_error": thresholds.MAX_ECE,
            "interval_coverage_band": list(thresholds.COVERAGE_BAND),
            "min_auc": thresholds.MIN_AUC,
            "min_concordance_index": thresholds.MIN_CONCORDANCE,
            "min_abstention_precision": thresholds.MIN_ABSTENTION_PRECISION,
        },
        "sample_size_floors": {
            "labelled_decisions": thresholds.MIN_LABELLED_DECISIONS,
            "held_out_decisions": thresholds.MIN_HELD_OUT_DECISIONS,
            "jurisdictions_with_depth": thresholds.MIN_JURISDICTIONS_WITH_DEPTH,
        },
        "abstention_rule": {
            "abstain_when_all_hold": {
                "comparable_decisions_below": thresholds.ABSTAIN_MAX_COMPARABLES,
                "pooling_weight_above": thresholds.ABSTAIN_MAX_POOLING_WEIGHT,
                "interval_width_above": thresholds.ABSTAIN_MAX_INTERVAL_WIDTH,
            },
            "also_abstain_when": {
                "data_older_than_days": thresholds.STALENESS_ABSTAIN_DAYS,
                "jurisdiction_chain_unresolved": True,
                "distinct_outcomes_in_training_below": thresholds.MIN_OUTCOME_CLASSES,
            },
            "flag_without_abstaining_when": {
                "data_older_than_days": thresholds.STALENESS_FLAG_DAYS
            },
        },
        "feature_selection": {
            "min_coverage": MIN_COVERAGE,
            "requires_verified_provenance": True,
            "requires_one_plain_sentence": True,
        },
        "features": [
            {
                "name": spec.name,
                "group": spec.group.value,
                "expected_direction": spec.direction.value,
                "plain_language": spec.plain_language,
            }
            for spec in FEATURES
        ],
        "disclaimer": (
            "Permission Bureau produces a probabilistic opinion with a disclosed methodology. It is not legal "
            "advice, not an appraisal and not a guarantee. It models published voting records and "
            "stated positions, never inferred motives, and never predicts how a named individual will "
            "vote."
        ),
    }
