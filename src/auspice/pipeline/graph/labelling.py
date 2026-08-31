"""The labelling console: the mechanism behind `auspice labels add`.

The corpus holds one terminal decision and needs four hundred. It holds one because each row costs
too much human effort, and the most expensive step is not judgement, it is transcription. A labeller
reads a document in a browser, retypes a sentence from it into YAML, and finds out afterwards from
`auspice labels verify` whether the retyping was exact. Three of the twenty one citations in the
repository today failed that check. Every one is a transcription error, not a judgement error.

This module inverts the order. Fetch and parse the document first, then select the quote out of the
parsed text. A quote that was selected from the parsed text cannot fail to appear in the parsed text,
so exact transcription stops being a thing a human can get wrong.

What that guarantee is, precisely, because overstating it would be worse than not having it. The
quote is verbatim in the document as parsed at labelling time, and the document id, which is the hash
of the fetched bytes, is recorded alongside it. `auspice labels verify` refetches the URL later and
re-parses. If it then disagrees, the stored hash distinguishes the two possible causes: the page
changed, or the parse is not deterministic. Neither is a transcription error, and before this module
existed the three were indistinguishable.

What this does not do. It cannot tell whether the sentence a labeller selected is the sentence that
supports the outcome they recorded. A labeller in a hurry can select a true sentence that is
irrelevant, and no mechanism available here detects that. The candidates are therefore shown with
surrounding context and confirmed explicitly, and this paragraph is the honest statement of the
residual risk rather than a claim it was solved.

## Why the file is edited textually and never re-dumped

`decisions.yaml` is the asset. Its diff history is the audit trail: every row has an author and a
date because it is version controlled. Loading it with pydantic and re-dumping it would reformat the
whole file, drop every comment, reorder every key and reflow every quote, so adding one row would
produce a diff of the entire corpus and the audit trail would be worthless.

So one row is dumped, on its own, and that text is inserted. The whole file is then loaded and
validated, which proves the insertion parsed, but it is never written back.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from auspice.domain import ParseMethod
from auspice.logging import get_logger
from auspice.pipeline.graph import labels as labels_module
from auspice.pipeline.parse import ParsedDocument, collapse_whitespace, normalise_text

log = get_logger(__name__, _stage="labels")

# How much text to show either side of a candidate, so a labeller can see whether the sentence is
# the one that supports the outcome rather than merely a sentence containing the search phrase.
CONTEXT_CHARS = 220

# A citation quote is bounded by the schema at 500 characters and floored at 10. A candidate longer
# than the ceiling cannot be stored, so it is trimmed to a sentence boundary rather than offered and
# then rejected by validation.
MAX_QUOTE_CHARS = 500
MIN_QUOTE_CHARS = 10

# Sentence ends, for trimming a candidate to something quotable. Deliberately crude: this decides
# where to cut a suggestion, not whether a quote is valid, and the exact match is what decides that.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

# The two top level sequence keys in decisions.yaml, in file order. A decision has to be inserted
# before `instruments:` rather than appended, because appending would put it inside that sequence.
_DECISIONS_KEY = "decisions:"
_INSTRUMENTS_KEY = "instruments:"


class LabellingError(Exception):
    """A labelling operation refused. The message is written to be read by the labeller."""


@dataclass(frozen=True, slots=True)
class QuoteCandidate:
    """One quotable span found in a parsed document."""

    text: str
    page: int
    char_start: int
    char_end: int
    context_before: str
    context_after: str

    @property
    def quotable(self) -> bool:
        return MIN_QUOTE_CHARS <= len(self.text) <= MAX_QUOTE_CHARS


def _sentence_bounds(
    haystack: str, start: int, end: int, *, lines_are_blocks: bool
) -> tuple[int, int]:
    """Widen a match to the sentence containing it, bounded by the quote ceiling.

    A labeller searches for a distinctive phrase such as a vote tally. The evidence is the sentence
    it sits in, not the phrase, so the candidate offered is the sentence.

    ``lines_are_blocks`` is the difference between HTML and PDF and it is not cosmetic. Extracted
    HTML carries a newline at every element boundary, so a newline is a hard boundary: navigation
    items, headings and paragraphs are separate blocks with no punctuation between them. Anchoring
    only on ``.!?`` offered "Website Sign In Search Home News Flash ..." as a citation, measured
    against a real county newsflash page. In a PDF a newline is a visual line wrap inside a
    paragraph, so treating it as a boundary would truncate a sentence at the edge of the page.
    """
    left = 0
    for match in _SENTENCE_END.finditer(haystack, 0, start):
        left = match.end()
    right = len(haystack)
    for match in _SENTENCE_END.finditer(haystack, end):
        right = match.start()
        break

    if lines_are_blocks:
        # The nearest boundary of either kind wins. A block start is as real a boundary as a full
        # stop when the text came from HTML.
        block_start = haystack.rfind("\n", left, start)
        if block_start >= 0:
            left = block_start + 1
        block_end = haystack.find("\n", end, right)
        if block_end >= 0:
            right = block_end

    if right - left <= MAX_QUOTE_CHARS:
        return left, right

    # Too long to store. Centre the window on the match, then pull the left edge forward to a word
    # boundary so the quote does not begin mid-word.
    left = max(left, start - max(0, (MAX_QUOTE_CHARS - (end - start)) // 2))
    right = min(right, left + MAX_QUOTE_CHARS)
    if right < end:
        right = min(len(haystack), end)
        left = max(0, right - MAX_QUOTE_CHARS)
    space = haystack.find(" ", left, start)
    if space >= 0:
        left = space + 1
    return left, right


def find_quote_candidates(
    parsed: ParsedDocument, phrase: str, *, limit: int = 8
) -> list[QuoteCandidate]:
    """Every sentence in the document containing ``phrase``, as quotable candidates.

    The search runs over the collapsed text, which is the exact string ``ParsedDocument.locate``
    matches against. That coordinate space is a decision rather than an accident, and the other one
    was tried first and was wrong. A candidate taken from the collapsed text is a single line, so it
    reads in YAML the way the verifier reads it. Sentence detection is not confused by the newlines
    HTML extraction leaves at every element boundary. And the offsets recorded on the citation come
    back from ``locate`` in original document coordinates, so the evidence row points into the source
    rather than into an intermediate string.
    """
    needle, _ = collapse_whitespace(normalise_text(phrase))
    needle = needle.strip()
    if not needle:
        raise LabellingError(
            "a search phrase is required. Type a distinctive few words to look for."
        )

    # Newlines are kept here so _sentence_bounds can use them as a weak boundary. The quote text
    # itself is collapsed per candidate, so what a labeller sees and stores is the single line the
    # verifier matches against.
    source = normalise_text(parsed.full_text)
    if not source.strip():
        raise LabellingError(
            "the document parsed to no text at all. It is probably a scanned image that the OCR "
            "stage could not read, and it cannot be cited until it can be read."
        )

    # Searching happens in collapsed space, because that is where the phrase and the document agree
    # about whitespace. The index map carries every collapsed offset back to ``source``.
    haystack, index_map = collapse_whitespace(source)
    # HTML parses to one page by the native_text method. Anything that went through PyMuPDF,
    # pdfplumber or Tesseract has soft line wraps rather than block boundaries.
    lines_are_blocks = bool(parsed.methods_used) and parsed.methods_used <= {
        ParseMethod.native_text
    }
    candidates: list[QuoteCandidate] = []
    seen: set[tuple[int, int]] = set()
    cursor = 0
    folded_haystack = haystack.casefold()
    folded_needle = needle.casefold()

    while len(candidates) < limit:
        found = folded_haystack.find(folded_needle, cursor)
        if found < 0:
            break
        cursor = found + max(1, len(folded_needle))

        source_start = index_map[found]
        source_end = index_map[min(found + len(needle), len(index_map)) - 1] + 1
        left, right = _sentence_bounds(
            source, source_start, source_end, lines_are_blocks=lines_are_blocks
        )
        if (left, right) in seen:
            continue
        seen.add((left, right))

        text, _ = collapse_whitespace(source[left:right])
        text = text.strip()
        if not text:
            continue
        # Locate the collapsed text the way the verifier will, so the page and offsets recorded on
        # the citation are the verifier's own rather than this function's arithmetic.
        located = parsed.locate(text)
        if located is None:
            # A span that is not independently locatable would fail verification, which would defeat
            # the entire mechanism. Skip it rather than offer it.
            continue
        page, char_start, char_end = located
        before, _ = collapse_whitespace(source[max(0, left - CONTEXT_CHARS) : left])
        after, _ = collapse_whitespace(source[right : right + CONTEXT_CHARS])
        candidates.append(
            QuoteCandidate(
                text=text,
                page=page,
                char_start=char_start,
                char_end=char_end,
                context_before=before.strip(),
                context_after=after.strip(),
            )
        )

    return candidates


@dataclass(frozen=True, slots=True)
class SourceDocument:
    """A fetched, stored and parsed document, ready to be quoted from."""

    url: str
    document_id: str
    parsed: ParsedDocument
    title: str | None
    media_type: str | None

    @property
    def pages(self) -> int:
        return len(self.parsed.pages)

    @property
    def characters(self) -> int:
        return len(self.parsed.full_text)

    @property
    def legibility(self) -> float:
        return self.parsed.mean_legibility


async def fetch_and_parse(url: str, *, kind: str = "minutes") -> SourceDocument:
    """Fetch a citation source, store it in the content addressed corpus, and parse it.

    Uses stage 1 and stage 2 unchanged, so a document a labeller quotes from is byte identical to
    one the pipeline would have ingested, and the parse is the same cascade. ``document_id`` is the
    hash of the fetched bytes, which is what makes a later verification disagreement attributable.
    """
    from auspice.pipeline.ingest import Fetcher, content_hash
    from auspice.pipeline.parse import parse_bytes

    async with Fetcher() as fetcher:
        outcome = await fetcher.fetch(url, kind=kind)
        if not outcome.ok or outcome.stored is None:
            raise LabellingError(
                f"could not fetch {url}: {outcome.error or outcome.outcome}. A citation whose source "
                "cannot be retrieved cannot be verified, so the row would load unverified and be "
                "excluded from training."
            )
        data = fetcher.store.get(outcome.stored.key)

    document_id = content_hash(data)
    media_type = outcome.headers.get("content-type")
    try:
        parsed = parse_bytes(data, document_id=document_id, media_type=media_type)
    except Exception as exc:  # the cascade raises many types; the labeller needs one message
        raise LabellingError(
            f"fetched {url} but could not extract text from it: {exc}. Without text there is nothing "
            "to quote and nothing for the verifier to match against."
        ) from exc

    return SourceDocument(
        url=url,
        document_id=document_id,
        parsed=parsed,
        title=_title_of(parsed),
        media_type=media_type,
    )


_TITLE_NOISE = re.compile(r"\s+")


def _title_of(parsed: ParsedDocument) -> str | None:
    """A suggested document title: the first substantial line of the parsed text.

    Only a suggestion. The schema requires 3 to 300 characters and the labeller confirms or replaces
    it, because a page's first line is frequently navigation rather than a title.
    """
    for line in parsed.full_text.splitlines():
        candidate = _TITLE_NOISE.sub(" ", line).strip()
        if 8 <= len(candidate) <= 300:
            return candidate
    return None


# ---------------------------------------------------------------------------
# Label identifiers
# ---------------------------------------------------------------------------
_ID_SAFE = re.compile(r"[^a-z0-9]+")


def suggest_label_id(
    *,
    jurisdiction: str,
    subject: str,
    on: date | None,
    taken: Sequence[str] = (),
) -> str:
    """A readable, stable id that is not already used.

    The schema requires 5 to 81 characters of lowercase, digits and hyphens. Ids are never reused and
    never renumbered, so a collision has to be refused rather than resolved by overwriting.
    """
    county = jurisdiction.rsplit("-", maxsplit=1)[-1] if jurisdiction else "unknown"
    words = [w for w in _ID_SAFE.split(subject.lower()) if w][:5]
    year = str(on.year) if on else "undated"
    stem = "-".join([county, *words, year]) if words else f"{county}-{year}"
    stem = _ID_SAFE.sub("-", stem).strip("-")[:74] or "label"

    if stem not in taken:
        return _pad(stem)
    for suffix in range(2, 100):
        candidate = f"{stem}-{suffix}"
        if candidate not in taken:
            return _pad(candidate)
    raise LabellingError(f"could not find an unused id near {stem!r}. Supply one explicitly.")


def _pad(stem: str) -> str:
    """The schema floor is five characters after the first. Pad rather than fail on a short county."""
    return stem if len(stem) >= 5 else f"{stem}-label"


def existing_label_ids(path: Path) -> set[str]:
    """Every id already in the file, decisions and instruments together.

    Read with a plain YAML load rather than through pydantic, because an id has to be refused as
    taken even if the row holding it currently fails validation.
    """
    if not path.exists():
        return set()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    ids: set[str] = set()
    for key in ("decisions", "instruments"):
        for item in raw.get(key) or []:
            if isinstance(item, dict) and item.get("label_id"):
                ids.add(str(item["label_id"]))
    return ids


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------
def render_row(payload: dict[str, Any], *, indent: str = "  ") -> str:
    """One row as YAML text, ready to insert.

    ``sort_keys=False`` preserves the order the caller built, which is the order the existing rows
    use and therefore the order a reviewer expects. Block style keeps long quotes readable in a diff
    instead of collapsing a row onto one line.
    """
    document = yaml.safe_dump(
        [payload],
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=100,
    )
    lines = [f"{indent}{line}" if line.strip() else line for line in document.splitlines()]
    return "\n".join(lines).rstrip() + "\n"


def _newline_of(text: str) -> str:
    """Match the file's own line endings. A whole file rewritten in the other kind hides the change."""
    return "\r\n" if "\r\n" in text else "\n"


