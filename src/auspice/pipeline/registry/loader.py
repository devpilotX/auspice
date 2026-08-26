"""Load the registry into the Permission Graph.

The load is idempotent and transactional. Running it twice produces the same rows, and a
partial load never lands, because a registry that is half loaded makes the abstention rule
read a wrong ``data_depth`` and abstain on the wrong jurisdictions.

Election dates are derived from the rule in the registry rather than copied, so the
``election`` table is rebuilt from scratch on every load. That is safe: nothing references an
election row by id.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import yaml
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection

from auspice.config import get_settings
from auspice.db import schema
from auspice.domain import CivicPlatform, DISCRETIONARY_RELIEF, Relief
from auspice.logging import get_logger
from auspice.pipeline.registry.boundaries import fetch_county_boundary
from auspice.pipeline.registry.elections import derive_elections
from auspice.pipeline.registry.models import JurisdictionSpec, Registry, load_registry

log = get_logger(__name__, _stage="registry")

DETECTED_PLATFORMS_FILE = "platforms.detected.yaml"
BOUNDARY_CACHE_DIR = "boundaries"

# Elections are materialised for a window around today. Wide enough that
# months_to_next_election is answerable for every historical decision in the corpus and for
# anything filed in the next few years.
HORIZON_BACK_YEARS = 12
HORIZON_FORWARD_YEARS = 8


class LoadReport:
    """What the load actually did. Printed by the CLI and asserted on in tests."""

    def __init__(self) -> None:
        self.jurisdictions = 0
        self.bodies = 0
        self.elections = 0
        self.sources = 0
        self.boundaries_loaded = 0
        self.boundaries_missing: list[str] = []
        self.platforms_detected = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "jurisdictions": self.jurisdictions,
            "bodies": self.bodies,
            "elections": self.elections,
            "sources": self.sources,
            "boundaries_loaded": self.boundaries_loaded,
            "boundaries_missing": self.boundaries_missing,
            "platforms_detected": self.platforms_detected,
        }


def _read_detected_platforms(registry_root: Path) -> dict[str, str]:
    """Platform detections written by `auspice registry probe`.

    Kept in a separate file so the hand authored registry stays hand authored. If the file is
    absent every jurisdiction stays ``unknown``, which is the honest default.
    """
    path = registry_root / DETECTED_PLATFORMS_FILE
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    detections = raw.get("detections", {})
    return {
        slug: str(entry["platform"])
        for slug, entry in detections.items()
        if entry.get("platform") and entry["platform"] != CivicPlatform.unknown.value
    }


def _upsert_jurisdiction(
    conn: Connection,
    spec: JurisdictionSpec,
    *,
    boundary_ewkt: str | None,
    land_area_sq_km: float | None,
    platform: str,
) -> int:
    values: dict[str, object] = {
        "slug": spec.slug,
        "name": spec.name,
        "kind": spec.kind.value,
        "country": spec.country,
        "region": spec.region,
        "admin_codes": {
            **spec.admin_codes,
            "fips": spec.fips,
            "legal_framework_source": str(spec.legal_framework_source.source),
            "legal_framework_retrieved_on": spec.legal_framework_source.retrieved_on.isoformat(),
            "target_use_classes": [u.value for u in spec.target_use_classes],
            "why_in_scope": spec.why_in_scope,
        },
        "legal_framework": spec.legal_framework.value,
        "civic_platform": platform,
        "notes": spec.notes,
        "updated_at": datetime.now(UTC),
    }
    if land_area_sq_km is not None:
        values["land_area_sq_km"] = round(land_area_sq_km, 2)

    statement = pg_insert(schema.jurisdiction).values(**values)
    update_columns = {k: statement.excluded[k] for k in values if k != "slug"}
    statement = statement.on_conflict_do_update(
        index_elements=[schema.jurisdiction.c.slug], set_=update_columns
    ).returning(schema.jurisdiction.c.id)
    jurisdiction_id = conn.execute(statement).scalar_one()

    # Geometry is set separately so the EWKT literal is cast explicitly rather than relying on
    # driver level adaptation, which is where silent SRID loss happens.
    if boundary_ewkt is not None:
        conn.execute(
            update(schema.jurisdiction)
            .where(schema.jurisdiction.c.id == jurisdiction_id)
            .values(boundary=text("ST_Multi(ST_GeomFromEWKT(:ewkt))").bindparams(ewkt=boundary_ewkt))
        )

    return int(jurisdiction_id)


def _load_bodies(conn: Connection, jurisdiction_id: int, spec: JurisdictionSpec, report: LoadReport) -> None:
    today = date.today()
    horizon_start = date(today.year - HORIZON_BACK_YEARS, 1, 1)
    horizon_end = date(today.year + HORIZON_FORWARD_YEARS, 12, 31)

    for body in spec.bodies:
        statement = pg_insert(schema.decision_body).values(
            jurisdiction_id=jurisdiction_id,
            name=body.name,
            kind=body.kind.value,
            seats=body.seats,
            quorum=body.quorum,
            vote_threshold=body.vote_threshold,
            recommendation_is_binding=body.recommendation_is_binding,
            meeting_cadence=body.meeting_cadence,
            statutory_decision_days=body.statutory_decision_days,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[schema.decision_body.c.jurisdiction_id, schema.decision_body.c.name],
            set_={
                "kind": statement.excluded.kind,
                "seats": statement.excluded.seats,
                "quorum": statement.excluded.quorum,
                "vote_threshold": statement.excluded.vote_threshold,
                "recommendation_is_binding": statement.excluded.recommendation_is_binding,
                "meeting_cadence": statement.excluded.meeting_cadence,
                "statutory_decision_days": statement.excluded.statutory_decision_days,
            },
        ).returning(schema.decision_body.c.id)
        body_id = int(conn.execute(statement).scalar_one())
        report.bodies += 1

        # Rebuild the calendar rather than merge it. The rule is the source of truth.
        conn.execute(delete(schema.election).where(schema.election.c.body_id == body_id))
        if body.election_rule is None:
            continue

        dates = derive_elections(
            anchor_year=body.election_rule.anchor_year,
            term_years=body.election_rule.term_years,
            horizon_start=horizon_start,
            horizon_end=horizon_end,
            stagger_offset_years=body.election_rule.stagger_offset_years,
            explicit_dates=body.election_rule.explicit_dates,
        )
        if not dates:
            continue

        seats_per_cycle = (
            body.seats
            if body.election_rule.stagger_offset_years is None
            # Staggered boards elect roughly half the seats each cycle. Rounding up matches
            # the usual arrangement on an odd numbered board.
            else -(-body.seats // 2)
        )
        conn.execute(
            schema.election.insert(),
            [
                {
                    "body_id": body_id,
                    "election_date": d,
                    "seats_contested": seats_per_cycle,
                    "kind": "general",
                }
                for d in dates
            ],
        )
        report.elections += len(dates)


def _load_sources(conn: Connection, jurisdiction_id: int, spec: JurisdictionSpec, platform: str, report: LoadReport) -> None:
    for source_spec in spec.sources:
        resolved_platform = (
            source_spec.platform.value
            if source_spec.platform is not CivicPlatform.unknown
            else platform
        )
        statement = pg_insert(schema.source).values(
            jurisdiction_id=jurisdiction_id,
            kind=source_spec.kind.value,
            platform=resolved_platform,
            url=str(source_spec.url),
            platform_config=source_spec.platform_config,
            refresh_hours=source_spec.refresh_hours,
            enabled=source_spec.enabled,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[
                schema.source.c.jurisdiction_id,
                schema.source.c.kind,
                schema.source.c.url,
            ],
            set_={
                "platform": statement.excluded.platform,
                "platform_config": statement.excluded.platform_config,
                "refresh_hours": statement.excluded.refresh_hours,
                "enabled": statement.excluded.enabled,
            },
        )
        conn.execute(statement)
        report.sources += 1


def load(
    conn: Connection,
    *,
    registry: Registry | None = None,
    registry_root: Path | None = None,
    fetch_boundaries: bool = True,
    refresh_boundaries: bool = False,
) -> LoadReport:
    """Load the registry. Idempotent. Call inside a transaction."""
    settings = get_settings()
    root = registry_root or settings.registry_path
    spec_registry = registry or load_registry(root / "jurisdictions.yaml")
    detected = _read_detected_platforms(root)
    report = LoadReport()

    client = httpx.Client(timeout=120.0, follow_redirects=True) if fetch_boundaries else None
    try:
        for spec in spec_registry.jurisdictions:
            platform = detected.get(spec.slug, spec.civic_platform.value)
            if spec.slug in detected:
                report.platforms_detected += 1

            boundary_ewkt: str | None = None
            land_area: float | None = None
            if fetch_boundaries and spec.fips is not None:
                try:
                    boundary = fetch_county_boundary(
                        spec.boundary_geoid,
                        cache_root=root / BOUNDARY_CACHE_DIR,
                        client=client,
                        refresh=refresh_boundaries,
                    )
                    boundary_ewkt = boundary.as_ewkt()
                    land_area = boundary.land_area_sq_km
                    report.boundaries_loaded += 1
                except Exception as exc:  # noqa: BLE001 - a missing boundary is recorded, not fatal
                    report.boundaries_missing.append(spec.slug)
                    log.warning("boundary unavailable", slug=spec.slug, error=str(exc))

            jurisdiction_id = _upsert_jurisdiction(
                conn,
                spec,
                boundary_ewkt=boundary_ewkt,
                land_area_sq_km=land_area,
                platform=platform,
            )
            report.jurisdictions += 1

            _load_bodies(conn, jurisdiction_id, spec, report)
            _load_sources(conn, jurisdiction_id, spec, platform, report)
    finally:
        if client is not None:
            client.close()

    log.info("registry loaded", **report.as_dict())
    return report


# ---------------------------------------------------------------------------
# Derived registry fields
# ---------------------------------------------------------------------------
def recompute_derived(conn: Connection) -> dict[str, dict[str, float | int | None]]:
    """Recompute ``data_depth`` and ``discretion_index`` from the decision record.

    Neither is asserted by hand. ``data_depth`` is the count of terminal decisions we hold for
    the jurisdiction, and it drives the abstention rule. ``discretion_index`` is the share of
    those decisions that turned on relief a body may lawfully refuse, which is the closest
    honest proxy for "how much of this is politics" that can be computed from the record
    rather than asserted.

    A jurisdiction with no decisions gets ``NULL`` discretion, not zero. Zero means fully by
    right, which is a strong claim, and we would be making it out of ignorance.
    """
    discretionary = sorted(r.value for r in DISCRETIONARY_RELIEF)
    all_reliefs = sorted(r.value for r in Relief)
    assert set(discretionary) <= set(all_reliefs)

    rows = conn.execute(
        text(
            """
            SELECT
                j.id,
                j.slug,
                count(a.id) FILTER (
                    WHERE a.outcome IN ('approved','approved_with_conditions','denied','withdrawn')
                ) AS terminal,
                count(a.id) FILTER (
                    WHERE a.outcome IN ('approved','approved_with_conditions','denied','withdrawn')
                      AND a.relief_sought && :discretionary
                ) AS discretionary
            FROM jurisdiction j
            LEFT JOIN application a ON a.jurisdiction_id = j.id
            GROUP BY j.id, j.slug
            ORDER BY j.slug
            """
        ).bindparams(discretionary=discretionary)
    ).all()

    summary: dict[str, dict[str, float | int | None]] = {}
    for jurisdiction_id, slug, terminal, disc in rows:
        index = round(disc / terminal, 3) if terminal else None
        conn.execute(
            update(schema.jurisdiction)
            .where(schema.jurisdiction.c.id == jurisdiction_id)
            .values(data_depth=terminal, discretion_index=index, updated_at=datetime.now(UTC))
        )
        summary[slug] = {"data_depth": terminal, "discretion_index": index}

    log.info("derived registry fields recomputed", jurisdictions=len(summary))
    return summary


def resolve_chain(conn: Connection, longitude: float, latitude: float) -> list[dict[str, object]]:
    """Answer the stage 0 question: who actually decides for this point?

    A spatial join against the boundary index, ordered from the most local body outward. This
    is the query that makes or breaks everything downstream, so it lives here rather than
    being written inline wherever it is needed.
    """
    rows = conn.execute(
        text(
            """
            SELECT
                j.id,
                j.slug,
                j.name,
                j.kind,
                j.region,
                j.legal_framework,
                j.data_depth,
                j.discretion_index,
                ST_Area(j.boundary::geography) AS area_sq_m
            FROM jurisdiction j
            WHERE j.boundary IS NOT NULL
              AND ST_Intersects(j.boundary, ST_SetSRID(ST_Point(:lon, :lat), 4326))
            ORDER BY area_sq_m ASC
            """
        ).bindparams(lon=longitude, lat=latitude)
    ).mappings().all()

    return [
        {
            "jurisdiction_id": row["id"],
            "slug": row["slug"],
            "name": row["name"],
            "kind": row["kind"],
            "region": row["region"],
            "legal_framework": row["legal_framework"],
            "data_depth": row["data_depth"],
            "discretion_index": float(row["discretion_index"]) if row["discretion_index"] is not None else None,
            # The smallest containing jurisdiction is the primary decider in every case in the
            # first twelve counties. Where that is not true the registry records it explicitly.
            "role": "primary_decider" if index == 0 else "clearance",
        }
        for index, row in enumerate(rows)
    ]


def registry_summary(conn: Connection) -> list[dict[str, object]]:
    """One row per jurisdiction, for `auspice registry status`."""
    rows = conn.execute(
        select(
            schema.jurisdiction.c.slug,
            schema.jurisdiction.c.name,
            schema.jurisdiction.c.region,
            schema.jurisdiction.c.legal_framework,
            schema.jurisdiction.c.civic_platform,
            schema.jurisdiction.c.data_depth,
            schema.jurisdiction.c.discretion_index,
            schema.jurisdiction.c.boundary.isnot(None).label("has_boundary"),
            select(func.count())
            .select_from(schema.decision_body)
            .where(schema.decision_body.c.jurisdiction_id == schema.jurisdiction.c.id)
            .scalar_subquery()
            .label("bodies"),
            select(func.count())
            .select_from(schema.election)
            .join(
                schema.decision_body,
                schema.decision_body.c.id == schema.election.c.body_id,
            )
            .where(schema.decision_body.c.jurisdiction_id == schema.jurisdiction.c.id)
            .scalar_subquery()
            .label("elections"),
        ).order_by(schema.jurisdiction.c.slug)
    ).mappings().all()
    return [dict(row) for row in rows]
