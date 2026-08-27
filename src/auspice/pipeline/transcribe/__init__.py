"""Stage 3: hearing audio to a citable transcript.

The single most underexploited input in this market. The minutes record that a motion failed; the recording
records why, and the why is what generalises to the next decision.
"""

from __future__ import annotations

from auspice.pipeline.transcribe.audio import (
    OVERLAP_SECONDS,
    TARGET_SAMPLE_RATE,
    WINDOW_SECONDS,
    Segment,
    Transcript,
    align_to_agenda,
    extract_audio,
    ffmpeg_available,
    persist,
    probe_duration,
    relevant_windows,
    transcribe,
)

__all__ = [
    "OVERLAP_SECONDS",
    "TARGET_SAMPLE_RATE",
    "WINDOW_SECONDS",
    "Segment",
    "Transcript",
    "align_to_agenda",
    "extract_audio",
    "ffmpeg_available",
    "persist",
    "probe_duration",
    "relevant_windows",
    "transcribe",
]
