"""The committee memo. Section 6.10 sub-component 3, and section 5.3(c).

The most underrated surface in the product. The buyer's real job is not to understand risk, it is to
defend a decision to a committee, and a clean, sourced, dated document that goes into a deal file is what
actually gets paid for. Sell the artefact, not the dashboard.

Three properties this module guarantees, because a memo that lacks any of them is worse than no memo.

**It is deterministic.** The same score and the same template version produce byte identical HTML. The
generation timestamp is passed in rather than read from the clock, so a memo can be regenerated years
later and compared against the copy in the deal file. A memo that cannot be reproduced cannot be
defended.

**Every claim is linked to its source.** Each driver and each precedent carries the quote and a link to
the document it came from. There is no summarising step and no language model anywhere in this file: the
sentences come from the feature dictionary with a value substituted, and the quotes come from
``fact_evidence`` rows that passed verbatim verification.

**It says what it does not know.** The missing features are listed by name. The abstention, if there is
one, is the entire first page rather than a footnote. An honest hole is usable; a convincing gap is not.

The HTML is the artefact and the PDF is a rendering of it. Chromium is used because it means the memo and
the web interface share one layout engine, so the printed document looks like the screen rather than like
a different product.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from auspice.logging import get_logger
from auspice.score.models import Score

log = get_logger(__name__, _stage="memo")

TEMPLATE_VERSION: Final = "1.0.0"
TEMPLATE_DIR = Path(__file__).parent / "templates"


@dataclass(frozen=True, slots=True)
class Memo:
    html: str
    score_public_id: str
    template_version: str
    generated_at: datetime
    content_hash: str

    @property
    def filename(self) -> str:
        return f"auspice-{self.score_public_id}-{self.generated_at.date().isoformat()}"


def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html"]),
        # An undefined variable is an error, not an empty string. A memo with a silently blank field is
        # exactly the failure this whole module exists to prevent.
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


def _percent(value: float | None) -> str:
    return "not stated" if value is None else f"{round(value * 100)}%"


def _months(value: float | None) -> str:
    return "not stated" if value is None else f"{value:.0f}"


def render(
    score: Score,
    *,
    generated_at: datetime | None = None,
    prepared_for: str | None = None,
) -> Memo:
    """Render the memo to HTML.

    ``generated_at`` is a parameter rather than a call to the clock so the output is reproducible.
    """
    stamp = generated_at or score.generated_at or datetime.now(UTC)
    environment = _environment()
    environment.filters["percent"] = _percent
    environment.filters["months"] = _months

    evidence_by_id = {item.evidence_id: item for item in score.evidence}
    determination = score.determination

    context: dict[str, Any] = {
        "score": score,
        "site": score.site,
        "head": score.site.jurisdiction_chain[0],
        "determination": determination,
        "provenance": score.provenance,
        "drivers": score.drivers,
        "precedents": score.precedents,
        "mitigations": score.mitigations,
        "alternatives": score.alternatives,
        "evidence_by_id": evidence_by_id,
        "template_version": TEMPLATE_VERSION,
        "generated_at": stamp,
        "prepared_for": prepared_for,
        "interval": determination.credible_interval_80,
        "use_class_label": score.site.use_class.value.replace("_", " "),
        "relief_label": ", ".join(r.value.replace("_", " ") for r in score.site.requested_relief),
    }

    html = environment.get_template("memo.html").render(**context)

    return Memo(
        html=html,
        score_public_id=score.public_id,
        template_version=TEMPLATE_VERSION,
        generated_at=stamp,
        content_hash=hashlib.sha256(html.encode("utf-8")).hexdigest(),
    )


def to_pdf(memo: Memo, destination: Path) -> Path:
    """Render the memo HTML to PDF with headless Chromium.

    Raises ``StageUnavailableError`` if Playwright or its browser is not installed, rather than falling
    back to a different renderer. A memo produced by a second layout engine would not match the one in
    the deal file, and silently switching renderers is how two copies of the same document stop agreeing.
    """
    from auspice.errors import StageUnavailableError

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise StageUnavailableError(
            "PDF rendering needs Playwright. Install it with `uv sync --extra memo` and then "
            "`uv run playwright install chromium`. The HTML is written either way and is the artefact "
            "of record."
        ) from exc

    destination.parent.mkdir(parents=True, exist_ok=True)
    html_path = destination.with_suffix(".html")
    html_path.write_text(memo.html, encoding="utf-8")

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page()
                page.goto(html_path.resolve().as_uri(), wait_until="load")
                page.pdf(
                    path=str(destination),
                    format="A4",
                    print_background=True,
                    margin={"top": "18mm", "bottom": "20mm", "left": "18mm", "right": "18mm"},
                    display_header_footer=True,
                    header_template="<div></div>",
                    footer_template=(
                        '<div style="width:100%;font-family:monospace;font-size:8pt;color:#8B9199;'
                        'padding:0 18mm;display:flex;justify-content:space-between;">'
                        f"<span>{memo.score_public_id} &middot; model {memo.template_version}</span>"
                        '<span class="pageNumber"></span>'
                        "</div>"
                    ),
                )
            finally:
                browser.close()
    except Exception as exc:
        raise StageUnavailableError(
            f"Chromium could not render the memo: {exc}. The HTML is at {html_path} and is complete."
        ) from exc

    log.info(
        "memo rendered",
        public_id=memo.score_public_id,
        pdf=str(destination),
        content_hash=memo.content_hash[:16],
    )
    return destination
