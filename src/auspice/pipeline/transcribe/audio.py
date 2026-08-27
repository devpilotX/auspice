"""Stage 3: hearing audio to a citable transcript.

Section 6.3 calls this the single most underexploited input in the market, and the reason is worth restating
because it drives every decision in this module.

The minutes say "Motion denied, 1 to 4". The recording says "I can't support this until we understand what
it does to the aquifer, and I've been asking for six months". One of those is a data point. The other is a
transferable feature: it predicts the next four decisions in that county and probably the neighbouring one
too, and it appears in no written record anywhere.

Four decisions shape the implementation.

**Audio only.** ``ffmpeg -vn -ac 1 -ar 16000`` before anything else. Video is fifty to a hundred times
larger and adds nothing a transcript needs, and the download volume is the binding cost on ingesting
hearings at all.

**Word level timestamps and speaker diarisation.** Without timestamps a quote cannot be cited, and a quote
that cannot be cited is not evidence. Without diarisation a three hour meeting is one undifferentiated wall
of text and the attribution that makes the feature valuable is lost.

**Segments are stored as a first class document.** A transcript gets the same provenance fields as a PDF, so
a quote from it can be verified by exactly the same mechanism, and cited as "Commissioner X, 1:47:22,
14 September 2025 hearing".

**Speaker labels are not names.** Diarisation produces SPEAKER_00, and turning that into a person is a
separate, evidence bearing step. Guessing an attribution is worse than leaving a quote unattributed, and
section 8.9 forbids modelling named individuals anyway, so the bar for naming anyone is high on purpose.

Cost control from section 6.3: transcribe the top counties only, and only the agenda items matching the
target use class. A three hour meeting is roughly twenty to forty minutes of relevant audio, so segmenting
by agenda item before transcribing is most of the saving.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from auspice.config import Settings, get_settings
from auspice.domain import ParseMethod
from auspice.errors import StageUnavailableError
from auspice.logging import get_logger

log = get_logger(__name__, _stage="transcribe")

TARGET_SAMPLE_RATE = 16_000
TARGET_CHANNELS = 1

# Whisper class models degrade on very long single passes, and a hearing runs three hours. Thirty minute
# windows with a small overlap keep quality up and let a failure cost one window rather than the meeting.
WINDOW_SECONDS = 1800
OVERLAP_SECONDS = 15


@dataclass(frozen=True, slots=True)
class Segment:
    """One utterance, with everything needed to cite it."""

    ordinal: int
    start_ms: int
    end_ms: int
    text: str
    speaker_label: str | None = None
    confidence: float | None = None
    agenda_item: str | None = None

    @property
    def timestamp(self) -> str:
        """The position in the hearing, as a person would write it."""
        total_seconds = self.start_ms // 1000
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours}:{minutes:02d}:{seconds:02d}"


@dataclass(slots=True)
class Transcript:
    document_id: str
    segments: list[Segment] = field(default_factory=list)
    duration_ms: int = 0
    model: str = ""
    language: str | None = None
    speakers: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        """The transcript as one string, with speaker labels, for storage and verification."""
        return "\n".join(
            f"[{segment.timestamp}] {segment.speaker_label or 'speaker'}: {segment.text}"
            for segment in self.segments
        )

    def citation_for(
        self, segment: Segment, *, hearing_date: date, speaker_name: str | None = None
    ) -> str:
        """The citation string a memo would print.

        ``speaker_name`` is only ever supplied when the attribution is supported by the record. The default
        is the diarisation label, which is honest about not knowing who spoke.
        """
        who = speaker_name or segment.speaker_label or "an unidentified speaker"
        return f"{who}, {segment.timestamp}, {hearing_date.isoformat()} hearing"


# ---------------------------------------------------------------------------
# Audio extraction
# ---------------------------------------------------------------------------
def ffmpeg_available(settings: Settings | None = None) -> bool:
    resolved = settings or get_settings()
    return shutil.which(resolved.ffmpeg_path) is not None


def extract_audio(
    source: str,
    destination: Path,
    *,
    settings: Settings | None = None,
    timeout: int = 1800,
) -> Path:
    """Download and convert to 16 kHz mono WAV.

    ``source`` may be a local path or a URL, because ffmpeg reads both, which removes a whole download step
    and its temporary file.

    Raises rather than returning a partial file. A truncated recording produces a transcript that stops
    halfway through a hearing, and the missing half is exactly where the vote is.
    """
    resolved = settings or get_settings()
    if not ffmpeg_available(resolved):
        raise StageUnavailableError(
            f"ffmpeg was not found at {resolved.ffmpeg_path!r}. Transcription needs it to extract audio, "
            "and audio only extraction is what makes ingesting hearings affordable at all."
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [
        resolved.ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        source,
        "-vn",
        "-ac",
        str(TARGET_CHANNELS),
        "-ar",
        str(TARGET_SAMPLE_RATE),
        "-c:a",
        "pcm_s16le",
        str(destination),
    ]

    log.info("extracting audio", source=source[:120], destination=str(destination))
    # The command is a fixed argument list with no shell, so a hostile URL cannot inject anything.
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )

    if result.returncode != 0 or not destination.exists():
        raise StageUnavailableError(
            f"ffmpeg failed on {source[:120]}: {result.stderr.strip()[:400]}"
        )

    size_mb = destination.stat().st_size / 1_000_000
    log.info("audio extracted", megabytes=round(size_mb, 1))
    return destination


def probe_duration(path: Path, *, settings: Settings | None = None) -> float | None:
    """Duration in seconds, or None if ffprobe is unavailable."""
    resolved = settings or get_settings()
    ffprobe = resolved.ffmpeg_path.replace("ffmpeg", "ffprobe")
    if shutil.which(ffprobe) is None:
        return None
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Transcription
# ---------------------------------------------------------------------------
def transcribe(
    audio: Path,
    *,
    document_id: str,
    settings: Settings | None = None,
    language: str | None = "en",
) -> Transcript:
    """Transcribe with a Whisper class model, with word level timestamps.

    Raises ``StageUnavailableError`` if the model is not installed rather than returning an empty
    transcript. An empty transcript and a silent meeting look identical downstream, and in a corpus those
    two things must never be confused.
    """
    resolved = settings or get_settings()

    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise StageUnavailableError(
            "Transcription needs faster-whisper. Install it with `uv sync --extra transcribe`. Until then "
            "the transcription stage reports as unavailable rather than producing empty transcripts, "
            "because an empty transcript and a silent hearing are not the same thing."
        ) from exc

    model = WhisperModel(
        resolved.whisper_model,
        device=resolved.whisper_device,
        # int8 on CPU is roughly four times faster than float32 with a word error rate difference that does
        # not survive the legibility gate. On GPU the default precision is used.
        compute_type="int8" if resolved.whisper_device == "cpu" else "float16",
    )

    log.info("transcribing", document_id=document_id[:12], model=resolved.whisper_model)
    raw_segments, info = model.transcribe(
        str(audio),
        language=language,
        word_timestamps=True,
        vad_filter=True,
        # A hearing has long silences while people read documents. Without voice activity detection the
        # model hallucinates filler into them, which is the failure mode that puts fabricated sentences in
        # a transcript.
        vad_parameters={"min_silence_duration_ms": 800},
    )

    transcript = Transcript(
        document_id=document_id,
        model=resolved.whisper_model,
        language=getattr(info, "language", language),
    )

    for ordinal, segment in enumerate(raw_segments):
        text = str(segment.text).strip()
        if not text:
            continue
        transcript.segments.append(
            Segment(
                ordinal=ordinal,
                start_ms=int(float(segment.start) * 1000),
                end_ms=int(float(segment.end) * 1000),
                text=text,
                confidence=(
                    float(1.0 - segment.no_speech_prob)
                    if getattr(segment, "no_speech_prob", None) is not None
                    else None
                ),
            )
        )

    if transcript.segments:
        transcript.duration_ms = transcript.segments[-1].end_ms

    if not transcript.segments:
        transcript.notes.append(
            "the model returned no speech. This is recorded rather than treated as an empty transcript, "
            "because a recording with no audio and a hearing with no words are different problems."
        )

    log.info(
        "transcribed",
        document_id=document_id[:12],
        segments=len(transcript.segments),
        minutes=round(transcript.duration_ms / 60_000, 1),
    )
    return transcript


def align_to_agenda(transcript: Transcript, agenda_items: list[tuple[str, int]]) -> Transcript:
    """Attach an agenda item to each segment.

    ``agenda_items`` is a list of (label, start_ms) in order. Alignment is by timestamp because that is the
    only signal that is reliably present: the agenda gives the order and the recording gives the clock, and
    matching text against agenda titles fails whenever a chair reads an item out of order, which is often.

    Segments before the first item keep no label rather than being assigned to item one, because the opening
    of a meeting is procedural and attributing procedural discussion to a specific application would put a
    quote about the minutes of the last meeting under someone's rezoning.
    """
    if not agenda_items:
        return transcript

    ordered = sorted(agenda_items, key=lambda pair: pair[1])
    labelled: list[Segment] = []

    for segment in transcript.segments:
        label: str | None = None
        for item_label, start_ms in ordered:
            if segment.start_ms >= start_ms:
                label = item_label
            else:
                break
        labelled.append(
            Segment(
                ordinal=segment.ordinal,
                start_ms=segment.start_ms,
                end_ms=segment.end_ms,
                text=segment.text,
                speaker_label=segment.speaker_label,
                confidence=segment.confidence,
                agenda_item=label,
            )
        )

    transcript.segments = labelled
    return transcript


def relevant_windows(
    transcript: Transcript, *, use_class_terms: list[str]
) -> list[tuple[int, int]]:
    """Time ranges worth an expensive extraction pass.

    Section 6.3 cost control: a three hour meeting is roughly twenty to forty minutes of relevant audio, so
    finding the relevant windows before sending anything to a frontier model is most of the saving.

    Deliberately generous at the edges. A window is padded by two minutes each way, because the sentence
    that names the aquifer often comes several minutes after the sentence that names the project, and losing
    it to save a few tokens would be a false economy.
    """
    if not transcript.segments or not use_class_terms:
        return []

    padding_ms = 120_000
    terms = [term.lower() for term in use_class_terms]
    hits: list[tuple[int, int]] = []

    for segment in transcript.segments:
        lowered = segment.text.lower()
        if any(term in lowered for term in terms):
            hits.append((max(0, segment.start_ms - padding_ms), segment.end_ms + padding_ms))

    if not hits:
        return []

    merged: list[tuple[int, int]] = [hits[0]]
    for start, end in hits[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def persist(conn: Any, transcript: Transcript, *, hearing_date: date | None = None) -> None:
    """Store the transcript as a document with page level provenance.

    The transcript becomes a one page document whose text is the full transcript, plus one
    ``transcript_segment`` row per utterance. That shape is deliberate: quote verification runs against the
    document text through exactly the same code path as a PDF, so a transcript quote is held to the same
    standard as an ordinance quote, and the segment rows carry the timestamps that make a citation possible.
    """
    from sqlalchemy import delete

    from auspice.db import schema
    from auspice.pipeline.parse import parse_plain_text, persist_parsed

    parsed = parse_plain_text(
        transcript.full_text,
        document_id=transcript.document_id,
        method=ParseMethod.transcription,
    )
    persist_parsed(conn, parsed)

    conn.execute(
        delete(schema.transcript_segment).where(
            schema.transcript_segment.c.document_id == transcript.document_id
        )
    )

    if not transcript.segments:
        return

    # Character offsets into the stored document text, so a segment can be highlighted in the transcript.
    cursor = 0
    rows: list[dict[str, Any]] = []
    for segment in transcript.segments:
        rendered = f"[{segment.timestamp}] {segment.speaker_label or 'speaker'}: {segment.text}"
        rows.append(
            {
                "document_id": transcript.document_id,
                "ordinal": segment.ordinal,
                "start_ms": segment.start_ms,
                "end_ms": segment.end_ms,
                "speaker_label": segment.speaker_label,
                "maker_id": None,
                "text": segment.text,
                "char_start": cursor,
                "char_end": cursor + len(rendered),
                "agenda_item": segment.agenda_item,
                "confidence": round(segment.confidence, 3)
                if segment.confidence is not None
                else None,
            }
        )
        cursor += len(rendered) + 1

    conn.execute(schema.transcript_segment.insert(), rows)
    log.info(
        "transcript persisted",
        document_id=transcript.document_id[:12],
        segments=len(rows),
        hearing_date=hearing_date.isoformat() if hearing_date else None,
    )
