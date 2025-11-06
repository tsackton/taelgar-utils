#!/usr/bin/env python3

"""
Normalize various transcript formats into a clean WebVTT file.

Currently supports:
* WebVTT input (with aggressive normalization of speaker tags / styling)
* ElevenLabs JSON (SpeechToTextChunkResponseModel) output

Usage examples:
    python normalize_transcript.py transcript.vtt
    python normalize_transcript.py session.elevenlabs.json --output-prefix session_clean
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List, Sequence

from webvtt import WebVTT


DEFAULT_SPEAKER = "Unknown Speaker"
MAX_CUE_DURATION_SECONDS = 60.0


@dataclass
class Segment:
    speaker: str
    start: float
    end: float
    text: str

    def merge_with(self, other: "Segment") -> "Segment":
        return Segment(
            speaker=self.speaker,
            start=min(self.start, other.start),
            end=max(self.end, other.end),
            text=_merge_text(self.text, other.text),
        )


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normalize JSON/WebVTT transcripts into clean WebVTT output."
    )
    parser.add_argument("input_path", type=Path, help="Input transcript file (VTT or JSON).")
    parser.add_argument(
        "--input-format",
        choices=("auto", "webvtt", "elevenlabs_json"),
        default="auto",
        help="Explicitly choose the parser. Defaults to auto-detection based on file extension.",
    )
    parser.add_argument(
        "--output-prefix",
        help="Optional prefix for the output filename. When omitted, defaults to '<input>.cleaned.vtt'.",
    )
    parser.add_argument(
        "--max-cue-seconds",
        type=float,
        default=MAX_CUE_DURATION_SECONDS,
        help="Maximum duration for any merged cue before forcing a split.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_arguments()

    input_path = args.input_path.expanduser().resolve()
    if not input_path.exists():
        raise SystemExit(f"Input file not found: {input_path}")

    parser = resolve_parser(input_path, args.input_format)
    raw_segments = list(parser(input_path))
    if not raw_segments:
        raise SystemExit("No timed speech segments found in input.")

    merged_segments = merge_segments(
        sorted(raw_segments, key=lambda seg: seg.start),
        max_cue_seconds=args.max_cue_seconds,
    )

    output_path = resolve_output_path(input_path, args.output_prefix)
    write_webvtt(merged_segments, output_path)

    print(f"Wrote {output_path}")
    return 0


def resolve_parser(path: Path, explicit_format: str) -> Callable[[Path], Iterable[Segment]]:
    if explicit_format == "webvtt":
        return parse_webvtt
    if explicit_format == "elevenlabs_json":
        return parse_elevenlabs_json

    suffix = path.suffix.lower()
    if suffix == ".vtt":
        return parse_webvtt
    if suffix == ".json":
        return parse_elevenlabs_json

    raise SystemExit(
        f"Could not infer parser for {path.name}. Use --input-format to choose one explicitly."
    )


def resolve_output_path(input_path: Path, prefix: str | None) -> Path:
    if prefix:
        return input_path.with_name(f"{prefix}.vtt")
    return input_path.with_name(f"{input_path.name}.cleaned.vtt")


# -----------------
# WebVTT utilities
# -----------------

VOICE_TAG_PATTERN = re.compile(r"<v\s+([^>]+)>(.*)", re.IGNORECASE)
TAG_PATTERN = re.compile(r"</?[^>]+>")
COLON_SPEAKER_PATTERN = re.compile(r"^\s*([^:]{1,100})\s*:\s*(.+)$")


def parse_webvtt(path: Path) -> Iterable[Segment]:
    for caption in WebVTT().read(path):
        start = _timestamp_to_seconds(caption.start)
        end = _timestamp_to_seconds(caption.end)
        if end <= start:
            continue

        speaker, text = _extract_speaker_and_text(caption.text)
        if not text:
            continue

        yield Segment(speaker=speaker, start=start, end=end, text=text)


def _extract_speaker_and_text(raw_text: str) -> tuple[str, str]:
    speaker: str | None = None
    lines: List[str] = []

    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        voice_match = VOICE_TAG_PATTERN.match(line)
        if voice_match:
            possible_speaker = _clean_text(voice_match.group(1))
            content = voice_match.group(2)
            # Voice tags can optionally close later in the line.
            if "</v>" in content:
                content = content.split("</v>", 1)[0]
            content = _clean_text(content)
            if possible_speaker:
                speaker = speaker or possible_speaker
            if content:
                lines.append(content)
            continue

        colon_match = COLON_SPEAKER_PATTERN.match(line)
        if colon_match:
            possible_speaker = _clean_text(colon_match.group(1))
            content = _clean_text(colon_match.group(2))
            if possible_speaker:
                speaker = speaker or possible_speaker
            if content:
                lines.append(content)
            continue

        cleaned = _clean_text(line)
        if cleaned:
            lines.append(cleaned)

    joined = " ".join(lines).strip()
    if not joined:
        return DEFAULT_SPEAKER, ""

    return speaker or DEFAULT_SPEAKER, joined


def _clean_text(value: str) -> str:
    no_tags = TAG_PATTERN.sub("", value)
    # Collapse internal whitespace while preserving single spaces.
    return re.sub(r"\s+", " ", no_tags).strip()


def _timestamp_to_seconds(timestamp: str) -> float:
    if "," in timestamp:
        timestamp = timestamp.replace(",", ".")

    try:
        hours, minutes, seconds = timestamp.split(":")
    except ValueError:
        raise ValueError(f"Invalid WebVTT timestamp: {timestamp}") from None

    return (
        int(hours) * 3600
        + int(minutes) * 60
        + float(seconds)
    )


# ------------------------
# ElevenLabs JSON parsing
# ------------------------

PUNCTUATION_NO_SPACE_BEFORE = {".", ",", "!", "?", ":", ";", ")", "]", "}", "..."}
PUNCTUATION_NO_SPACE_AFTER = {"(", "[", "{"}


def parse_elevenlabs_json(path: Path) -> Iterable[Segment]:
    data = json.loads(path.read_text(encoding="utf-8"))
    words = data.get("words") or []
    if not isinstance(words, Sequence):
        return []

    current_tokens: List[str] = []
    current_speaker: str | None = None
    start_time: float | None = None
    end_time: float | None = None

    for raw_word in words:
        if not isinstance(raw_word, dict):
            continue

        speaker_id = raw_word.get("speaker_id") or raw_word.get("channel_index")
        speaker = f"{speaker_id}" if speaker_id else DEFAULT_SPEAKER

        word_type = raw_word.get("type", "word")
        word_text = (raw_word.get("text") or "").strip()
        token = _normalize_word(word_text, word_type)
        start = raw_word.get("start")
        end = raw_word.get("end")

        if token is None and start is None and end is None:
            continue

        if current_speaker is None:
            current_speaker = speaker
        change_in_speaker = speaker != current_speaker

        if change_in_speaker and current_tokens:
            if start_time is not None and end_time is not None and end_time > start_time:
                text = _join_tokens(current_tokens)
                if text:
                    yield Segment(
                        speaker=current_speaker,
                        start=start_time,
                        end=end_time,
                        text=text,
                    )
            current_tokens = []
            current_speaker = speaker
            start_time = None
            end_time = None

        if token is not None:
            current_tokens.append(token)

        if start is not None:
            start_time = start if start_time is None else min(start_time, start)
        if end is not None:
            end_time = end if end_time is None else max(end_time, end)

    if current_tokens and start_time is not None and end_time is not None and end_time > start_time:
        text = _join_tokens(current_tokens)
        if text:
            yield Segment(
                speaker=current_speaker or DEFAULT_SPEAKER,
                start=start_time,
                end=end_time,
                text=text,
            )


def _normalize_word(text: str, word_type: str) -> str | None:
    if not text and word_type != "spacing":
        return None

    if word_type == "spacing":
        return ""
    if word_type == "audio_event":
        cleaned = text.strip("[]")
        return f"[{cleaned or 'audio'}]"
    return text


def _join_tokens(tokens: Sequence[str]) -> str:
    result = ""
    for token in tokens:
        if not token:
            continue

        needs_space = True
        if not result:
            needs_space = False
        elif token in PUNCTUATION_NO_SPACE_BEFORE or token.startswith("'"):
            needs_space = False
        elif result[-1] == " ":
            needs_space = False
        elif token and token[0] in PUNCTUATION_NO_SPACE_AFTER:
            needs_space = True

        if needs_space:
            result += " "
        result += token

    return result.strip()


# ------------------------
# Shared merge / writing
# ------------------------

def merge_segments(segments: Sequence[Segment], max_cue_seconds: float) -> List[Segment]:
    if not segments:
        return []

    merged: List[Segment] = []
    current = segments[0]

    for segment in segments[1:]:
        same_speaker = segment.speaker == current.speaker
        prospective_duration = max(segment.end, current.end) - current.start

        if same_speaker and prospective_duration <= max_cue_seconds:
            current = current.merge_with(segment)
            continue

        merged.append(current)
        current = segment

    merged.append(current)
    return merged


def write_webvtt(segments: Sequence[Segment], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file_obj:
        file_obj.write("WEBVTT\n\n")
        for segment in segments:
            start = _format_timestamp(segment.start)
            end = _format_timestamp(segment.end)
            cue_text = f"{segment.speaker}: {segment.text}"
            file_obj.write(f"{start} --> {end}\n{cue_text}\n\n")


def _format_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds - (hours * 3600 + minutes * 60)
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


def _merge_text(existing: str, new: str) -> str:
    if not existing:
        return new
    if not new:
        return existing

    if existing[-1] in {" ", "\n", "-"} or new[0] in {".", ",", "!", "?", ":", ";"}:
        return existing + new
    return f"{existing} {new}"


if __name__ == "__main__":
    raise SystemExit(main())

