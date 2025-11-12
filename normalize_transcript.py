#!/usr/bin/env python3

"""Normalize raw transcript outputs into a canonical JSON schema."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from webvtt import WebVTT

from session_pipeline.offsets import determine_offset
from session_pipeline.segments import group_words_into_segments
from session_pipeline.time_utils import parse_timecode


SCHEMA_VERSION = "1.0.0"

FORMAT_ELEVENLABS = "elevenlabs_json"
FORMAT_PLAIN_TEXT = "plain_text"
FORMAT_VTT_VOICE = "vtt_voice"
FORMAT_VTT_SPEAKER = "vtt_speaker"
FORMAT_WHISPER_DIAR = "whisper_diarization"

FORMAT_CHOICES = {
    FORMAT_ELEVENLABS,
    FORMAT_PLAIN_TEXT,
    FORMAT_VTT_VOICE,
    FORMAT_VTT_SPEAKER,
    FORMAT_WHISPER_DIAR,
}

DEFAULT_WORD_GAP_SECONDS = 1.0
DEFAULT_UNKNOWN_SPEAKER = "unknown_speaker"

VOICE_TAG_PATTERN = re.compile(r"^<v\s+([^>]+)>(.*)$", re.IGNORECASE)
COLON_SPEAKER_PATTERN = re.compile(r"^\s*([^:]{1,100})\s*:\s*(.+)$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize a transcript to canonical JSON.")
    parser.add_argument("input_path", type=Path, help="Path to the transcript input file.")
    parser.add_argument(
        "--input-format",
        choices=sorted(FORMAT_CHOICES),
        required=True,
        help="Explicitly choose how to interpret the input file.",
    )
    parser.add_argument(
        "--diarization",
        type=Path,
        help="Path to diarization JSON (required for whisper_diarization format).",
    )
    parser.add_argument(
        "--session-id",
        help="Optional session identifier stored in the normalized bundle.",
    )
    parser.add_argument(
        "--source-id",
        help="Identifier for the audio source; defaults to the input stem.",
    )
    parser.add_argument(
        "--offset",
        type=float,
        default=None,
        help="Manual offset in seconds from the start of the session.",
    )
    parser.add_argument(
        "--offsets-json",
        type=Path,
        help="JSON produced by get_audio_offsets.py for automatic offsets.",
    )
    parser.add_argument(
        "--audio-path",
        type=Path,
        help="Path to the source audio file (required when using --offsets-json).",
    )
    parser.add_argument(
        "--word-gap-seconds",
        type=float,
        default=DEFAULT_WORD_GAP_SECONDS,
        help="Maximum gap between words before a new segment is started (ElevenLabs/Whisper).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Destination for the normalized JSON (defaults to <input>.normalized.json).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = args.input_path.expanduser().resolve()
    if not input_path.exists():
        raise SystemExit(f"Input file not found: {input_path}")

    if args.input_format == FORMAT_WHISPER_DIAR and not args.diarization:
        raise SystemExit("--diarization is required when --input-format=whisper_diarization")

    segments_data: List[Dict[str, Any]]
    speaker_hints: Dict[str, Dict[str, Any]]
    extras: Dict[str, Any]

    if args.input_format == FORMAT_ELEVENLABS:
        segments_data, speaker_hints, extras = parse_elevenlabs_json(
            input_path, gap_seconds=args.word_gap_seconds
        )
    elif args.input_format == FORMAT_PLAIN_TEXT:
        segments_data, speaker_hints, extras = parse_plain_text(input_path)
    elif args.input_format == FORMAT_VTT_VOICE:
        segments_data, speaker_hints, extras = parse_vtt_voice_tags(input_path)
    elif args.input_format == FORMAT_VTT_SPEAKER:
        segments_data, speaker_hints, extras = parse_vtt_speaker_cues(input_path)
    elif args.input_format == FORMAT_WHISPER_DIAR:
        segments_data, speaker_hints, extras = parse_whisper_with_diarization(
            input_path, args.diarization.expanduser().resolve(), gap_seconds=args.word_gap_seconds
        )
    else:
        raise SystemExit(f"Unsupported input format: {args.input_format}")

    source_id = args.source_id or input_path.stem

    audio_path = args.audio_path.expanduser().resolve() if args.audio_path else None
    offset_seconds = determine_offset(
        manual_offset=args.offset,
        offsets_json=args.offsets_json,
        audio_path=audio_path,
    )

    segments = build_segments(segments_data, source_id)
    speakers = build_speakers(segments, speaker_hints)

    source_block: Dict[str, Any] = {
        "id": source_id,
        "path": str(input_path),
        "offset_seconds": offset_seconds,
    }
    if audio_path:
        source_block["audio_path"] = str(audio_path)
    if extras.get("duration_seconds") is not None:
        source_block["duration_seconds"] = float(extras["duration_seconds"])

    normalized: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "source": source_block,
        "segments": segments,
        "speakers": speakers,
        "meta": {
            "input_format": args.input_format,
            "input_path": str(input_path),
        },
    }

    if args.session_id:
        normalized["session_id"] = args.session_id

    input_details = {k: v for k, v in extras.items() if k != "duration_seconds"}
    if input_details:
        normalized["meta"]["input_details"] = input_details

    output_path = args.output
    if output_path is None:
        if args.session_id:
            output_path = input_path.parent / f"{args.session_id}-{args.input_format}-normalized.json"
        else:
            output_path = input_path.with_suffix(".normalized.json")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fh:
        json.dump(normalized, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    print(f"Wrote normalized transcript to {output_path}")
    return 0


# ---------------------------------------------------------------------------
# Segment builders
# ---------------------------------------------------------------------------


def build_segments(raw_segments: List[Dict[str, Any]], source_id: str) -> List[Dict[str, Any]]:
    segments: List[Dict[str, Any]] = []
    for index, raw in enumerate(sorted(raw_segments, key=lambda item: item.get("start", 0.0))):
        start = float(raw.get("start", 0.0))
        end = float(raw.get("end", start))
        speaker_id = str(raw.get("speaker_id") or DEFAULT_UNKNOWN_SPEAKER)
        text = (raw.get("text") or "").strip()

        segment: Dict[str, Any] = {
            "id": f"seg_{index:06d}",
            "start": start,
            "end": max(end, start),
            "speaker_id": speaker_id,
            "text": text,
        }

        raw_words = raw.get("words") or []
        words: List[Dict[str, Any]] = []
        for word in raw_words:
            word_text = (word.get("text") or "").strip()
            if not word_text:
                continue
            word_start = float(word.get("start", start))
            word_end = float(word.get("end", word_start))
            word_speaker = str(word.get("speaker_id") or speaker_id)
            words.append(
                {
                    "start": word_start,
                    "end": max(word_end, word_start),
                    "text": word_text,
                    "speaker_id": word_speaker,
                    "source_id": source_id,
                }
            )

        segment["words"] = words

        if raw.get("meta"):
            segment["meta"] = raw["meta"]

        segments.append(segment)

    return segments


def build_speakers(
    segments: Iterable[Dict[str, Any]],
    hints: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    speaker_map: Dict[str, Dict[str, Any]] = {}

    for seg in segments:
        speaker_id = str(seg.get("speaker_id") or DEFAULT_UNKNOWN_SPEAKER)
        if speaker_id not in speaker_map:
            hint = hints.get(speaker_id, {})
            speaker_entry: Dict[str, Any] = {
                "id": speaker_id,
                "label": hint.get("label", speaker_id),
            }
            if hint.get("meta"):
                speaker_entry["meta"] = hint["meta"]
            speaker_map[speaker_id] = speaker_entry

    return list(speaker_map.values())


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def parse_elevenlabs_json(
    path: Path,
    *,
    gap_seconds: float,
) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]], Dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    words_data = data.get("words") or []

    words: List[Dict[str, Any]] = []
    speaker_hints: Dict[str, Dict[str, Any]] = {}

    for raw in words_data:
        if not isinstance(raw, dict):
            continue
        word_type = raw.get("type", "word")
        if word_type == "spacing":
            continue

        text = (raw.get("text") or raw.get("word") or "").strip()
        if not text and word_type != "audio_event":
            continue

        if word_type == "audio_event":
            text = f"[{text.strip('[]') or 'event'}]"

        start = raw.get("start")
        if start is None:
            continue
        end = raw.get("end", start)

        speaker = raw.get("speaker") or raw.get("speaker_id") or raw.get("channel_index")
        speaker_id = str(speaker) if speaker is not None else DEFAULT_UNKNOWN_SPEAKER
        speaker_hints.setdefault(speaker_id, {"label": speaker_id})

        words.append(
            {
                "start": float(start),
                "end": float(end if end is not None else start),
                "text": text,
                "speaker_id": speaker_id,
            }
        )

    segments = group_words_into_segments(words, gap_seconds)

    extras: Dict[str, Any] = {}
    if data.get("duration") is not None:
        extras["duration_seconds"] = float(data["duration"])
    extras["source"] = "elevenlabs_scribe_v1"

    return segments, speaker_hints, extras


def parse_plain_text(path: Path) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]], Dict[str, Any]]:
    pattern = re.compile(r"^(?P<speaker>.+?)\s*\((?P<time>\d+:\d+(?::\d+)?)\):\s*(?P<text>.*)$")
    entries: List[Dict[str, Any]] = []
    speaker_hints: Dict[str, Dict[str, Any]] = {}

    current: Optional[Dict[str, Any]] = None
    text_lines: List[str] = []

    def flush() -> None:
        nonlocal current, text_lines
        if not current:
            return
        text = " ".join(line.strip() for line in text_lines if line.strip())
        current_entry = {
            "start": current["start"],
            "speaker_id": current["speaker_id"],
            "text": text,
        }
        entries.append(current_entry)
        speaker_hints.setdefault(current_entry["speaker_id"], {"label": current_entry["speaker_id"]})
        current = None
        text_lines = []

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip() and current is None:
            continue

        match = pattern.match(raw_line)
        if match:
            flush()
            speaker = match.group("speaker").strip() or DEFAULT_UNKNOWN_SPEAKER
            start = parse_timecode(match.group("time"))
            text_initial = match.group("text").strip()
            current = {"speaker_id": speaker, "start": start}
            text_lines = [text_initial] if text_initial else []
            continue

        if current is None:
            raise ValueError(f"Unrecognised line format: {raw_line}")

        text_lines.append(raw_line)

    flush()

    entries.sort(key=lambda item: item["start"])

    for idx, entry in enumerate(entries):
        if idx + 1 < len(entries):
            next_start = entries[idx + 1]["start"]
            entry["end"] = max(next_start, entry["start"])
            entry.setdefault("meta", {})["end_inferred_from_next"] = True
        else:
            entry["end"] = entry["start"]
            entry.setdefault("meta", {})["end_inferred_no_successor"] = True
        entry["words"] = []

    extras = {"source": "plain_text"}
    return entries, speaker_hints, extras


def parse_vtt_voice_tags(path: Path) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]], Dict[str, Any]]:
    vtt = WebVTT().read(path)
    segments: List[Dict[str, Any]] = []
    speaker_hints: Dict[str, Dict[str, Any]] = {}

    previous_speaker = DEFAULT_UNKNOWN_SPEAKER

    for cue in vtt:
        cue_speaker = (getattr(cue, "voice", None) or previous_speaker or DEFAULT_UNKNOWN_SPEAKER).strip()
        lines: List[str] = []

        raw_text = getattr(cue, "raw_text", cue.text)
        for raw_line in raw_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            speaker_candidate, content = extract_voice_line(line, cue_speaker)
            if speaker_candidate is not None:
                cue_speaker = speaker_candidate or cue_speaker
            if content:
                lines.append(content)

        if not lines:
            continue

        text = " ".join(lines).strip()
        if not text:
            continue

        start = parse_timecode(cue.start)
        end = parse_timecode(cue.end)
        speaker_id = cue_speaker or previous_speaker or DEFAULT_UNKNOWN_SPEAKER
        speaker_id = str(speaker_id)

        speaker_hints.setdefault(speaker_id, {"label": speaker_id})

        segments.append(
            {
                "start": start,
                "end": end,
                "speaker_id": speaker_id,
                "text": text,
                "words": [],
            }
        )

        previous_speaker = speaker_id

    extras = {"source": "webvtt_voice_tags"}
    return segments, speaker_hints, extras


def parse_vtt_speaker_cues(path: Path) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]], Dict[str, Any]]:
    vtt = WebVTT().read(path)
    segments: List[Dict[str, Any]] = []
    speaker_hints: Dict[str, Dict[str, Any]] = {}

    for cue in vtt:
        lines: List[str] = []
        cue_speaker: Optional[str] = None

        for raw_line in cue.text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            match = COLON_SPEAKER_PATTERN.match(line)
            if match and cue_speaker is None:
                cue_speaker = match.group(1).strip()
                rest = match.group(2).strip()
                if rest:
                    lines.append(rest)
            else:
                lines.append(line)

        if not lines:
            continue

        text = " ".join(lines).strip()
        if not text:
            continue

        start = parse_timecode(cue.start)
        end = parse_timecode(cue.end)
        speaker_id = str(cue_speaker or DEFAULT_UNKNOWN_SPEAKER)
        speaker_hints.setdefault(speaker_id, {"label": speaker_id})

        segments.append(
            {
                "start": start,
                "end": end,
                "speaker_id": speaker_id,
                "text": text,
                "words": [],
            }
        )

    extras = {"source": "webvtt_speaker_cues"}
    return segments, speaker_hints, extras


def parse_whisper_with_diarization(
    transcript_path: Path,
    diarization_path: Path,
    *,
    gap_seconds: float,
) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]], Dict[str, Any]]:
    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    diarization = json.loads(diarization_path.read_text(encoding="utf-8"))

    words_data = transcript.get("words") or []
    diar_entries = diarization or []

    words = [
        {
            "start": float(item.get("start", 0.0)),
            "end": float(item.get("end", item.get("start", 0.0))),
            "text": (item.get("word") or item.get("text") or "").strip(),
        }
        for item in words_data
        if isinstance(item, dict)
    ]
    words.sort(key=lambda item: item["start"])

    diar_segments = [
        {
            "speaker": str(entry.get("speaker") or DEFAULT_UNKNOWN_SPEAKER),
            "start": float(entry.get("segment", {}).get("start", 0.0)),
            "end": float(entry.get("segment", {}).get("end", 0.0)),
        }
        for entry in diar_entries
        if isinstance(entry, dict) and isinstance(entry.get("segment"), dict)
    ]
    diar_segments.sort(key=lambda item: item["start"])

    segments: List[Dict[str, Any]] = []
    speaker_hints: Dict[str, Dict[str, Any]] = {}

    word_index = 0
    total_words = len(words)

    for diar in diar_segments:
        start = diar["start"]
        end = max(diar["end"], start)
        speaker_id = diar["speaker"]

        segment_words: List[Dict[str, Any]] = []

        while word_index < total_words:
            word = words[word_index]
            word_start = word["start"]
            word_end = word["end"]

            if word_end <= start:
                word_index += 1
                continue
            if word_start >= end:
                break

            segment_words.append(
                {
                    "start": word_start,
                    "end": word_end,
                    "text": word["text"],
                    "speaker_id": speaker_id,
                }
            )
            word_index += 1

        if not segment_words:
            continue

        segment_text = " ".join(word["text"] for word in segment_words).strip()
        if not segment_text:
            continue

        segments.append(
            {
                "start": segment_words[0]["start"],
                "end": segment_words[-1]["end"],
                "speaker_id": speaker_id,
                "text": segment_text,
                "words": segment_words,
            }
        )

        speaker_hints.setdefault(speaker_id, {"label": speaker_id})

    extras: Dict[str, Any] = {"source": "whisper_json_with_diarization"}
    if transcript.get("duration") is not None:
        extras["duration_seconds"] = float(transcript["duration"])

    return segments, speaker_hints, extras


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def extract_voice_line(line: str, previous_speaker: str) -> Tuple[Optional[str], str]:
    match = VOICE_TAG_PATTERN.match(line)
    if match:
        speaker = match.group(1).strip()
        content = match.group(2).strip()
        if content.endswith("</v>"):
            content = content[:-4].strip()
        return speaker, content

    if line.endswith("</v>"):
        line = line[:-4].strip()

    return None, line


if __name__ == "__main__":
    raise SystemExit(main())
