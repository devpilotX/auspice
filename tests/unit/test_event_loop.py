"""Route handlers must not put blocking work on the event loop.

Every handler in this service does synchronous work: a SQLAlchemy round trip at minimum, and in the
scoring path polars frames, an XGBoost predict and a NumPyro posterior. Declared ``async def``, that work
runs on the event loop and blocks every other request in the process for its whole duration. FastAPI
dispatches a plain ``def`` to its threadpool instead.

Every router was ``async def`` and not one of them awaited anything. Combined with the in-process rate
limiter, which caps the deployment at a single uvicorn worker, effective concurrency was about one
request: a portfolio screen carrying up to 500 sites stalled the health check and every map tile with it.

This is asserted mechanically rather than by a timing test. The difference is one keyword, it is invisible
in review, and a timing test for it would be slow and flaky while proving something weaker. Walking the
route table means a handler added later is covered without anyone remembering to add a case.
"""

from __future__ import annotations

import inspect

from fastapi.routing import APIRoute

# Handlers allowed to be coroutines, with the reason. Nothing is on this list today. An entry here should
# await something real, and if it does then it is not doing blocking work and the rule does not apply.
COROUTINES_ALLOWED: frozenset[str] = frozenset()


def _api_routes() -> list[APIRoute]:
    """Every APIRoute in the application, found by walking the tree rather than one level of it.

    ``app.routes`` on FastAPI 0.141.1 does not hold the included routers' routes directly. It holds three
    ``fastapi.routing._IncludedRouter`` objects, one per ``include_router`` call, and each exposes the
    router it wrapped as ``original_router`` rather than as ``routes``. A single level scan therefore finds
    exactly one route, ``/healthz``, the one registered on the application itself, and an assertion built
    on that would pass while examining almost nothing. The first version of this test did exactly that and
    reported one route where there are twelve.

    Both attribute names are followed, so this keeps working whether a version nests, wraps or flattens.
    """
    from app.main import app

    found: list[APIRoute] = []
    stack: list[object] = list(app.routes)
    seen: set[int] = set()
    while stack:
        item = stack.pop()
        if id(item) in seen:
            continue
        seen.add(id(item))

        if isinstance(item, APIRoute):
            found.append(item)
            continue

        for attribute in ("routes", "original_router"):
            nested = getattr(item, attribute, None)
            if nested is None:
                continue
            stack.extend(nested if isinstance(nested, list) else [nested])
    return found


class TestNoHandlerBlocksTheEventLoop:
    def test_the_route_table_is_not_empty(self) -> None:
        # Guards against the walk below passing because it found nothing to check.
        routes = _api_routes()
        assert len(routes) >= 10, f"expected the full route table, found {len(routes)}"

    def test_every_handler_is_a_plain_function(self) -> None:
        offenders = [
            route.endpoint.__name__
            for route in _api_routes()
            if inspect.iscoroutinefunction(route.endpoint)
            and route.endpoint.__name__ not in COROUTINES_ALLOWED
        ]
        assert offenders == [], (
            "these handlers are async def while their bodies block, so they run on the event loop "
            f"and stall every other request: {', '.join(sorted(offenders))}. Make them def, or add "
            "them to COROUTINES_ALLOWED with the thing they await."
        )

    def test_the_scoring_and_public_paths_are_covered_by_the_walk(self) -> None:
        # Names the paths that matter, so a refactor that drops a router from the app is visible here
        # rather than silently reducing what the assertion above examines.
        paths = {route.path for route in _api_routes()}
        for expected in (
            "/healthz",
            "/v1/score",
            "/v1/portfolio",
            "/v1/public/accuracy",
            "/v1/public/jurisdictions",
            "/v1/tiles/jurisdictions/{z}/{x}/{y}.mvt",
        ):
            assert expected in paths, f"{expected} is not in the route table"


class TestTheGenuinelyAsynchronousCodeStaysAsynchronous:
    def test_the_middlewares_and_lifespan_are_still_coroutines(self) -> None:
        """The rule is not "never async". It is "not async while the body blocks".

        The middlewares await ``call_next`` and the lifespan is an async context manager, so making these
        synchronous would be wrong in the opposite direction. Asserted so a future sweep of ``async def``
        does not take them with it.
        """
        from app import main

        assert inspect.isasyncgenfunction(main.lifespan.__wrapped__)  # type: ignore[attr-defined]
        assert inspect.iscoroutinefunction(main.rate_limit)
        assert inspect.iscoroutinefunction(main.add_standard_headers)
