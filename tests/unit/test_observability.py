"""Observability, and the reason it comes before an error tracker.

Audit finding P2-3 was "no error tracking, no uptime metrics, no automated or tested backups". Before
this an unhandled exception produced a traceback on stderr, a 500 with no body a caller could act on,
and nothing to join the two. A customer reporting "it errored at about two o'clock" could not be
matched to a log line, and two simultaneous failures were indistinguishable.

A third party tracker does not fix that. It helps triage once an identifier exists. So the tests here
are about the identifier and about the metrics endpoint being fail closed, not about Sentry, which is
off unless a DSN is set and makes no network call when it is not.

The metrics endpoint tests matter more than they look. An unauthenticated metrics endpoint publishes
request volumes, error rates and model identity, and this service already has three unauthenticated
endpoints whose cost had to be bounded by hand after the audit. So the route is not registered at all
without a token, and it answers 404 rather than 401 to a wrong one.
"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import observability
from app.observability import REQUEST_ID_HEADER, Metrics, new_request_id


class TestRequestIds:
    def test_an_id_is_minted_when_the_caller_supplies_none(self) -> None:
        first, second = new_request_id(), new_request_id()
        assert len(first) == 32
        assert first != second

    def test_a_callers_id_is_reused_so_traces_can_be_joined(self) -> None:
        assert new_request_id("abc123def456") == "abc123def456"

    def test_an_id_with_a_newline_cannot_forge_a_log_line(self) -> None:
        """The header lands in a log line and in a response body, so it is filtered, not trusted."""
        cleaned = new_request_id("abcdefgh\nlevel=error event=fake")
        assert "\n" not in cleaned
        assert " " not in cleaned

    def test_an_absurdly_long_id_is_bounded(self) -> None:
        assert len(new_request_id("a" * 5000)) == observability.MAX_INBOUND_REQUEST_ID

    def test_an_id_too_short_to_be_useful_is_replaced(self) -> None:
        """A one character id collides constantly, which is worse than no correlation at all."""
        assert new_request_id("x") != "x"
        assert len(new_request_id("x")) == 32

    def test_quotes_and_braces_are_stripped(self) -> None:
        """These would break a Prometheus label and a JSON body respectively."""
        cleaned = new_request_id('req"id{with}junk')
        assert set(cleaned) <= set(
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
        )


class TestMetricsRendering:
    def test_the_format_is_parseable_and_carries_the_counters(self) -> None:
        metrics = Metrics()
        metrics.observe(route="/v1/score/site", status=200, seconds=0.25)
        metrics.observe(route="/v1/score/site", status=200, seconds=0.75)
        metrics.observe(route="/v1/score/site", status=429, seconds=0.001)
        metrics.record_error("ValueError")

        rendered = metrics.render()
        assert 'auspice_requests_total{route="/v1/score/site",status="200"} 2' in rendered
        assert 'auspice_requests_total{route="/v1/score/site",status="429"} 1' in rendered
        assert 'auspice_request_duration_seconds_count{route="/v1/score/site"} 3' in rendered
        assert 'auspice_unhandled_errors_total{kind="ValueError"} 1' in rendered
        assert "auspice_rate_limited_total 1" in rendered
        assert rendered.endswith("\n")

    def test_every_metric_has_a_help_and_a_type(self) -> None:
        """A scrape without them is valid and unreadable in a dashboard."""
        rendered = Metrics().render()
        names = {
            line.split()[0]
            for line in rendered.splitlines()
            if line and not line.startswith("#") and "{" not in line
        }
        for name in names:
            assert f"# TYPE {name}" in rendered

    def test_a_quote_in_a_label_cannot_break_the_scrape(self) -> None:
        metrics = Metrics()
        metrics.observe(route='/v1/x"y', status=200, seconds=0.1)
        assert '\\"' in metrics.render()

    def test_a_newline_in_a_label_cannot_forge_a_metric(self) -> None:
        metrics = Metrics()
        metrics.observe(route="/v1/x\nauspice_fake_total 999", status=200, seconds=0.1)
        rendered = metrics.render()
        assert "\nauspice_fake_total 999" not in rendered

    def test_an_absent_gauge_is_omitted_rather_than_reported_as_zero(self) -> None:
        """Zero is a measurement. Reporting an unknown as zero is the same lie the features avoid."""
        rendered = Metrics().render(extra={"alerts_pending": None, "decisions_held": 4})
        assert "alerts_pending" not in rendered
        assert "auspice_decisions_held 4" in rendered

    def test_uptime_is_reported(self) -> None:
        assert "auspice_uptime_seconds" in Metrics().render()


class TestRouteTemplate:
    def test_the_pattern_is_used_rather_than_the_path(self) -> None:
        """Otherwise every published report id becomes its own label and the label set is unbounded."""

        class _Route:
            path = "/v1/report/{public_id}"

        class _Request:
            scope: ClassVar[dict[str, Any]] = {"route": _Route()}

        assert observability.route_template(_Request()) == "/v1/report/{public_id}"

    def test_an_unmatched_request_is_labelled_once(self) -> None:
        class _Request:
            scope: ClassVar[dict[str, Any]] = {}

        assert observability.route_template(_Request()) == "unmatched"


# ---------------------------------------------------------------------------
# The middleware and the outermost handler, on a throwaway app
# ---------------------------------------------------------------------------
def _app_with_middleware() -> FastAPI:
    """A minimal app carrying the same middleware and handler as the real one.

    Built here rather than importing `app.main`, because the real app's lifespan connects to the
    database and loads models, and none of that is under test.
    """
    import time

    from fastapi.responses import JSONResponse

    metrics = Metrics()
    application = FastAPI()

    @application.middleware("http")
    async def headers(request: Any, call_next: Any) -> Any:
        started = time.perf_counter()
        request_id = new_request_id(request.headers.get(REQUEST_ID_HEADER))
        request.state.request_id = request_id
        observability.bind_request(request_id, method=request.method, path=request.url.path)
        try:
            response = await call_next(request)
        finally:
            observability.clear_request()
        response.headers[REQUEST_ID_HEADER] = request_id
        metrics.observe(
            route=observability.route_template(request),
            status=response.status_code,
            seconds=time.perf_counter() - started,
        )
        return response

    @application.exception_handler(Exception)
    async def unhandled(request: Any, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "unknown")
        metrics.record_error(type(exc).__name__)
        observability.capture(
            exc, request_id=request_id, route=observability.route_template(request)
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Something failed inside this service.", "request_id": request_id},
            headers={REQUEST_ID_HEADER: request_id},
        )

    @application.get("/fine")
    def fine() -> dict[str, bool]:
        return {"ok": True}

    @application.get("/boom")
    def boom() -> dict[str, bool]:
        raise RuntimeError("the database fell over and took the ledger with it")

    application.state.metrics = metrics
    return application


class TestTheOutermostHandler:
    @pytest.fixture
    def client(self) -> TestClient:
        return TestClient(_app_with_middleware(), raise_server_exceptions=False)

    def test_a_successful_response_carries_a_request_id(self, client: TestClient) -> None:
        response = client.get("/fine")
        assert response.status_code == 200
        assert len(response.headers[REQUEST_ID_HEADER]) == 32

    def test_a_caller_supplied_id_comes_back(self, client: TestClient) -> None:
        response = client.get("/fine", headers={REQUEST_ID_HEADER: "customer-trace-01"})
        assert response.headers[REQUEST_ID_HEADER] == "customer-trace-01"

    def test_an_unhandled_exception_becomes_a_500_with_an_id_to_quote(
        self, client: TestClient
    ) -> None:
        response = client.get("/boom")
        assert response.status_code == 500
        body = response.json()
        assert body["request_id"]
        assert body["request_id"] == response.headers[REQUEST_ID_HEADER]

    def test_the_exception_text_is_not_returned_to_the_caller(self, client: TestClient) -> None:
        """These endpoints are unauthenticated. Internals do not go in the body."""
        response = client.get("/boom")
        assert "ledger" not in response.text
        assert "RuntimeError" not in response.text
        assert "fell over" not in response.text

    def test_the_error_is_counted(self, client: TestClient) -> None:
        client.get("/boom")
        rendered = client.app.state.metrics.render()  # type: ignore[attr-defined]
        assert 'auspice_unhandled_errors_total{kind="RuntimeError"} 1' in rendered

    def test_two_failures_get_different_identifiers(self, client: TestClient) -> None:
        """The whole point. Indistinguishable failures were the state being fixed."""
        first = client.get("/boom").json()["request_id"]
        second = client.get("/boom").json()["request_id"]
        assert first != second

    def test_the_context_does_not_leak_between_requests(self, client: TestClient) -> None:
        """contextvars outlive a request in an event loop worker, so they are cleared explicitly."""
        import structlog

        client.get("/fine")
        assert structlog.contextvars.get_contextvars() == {}


class TestErrorTrackingIsOffByDefault:
    def test_no_dsn_means_nothing_starts(self) -> None:
        """No network call leaves the process, which is the right default for public records."""
        assert observability.init_error_tracking() is False

    def test_capture_still_logs_without_a_tracker(self) -> None:
        """The log is the durable record. The tracker is triage on top of it."""
        observability.capture(ValueError("x"), request_id="abc", route="/v1/x")

    def test_a_configured_dsn_with_the_package_absent_warns_rather_than_failing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A service that will not start because error reporting is misinstalled is worse than one
        that starts and says so."""
        import builtins

        from auspice.config import get_settings

        patched = get_settings().model_copy(update={"sentry_dsn": "https://x@example/1"})
        monkeypatch.setattr(observability, "get_settings", lambda: patched)
        monkeypatch.setattr(observability, "_sentry_ready", False)

        real_import = builtins.__import__

        def _no_sentry(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "sentry_sdk":
                raise ImportError("not installed")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _no_sentry)
        assert observability.init_error_tracking() is False


class TestMetricsEndpointIsFailClosed:
    """The route is registered from module level configuration, so these read the real app."""

    def test_without_a_token_the_route_does_not_exist(self) -> None:
        from auspice.config import get_settings

        if get_settings().metrics_token:
            pytest.skip("AUSPICE_METRICS_TOKEN is set in this environment")

        from app.main import app

        paths = {route.path for route in app.routes if hasattr(route, "path")}
        assert "/metrics" not in paths, (
            "the metrics route must not be registered without a token. A route that does not exist "
            "cannot be probed."
        )

    def test_it_is_kept_out_of_the_published_schema(self) -> None:
        """It is the only endpoint that would not be JSON, and it is an operations surface."""
        import inspect

        from app import main

        source = inspect.getsource(main)
        assert "include_in_schema=False" in source
        assert "compare_digest" in source, (
            "the token comparison must be constant time, or the endpoint is an oracle"
        )
