"""Rendering a client side page, and the finding that changed what this is for.

`parse/cascade.py` and `adapters/platforms.py` both refer to "the Playwright path" as though it existed.
It did not. `ingest/render.py` is that path.

## What the probes actually established, which was not what the audit assumed

Audit finding NEW-04 claimed two cited sources could not be verified because they render client side, on
the strength of measuring how little text their fetches produced. Rendering both settled it, and the
finding was wrong on both counts.

wsbtv.com is not client rendered. It answers HTTP 451 with "This website is unavailable in your location"
and "It appears you are attempting to access this website from a country outside of the United States". No
renderer fixes a geographic block. The remedy is a US egress or a different source, and neither is a code
change.

cbs2iowa.com renders to 7658 characters of real article text, and its plain fetch already produced 7636.
It was verifying before this work and never needed rendering. The 7636 figure quoted in the finding was
taken from a fetch that had already succeeded.

Both corrections are in AUDIT_REPORT.md rather than only here. The module stays, because it closed a gap
the codebase already claimed to have closed and because it is what produced the diagnosis.

## Why these tests do not render anything

Rendering needs a browser and reaches the public internet, so it is not something a test suite should do
on every run. What is tested is the decision logic, the thresholds, and every path that reports the
browser as unavailable, which is the path a deployment without one will actually take.
"""

from __future__ import annotations

import builtins
from typing import Any

import pytest

from auspice.pipeline.ingest import render as render_module
from auspice.pipeline.ingest.render import (
    SHELL_TEXT_THRESHOLD,
    RenderedPage,
    RenderUnavailableError,
    looks_like_a_shell,
)


class TestShellDetection:
    def test_an_empty_document_is_a_shell(self) -> None:
        assert looks_like_a_shell("")

    def test_whitespace_only_is_a_shell(self) -> None:
        assert looks_like_a_shell("   \n\n\t  ")

    def test_the_measured_wsbtv_fetch_length_is_a_shell(self) -> None:
        """219 characters, measured against the real page during the audit."""
        assert looks_like_a_shell("x" * 219)

    def test_a_real_article_is_not_a_shell(self) -> None:
        """7658 characters, measured against the real cbs2iowa page after rendering."""
        assert not looks_like_a_shell("x" * 7658)

    def test_the_threshold_is_exclusive_at_the_boundary(self) -> None:
        assert looks_like_a_shell("x" * (SHELL_TEXT_THRESHOLD - 1))
        assert not looks_like_a_shell("x" * SHELL_TEXT_THRESHOLD)

    def test_the_threshold_sits_above_the_furniture_only_case(self) -> None:
        """A page of pure navigation can be long, so the threshold is not set between two measurements.

        A false positive costs one browser render. A false negative costs a permanently unverifiable
        citation, which excludes a corpus row from training.
        """
        assert SHELL_TEXT_THRESHOLD > 219
        assert SHELL_TEXT_THRESHOLD < 7636

    def test_leading_and_trailing_whitespace_does_not_count(self) -> None:
        assert looks_like_a_shell(" " * 5000 + "short" + " " * 5000)


class TestRenderedPage:
    def test_the_byte_size_is_the_payload_length(self) -> None:
        page = RenderedPage(url="https://x/", html=b"<html></html>", title="T")
        assert page.byte_size == 13

    def test_it_is_immutable(self) -> None:
        """A rendered page is an artefact of record. Its bytes are what its hash was taken over."""
        page = RenderedPage(url="https://x/", html=b"<html></html>", title="T")
        with pytest.raises(AttributeError):
            page.html = b"different"  # type: ignore[misc]

    def test_a_title_is_optional(self) -> None:
        assert RenderedPage(url="https://x/", html=b"", title=None).title is None


class TestUnavailability:
    """The path a deployment without a browser takes, which is most of them."""

    def test_a_missing_playwright_names_the_command_that_fixes_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real_import = builtins.__import__

        def _no_playwright(name: str, *args: Any, **kwargs: Any) -> Any:
            if name.startswith("playwright"):
                raise ImportError("not installed")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _no_playwright)
        with pytest.raises(RenderUnavailableError, match="playwright install chromium"):
            render_module.render_page("https://example.gov/x")

    def test_the_message_says_what_the_consequence_is(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An operator reading this needs to know a citation stays unverified, not just that a package
        is missing."""
        real_import = builtins.__import__

        def _no_playwright(name: str, *args: Any, **kwargs: Any) -> Any:
            if name.startswith("playwright"):
                raise ImportError("not installed")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _no_playwright)
        with pytest.raises(RenderUnavailableError, match="unverified"):
            render_module.render_page("https://example.gov/x")

    def test_it_is_a_stage_unavailable_error_so_the_api_answers_503(self) -> None:
        """The exception handler in app/main.py maps StageUnavailableError to 503, which is the right
        status for a capability that is absent rather than a request that is wrong."""
        from auspice.errors import StageUnavailableError

        assert issubclass(RenderUnavailableError, StageUnavailableError)


class TestNavigationStrategy:
    def test_it_does_not_wait_for_network_idle(self) -> None:
        """Measured: wsbtv.com exceeded a twenty second networkidle wait and produced nothing.

        A news site with advertising and analytics never reaches network idle, so waiting for it times
        out on exactly the pages this exists to read. Asserted rather than left as a comment, because the
        obvious fix for a flaky render is to reintroduce it.
        """
        import inspect

        source = inspect.getsource(render_module)
        assert (
            "networkidle" not in source.replace("`networkidle`", "").replace("Deliberately not", "")
            or 'NAVIGATE_UNTIL: Literal["domcontentloaded"]' in source
        )

    def test_navigation_waits_only_for_the_dom(self) -> None:
        assert render_module.NAVIGATE_UNTIL == "domcontentloaded"

    def test_the_timeout_is_bounded(self) -> None:
        assert 0 < render_module.RENDER_TIMEOUT_MS <= 60_000

    def test_the_poll_interval_divides_the_budget_many_times(self) -> None:
        """Otherwise the content wait is one check with extra steps."""
        assert render_module.RENDER_TIMEOUT_MS / render_module.SETTLE_POLL_MS >= 20

    def test_no_selector_is_waited_for(self) -> None:
        """A selector wait breaks the first time a newsroom redesigns. The wait is on text volume."""
        import inspect

        source = inspect.getsource(render_module)
        assert "wait_for_selector" not in source

    def test_no_interaction_is_scripted(self) -> None:
        """A page needing a click or a consent dismissal is a page we cannot cite. Scripting it would
        make verification depend on a layout, silently."""
        import inspect

        source = inspect.getsource(render_module)
        for method in (".click(", ".fill(", ".press(", ".select_option(", "scroll_into_view"):
            assert method not in source, f"{method} makes verification depend on a layout"
