"""Registry commands: validate, load, probe, status."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
import yaml
from pydantic import ValidationError

from auspice.cli.output import console, fail, heading, note, ok, render_table
from auspice.config import get_settings
from auspice.db import transaction
from auspice.pipeline.registry import loader
from auspice.pipeline.registry.models import load_registry
from auspice.pipeline.registry.probe import probe_all

app = typer.Typer(no_args_is_help=True, help="Stage 0: who actually decides for this parcel.")


@app.command("validate")
def validate() -> None:
    """Check the registry file without touching the database."""
    settings = get_settings()
    path = settings.registry_path / "jurisdictions.yaml"
    try:
        registry = load_registry(path)
    except ValidationError as exc:
        heading("Registry is not valid")
        for error in exc.errors():
            location = ".".join(str(p) for p in error["loc"])
            console.print(f"  {location}: {error['msg']}")
        fail(f"{len(exc.errors())} problem(s) in {path}")
    except FileNotFoundError:
        fail(f"registry file not found: {path}", hint="Expected data/registry/jurisdictions.yaml")

    heading(f"Registry {registry.version}")
    note(f"{registry.beachhead}")
    console.print()

    render_table(
        [
            {
                "slug": j.slug,
                "name": j.name,
                "region": j.region,
                "fips": j.fips,
                "framework": j.legal_framework.value,
                "platform": j.civic_platform.value,
                "bodies": len(j.bodies),
                "seats": sum(b.seats for b in j.bodies),
                "elected_bodies": sum(1 for b in j.bodies if b.election_rule is not None),
            }
            for j in registry.jurisdictions
        ],
        numeric=("bodies", "seats", "elected_bodies"),
    )

    console.print()
    ok(f"{len(registry.jurisdictions)} jurisdictions, every assertion sourced")


@app.command("boundaries")
def boundaries(
    refresh: Annotated[bool, typer.Option(help="Re-fetch even if a cached copy exists")] = False,
) -> None:
    """Fetch county boundaries from the Census TIGERweb service into the local cache."""
    from auspice.pipeline.registry.boundaries import fetch_county_boundary

    settings = get_settings()
    registry = load_registry(settings.registry_path / "jurisdictions.yaml")
    cache_root = settings.registry_path / loader.BOUNDARY_CACHE_DIR

    heading("Boundaries")
    rows: list[dict[str, object]] = []
    failures = 0
    for spec in registry.jurisdictions:
        if spec.fips is None:
            continue
        try:
            boundary = fetch_county_boundary(
                spec.boundary_geoid, cache_root=cache_root, refresh=refresh
            )
            rows.append(
                {
                    "slug": spec.slug,
                    "geoid": boundary.geoid,
                    "name": boundary.name,
                    "parts": len(boundary.geometry.geoms),
                    "vertices": sum(len(p.exterior.coords) for p in boundary.geometry.geoms),
                    "land_sq_km": round(boundary.land_area_sq_km or 0.0, 1),
                }
            )
        except Exception as exc:
            failures += 1
            rows.append({"slug": spec.slug, "geoid": spec.fips, "name": f"failed: {exc}"})

    render_table(rows, numeric=("parts", "vertices", "land_sq_km"))
    console.print()
    if failures:
        fail(f"{failures} boundary fetch(es) failed", hint=f"Cache lives at {cache_root}")
    ok(f"{len(rows)} boundaries cached at {cache_root}")


@app.command("probe")
def probe(
    timeout: Annotated[float, typer.Option(help="Per request timeout in seconds")] = 30.0,
) -> None:
    """Detect which civic platform each jurisdiction runs, from its live site.

    Writes data/registry/platforms.detected.yaml. The hand authored registry is never edited by
    this command, because a machine detection and a human assertion are different kinds of
    claim and should not share a file.
    """
    settings = get_settings()
    registry = load_registry(settings.registry_path / "jurisdictions.yaml")

    heading("Civic platform detection")
    note("Section 6.1: five adapters instead of ten thousand scrapers, so knowing the")
    note("vendor for each jurisdiction is what makes the adapter count small.")
    console.print()

    results = probe_all(registry, timeout=timeout)

    render_table(
        [
            {
                "slug": slug,
                "platform": result.platform.value,
                "confidence": result.confidence,
                "evidence": result.evidence,
                "checked": result.url,
            }
            for slug, result in results.items()
        ],
        numeric=("confidence",),
    )

    path = settings.registry_path / loader.DETECTED_PLATFORMS_FILE
    payload = {
        "generated_by": "auspice registry probe",
        "detections": {
            slug: {
                "platform": result.platform.value,
                "confidence": result.confidence,
                "evidence": result.evidence,
                "url": result.url,
                "checked_at": result.checked_at.isoformat(),
            }
            for slug, result in results.items()
        },
    }
    path.write_text(
        "# Generated by `auspice registry probe`. Do not hand edit; re-run instead.\n"
        + yaml.safe_dump(payload, sort_keys=True, allow_unicode=True),
        encoding="utf-8",
    )

    identified = sum(1 for r in results.values() if r.platform.value != "unknown")
    console.print()
    ok(f"{identified} of {len(results)} identified, written to {path.name}")


@app.command("load")
def load(
    skip_boundaries: Annotated[
        bool, typer.Option(help="Load without geometry. Spatial resolution will not work.")
    ] = False,
    refresh_boundaries: Annotated[bool, typer.Option(help="Re-fetch boundaries")] = False,
) -> None:
    """Load the registry into the Permission Graph. Idempotent."""
    heading("Loading the registry")
    with transaction() as conn:
        report = loader.load(
            conn,
            fetch_boundaries=not skip_boundaries,
            refresh_boundaries=refresh_boundaries,
        )
        summary = loader.recompute_derived(conn)

    render_table(
        [{"metric": k, "value": v} for k, v in report.as_dict().items()],
        columns=("metric", "value"),
    )
    console.print()

    render_table(
        [
            {"slug": slug, "data_depth": v["data_depth"], "discretion_index": v["discretion_index"]}
            for slug, v in summary.items()
        ],
        numeric=("data_depth", "discretion_index"),
    )

    console.print()
    if report.boundaries_missing:
        note(f"boundaries missing for: {', '.join(report.boundaries_missing)}")
    ok(
        f"{report.jurisdictions} jurisdictions, {report.bodies} bodies, {report.elections} elections"
    )


@app.command("status")
def status() -> None:
    """What the graph currently holds for each jurisdiction."""
    heading("Registry status")
    with transaction() as conn:
        rows = loader.registry_summary(conn)
    if not rows:
        fail("the registry is empty", hint="Run `auspice registry load`")
    render_table(rows, numeric=("data_depth", "discretion_index", "bodies", "elections"))


@app.command("resolve")
def resolve(
    longitude: Annotated[float, typer.Argument(help="Longitude in decimal degrees, WGS84")],
    latitude: Annotated[float, typer.Argument(help="Latitude in decimal degrees, WGS84")],
) -> None:
    """Answer the stage 0 question for a point: who decides here?"""
    heading(f"Jurisdiction chain for {latitude:.5f}, {longitude:.5f}")
    with transaction() as conn:
        chain = loader.resolve_chain(conn, longitude, latitude)
    if not chain:
        note("No jurisdiction in the registry contains that point.")
        note("This is the honest answer for a site outside the twelve county beachhead.")
        raise typer.Exit(0)
    render_table(chain, numeric=("data_depth", "discretion_index"))


@app.command("recompute")
def recompute() -> None:
    """Recompute data_depth and discretion_index from the decision record."""
    heading("Recomputing derived registry fields")
    with transaction() as conn:
        summary = loader.recompute_derived(conn)
    render_table(
        [
            {"slug": slug, "data_depth": v["data_depth"], "discretion_index": v["discretion_index"]}
            for slug, v in summary.items()
        ],
        numeric=("data_depth", "discretion_index"),
    )


def _registry_path() -> Path:
    return get_settings().registry_path
