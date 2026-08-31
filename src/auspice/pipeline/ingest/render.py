"""Rendering a page that serves its content client side.

Audit finding NEW-04. Two cited news sources cannot be verified at all because they render in the browser:
wsbtv.com parses to 219 characters and cbs2iowa.com to 7636, both application shell rather than article
text. No transcription of any quote from either can be located, so those citations stay unverified however
carefully they were transcribed, and any row whose only source is a client rendered news site is
permanently excluded from training.

## Why this is a separate document, not a repaired fetch

A document id is the hash of its bytes. Rendered HTML is not the bytes the server sent, so it is a
different artefact and it gets its own id. Pretending otherwise would mean two different byte strings
sharing one hash, which would break the one guarantee the content addressed corpus makes.

So a rendered page is stored alongside the original, `render_method` records that a browser produced it,
and the evidence row points at whichever document the quote was actually found in. A reader following the
provenance sees a rendered document and knows to expect that the raw fetch does not contain the quote.

## Why this is not the default

Rendering executes the page's JavaScript. That is a much larger trust surface than reading bytes, it is
roughly a hundred times slower, and it defeats the politeness accounting in the fetcher, which counts
requests it makes and cannot count the dozens a page makes for itself. So it runs only where a plain fetch
produced implausibly little text, which is a measurable condition rather than a per site allowlist that
would go stale.

## What it does not do

It does not click, scroll, dismiss a consent dialog, or wait for anything beyond the network settling. A
page that needs any of those is a page we cannot cite, and the honest outcome is an unverified citation
rather than a scripted interaction that silently starts depending on a layout.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from auspice.errors import StageUnavailableError
from auspice.logging import get_logger

log = get_logger(__name__, _stage="ingest")

# Below this many characters of extracted text, an HTML document is an application shell rather than a
# document. Measured against the two sources that prompted this: 219 characters for one, 7636 for the
# other, where the second is entirely navigation and app furniture. A real minutes page or news article
# carries thousands of characters of prose.
#
# Set at 1200 rather than between those two numbers, because the quantity that matters is not the total
# but whether the text contains the quote, and a page of pure furniture can be long. A false positive here
# costs one browser render; a false negative costs a permanently unverifiable citation.
SHELL_TEXT_THRESHOLD = 1200

# How long to allow. A page that has not produced its text in this long is not going to.
RENDER_TIMEOUT_MS = 20_000

# Deliberately not `networkidle`. A news site with advertising and analytics never reaches network idle,
# so waiting for it times out on exactly the pages this exists to read. Measured: wsbtv.com exceeded a
# twenty second networkidle wait and produced nothing.
#
# The wait is on content instead. Navigate until the DOM is parsed, then poll the body text until it is
# thick enough to be a document, bounded by the same timeout. That waits for the thing that matters rather
# than for a proxy, and it never depends on a selector, which would make this break the first time a
# newsroom redesigned.
NAVIGATE_UNTIL: Literal["domcontentloaded"] = "domcontentloaded"
SETTLE_POLL_MS = 250


class RenderUnavailableError(StageUnavailableError):
    """Playwright or its browser is absent. The message names the command that fixes it."""


@dataclass(frozen=True, slots=True)
class RenderedPage:
    url: str
    html: bytes
    title: str | None

    @property
    def byte_size(self) -> int:
        return len(self.html)


def looks_like_a_shell(text: str) -> bool:
    """Whether an extracted document is too thin to be the document it claims to be."""
    return len(text.strip()) < SHELL_TEXT_THRESHOLD


def render_page(url: str, *, timeout_ms: int = RENDER_TIMEOUT_MS) -> RenderedPage:
    """Load a URL in a headless browser and return the DOM it settled on.

    Raises ``RenderUnavailableError`` when the browser is not installed, which is a configuration state rather
    than a failure, and the caller reports it as the reason a citation stayed unverified.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RenderUnavailableError(
            "playwright is not installed, so a client rendered page cannot be read. Install it with "
            "`uv sync --extra memo`, then `uv run playwright install chromium`. Citations to such "
            "pages stay unverified until then, which excludes their rows from training."
        ) from exc

    from auspice.config import get_settings

    settings = get_settings()
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Exception as exc:
            raise RenderUnavailableError(
                "playwright is installed and its browser is not. Run "
                "`uv run playwright install chromium`. Until then a citation to a client rendered page "
                f"stays unverified. The launcher said: {str(exc)[:200]}"
            ) from exc

        try:
            context = browser.new_context(
                # The same identity the fetcher uses. A crawler that identifies honestly in one code
                # path and anonymously in another is not identifying honestly.
                user_agent=settings.crawler_user_agent,
                locale="en-US",
                viewport={"width": 1280, "height": 900},
            )
            page = context.new_page()
            # No images, fonts or media. They cannot contain a quote and they are most of the bytes.
            page.route(
                "**/*",
                lambda route: (
                    route.abort()
                    if route.request.resource_type in {"image", "media", "font"}
                    else route.continue_()
                ),
            )
            page.goto(url, wait_until=NAVIGATE_UNTIL, timeout=timeout_ms)
            _wait_for_text(page, timeout_ms=timeout_ms)
            html = page.content()
            title = page.title() or None
        finally:
            browser.close()

    log.info("rendered a client side page", url=url, bytes=len(html.encode("utf-8")))
    return RenderedPage(url=url, html=html.encode("utf-8"), title=title)


def _wait_for_text(page: Any, *, timeout_ms: int) -> None:
    """Poll until the body carries enough text to be a document, or the budget runs out.

    Returning on timeout rather than raising is deliberate. A page that produced some text and not much is
    still worth parsing: the quote may be in it. What the caller needs is the best available content and an
    honest record of how it was obtained, not an exception because a threshold was not met.
    """
    import time

    deadline = time.monotonic() + (timeout_ms / 1000.0)
    while time.monotonic() < deadline:
        try:
            length = int(page.evaluate("() => (document.body?.innerText || '').trim().length"))
        except Exception:
            # A navigation mid-poll invalidates the execution context. Try again on the next tick.
            length = 0
        if length >= SHELL_TEXT_THRESHOLD:
            return
        page.wait_for_timeout(SETTLE_POLL_MS)
