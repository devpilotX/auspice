"""Boundary geometry, fetched rather than typed.

The registry file carries no polygons. A hand entered boundary has no provenance, cannot be
checked, and a single transposed digit produces a spatial join that returns nothing, which
looks exactly like a county with no decisions.

So boundaries come from the Census Bureau's TIGERweb service, keyed on the FIPS code that is
already in the registry. The response is cached to disk under ``data/registry/boundaries/`` so
a re-run costs one file read, and the cache file is the artefact a reviewer can inspect.

TIGERweb is an ArcGIS REST service. Layer 1 of the State_County map service is the county
layer. The service returns GeoJSON directly, which avoids a conversion step and the errors
that come with one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from shapely.geometry import MultiPolygon, shape
from shapely.geometry.base import BaseGeometry

from auspice.errors import FetchError
from auspice.logging import get_logger

log = get_logger(__name__, _stage="registry")

TIGERWEB_COUNTY_URL = (
    "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/1/query"
)
TIGERWEB_PLACE_URL = (
    "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Places_CouSub_ConCity_SubMCD"
    "/MapServer/0/query"
)

# WGS84. Everything in the graph is 4326 so no reprojection happens anywhere.
TARGET_SRID = 4326


@dataclass(frozen=True, slots=True)
class Boundary:
    """A fetched boundary with the provenance needed to defend it."""

    geoid: str
    name: str
    geometry: MultiPolygon
    land_area_sq_m: int | None
    water_area_sq_m: int | None
    source_url: str
    fetched_at: datetime

    @property
    def land_area_sq_km(self) -> float | None:
        if self.land_area_sq_m is None:
            return None
        return self.land_area_sq_m / 1_000_000

    def as_ewkt(self) -> str:
        """SRID prefixed WKT, which is what PostGIS accepts directly."""
        return f"SRID={TARGET_SRID};{self.geometry.wkt}"


def _to_multipolygon(geometry: BaseGeometry) -> MultiPolygon:
    """Coerce to MultiPolygon.

    The schema declares MULTIPOLYGON because some counties are genuinely multi part, and a
    column that accepts either type makes every downstream query defensive for no reason.
    """
    if isinstance(geometry, MultiPolygon):
        return geometry
    if geometry.geom_type == "Polygon":
        return MultiPolygon([geometry])
    raise ValueError(f"expected a polygonal geometry, got {geometry.geom_type}")


def cache_path(root: Path, geoid: str) -> Path:
    return root / f"{geoid}.geojson"


def load_cached(root: Path, geoid: str) -> Boundary | None:
    path = cache_path(root, geoid)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return _boundary_from_feature(
        payload["features"][0],
        source_url=payload["_auspice"]["source_url"],
        fetched_at=datetime.fromisoformat(payload["_auspice"]["fetched_at"]),
    )


def _boundary_from_feature(
    feature: dict[str, Any], *, source_url: str, fetched_at: datetime
) -> Boundary:
    props = feature["properties"]
    geometry = _to_multipolygon(shape(feature["geometry"]))
    if not geometry.is_valid:
        # Census polygons occasionally self touch at a shared vertex. buffer(0) is the
        # standard repair and it does not move any vertex that was already fine.
        geometry = _to_multipolygon(geometry.buffer(0))
    return Boundary(
        geoid=str(props["GEOID"]),
        name=str(props.get("BASENAME") or props.get("NAME") or ""),
        geometry=geometry,
        land_area_sq_m=int(props["AREALAND"]) if props.get("AREALAND") is not None else None,
        water_area_sq_m=int(props["AREAWATER"]) if props.get("AREAWATER") is not None else None,
        source_url=source_url,
        fetched_at=fetched_at,
    )


def fetch_county_boundary(
    geoid: str,
    *,
    cache_root: Path,
    client: httpx.Client | None = None,
    refresh: bool = False,
) -> Boundary:
    """Fetch one county boundary, using the on disk cache unless ``refresh`` is set."""
    if not refresh:
        cached = load_cached(cache_root, geoid)
        if cached is not None:
            log.debug("boundary cache hit", geoid=geoid)
            return cached

    params = {
        "where": f"GEOID='{geoid}'",
        "outFields": "GEOID,NAME,BASENAME,STATE,COUNTY,AREALAND,AREAWATER,INTPTLAT,INTPTLON",
        "returnGeometry": "true",
        "outSR": str(TARGET_SRID),
        "f": "geojson",
    }

    owns_client = client is None
    active = client or httpx.Client(timeout=120.0, follow_redirects=True)
    try:
        response = active.get(TIGERWEB_COUNTY_URL, params=params)
        if response.status_code != 200:
            raise FetchError(
                f"TIGERweb returned {response.status_code} for GEOID {geoid}",
                url=str(response.request.url),
                status_code=response.status_code,
            )
        payload = response.json()
    finally:
        if owns_client:
            active.close()

    features = payload.get("features") or []
    if not features:
        raise FetchError(
            f"TIGERweb has no county with GEOID {geoid}. Check the FIPS code in the registry.",
            url=TIGERWEB_COUNTY_URL,
        )
    if len(features) > 1:
        raise FetchError(
            f"TIGERweb returned {len(features)} features for GEOID {geoid}, expected exactly one",
            url=TIGERWEB_COUNTY_URL,
        )

    fetched_at = datetime.now(UTC)
    source_url = str(response.request.url)

    cache_root.mkdir(parents=True, exist_ok=True)
    payload["_auspice"] = {
        "source_url": source_url,
        "fetched_at": fetched_at.isoformat(),
        "service": "Census TIGERweb State_County layer 1",
    }
    cache_path(cache_root, geoid).write_text(json.dumps(payload), encoding="utf-8")

    boundary = _boundary_from_feature(features[0], source_url=source_url, fetched_at=fetched_at)
    log.info(
        "boundary fetched",
        geoid=geoid,
        name=boundary.name,
        parts=len(boundary.geometry.geoms),
        land_sq_km=round(boundary.land_area_sq_km or 0, 1),
    )
    return boundary
