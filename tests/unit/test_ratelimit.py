"""The rate limiter.

Every unauthenticated endpoint does real work: verifying the ledger, a spatial join, an ST_AsMVT over
county polygons. None was limited, so one client in a loop could hold the connection pool open and queue
every other request behind it.

These tests drive the bucket with an injected clock rather than by sleeping, because a test that sleeps to
prove a rate limit is slow and flaky, and one that cannot control time cannot test refill at all.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.ratelimit import DEFAULT_LIMIT, EXEMPT, LIMITS, Limit, RateLimiter, limit_for


class TestTheBucket:
    def test_a_burst_is_allowed_then_refused(self) -> None:
        limiter = RateLimiter()
        limit = Limit(per_second=1.0, burst=3)

        assert [limiter.check("k", limit, now=0.0) for _ in range(3)] == [None, None, None]
        refused = limiter.check("k", limit, now=0.0)
        assert refused is not None
        assert refused > 0

    def test_it_refills_at_the_stated_rate(self) -> None:
        limiter = RateLimiter()
        limit = Limit(per_second=2.0, burst=2)

        limiter.check("k", limit, now=0.0)
        limiter.check("k", limit, now=0.0)
        assert limiter.check("k", limit, now=0.0) is not None

        # Half a second at two per second is exactly one token.
        assert limiter.check("k", limit, now=0.5) is None
        assert limiter.check("k", limit, now=0.5) is not None

    def test_it_never_holds_more_than_its_burst(self) -> None:
        """An idle client must not accumulate an unlimited allowance and then spend it at once."""
        limiter = RateLimiter()
        limit = Limit(per_second=10.0, burst=4)

        # Idle for an hour.
        allowed = sum(1 for _ in range(100) if limiter.check("k", limit, now=3600.0) is None)
        assert allowed == 4

    def test_keys_do_not_share_an_allowance(self) -> None:
        limiter = RateLimiter()
        limit = Limit(per_second=1.0, burst=1)

        assert limiter.check("a", limit, now=0.0) is None
        assert limiter.check("b", limit, now=0.0) is None
        assert limiter.check("a", limit, now=0.0) is not None

    def test_the_wait_it_reports_is_long_enough(self) -> None:
        limiter = RateLimiter()
        limit = Limit(per_second=4.0, burst=1)

        assert limiter.check("k", limit, now=0.0) is None
        wait = limiter.check("k", limit, now=0.0)
        assert wait is not None
        # Waiting exactly what it said must be enough, or a well behaved client still gets refused.
        assert limiter.check("k", limit, now=wait) is None

    def test_idle_buckets_are_swept_so_the_map_cannot_grow_forever(self) -> None:
        """An unbounded dictionary keyed by client address is itself a denial of service."""
        limiter = RateLimiter(sweep_every_seconds=1.0, idle_seconds=10.0)
        limit = Limit(per_second=1.0, burst=1)

        for index in range(50):
            limiter.check(f"ip:{index}", limit, now=0.0)
        assert len(limiter.buckets) == 50

        # Long enough after that every one of them is idle.
        limiter.check("ip:new", limit, now=100.0)
        assert len(limiter.buckets) == 1

    def test_a_limit_must_be_sane(self) -> None:
        for bad in [(0.0, 5), (-1.0, 5), (1.0, 0)]:
            with pytest.raises(ValueError, match="positive rate and a burst"):
                Limit(per_second=bad[0], burst=bad[1])


class TestTheLimitsChosen:
    @pytest.mark.parametrize(
        ("path", "expected_prefix"),
        [
            ("/v1/tiles/jurisdictions/7/36/48.mvt", "/v1/tiles/"),
            ("/v1/score", "/v1/score"),
            ("/v1/score/scr_abc", "/v1/score"),
            ("/v1/portfolio", "/v1/portfolio"),
            ("/v1/public/accuracy", "/v1/public/"),
        ],
    )
    def test_each_path_gets_its_intended_limit(self, path: str, expected_prefix: str) -> None:
        expected = dict(LIMITS)[expected_prefix]
        assert limit_for(path) == expected

    def test_an_unknown_path_still_gets_a_limit(self) -> None:
        assert limit_for("/v1/something/new") == DEFAULT_LIMIT

    def test_a_map_can_load_a_screen_of_tiles_in_one_burst(self) -> None:
        """A limit that breaks the map would be removed within a week, so it has to allow real behaviour.

        Panning at zoom 7 asks for tens of tiles at once. Forty covers a full screen at any zoom served.
        """
        limiter = RateLimiter()
        tiles = limit_for("/v1/tiles/jurisdictions/7/36/48.mvt")
        allowed = sum(1 for _ in range(40) if limiter.check("ip:map", tiles, now=0.0) is None)
        assert allowed == 40

    def test_scoring_is_tighter_than_tiles(self) -> None:
        assert limit_for("/v1/score").per_second < limit_for("/v1/tiles/x").per_second

    def test_health_is_never_limited(self) -> None:
        """A health check that can be throttled reports an outage during a traffic spike."""
        assert "/healthz" in EXEMPT


class TestThroughTheApp:
    """Exercised through api_client, not a bare TestClient.

    /v1/public/freshness reads the database, so a bare client would open its own connection to
    AUSPICE_DATABASE_URL and read a different database from the one the fixtures write to. The autouse
    guard in conftest refuses that now, which is how these two tests found their way here.
    """

    def test_a_flood_is_refused_with_a_retry_after(self, api_client: TestClient) -> None:
        # Well past the burst for a public path.
        statuses = [api_client.get("/v1/public/freshness").status_code for _ in range(60)]
        assert 429 in statuses, "a public endpoint accepted 60 requests in a burst"

        first_refusal = statuses.index(429)
        assert first_refusal >= 20, "the burst allowance was smaller than advertised"

        response = api_client.get("/v1/public/freshness")
        if response.status_code == 429:
            assert "Retry-After" in response.headers
            assert int(response.headers["Retry-After"]) >= 1
            assert "Too many requests" in response.json()["detail"]

    def test_health_survives_a_flood(self, api_client: TestClient) -> None:
        for _ in range(80):
            api_client.get("/v1/public/freshness")
        assert api_client.get("/healthz").status_code == 200

    def test_the_refusal_names_the_limit_it_applied(self, api_client: TestClient) -> None:
        from app.ratelimit import limit_for, refusal

        body, headers = refusal("/v1/tiles/jurisdictions/7/36/48.mvt", 3)
        limit = limit_for("/v1/tiles/jurisdictions/7/36/48.mvt")
        assert str(limit.burst) in body["detail"]
        assert headers["Retry-After"] == "3"
