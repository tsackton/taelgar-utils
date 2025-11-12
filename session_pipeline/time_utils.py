"""Time and timestamp helper functions used across the session pipeline."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional


def parse_timecode(value: str) -> float:
    """
    Convert ``value`` (HH:MM:SS, MM:SS, or seconds) into floating-point seconds.

    The function accepts plain seconds, ``MM:SS`` pairs, or ``HH:MM:SS``
    triplets, mirroring how WebVTT and Zoom transcripts encode timestamps.
    """

    value = value.strip()
    parts = value.split(":")
    if len(parts) == 1:
        return float(parts[0])
    if len(parts) == 2:
        minutes, seconds = parts
        return float(minutes) * 60 + float(seconds)
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return float(hours) * 3600 + float(minutes) * 60 + float(seconds)
    raise ValueError(f"Unsupported time code: {value}")


def parse_vtt_timestamp(value: Optional[str]) -> float:
    """
    Parse a WebVTT timestamp (HH:MM:SS.mmm) string into seconds.

    The parser tolerates commas as decimal separators and gracefully
    handles malformed inputs by returning zero.
    """

    if not value:
        return 0.0
    sanitized = value.replace(",", ".")
    parts = sanitized.split(":")
    if len(parts) == 3:
        hours, minutes, seconds = parts
    elif len(parts) == 2:
        hours = "0"
        minutes, seconds = parts
    else:
        return 0.0
    try:
        total_seconds = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    except ValueError:
        return 0.0
    return max(0.0, total_seconds)


def format_timestamp(seconds: float) -> str:
    """
    Format ``seconds`` into a WebVTT-compatible HH:MM:SS.mmm string.
    """

    seconds = max(0.0, seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds - (hours * 3600 + minutes * 60)
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


def format_timestamp_hundredths(seconds: float) -> str:
    """
    Format ``seconds`` into ``HH:MM:SS.hh`` with rounding to hundredths.
    """

    safe_seconds = Decimal(str(max(0.0, float(seconds))))
    total_hundredths = int((safe_seconds * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    total_seconds, hundredths = divmod(total_hundredths, 100)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{hundredths:02d}"


__all__ = [
    "parse_timecode",
    "parse_vtt_timestamp",
    "format_timestamp",
    "format_timestamp_hundredths",
]
