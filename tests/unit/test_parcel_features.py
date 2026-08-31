"""The two features that could not fire.

`setback_compliance_margin_ft` and `distance_to_residential_m` were described in the feature dictionary,
carried notes saying they needed parcel geometry, and were passed `None` as a hardcoded literal at their
call sites in `_build`. So loading parcel geometry would not have populated them. They were dead code
wearing a documentation note about missing data.

Both now come from one PostGIS distance: the metres from the application's parcel to the nearest
residentially zoned parcel, as it stood on the as-of date. That is the quantity a data centre setback
ordinance regulates, which is why one number answers both.

What is tested here, in order of how badly it would hurt to get wrong.

**Leakage.** Parcels are bi-temporal because they split, merge and get renumbered. A field subdivided
into house lots in 2025 must not make a 2023 site look adjacent to housing it was not adjacent to. This
is the same class of defect as the leakage test on the history features and it is the reason the
predicate is on both sides of the join.

**Unknown is not far.** A missing parcel, a parcel with no valid geometry, and neighbours with no zoning
string all mean the distance is unknown. Reporting a large number for any of them would tell the model
the site is comfortably isolated on the strength of missing data.

**The zoning match is narrow.** A false positive invents a constraint that does not exist. "AR"
agricultural and "MR" mineral reserve must not read as residential.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import Connection, text

from auspice.pipeline.features import build_for_application
from auspice.pipeline.features.builder import METRES_TO_FEET, RESIDENTIAL_ZONING_PATTERN
from tests.conftest import requires_db

AS_OF = date(2024, 6, 1)

# Two points about 1.1 km apart in northern Virginia. Chosen over a synthetic unit square because the
# distance is computed on the ellipsoid, so a plausible latitude is what makes the number meaningful.
SUBJECT_LON, SUBJECT_LAT = -77.500, 39.100
NEIGHBOUR_LON, NEIGHBOUR_LAT = -77.487, 39.100


def _square(longitude: float, latitude: float, *, size: float = 0.002) -> str:
    """A small MULTIPOLYGON around a point, as WKT."""
    half = size / 2
    ring = [
        (longitude - half, latitude - half),
        (longitude + half, latitude - half),
        (longitude + half, latitude + half),
        (longitude - half, latitude + half),
        (longitude - half, latitude - half),
    ]
    coordinates = ", ".join(f"{x} {y}" for x, y in ring)
    return f"MULTIPOLYGON((({coordinates})))"


def _seed(conn: Connection) -> tuple[int, int]:
    jurisdiction_id = int(
        conn.execute(
            text(
                """
                INSERT INTO jurisdiction (slug, name, kind, country, region, legal_framework,
                                          discretion_index, data_depth)
                VALUES ('us-va-parcel', 'Parcel County', 'county', 'US', 'VA', 'dillons_rule',
                        0.6, 0)
                RETURNING id
                """
            )
        ).scalar_one()
    )
    body_id = int(
        conn.execute(
            text(
                """
                INSERT INTO decision_body (jurisdiction_id, name, kind, seats, quorum)
                VALUES (:jid, 'Board of Supervisors', 'board_of_supervisors', 9, 5)
                RETURNING id
                """
            ).bindparams(jid=jurisdiction_id)
        ).scalar_one()
    )
    return jurisdiction_id, body_id


def _parcel(
    conn: Connection,
    *,
    jurisdiction_id: int,
    longitude: float,
    latitude: float,
    zoning: str | None,
    external_id: str,
    valid_from: date = date(2020, 1, 1),
    valid_to: date | None = None,
) -> int:
    return int(
        conn.execute(
            text(
                """
                INSERT INTO parcel (jurisdiction_id, external_id, geom, current_zoning,
                                    valid_from, valid_to)
                VALUES (:jid, :ext, ST_GeomFromText(:wkt, 4326), :zoning, :vfrom, :vto)
                RETURNING id
                """
            ).bindparams(
                jid=jurisdiction_id,
                ext=external_id,
                wkt=_square(longitude, latitude),
                zoning=zoning,
                vfrom=valid_from,
                vto=valid_to,
            )
        ).scalar_one()
    )


def _application(
    conn: Connection, *, jurisdiction_id: int, body_id: int, parcel_id: int | None
) -> int:
    return int(
        conn.execute(
            text(
                """
                INSERT INTO application (
                    jurisdiction_id, body_id, parcel_id, external_id, use_class, relief_sought,
                    filed_on, outcome, censored, label_source
                ) VALUES (
                    :jid, :bid, :pid, 'REZ-1', 'data_center_hyperscale', ARRAY['rezoning'],
                    :filed, 'pending', true, 'hand_labelled'
                ) RETURNING id
                """
            ).bindparams(jid=jurisdiction_id, bid=body_id, pid=parcel_id, filed=date(2024, 1, 5))
        ).scalar_one()
    )


@requires_db
class TestDistanceToResidential:
    def test_the_feature_now_has_a_value(self, clean_db: Connection) -> None:
        """The whole point. Before this it was None regardless of what the database held."""
        jurisdiction_id, body_id = _seed(clean_db)
        subject = _parcel(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            longitude=SUBJECT_LON,
            latitude=SUBJECT_LAT,
            zoning="I-2 Heavy Industrial",
            external_id="SUBJECT",
        )
        _parcel(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            longitude=NEIGHBOUR_LON,
            latitude=NEIGHBOUR_LAT,
            zoning="R-2 Single Family Residential",
            external_id="HOUSES",
        )
        application_id = _application(
            clean_db, jurisdiction_id=jurisdiction_id, body_id=body_id, parcel_id=subject
        )

        row = build_for_application(clean_db, application_id, as_of=AS_OF)
        distance = row.values["distance_to_residential_m"]
        assert distance is not None, "the feature must now populate from geometry"
        # Roughly 1.1 km between the two squares, minus their half widths.
        assert 800 < float(distance) < 1400, distance
        assert "distance_to_residential_m" not in row.missing

    def test_an_abutting_residential_parcel_gives_zero_rather_than_nothing(
        self, clean_db: Connection
    ) -> None:
        """Zero separation is the strongest form of this signal, not a missing value."""
        jurisdiction_id, body_id = _seed(clean_db)
        subject = _parcel(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            longitude=SUBJECT_LON,
            latitude=SUBJECT_LAT,
            zoning="I-2",
            external_id="SUBJECT",
        )
        _parcel(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            longitude=SUBJECT_LON,
            latitude=SUBJECT_LAT,
            zoning="R-1",
            external_id="OVERLAPS",
        )
        application_id = _application(
            clean_db, jurisdiction_id=jurisdiction_id, body_id=body_id, parcel_id=subject
        )
        row = build_for_application(clean_db, application_id, as_of=AS_OF)
        assert row.values["distance_to_residential_m"] == 0.0

    def test_no_parcel_means_unknown_rather_than_far(self, clean_db: Connection) -> None:
        jurisdiction_id, body_id = _seed(clean_db)
        application_id = _application(
            clean_db, jurisdiction_id=jurisdiction_id, body_id=body_id, parcel_id=None
        )
        row = build_for_application(clean_db, application_id, as_of=AS_OF)
        assert row.values["distance_to_residential_m"] is None
        assert "distance_to_residential_m" in row.missing

    def test_neighbours_with_no_zoning_string_mean_unknown(self, clean_db: Connection) -> None:
        """A county whose assessor publishes no zoning cannot be said to have distant housing."""
        jurisdiction_id, body_id = _seed(clean_db)
        subject = _parcel(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            longitude=SUBJECT_LON,
            latitude=SUBJECT_LAT,
            zoning="I-2",
            external_id="SUBJECT",
        )
        _parcel(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            longitude=NEIGHBOUR_LON,
            latitude=NEIGHBOUR_LAT,
            zoning=None,
            external_id="UNKNOWN-ZONING",
        )
        application_id = _application(
            clean_db, jurisdiction_id=jurisdiction_id, body_id=body_id, parcel_id=subject
        )
        row = build_for_application(clean_db, application_id, as_of=AS_OF)
        assert row.values["distance_to_residential_m"] is None


@requires_db
class TestNoGeometryLeakage:
    def test_a_subdivision_after_the_as_of_date_cannot_move_the_feature(
        self, clean_db: Connection
    ) -> None:
        """The defect this predicate exists to prevent.

        A field beside the site is subdivided into house lots in 2025. A score computed as of 2024 must
        not see them, or the backtest is scoring against a world that did not exist yet.
        """
        jurisdiction_id, body_id = _seed(clean_db)
        subject = _parcel(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            longitude=SUBJECT_LON,
            latitude=SUBJECT_LAT,
            zoning="I-2",
            external_id="SUBJECT",
        )
        _parcel(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            longitude=NEIGHBOUR_LON,
            latitude=NEIGHBOUR_LAT,
            zoning="R-2",
            external_id="FUTURE-HOUSES",
            valid_from=date(2025, 3, 1),
        )
        application_id = _application(
            clean_db, jurisdiction_id=jurisdiction_id, body_id=body_id, parcel_id=subject
        )

        before = build_for_application(clean_db, application_id, as_of=AS_OF)
        assert before.values["distance_to_residential_m"] is None, (
            "a 2025 subdivision must be invisible to a 2024 as-of date"
        )

        after = build_for_application(clean_db, application_id, as_of=date(2025, 6, 1))
        assert after.values["distance_to_residential_m"] is not None

    def test_a_retired_parcel_is_invisible_after_its_validity_ends(
        self, clean_db: Connection
    ) -> None:
        jurisdiction_id, body_id = _seed(clean_db)
        subject = _parcel(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            longitude=SUBJECT_LON,
            latitude=SUBJECT_LAT,
            zoning="I-2",
            external_id="SUBJECT",
        )
        _parcel(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            longitude=NEIGHBOUR_LON,
            latitude=NEIGHBOUR_LAT,
            zoning="R-2",
            external_id="MERGED-AWAY",
            valid_to=date(2024, 1, 1),
        )
        application_id = _application(
            clean_db, jurisdiction_id=jurisdiction_id, body_id=body_id, parcel_id=subject
        )
        row = build_for_application(clean_db, application_id, as_of=AS_OF)
        assert row.values["distance_to_residential_m"] is None

    def test_a_parcel_in_another_county_does_not_count(self, clean_db: Connection) -> None:
        """A distance across a jurisdiction boundary is not a constraint this board enforces."""
        jurisdiction_id, body_id = _seed(clean_db)
        other = int(
            clean_db.execute(
                text(
                    """
                    INSERT INTO jurisdiction (slug, name, kind, country, region, legal_framework)
                    VALUES ('us-va-other', 'Other County', 'county', 'US', 'VA', 'dillons_rule')
                    RETURNING id
                    """
                )
            ).scalar_one()
        )
        subject = _parcel(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            longitude=SUBJECT_LON,
            latitude=SUBJECT_LAT,
            zoning="I-2",
            external_id="SUBJECT",
        )
        _parcel(
            clean_db,
            jurisdiction_id=other,
            longitude=NEIGHBOUR_LON,
            latitude=NEIGHBOUR_LAT,
            zoning="R-2",
            external_id="ACROSS-THE-LINE",
        )
        application_id = _application(
            clean_db, jurisdiction_id=jurisdiction_id, body_id=body_id, parcel_id=subject
        )
        row = build_for_application(clean_db, application_id, as_of=AS_OF)
        assert row.values["distance_to_residential_m"] is None


@requires_db
class TestSetbackMargin:
    def test_the_margin_is_the_distance_in_feet_minus_the_ordinance(
        self, clean_db: Connection
    ) -> None:
        """The second feature that could not fire. It needs both the geometry and an instrument."""
        jurisdiction_id, body_id = _seed(clean_db)
        clean_db.execute(
            text(
                """
                INSERT INTO instrument (jurisdiction_id, kind, title, adopted_on, effective_on,
                                        applies_to_use_classes, restrictions)
                VALUES (:jid, 'zoning_ordinance', 'Data centre setback', :adopted, :adopted,
                        ARRAY['data_center_hyperscale'], '{"setback_ft": 500}'::jsonb)
                """
            ).bindparams(jid=jurisdiction_id, adopted=date(2023, 1, 1))
        )
        subject = _parcel(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            longitude=SUBJECT_LON,
            latitude=SUBJECT_LAT,
            zoning="I-2",
            external_id="SUBJECT",
        )
        _parcel(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            longitude=NEIGHBOUR_LON,
            latitude=NEIGHBOUR_LAT,
            zoning="R-2",
            external_id="HOUSES",
        )
        application_id = _application(
            clean_db, jurisdiction_id=jurisdiction_id, body_id=body_id, parcel_id=subject
        )

        row = build_for_application(clean_db, application_id, as_of=AS_OF)
        distance_m = row.values["distance_to_residential_m"]
        margin = row.values["setback_compliance_margin_ft"]
        assert distance_m is not None
        assert margin is not None
        assert float(margin) == pytest.approx(float(distance_m) * METRES_TO_FEET - 500, abs=0.01)
        assert float(margin) > 0, "a kilometre of separation comfortably clears a 500 foot setback"

    def test_no_ordinance_means_unknown_even_with_geometry(self, clean_db: Connection) -> None:
        """A margin against no requirement is not zero, it is undefined."""
        jurisdiction_id, body_id = _seed(clean_db)
        subject = _parcel(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            longitude=SUBJECT_LON,
            latitude=SUBJECT_LAT,
            zoning="I-2",
            external_id="SUBJECT",
        )
        _parcel(
            clean_db,
            jurisdiction_id=jurisdiction_id,
            longitude=NEIGHBOUR_LON,
            latitude=NEIGHBOUR_LAT,
            zoning="R-2",
            external_id="HOUSES",
        )
        application_id = _application(
            clean_db, jurisdiction_id=jurisdiction_id, body_id=body_id, parcel_id=subject
        )
        row = build_for_application(clean_db, application_id, as_of=AS_OF)
        assert row.values["distance_to_residential_m"] is not None
        assert row.values["setback_compliance_margin_ft"] is None


@requires_db
class TestZoningMatching:
    """A false positive invents a constraint that does not exist."""

    @pytest.mark.parametrize(
        "zoning",
        [
            "R-1",
            "R-2 Single Family",
            "RR Rural Residential",
            "RSF",
            "RMF-12",
            "SFR",
            "PRD Planned Residential",
            "Residential",
            "residential",
        ],
    )
    def test_residential_strings_match(self, clean_db: Connection, zoning: str) -> None:
        assert self._distance(clean_db, zoning) is not None, (
            f"{zoning!r} should read as residential"
        )

    @pytest.mark.parametrize(
        "zoning",
        [
            "AR Agricultural Reserve",
            "MR Mineral Reserve",
            "I-2 Heavy Industrial",
            "C-1 Commercial",
            "PDIP Planned Development Industrial Park",
            "AG",
            "M-1",
            "OP Office Park",
        ],
    )
    def test_non_residential_strings_do_not_match(self, clean_db: Connection, zoning: str) -> None:
        assert self._distance(clean_db, zoning) is None, f"{zoning!r} must not read as residential"

    @staticmethod
    def _distance(conn: Connection, neighbour_zoning: str) -> float | None:
        jurisdiction_id, body_id = _seed(conn)
        subject = _parcel(
            conn,
            jurisdiction_id=jurisdiction_id,
            longitude=SUBJECT_LON,
            latitude=SUBJECT_LAT,
            zoning="I-2",
            external_id="SUBJECT",
        )
        _parcel(
            conn,
            jurisdiction_id=jurisdiction_id,
            longitude=NEIGHBOUR_LON,
            latitude=NEIGHBOUR_LAT,
            zoning=neighbour_zoning,
            external_id="NEIGHBOUR",
        )
        application_id = _application(
            conn, jurisdiction_id=jurisdiction_id, body_id=body_id, parcel_id=subject
        )
        value = build_for_application(conn, application_id, as_of=AS_OF).values[
            "distance_to_residential_m"
        ]
        return float(value) if value is not None else None

    def test_the_pattern_is_anchored_on_word_boundaries(self) -> None:
        """Asserted directly, because the parametrised cases above are easy to extend and easy to
        under-cover, and the anchoring is the part that makes them pass."""
        assert "^|[^a-z]" in RESIDENTIAL_ZONING_PATTERN
