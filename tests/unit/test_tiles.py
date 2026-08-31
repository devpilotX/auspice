"""The vector tile endpoint. Section 7.3 point 2.

Serving tiles from PostGIS with ``ST_AsMVT`` means there is no tile vendor and no second copy of the
boundaries. It also means the correctness of the map depends on a binary response, which is the kind of
thing that looks fine in a browser right up until it does not.

So these tests check the bytes rather than the status code. A 200 carrying a zero length body, or a
protobuf missing its layer name, would draw an empty map and report success.

A minimal Mapbox Vector Tile decoder is included rather than a dependency. The format is four wire types
and the part that matters here is small: layer name, extent, feature count and the key and value tables.
Writing it means the test reads the tile the way MapLibre would rather than trusting that bytes of roughly
the right length are a tile.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, text

pytestmark = pytest.mark.db


# ---------------------------------------------------------------------------
# Just enough protobuf to read a vector tile
# ---------------------------------------------------------------------------
def _varint(buffer: bytes, position: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        byte = buffer[position]
        position += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, position
        shift += 7


def _fields(buffer: bytes) -> list[tuple[int, int, bytes | int]]:
    """Walk the top level fields of a protobuf message."""
    out: list[tuple[int, int, bytes | int]] = []
    position = 0
    while position < len(buffer):
        key, position = _varint(buffer, position)
        field, wire = key >> 3, key & 0x07
        if wire == 0:
            value, position = _varint(buffer, position)
            out.append((field, wire, value))
        elif wire == 2:
            length, position = _varint(buffer, position)
            out.append((field, wire, buffer[position : position + length]))
            position += length
        elif wire == 5:
            out.append((field, wire, int.from_bytes(buffer[position : position + 4], "little")))
            position += 4
        elif wire == 1:
            out.append((field, wire, int.from_bytes(buffer[position : position + 8], "little")))
            position += 8
        else:  # pragma: no cover - a tile with an unknown wire type is a broken tile
            raise AssertionError(f"unknown wire type {wire}")
    return out


class Layer:
    """One decoded layer of a vector tile."""

    def __init__(self, raw: bytes) -> None:
        self.name = ""
        self.extent = 4096
        self.version = 0
        self.keys: list[str] = []
        self.string_values: list[str] = []
        self.features = 0

        for field, _wire, value in _fields(raw):
            if field == 1 and isinstance(value, bytes):
                self.name = value.decode("utf-8")
            elif field == 2:
                self.features += 1
            elif field == 3 and isinstance(value, bytes):
                self.keys.append(value.decode("utf-8"))
            elif field == 4 and isinstance(value, bytes):
                for inner_field, _inner_wire, inner in _fields(value):
                    if inner_field == 1 and isinstance(inner, bytes):
                        self.string_values.append(inner.decode("utf-8"))
            elif field == 5 and isinstance(value, int):
                self.extent = value
            elif field == 15 and isinstance(value, int):
                self.version = value


def decode(tile: bytes) -> list[Layer]:
    return [
        Layer(value)
        for field, _wire, value in _fields(tile)
        if field == 3 and isinstance(value, bytes)
    ]


# ---------------------------------------------------------------------------
# Tiles
# ---------------------------------------------------------------------------
def tile_for(longitude: float, latitude: float, zoom: int) -> tuple[int, int]:
    """The tile index containing a coordinate, by the standard web mercator scheme."""
    import math

    n = 2**zoom
    x = int((longitude + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(math.radians(latitude))) / math.pi) / 2.0 * n)
    return x, y


# Real places inside three of the covered counties, chosen so a boundary change that broke the projection
# would move them out of frame.
NORTHERN_VIRGINIA = tile_for(-77.5, 39.0, 7)
MARICOPA = tile_for(-112.0, 33.4, 8)
OPEN_PACIFIC = tile_for(-140.0, 10.0, 7)


# Boxes rather than the real county outlines, and that keeps what these tests are for. The stated intent
# is to catch a projection mistake, a swapped x and y, or a boundary loaded with reversed coordinates, and
# every one of those moves a box out of frame exactly as it would move a county. What boxes buy is that the
# fixture creates its own geography instead of depending on a registry someone loaded earlier.
#
# A quarter of a degree each way, comfortably inside a zoom 7 tile, which spans about 2.8 degrees.
_SEEDED = (
    ("us-va-loudoun", "Loudoun County", "VA", "dillons_rule", -77.5, 39.0),
    ("us-az-maricopa", "Maricopa County", "AZ", "dillons_rule", -112.0, 33.4),
)

_INSERT_JURISDICTION = text(
    """
    INSERT INTO jurisdiction
        (slug, name, kind, region, legal_framework, data_depth, discretion_index, boundary)
    VALUES
        (:slug, :name, 'county', :region, :framework, 3, 0.500,
         ST_Multi(ST_MakeEnvelope(:x1, :y1, :x2, :y2, 4326))::geometry(MultiPolygon, 4326))
    """
)


@pytest.fixture
def client(clean_db: Connection) -> Iterator[TestClient]:
    """A client that reads the same transaction this fixture writes to, with its own geography.

    Two problems are fixed here and the second one was silent.

    The fixture used to seed nothing and rely on whatever boundaries happened to be in the database. That
    is not a test of the tile query, it is a test of somebody's working copy.

    Worse, ``app.deps.get_connection`` opens its own connection through ``transaction()``, which uses the
    non test engine. Locally ``AUSPICE_DATABASE_URL`` points at ``auspice`` and
    ``AUSPICE_TEST_DATABASE_URL`` at ``auspice_test``, so the endpoint read a different database from the
    one the fixtures write to. These tests passed because ``auspice`` had twelve counties loaded by hand.
    Measured on 2026-08-31: ``auspice`` held 12 jurisdictions with boundaries and ``auspice_test`` held 0,
    and CI points both variables at ``auspice_test``, so the assertions here could not have been satisfied
    there. Green locally, unsatisfiable in CI, and testing production data in both readings.
    """
    from app.deps import get_connection
    from app.main import app

    for slug, name, region, framework, longitude, latitude in _SEEDED:
        clean_db.execute(
            _INSERT_JURISDICTION.bindparams(
                slug=slug,
                name=name,
                region=region,
                framework=framework,
                x1=longitude - 0.25,
                y1=latitude - 0.25,
                x2=longitude + 0.25,
                y2=latitude + 0.25,
            )
        )

    # A generator function, not a lambda returning an iterator: FastAPI injects the yielded value for the
    # former and the iterator itself for the latter.
    def _use_the_test_connection() -> Iterator[Connection]:
        yield clean_db

    app.dependency_overrides[get_connection] = _use_the_test_connection
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_connection, None)


class TestTheTileIsARealTile:
    def test_a_covered_region_returns_a_decodable_tile(self, client: TestClient) -> None:
        x, y = NORTHERN_VIRGINIA
        response = client.get(f"/v1/tiles/jurisdictions/7/{x}/{y}.mvt")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/vnd.mapbox-vector-tile"
        assert len(response.content) > 0

        layers = decode(response.content)
        assert len(layers) == 1
        layer = layers[0]
        assert layer.name == "jurisdictions"
        assert layer.extent == 4096
        assert layer.features >= 1

    def test_the_attributes_the_map_styles_on_are_present(self, client: TestClient) -> None:
        """A tile with geometry and no attributes draws grey shapes with no labels."""
        x, y = NORTHERN_VIRGINIA
        layer = decode(client.get(f"/v1/tiles/jurisdictions/7/{x}/{y}.mvt").content)[0]

        for key in ("slug", "name", "kind", "region", "legal_framework", "data_depth"):
            assert key in layer.keys, f"{key} is missing from the tile, so the map cannot use it"

    def test_the_expected_counties_are_in_the_expected_tiles(self, client: TestClient) -> None:
        """Geography, not plumbing.

        A projection mistake, a swapped x and y, or a boundary loaded with reversed coordinates all return a
        perfectly valid tile of the wrong part of the world. Naming the county that has to be inside a
        specific tile is what catches that.
        """
        x, y = NORTHERN_VIRGINIA
        virginia = decode(client.get(f"/v1/tiles/jurisdictions/7/{x}/{y}.mvt").content)[0]
        assert "us-va-loudoun" in virginia.string_values

        x, y = MARICOPA
        arizona = decode(client.get(f"/v1/tiles/jurisdictions/8/{x}/{y}.mvt").content)[0]
        assert "us-az-maricopa" in arizona.string_values
        # And the counties three time zones away are not in it.
        assert "us-va-loudoun" not in arizona.string_values

    def test_an_empty_region_is_204_not_an_empty_200(self, client: TestClient) -> None:
        """MapLibre reads both as nothing there. A zero length 200 caches as a body that later looks
        truncated, which is a bug that only appears after the cache is warm."""
        x, y = OPEN_PACIFIC
        response = client.get(f"/v1/tiles/jurisdictions/7/{x}/{y}.mvt")
        assert response.status_code == 204
        assert response.content == b""

    def test_the_tile_is_cacheable(self, client: TestClient) -> None:
        x, y = NORTHERN_VIRGINIA
        response = client.get(f"/v1/tiles/jurisdictions/7/{x}/{y}.mvt")
        assert "max-age" in response.headers.get("cache-control", "")


class TestMalformedRequestsAreRefused:
    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("/v1/tiles/jurisdictions/1/0/0.mvt", 422),
            ("/v1/tiles/jurisdictions/20/0/0.mvt", 422),
            ("/v1/tiles/jurisdictions/7/-1/0.mvt", 422),
            ("/v1/tiles/jurisdictions/7/0/-1.mvt", 422),
        ],
    )
    def test_out_of_bounds_parameters(self, client: TestClient, path: str, expected: int) -> None:
        assert client.get(path).status_code == expected

    def test_an_index_outside_its_own_zoom_pyramid_is_a_bad_request(
        self, client: TestClient
    ) -> None:
        """Not a 204. At zoom 7 the indices run 0 to 127, so 9999 is a broken client rather than empty sea,
        and answering "nothing here" would hide the fault."""
        response = client.get("/v1/tiles/jurisdictions/7/9999/0.mvt")
        assert response.status_code == 400
        assert "does not exist at zoom 7" in response.json()["detail"]


class TestTheTileReadsTheSameRowsAsTheApi:
    def test_every_jurisdiction_with_a_boundary_can_appear(self, db: Connection) -> None:
        """The tile query and the coverage list must not disagree about what exists.

        Checked against the database rather than by comparing two endpoints, because both endpoints reading
        the same wrong thing would agree with each other.
        """
        with_boundary = db.execute(
            text("SELECT count(*) FROM jurisdiction WHERE boundary IS NOT NULL")
        ).scalar_one()
        total = db.execute(text("SELECT count(*) FROM jurisdiction")).scalar_one()

        assert with_boundary == total, (
            f"{total - with_boundary} jurisdictions have no boundary and would be invisible on the map "
            "while still appearing in the coverage table"
        )

    def test_the_geometry_is_valid(self, db: Connection) -> None:
        """ST_AsMVTGeom on an invalid polygon can return null and drop a county silently."""
        invalid = db.execute(
            text(
                "SELECT slug FROM jurisdiction "
                "WHERE boundary IS NOT NULL AND NOT ST_IsValid(boundary)"
            )
        ).all()
        assert invalid == [], f"invalid geometry would drop these from the map: {invalid}"
