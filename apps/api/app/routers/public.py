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

from typing import Any

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text

from app.deps import Db
from app.schemas import (
    AccuracyResponse,
    FreshnessRow,
    JurisdictionProfile,
    JurisdictionSummary,
)

router = APIRouter(prefix="/v1/public", tags=["public"])

NO_RECORD_YET = (
    "No prediction has resolved yet, so there is no accuracy record to publish. This page will show a "
    "Brier score, a reliability curve and every miss as soon as there is one. It will not show a number "
    "before then."
)


def _freshness(conn: Db, slug: str | None = None) -> list[dict[str, Any]]:
    from auspice.pipeline.ingest import freshness_report

    rows = freshness_report(conn)
    if slug is None:
        return rows
    return [r for r in rows if r["slug"] == slug]


@router.get("/accuracy", response_model=AccuracyResponse, summary="The published accuracy record")
async def accuracy(conn: Db) -> AccuracyResponse:
    from auspice import ledger

    record = ledger.public_record(conn)

    kill_test = conn.execute(
        text(
            """
            SELECT metrics, n_train, n_test, train_cutoff, trained_at, dataset_hash
            FROM model_run
            WHERE metrics ? 'brier_skill_vs_base_rate'
            ORDER BY trained_at DESC
            LIMIT 1
            """
        )
    ).mappings().first()

    statement = NO_RECORD_YET if record["resolved"] == 0 else (
        f"{record['answered']} predictions have resolved and been graded. The Brier score below "
        "counts every one of them, including the ones we got wrong, which are listed in full."
    )

    return AccuracyResponse(
        published=record["published"],
        resolved=record["resolved"],
        pending=record["pending"],
        answered=record["answered"],
        abstained=record["abstained"],
        brier_score=record["brier_score"],
        chain=record["chain"],
        misses=record["misses"],
        reliability=None,
        kill_test=dict(kill_test) if kill_test else None,
        statement=statement,
    )


@router.get("/ledger", summary="The full prediction ledger, newline delimited JSON")
async def ledger_export(conn: Db) -> Any:
    """The whole ledger, so anyone can verify it without using our interface.

    A record that can only be checked through the publisher's own tooling is not a public record.
    """
    from fastapi.responses import PlainTextResponse

    from auspice import ledger

    return PlainTextResponse(
        ledger.export_jsonl(conn),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": 'attachment; filename="auspice-ledger.ndjson"'},
    )


@router.get("/jurisdictions", response_model=list[JurisdictionSummary], summary="Coverage")
async def jurisdictions(conn: Db) -> list[JurisdictionSummary]:
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
async def jurisdiction_profile(slug: str, conn: Db) -> JurisdictionProfile:
    summaries = await jurisdictions(conn)
    summary = next((s for s in summaries if s.slug == slug), None)
    if summary is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{slug} is not in the registry. Twelve counties are covered; the rest abstain.",
        )

    rates = conn.execute(
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
    ).mappings().all()

    instruments = conn.execute(
        text(
            """
            SELECT i.kind, i.citation, i.title, i.adopted_on, i.expires_on, i.restrictions,
                   i.applies_to_use_classes
            FROM instrument i JOIN jurisdiction j ON j.id = i.jurisdiction_id
            WHERE j.slug = :slug
            ORDER BY i.adopted_on DESC NULLS LAST
            """
        ).bindparams(slug=slug)
    ).mappings().all()

    bodies = conn.execute(
        text(
            """
            SELECT b.name, b.kind, b.seats, b.quorum, b.vote_threshold, b.recommendation_is_binding
            FROM decision_body b JOIN jurisdiction j ON j.id = b.jurisdiction_id
            WHERE j.slug = :slug
            ORDER BY b.seats DESC NULLS LAST
            """
        ).bindparams(slug=slug)
    ).mappings().all()

    elections = conn.execute(
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
    ).mappings().all()

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


@router.get("/freshness", response_model=list[FreshnessRow], summary="How stale our data is")
async def freshness(conn: Db) -> list[FreshnessRow]:
    return [
        FreshnessRow(
            jurisdiction=row["slug"],
            kind=row["kind"],
            platform=row["platform"],
            refresh_hours=int(row["refresh_hours"]),
            hours_since_success=(
                float(row["hours_since_success"]) if row["hours_since_success"] is not None else None
            ),
            consecutive_failures=int(row["consecutive_failures"]),
            status=row["status"],
        )
        for row in _freshness(conn)
    ]


@router.get("/methodology", summary="The published method")
async def methodology() -> dict[str, Any]:
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
            "Auspice produces a probabilistic opinion with a disclosed methodology. It is not legal "
            "advice, not an appraisal and not a guarantee. It models published voting records and "
            "stated positions, never inferred motives, and never predicts how a named individual will "
            "vote."
        ),
    }
