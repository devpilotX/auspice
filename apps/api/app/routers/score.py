"""Score endpoints. Section 5.4 products 1 and 2."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, status

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
async def score_one(
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
async def score_portfolio(
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

    return PortfolioResponse(ranked=rows, scored=len(rows), abstained=abstained)


@router.get("/score/as-of", summary="The date the served data is current to")
async def data_as_of(principal: CurrentPrincipal, models: Models) -> dict[str, object]:
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
