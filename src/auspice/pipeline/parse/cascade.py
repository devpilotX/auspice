"""Stage 2: the document cascade.

Section 6.2 specifies a cost ordered cascade and the reason for it: never send a document to an
expensive model if a cheap deterministic tool can read it.

    1. PyMuPDF        digital native PDFs, which are the majority. Fast, free, exact.
    2. pdfplumber     table extraction where layout carries meaning
    3. Tesseract      scanned documents
    4. vision model   only when 1 to 3 produce garbage

Each step's output passes a legibility gate before it is accepted. Below threshold the document
escalates. The escalation rate per jurisdiction is logged, because a sudden rise means a source
changed format, and that is the failure that is otherwise silent.

The part that is not retrofittable is the offsets. Every page records its character range within
the concatenated document text, and every chunk records the page and character range it came
from. Without those a quote cannot be located in its source, and without that the whole trust
architecture in section 8 collapses.
"""

from __future__ import annotations

import itertools
import re
import unicodedata
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from auspice.domain import ParseMethod
from auspice.errors import IllegibleDocumentError
from auspice.logging import get_logger

log = get_logger(__name__, _stage="parse")

# Below this a page is treated as unreadable and escalates to the next step.
LEGIBILITY_THRESHOLD = 0.55

# A page with almost no text is not illegible, it is blank. Escalating a blank page to a vision
# model is pure cost, so it is accepted as empty with a legibility of 1.
BLANK_PAGE_MAX_CHARS = 24

# Words that appear in essentially every planning document. Their presence is a strong signal
# that the text came out in the right order rather than as scrambled columns.
_EXPECTED_TOKENS = frozenset(
    {
        "the",
        "and",
        "of",
        "to",
        "in",
        "shall",
        "county",
        "board",
        "commission",
        "public",
        "hearing",
        "application",
        "zoning",
        "district",
        "property",
        "approve",
        "approved",
        "motion",
        "staff",
        "meeting",
        "development",
        "plan",
        "section",
        "ordinance",
        "member",
    }
)

_WORD = re.compile(r"[A-Za-z][A-Za-z'\-]{1,}")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

# Structural boundaries documents actually use. Chunking on these instead of a token count is
# what keeps a motion and its vote in the same chunk.
_HEADING_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*(?:SEC(?:TION)?\.?\s+[\d.\-]+[A-Za-z]?)\s*[.:\-]?\s*(.*)$", re.I),
    re.compile(r"^\s*(?:ARTICLE\s+[IVXLC\d]+)\s*[.:\-]?\s*(.*)$", re.I),
    re.compile(r"^\s*(?:ITEM|AGENDA ITEM)\s+(?:NO\.?\s*)?([\w.\-]+)\s*[.:\-]?\s*(.*)$", re.I),
    re.compile(r"^\s*(\d+(?:\.\d+){0,3})\s+([A-Z][A-Za-z].{4,90})$"),
    re.compile(r"^\s*(?:MOTION|MOVED|RESOLUTION|ORDINANCE)\b\s*[.:\-]?\s*(.*)$", re.I),
    re.compile(r"^\s*([A-Z][A-Z \-&/,'()]{8,90})\s*$"),
)