def _top_level_index(lines: Sequence[str], key: str) -> int | None:
    for index, line in enumerate(lines):
        if line.startswith(key):
            return index
    return None


def insert_row(path: Path, *, section: str, row_text: str) -> None:
    """Insert one rendered row into the right sequence, leaving everything else byte identical.

    A decision cannot simply be appended: `instruments:` follows `decisions:` in the file, so an
    append would land inside the instruments sequence and change the meaning of the row. The banner
    comment above `instruments:` belongs to that section, so the insertion point is the top of that
    banner rather than the key itself.
    """
    if section not in {"decisions", "instruments"}:
        raise LabellingError(f"unknown section {section!r}")
    if not path.exists():
        raise LabellingError(
            f"{path} does not exist. This command edits the corpus, it does not create it."
        )

    original = path.read_text(encoding="utf-8")
    newline = _newline_of(original)
    lines = original.splitlines()

    decisions_at = _top_level_index(lines, _DECISIONS_KEY)
    instruments_at = _top_level_index(lines, _INSTRUMENTS_KEY)
    if decisions_at is None or instruments_at is None:
        raise LabellingError(
            f"{path} does not have both a top level `decisions:` and `instruments:` key. Fix the "
            "file by hand rather than letting this command guess where the row belongs."
        )

    if section == "decisions":
        insert_at = instruments_at
        # Walk back over the banner comment and the blank line that separate the two sections, so
        # the new row joins the decisions sequence rather than being orphaned above the banner.
        while insert_at > decisions_at + 1 and (
            lines[insert_at - 1].startswith("#") or not lines[insert_at - 1].strip()
        ):
            insert_at -= 1
    else:
        insert_at = len(lines)
        while insert_at > instruments_at + 1 and not lines[insert_at - 1].strip():
            insert_at -= 1

    block = row_text.rstrip("\r\n").split("\n")
    updated = [*lines[:insert_at], *block, "", *lines[insert_at:]]
    path.write_text(newline.join(updated) + newline, encoding="utf-8", newline="")


