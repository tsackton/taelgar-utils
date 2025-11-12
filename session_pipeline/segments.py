"""Helpers for manipulating transcript segments and word timelines."""

from __future__ import annotations

from typing import Any, Dict, List

DEFAULT_UNKNOWN_SPEAKER = "unknown_speaker"


def group_words_into_segments(
    words: List[Dict[str, Any]],
    gap_seconds: float,
) -> List[Dict[str, Any]]:
    """
    Group sorted ``words`` (each with ``start``, ``end``, ``speaker_id``) into segments.

    A new segment is started when the speaker changes or the gap between words
    exceeds ``gap_seconds``.
    """

    if not words:
        return []

    segments: List[Dict[str, Any]] = []
    current_words: List[Dict[str, Any]] = [words[0]]
    current_speaker = words[0]["speaker_id"]

    for word in words[1:]:
        gap = word["start"] - current_words[-1]["end"]
        if word["speaker_id"] != current_speaker or gap > gap_seconds:
            segments.append(segment_from_words(current_words))
            current_words = [word]
            current_speaker = word["speaker_id"]
        else:
            current_words.append(word)

    segments.append(segment_from_words(current_words))
    return segments


def segment_from_words(words: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Convert ``words`` belonging to a single speaker into a segment dictionary.
    """

    speaker_id = words[0]["speaker_id"] if words else DEFAULT_UNKNOWN_SPEAKER
    text = " ".join(word["text"] for word in words).strip()
    return {
        "start": words[0]["start"],
        "end": words[-1]["end"],
        "speaker_id": speaker_id,
        "text": text,
        "words": words,
    }


__all__ = [
    "group_words_into_segments",
    "segment_from_words",
]
