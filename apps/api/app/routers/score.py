"""Score endpoints. Section 5.4 products 1 and 2."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text

from app.deps import Db, Models
from app.schemas import PortfolioRequest, PortfolioResponse, PortfolioRow, ScoreRequest
from app.security import CurrentPrincipal
from auspice.score import Score, SiteRequest, score_site

router = APIRouter(prefix="/v1", tags=["score"])


def _to_site_request(body: ScoreRequest) -> SiteRequest:
    return SiteRequest(
        use_class=body.use_class,
        relief_sought=list(body.relief_sought),
        longitude=body.longitude,
        latitude=body.latitude,
        jurisdiction_slug=body.jurisdiction,
        parcel_ids=list(body.parcel_ids),
        label=body.label,
        acres=body.acres,
        capacity_mw=body.capacity_mw,
        by_right=body.by_right,
    )


@router.post(
    "/score",
    response_model=Score,
    summary="Score one site",
    response_description="The full score object, or an abstention.",
)
def score_one(
    body: ScoreRequest,
    principal: CurrentPrincipal,
    conn: Db,
    models: Models,
) -> Score:
    """Probability of approval, a time distribution, drivers with evidence, and alternatives.

    Returns 200 with ``abstained`` set to true when the evidence is too thin for a number. An abstention
    is a successful response, not an error: the customer asked a question and got the honest answer.
    """
    del principal
    return score_site(
        conn,
        _to_site_request(body),
        models=models,
        as_of=body.as_of,
        include_alternatives=body.include_alternatives,
    )


@router.post(
    "/portfolio",
    response_model=PortfolioResponse,
    summary="Screen a portfolio",
)
def score_portfolio(
    body: PortfolioRequest,
    principal: CurrentPrincipal,
    conn: Db,
    models: Models,
) -> PortfolioResponse:
    """Score up to 500 sites and rank them.

    This is the wedge feature. Section 9.2: never compete on one site, where a good local lawyer is
    often better than any model. Compete on three hundred, which no lawyer can do at any price.
    """
    if len(body.sites) > principal.portfolio_limit:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"The {principal.tier.value} tier covers {principal.portfolio_limit} sites and this "
                f"request has {len(body.sites)}."
            ),
        )

    rows: list[PortfolioRow] = []
    abstained = 0

    for site in body.sites:
        score = score_site(
            conn,
            _to_site_request(site),
            models=models,
            as_of=site.as_of,
            # Alternatives are per site and expensive. A portfolio screen is about ordering, and the
            # customer asks for alternatives on the handful that survive the screen.
            include_alternatives=False,
        )
        head = score.site.jurisdiction_chain[0]
        if score.determination.abstained:
            abstained += 1
        rows.append(
            PortfolioRow(
                label=score.site.label,
                jurisdiction=head.name,
                approval_probability=score.determination.approval_probability,
                credible_interval_80=score.determination.credible_interval_80,
                abstained=score.determination.abstained,
                months_p50=(
                    score.determination.time_to_decision_months.p50
                    if score.determination.time_to_decision_months
                    else None
                ),
                rule_change_probability=score.determination.probability_of_rule_change_before_decision,
                data_depth=head.data_depth,
                stale=score.provenance.stale,
                public_id=score.public_id,
            )
        )

    # Abstentions sort last and keep no number. Treating an abstention as a low score would make
    # refusing to answer indistinguishable from answering badly.
    rows.sort(key=lambda r: (r.abstained, -(r.approval_probability or 0.0)))

    return PortfolioResponse(
        ranked=rows,
        submitted=len(rows),
        scored=len(rows) - abstained,
        abstained=abstained,
    )


@router.get("/score/as-of", summary="The date the served data is current to")
def data_as_of(principal: CurrentPrincipal, models: Models) -> dict[str, object]:
    """Every score carries ``data_as_of``. This exposes it without running a score."""
    del principal
    return {
        "serving_model": models.primary_kind,
        "dataset_hash": models.dataset.hash(),
        "trained_at": models.trained_at.isoformat() if models.trained_at else None,
        "decisions_held": models.dataset.decided.height,
        "today": date.today().isoformat(),
        "notes": models.notes or [],
    }


@router.get(
    "/score/{public_id}",
    response_model=Score,
    summary="Retrieve a score that was already produced",
)
def get_score(public_id: str, principal: CurrentPrincipal, conn: Db) -> Score:
    """Read back a stored prediction by its public identifier.

    Retrieval rather than recomputation, deliberately. A score is a dated statement about what was known on a
    particular day, and a report opened next month has to show the same number the memo in the deal file
    shows. Recomputing on read would quietly revise a published prediction, which section 8.9 forbids.
    """
    del principal

    row = (
        conn.execute(
            text(
                """
            SELECT p.public_id, p.created_at, p.site, p.approval_probability, p.ci80_low, p.ci80_high,
                   p.confidence, p.abstained, p.abstention_reasons, p.months_p10, p.months_p50, p.months_p90,
                   p.rule_change_probability, p.drivers, p.precedents, p.mitigations, p.alternatives,
                   p.provenance, p.features_hash, p.data_as_of
            FROM prediction p
            WHERE p.public_id = :public_id
            """
            ).bindparams(public_id=public_id)
        )
        .mappings()
        .first()
    )

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No score with the identifier {public_id}. Scores are stored when they are published to "
                "the ledger; an unpublished score exists only in the response that produced it."
            ),
        )

    return _rehydrate(row)


def _rehydrate(row: Any) -> Score:
    """Rebuild the score object from its stored columns.

    Validated on the way out through the same model that validated it on the way in, so a row that somehow
    violates an invariant fails here rather than rendering. The database has CHECK constraints saying the
    same things, and this is the second of the two locks.
    """
    determination = {
        "approval_probability": _as_float(row["approval_probability"]),
        "credible_interval_80": (
            (_as_float(row["ci80_low"]), _as_float(row["ci80_high"]))
            if row["ci80_low"] is not None and row["ci80_high"] is not None
            else None
        ),
        "interval_kind": "credible",
        "confidence": row["confidence"],
        "abstained": bool(row["abstained"]),
        "abstention_reasons": list(row["abstention_reasons"] or []),
        "time_to_decision_months": (
            {
                "p10": _as_float(row["months_p10"]),
                "p50": _as_float(row["months_p50"]),
                "p90": _as_float(row["months_p90"]),
                "basis": "fitted",
            }
            if row["months_p50"] is not None
            else None
        ),
        "probability_of_rule_change_before_decision": _as_float(row["rule_change_probability"]),
        "local_base_rate": None,
    }

    return Score.model_validate(
        {
            "public_id": row["public_id"],
            "generated_at": row["created_at"],
            "site": row["site"],
            "determination": determination,
            "drivers": list(row["drivers"] or []),
            "precedents": list(row["precedents"] or []),
            "mitigations": list(row["mitigations"] or []),
            "alternatives": list(row["alternatives"] or []),
            "evidence": [],
            "provenance": row["provenance"],
            "features_hash": row["features_hash"],
        }
    )


def _as_float(value: Any) -> float | None:
    return None if value is None else float(value)
