"""Vector tiles, served straight from PostGIS. Section 7.3 point 2.

The map is the product's face and MapLibre makes it free. Serving tiles with ``ST_AsMVT`` means the
geospatial data never leaves the database and there is no per view billing, no tile vendor, and no second
copy of the boundaries to keep in step with the registry.

Two things about the shape of this router.

It returns binary, so it does not go through the JSON response models the rest of the API uses. A tile is
either a valid protobuf or it is nothing, and there is no partial answer to render.

An empty tile is a 204 rather than an empty 200 body. MapLibre treats both as "nothing here", and 204 keeps
an empty tile out of the browser cache as a zero length body that later looks like a truncated response.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Response, status
from sqlalchemy import text

from app.deps import Db

router = APIRouter(prefix="/v1/tiles", tags=["tiles"])

MVT_MEDIA_TYPE = "application/vnd.mapbox-vector-tile"

# Beyond this the tiles carry no more detail than the county boundary already has, and the request count
# grows by four for every level. Twelve is well past the point where a whole county fills the screen.
MAX_ZOOM = 12

# Below this a boundary is thinner than a pixel and the browser is fetching a tile to draw nothing.
MIN_ZOOM = 3

_JURISDICTION_TILE = text(
    """
    WITH bounds AS (
        SELECT ST_TileEnvelope(:z, :x, :y) AS envelope
    ),
    features AS (
        SELECT
            j.slug,
            j.name,
            j.kind,
            j.region,
            j.legal_framework,
            j.data_depth,
            j.discretion_index,
            -- Simplify in tile coordinate space rather than in degrees. A fixed tolerance in degrees
            -- oversimplifies near the poles and undersimplifies at the equator, and the point of
            -- simplifying at all is to match the resolution the tile can actually show.
            ST_AsMVTGeom(
                ST_Transform(j.boundary, 3857),
                bounds.envelope,
                4096,
                64,
                true
            ) AS geom
        FROM jurisdiction j
        CROSS JOIN bounds
        WHERE j.boundary IS NOT NULL
          AND ST_Transform(j.boundary, 3857) && bounds.envelope
    )
    SELECT ST_AsMVT(features.*, 'jurisdictions', 4096, 'geom') AS tile
    FROM features
    WHERE geom IS NOT NULL
    """
)


@router.get(
    "/jurisdictions/{z}/{x}/{y}.mvt",
    summary="Jurisdiction boundaries as a Mapbox vector tile",
    responses={
        200: {"content": {MVT_MEDIA_TYPE: {}}, "description": "A vector tile"},
        204: {"description": "No jurisdiction intersects this tile"},
    },
    response_class=Response,
)
def jurisdiction_tile(
    conn: Db,
    z: Annotated[int, Path(ge=MIN_ZOOM, le=MAX_ZOOM)],
    x: Annotated[int, Path(ge=0)],
    y: Annotated[int, Path(ge=0)],
) -> Response:
    """One tile of county boundaries, with the registry attributes attached.

    The attributes travel with the geometry so the map can style and label without a second request per
    feature. They are the same values `/v1/public/jurisdictions` serves, and both read the same columns.
    """
    limit = 2**z
    if x >= limit or y >= limit:
        # A tile index outside the pyramid for its own zoom level is a malformed request rather than an
        # empty region, and answering 204 would hide a broken client.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"tile {x},{y} does not exist at zoom {z}, where indices run 0 to {limit - 1}",
        )

    tile = conn.execute(_JURISDICTION_TILE.bindparams(z=z, x=x, y=y)).scalar_one_or_none()

    if tile is None or len(tile) == 0:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return Response(
        content=bytes(tile),
        media_type=MVT_MEDIA_TYPE,
        headers={
            # The boundaries change when the registry changes, which is a deploy rather than a request.
            # An hour is short enough that a coverage change appears the same day and long enough that
            # panning a map does not re-query Postgres for tiles it just fetched.
            "cache-control": "public, max-age=3600",
        },
    )