def validate_file(path: Path) -> labels_module.LabelSet:
    """Load and validate the whole corpus. Raises if the insertion produced anything invalid."""
    return labels_module.load_label_set(path)


def append_decision(path: Path, payload: dict[str, Any]) -> labels_module.LabelSet:
    """Validate one row, insert it, then revalidate the file. Restores the file if anything fails.

    Validating the row alone first gives a precise error before the file is touched at all. The
    restore exists for the case the row is individually valid and still invalid in context, which a
    duplicate id would be.
    """
    labels_module.DecisionLabel.model_validate(payload)

    before = path.read_text(encoding="utf-8")
    row_text = render_row(payload)
    insert_row(path, section="decisions", row_text=row_text)
    try:
        return validate_file(path)
    except Exception:
        path.write_text(before, encoding="utf-8", newline="")
        raise


def append_instrument(path: Path, payload: dict[str, Any]) -> labels_module.LabelSet:
    """The instrument equivalent of ``append_decision``."""
    labels_module.InstrumentLabel.model_validate(payload)

    before = path.read_text(encoding="utf-8")
    row_text = render_row(payload)
    insert_row(path, section="instruments", row_text=row_text)
    try:
        return validate_file(path)
    except Exception:
        path.write_text(before, encoding="utf-8", newline="")
        raise