MAX_CHUNK_CHARS = 6_000
MIN_CHUNK_CHARS = 200


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------
def normalise_text(raw: str) -> str:
    """Make text comparable without moving any character that matters.

    Quote verification compares an extracted quote against this output, so normalisation has to
    be idempotent and has to be applied identically on both sides. It does four things:

      - NFKC, so a ligature or a full width character matches its plain form
      - curly quotes and dashes folded to ASCII, because a language model reproducing a quote
        will normalise them and a byte comparison would then fail on a correct quote
      - control characters removed
      - runs of whitespace collapsed to single spaces, newlines preserved

    It deliberately does not lowercase, strip punctuation, or remove stop words. Those would make
    verification pass on text that does not actually say the same thing.
    """
    text = unicodedata.normalize("NFKC", raw)
    replacements: dict[str, str | int | None] = {
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u201f": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2015": "-",
        "\u2212": "-",
        "\u00a0": " ",
        "\u2009": " ",
        "\u200a": " ",
        "\u202f": " ",
        "\u2026": "...",
        "\ufeff": "",
        "\u200b": "",
        "\u200c": "",
        "\u200d": "",
    }
    text = text.translate(str.maketrans(replacements))
    text = _CONTROL.sub(" ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# Punctuation that inline markup routinely leaves a stray space in front of. Extracting text
# from HTML inserts a separator at every element boundary, so a sentence where a phrase was a
# hyperlink comes out as "developments , defeating" rather than "developments, defeating". A space
# before a comma is a rendering artefact and never content, so it is dropped, on both sides of the
# comparison, exactly like a line break is.
_NO_SPACE_BEFORE = frozenset(",.;:!?)]}%\u2019'\"")


def collapse_whitespace(text: str) -> tuple[str, list[int]]:
    """Collapse every run of whitespace to one space, with a map back to the original offsets.

    Used only by quote location. The returned list has one entry per character of the collapsed
    string, holding that character's index in the input, so a match found in collapsed space can be
    reported as a range in the original text.

    Written as an explicit loop rather than a regex because the index map has to be built alongside
    the output, and a regex substitution throws the positions away.
    """
    out: list[str] = []
    index_map: list[int] = []
    previous_was_space = True  # drops leading whitespace
    for position, character in enumerate(text):
        if character.isspace():
            if not previous_was_space:
                out.append(" ")
                index_map.append(position)
                previous_was_space = True
            continue
        if previous_was_space and out and out[-1] == " " and character in _NO_SPACE_BEFORE:
            out.pop()
            index_map.pop()
        out.append(character)
        index_map.append(position)
        previous_was_space = False

    while out and out[-1] == " ":
        out.pop()
        index_map.pop()

    return "".join(out), index_map


def legibility(text: str) -> float:
    """A heuristic score in [0, 1] for whether this text came out readable.

    Three components, per section 6.2: character density, dictionary word ratio, and the presence
    of tokens every planning document contains. OCR failure produces text that fails all three at
    once, which is why a simple length check is not enough.
    """
    stripped = text.strip()
    if len(stripped) <= BLANK_PAGE_MAX_CHARS:
        # A genuinely blank page. Legible, and there is nothing to escalate.
        return 1.0

    words = _WORD.findall(stripped)
    if not words:
        return 0.0

    # 1. Share of characters that are letters, digits, spaces or ordinary punctuation. OCR noise
    #    is full of characters that are none of those.
    plausible = sum(
        1 for ch in stripped if ch.isalnum() or ch.isspace() or ch in ".,;:'\"()-/$%&#*[]"
    )
    density = plausible / len(stripped)

    # 2. Share of words of a plausible length. OCR failure produces long consonant runs and
    #    single character fragments.
    reasonable = sum(1 for w in words if 2 <= len(w) <= 20)
    word_shape = reasonable / len(words)

    # 3. Presence of the vocabulary these documents always contain.
    lowered = {w.lower() for w in words}
    expected_hits = len(lowered & _EXPECTED_TOKENS)
    expected = min(expected_hits / 6.0, 1.0)

    return round(0.4 * density + 0.35 * word_shape + 0.25 * expected, 3)


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ParsedPage:
    page: int
    text: str
    char_start: int
    char_end: int
    method: ParseMethod
    legibility: float
    escalated: bool


@dataclass(frozen=True, slots=True)
class ParsedChunk:
    ordinal: int
    heading: str | None
    page_start: int
    page_end: int
    char_start: int
    char_end: int
    text: str

    @property
    def token_estimate(self) -> int:
        # Four characters per token is close enough for budgeting and costs nothing to compute.
        return max(1, len(self.text) // 4)


@dataclass(slots=True)
class ParsedDocument:
    document_id: str
    pages: list[ParsedPage] = field(default_factory=list)
    chunks: list[ParsedChunk] = field(default_factory=list)
    methods_used: set[ParseMethod] = field(default_factory=set)
    escalations: int = 0
    _text_cache: str | None = None
    _collapsed_cache: tuple[str, list[int]] | None = None

    @property
    def full_text(self) -> str:
        if self._text_cache is None:
            self._text_cache = "".join(page.text for page in self.pages)
        return self._text_cache

    @property
    def mean_legibility(self) -> float:
        if not self.pages:
            return 0.0
        return round(sum(p.legibility for p in self.pages) / len(self.pages), 3)

    @property
    def primary_method(self) -> ParseMethod:
        """The most expensive method any page needed. That is what the document cost."""
        order = [
            ParseMethod.native_text,
            ParseMethod.pymupdf,
            ParseMethod.pdfplumber,
            ParseMethod.tesseract,
            ParseMethod.vision_model,
        ]
        for method in reversed(order):
            if method in self.methods_used:
                return method
        return ParseMethod.pymupdf

    def _collapsed(self) -> tuple[str, list[int]]:
        if self._collapsed_cache is None:
            self._collapsed_cache = collapse_whitespace(self.full_text)
        return self._collapsed_cache

    def page_for_offset(self, offset: int) -> int:
        for page in self.pages:
            if page.char_start <= offset < page.char_end:
                return page.page
        return self.pages[0].page if self.pages else 1

    def locate(self, quote: str, *, from_offset: int = 0) -> tuple[int, int, int] | None:
        """Find a quote in the document. Returns (page, char_start, char_end) or None.

        This is the function the whole citation guarantee rests on, so it does exactly one thing:
        an exact match, insensitive only to how whitespace was laid out.

        Whitespace insensitivity is not fuzzy matching, and the distinction is the whole point. A
        line break inside a PDF is an artefact of page layout, never of content, so a quote
        transcribed on one line has to match the same sentence broken across three. Every other
        difference still fails: a changed word, a dropped clause, a different number, a rewritten
        date. There is no token overlap threshold, no edit distance and no embedding similarity,
        because a fuzzy matcher would quietly convert a fabricated citation into a passing one,
        which is the exact failure this exists to prevent.

        Offsets are returned in the original text rather than the collapsed text, so a verified
        quote can be highlighted in the source exactly where it sits.
        """
        needle, _ = collapse_whitespace(normalise_text(quote))
        if not needle:
            return None

        haystack, index_map = self._collapsed()

        start_bound = 0
        if from_offset > 0:
            start_bound = next(
                (i for i, original in enumerate(index_map) if original >= from_offset),
                len(haystack),
            )

        found = haystack.find(needle, start_bound)
        if found < 0:
            return None

        char_start = index_map[found]
        char_end = index_map[found + len(needle) - 1] + 1
        return self.page_for_offset(char_start), char_start, char_end


# ---------------------------------------------------------------------------
# The cascade
# ---------------------------------------------------------------------------
def _open_pdf(data: bytes) -> Any:
    """Open a PDF with PyMuPDF.

    PyMuPDF's Document constructor carries no annotations, so this is the one place the untyped
    boundary is crossed. Naming it here keeps every call site typed.
    """
    import pymupdf

    # PyMuPDF ships a py.typed marker but its Document constructor is unannotated, so mypy reads the
    # call as untyped. This is the only place that boundary is crossed, and it is crossed once.
    return pymupdf.open(stream=data, filetype="pdf")  # type: ignore[no-untyped-call]


def _pages_from_pymupdf(data: bytes) -> Iterator[tuple[int, str]]:
    with _open_pdf(data) as doc:
        for number, page in enumerate(doc, start=1):
            yield number, page.get_text("text")


def _page_from_pdfplumber(data: bytes, page_number: int) -> str:
    """One page through pdfplumber, with any tables rendered as pipe separated rows.

    Use tables and setback schedules are the highest value content in a zoning ordinance and
    PyMuPDF flattens them into unreadable runs. Rendering them explicitly keeps the relationship
    between a district and its setback, which is what the ``setback_compliance_margin`` feature
    depends on.
    """
    import io

    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        if page_number > len(pdf.pages):
            return ""
        page = pdf.pages[page_number - 1]
        parts: list[str] = []
        body = page.extract_text() or ""
        if body:
            parts.append(body)
        for table in page.extract_tables() or []:
            rendered = "\n".join(
                " | ".join((cell or "").strip() for cell in row) for row in table if any(row)
            )
            if rendered.strip():
                parts.append("\n[table]\n" + rendered)
        return "\n".join(parts)


def _page_from_tesseract(data: bytes, page_number: int, *, dpi: int = 300) -> str:
    import io

    import pytesseract
    from PIL import Image

    with _open_pdf(data) as document:
        if page_number > document.page_count:
            return ""
        page = document[page_number - 1]
        pixmap = page.get_pixmap(dpi=dpi)
        image = Image.open(io.BytesIO(pixmap.tobytes("png")))
    return str(pytesseract.image_to_string(image))


def tesseract_available() -> bool:
    """Whether the Tesseract binary is installed.

    Checked rather than assumed. If it is absent, scanned pages are recorded as illegible with
    the reason, and the document goes to the dead letter queue. It is not silently skipped: a
    document that produced no facts because a binary was missing looks exactly like a document
    that contained no facts.
    """
    import shutil

    if shutil.which("tesseract") is not None:
        return True
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
    except Exception:
        return False
    return True


def parse_pdf(data: bytes, *, document_id: str, allow_ocr: bool = True) -> ParsedDocument:
    """Run the cascade over a PDF."""
    result = ParsedDocument(document_id=document_id)
    cursor = 0

    for page_number, raw in _pages_from_pymupdf(data):
        candidates: list[tuple[ParseMethod, str, float]] = []

        text = normalise_text(raw)
        score = legibility(text)
        candidates.append((ParseMethod.pymupdf, text, score))

        if score < LEGIBILITY_THRESHOLD:
            try:
                plumbed = normalise_text(_page_from_pdfplumber(data, page_number))
            except Exception as exc:
                log.debug(
                    "pdfplumber failed", document_id=document_id, page=page_number, error=str(exc)
                )
            else:
                candidates.append((ParseMethod.pdfplumber, plumbed, legibility(plumbed)))

        if max(c[2] for c in candidates) < LEGIBILITY_THRESHOLD and allow_ocr:
            if tesseract_available():
                try:
                    ocr = normalise_text(_page_from_tesseract(data, page_number))
                except Exception as exc:
                    log.debug(
                        "tesseract failed",
                        document_id=document_id,
                        page=page_number,
                        error=str(exc),
                    )
                else:
                    candidates.append((ParseMethod.tesseract, ocr, legibility(ocr)))
            else:
                log.warning(
                    "page needs OCR and tesseract is not installed",
                    document_id=document_id,
                    page=page_number,
                )

        method, best_text, best_score = max(candidates, key=lambda c: c[2])
        escalated = method is not ParseMethod.pymupdf

        # A trailing newline separates pages in the concatenated text so a quote cannot
        # accidentally span a page boundary and then fail to locate.
        page_text = best_text + "\n"
        page_result = ParsedPage(
            page=page_number,
            text=page_text,
            char_start=cursor,
            char_end=cursor + len(page_text),
            method=method,
            legibility=best_score,
            escalated=escalated,
        )
        cursor += len(page_text)
        result.pages.append(page_result)
        result.methods_used.add(method)
        if escalated:
            result.escalations += 1

    if not result.pages:
        raise IllegibleDocumentError(
            "the PDF contains no pages", document_id=document_id, best_score=0.0
        )

    result.chunks = chunk_pages(result.pages)
    log.info(
        "parsed",
        document_id=document_id[:12],
        pages=len(result.pages),
        chunks=len(result.chunks),
        legibility=result.mean_legibility,
        escalations=result.escalations,
        method=result.primary_method.value,
    )
    return result


def parse_html(data: bytes, *, document_id: str) -> ParsedDocument:
    """Extract readable text from HTML.

    Civic platforms serve agendas and minutes as HTML at least as often as PDF, and the tables in
    them carry the vote tallies. selectolax is used rather than a full browser because these are
    server rendered pages. A page that genuinely needs JavaScript goes through
    ``ingest/render.py``, which loads it in a headless browser and hands the settled DOM back to this
    function. That module is new: this comment previously said the adapters handled such pages, and
    they did not.
    """
    from selectolax.parser import HTMLParser

    tree = HTMLParser(data.decode("utf-8", errors="replace"))
    for tag in tree.css("script, style, noscript, svg, nav, footer"):
        tag.decompose()

    body = tree.body or tree.root
    text = normalise_text(body.text(separator="\n") if body is not None else "")
    page_text = text + "\n"

    result = ParsedDocument(document_id=document_id)
    result.pages.append(
        ParsedPage(
            page=1,
            text=page_text,
            char_start=0,
            char_end=len(page_text),
            method=ParseMethod.native_text,
            legibility=legibility(text),
            escalated=False,
        )
    )
    result.methods_used.add(ParseMethod.native_text)
    result.chunks = chunk_pages(result.pages)
    return result


def parse_plain_text(text: str, *, document_id: str, method: ParseMethod) -> ParsedDocument:
    """Wrap already extracted text, used by the transcription stage."""
    normalised = normalise_text(text) + "\n"
    result = ParsedDocument(document_id=document_id)
    result.pages.append(
        ParsedPage(
            page=1,
            text=normalised,
            char_start=0,
            char_end=len(normalised),
            method=method,
            legibility=legibility(normalised),
            escalated=False,
        )
    )
    result.methods_used.add(method)
    result.chunks = chunk_pages(result.pages)
    return result


def parse_bytes(data: bytes, *, document_id: str, media_type: str | None) -> ParsedDocument:
    """Dispatch on media type, falling back to a signature check."""
    resolved = (media_type or "").split(";")[0].strip().lower()
    if resolved == "application/pdf" or data[:5] == b"%PDF-":
        return parse_pdf(data, document_id=document_id)
    if resolved in {"text/html", "application/xhtml+xml"} or data[:200].lstrip()[:1] == b"<":
        return parse_html(data, document_id=document_id)
    if resolved.startswith("text/"):
        return parse_plain_text(
            data.decode("utf-8", errors="replace"),
            document_id=document_id,
            method=ParseMethod.native_text,
        )
    raise IllegibleDocumentError(
        f"no parser for media type {resolved or 'unknown'}", document_id=document_id, best_score=0.0
    )


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------
def _detect_heading(line: str) -> str | None:
    stripped = line.strip()
    if not (4 <= len(stripped) <= 120):
        return None
    for pattern in _HEADING_PATTERNS:
        match = pattern.match(stripped)
        if match is not None:
            return stripped
    return None


def chunk_pages(pages: Sequence[ParsedPage]) -> list[ParsedChunk]:
    """Split on structural boundaries, not on a token count.

    A fixed window cuts a motion away from its vote tally, and then no amount of prompt
    engineering can recover the association. Splitting on headings, agenda items and motion
    blocks keeps them together. Where a section runs past ``MAX_CHUNK_CHARS`` it is split on a
    paragraph boundary, which is the least bad place to cut.
    """
    if not pages:
        return []

    # (absolute offset, page number, line text)
    lines: list[tuple[int, int, str]] = []
    for page in pages:
        offset = page.char_start
        for line in page.text.splitlines(keepends=True):
            lines.append((offset, page.page, line))
            offset += len(line)

    boundaries: list[int] = []
    for index, (_offset, _page, line) in enumerate(lines):
        if _detect_heading(line) is not None:
            boundaries.append(index)
    if not boundaries or boundaries[0] != 0:
        boundaries.insert(0, 0)
    boundaries.append(len(lines))

    chunks: list[ParsedChunk] = []
    ordinal = 0
    for start_index, end_index in itertools.pairwise(boundaries):
        if start_index >= end_index:
            continue
        segment = lines[start_index:end_index]
        heading = _detect_heading(segment[0][2])
        text = "".join(line for _o, _p, line in segment)

        if len(text) <= MAX_CHUNK_CHARS:
            ordinal = _append_chunk(chunks, ordinal, segment, heading, text)
            continue

        # Too long: split on paragraph boundaries, keeping the heading on every piece so a chunk
        # read in isolation still says which section it belongs to.
        buffer: list[tuple[int, int, str]] = []
        length = 0
        for entry in segment:
            buffer.append(entry)
            length += len(entry[2])
            if length >= MAX_CHUNK_CHARS and entry[2].strip() == "":
                ordinal = _append_chunk(
                    chunks, ordinal, buffer, heading, "".join(line for _o, _p, line in buffer)
                )
                buffer, length = [], 0
        if buffer:
            ordinal = _append_chunk(
                chunks, ordinal, buffer, heading, "".join(line for _o, _p, line in buffer)
            )

    return _merge_tiny(chunks)


def _append_chunk(
    chunks: list[ParsedChunk],
    ordinal: int,
    segment: Sequence[tuple[int, int, str]],
    heading: str | None,
    text: str,
) -> int:
    if not text.strip():
        return ordinal
    char_start = segment[0][0]
    char_end = segment[-1][0] + len(segment[-1][2])
    chunks.append(
        ParsedChunk(
            ordinal=ordinal,
            heading=heading,
            page_start=min(p for _o, p, _l in segment),
            page_end=max(p for _o, p, _l in segment),
            char_start=char_start,
            char_end=char_end,
            text=text,
        )
    )
    return ordinal + 1


def _merge_tiny(chunks: list[ParsedChunk]) -> list[ParsedChunk]:
    """Fold chunks shorter than MIN_CHUNK_CHARS into the next one.

    A heading on its own line becomes a chunk containing only the heading, which is useless to
    extract from and costs a model call. Merging forward keeps the heading attached to the text it
    introduces.
    """
    if not chunks:
        return []
    merged: list[ParsedChunk] = []
    pending: ParsedChunk | None = None
    for original in chunks:
        chunk = original
        if pending is not None:
            chunk = ParsedChunk(
                ordinal=pending.ordinal,
                heading=pending.heading or chunk.heading,
                page_start=pending.page_start,
                page_end=chunk.page_end,
                char_start=pending.char_start,
                char_end=chunk.char_end,
                text=pending.text + chunk.text,
            )
            pending = None
        if len(chunk.text.strip()) < MIN_CHUNK_CHARS and chunk is not chunks[-1]:
            pending = chunk
            continue
        merged.append(chunk)
    if pending is not None:
        merged.append(pending)
    return [
        ParsedChunk(
            ordinal=index,
            heading=c.heading,
            page_start=c.page_start,
            page_end=c.page_end,
            char_start=c.char_start,
            char_end=c.char_end,
            text=c.text,
        )
        for index, c in enumerate(merged)
    ]
