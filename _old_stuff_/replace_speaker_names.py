#!/usr/bin/env python3

"""Apply speaker mapping to a canonical bundle and emit updated outputs."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


FORMAT_JSON = "json"
FORMAT_VTT = "vtt"
FORMAT_WHISPER_DIAR = "whisper_diarization"
FORMAT_ALL = "all"

DEFAULT_UNKNOWN = "unknown_speaker"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replace speaker IDs in canonical outputs.")
    parser.add_argument("canonical_bundle", type=Path, help="Path to canonical synchronized JSON bundle.")
    parser.add_argument("speaker_mapping", type=Path, help="JSON mapping raw speaker IDs to canonical names.")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("named_transcripts"),
        help="Directory to write outputs (default: named_transcripts).",
    )
    parser.add_argument(
        "--prefix",
        default="named",
        help="Prefix for output files (default: named).",
    )
    parser.add_argument(
        "--format",
        choices=[FORMAT_JSON, FORMAT_VTT, FORMAT_WHISPER_DIAR, FORMAT_ALL],
        default=FORMAT_ALL,
        help="Output format(s) to produce (default: all).",
    )
    parser.add_argument(
        "--canonical-diarization",
        type=Path,
        help="Optional path to canonical diarization JSON (required when outputting whisper/diarization pair).",
    )
    parser.add_argument(
        "--canonical-whisper",
        type=Path,
        help="Optional path to canonical whisper JSON (required when outputting whisper/diarization pair).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    bundle = json.loads(args.canonical_bundle.read_text(encoding="utf-8"))
    mapping = load_mapping(args.speaker_mapping)

    out_dir = args.out_dir.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    formats = determine_formats(args.format)

    if FORMAT_JSON in formats:
        updated_bundle = apply_mapping_to_bundle(bundle, mapping)
        json_path = out_dir / f"{args.prefix}.json"
        write_json(json_path, updated_bundle)
        print(f"Wrote normalized bundle with canonical speakers to {json_path}")

    if FORMAT_VTT in formats:
        updated_segments = apply_mapping_to_segments(bundle.get("segments") or [], mapping)
        vtt_path = out_dir / f"{args.prefix}.vtt"
        write_vtt(vtt_path, updated_segments)
        print(f"Wrote VTT with canonical speakers to {vtt_path}")

    if FORMAT_WHISPER_DIAR in formats:
        if not args.canonical_whisper or not args.canonical_diarization:
            raise SystemExit("--canonical-whisper and --canonical-diarization are required for whisper_diarization output.")
        whisper = json.loads(args.canonical_whisper.read_text(encoding="utf-8"))
        diar = json.loads(args.canonical_diarization.read_text(encoding="utf-8"))
        whisper_path = out_dir / f"{args.prefix}.whisper.json"
        diar_path = out_dir / f"{args.prefix}.diarization.json"
        updated_whisper = apply_mapping_to_whisper(whisper, mapping)
        updated_diar = apply_mapping_to_diarization(diar, mapping)
        write_json(whisper_path, updated_whisper)
        write_json(diar_path, updated_diar)
        print(f"Wrote whisper transcript to {whisper_path}")
        print(f"Wrote diarization to {diar_path}")

    return 0


def load_mapping(path: Path) -> Dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return {str(key): str(value) for key, value in data.items()}
    raise ValueError("Speaker mapping must be a JSON object mapping raw IDs to canonical names.")


def determine_formats(requested: str) -> List[str]:
    if requested == FORMAT_ALL:
        return [FORMAT_JSON, FORMAT_VTT, FORMAT_WHISPER_DIAR]
    return [requested]


def apply_mapping_to_bundle(bundle: Dict[str, Any], mapping: Dict[str, str]) -> Dict[str, Any]:
    updated = deepcopy(bundle)
    updated["segments"] = apply_mapping_to_segments(bundle.get("segments") or [], mapping)
    if "speakers" in updated:
        updated["speakers"] = update_speakers(updated["speakers"], mapping)
    return updated


def update_speakers(speakers: Iterable[Dict[str, Any]], mapping: Dict[str, str]) -> List[Dict[str, Any]]:
    updated: List[Dict[str, Any]] = []
    for speaker in speakers:
        new_speaker = dict(speaker)
        speaker_id = str(speaker.get("id") or DEFAULT_UNKNOWN)
        canonical = mapping.get(speaker_id)
        if canonical:
            new_speaker["label"] = canonical
        updated.append(new_speaker)
    return updated


def apply_mapping_to_segments(
    segments: Iterable[Dict[str, Any]],
    mapping: Dict[str, str],
) -> List[Dict[str, Any]]:
    updated_segments: List[Dict[str, Any]] = []
    for segment in segments:
        new_segment = dict(segment)
        speaker_id = str(segment.get("speaker_id") or DEFAULT_UNKNOWN)
        canonical = mapping.get(speaker_id)
        if canonical:
            new_segment["speaker_id"] = canonical
        updated_segments.append(new_segment)
    return updated_segments


def apply_mapping_to_whisper(whisper: Dict[str, Any], mapping: Dict[str, str]) -> Dict[str, Any]:
    updated = deepcopy(whisper)
    # Whisper transcripts typically do not include speaker IDs, but keep a hook if present
    for segment in updated.get("segments", []):
        speaker_id = str(segment.get("speaker")) if "speaker" in segment else None
        if speaker_id and speaker_id in mapping:
            segment["speaker"] = mapping[speaker_id]
    return updated


def apply_mapping_to_diarization(
    diarization: Iterable[Dict[str, Any]],
    mapping: Dict[str, str],
) -> List[Dict[str, Any]]:
    updated: List[Dict[str, Any]] = []
    for entry in diarization:
        new_entry = dict(entry)
        speaker_id = str(entry.get("speaker") or DEFAULT_UNKNOWN)
        canonical = mapping.get(speaker_id)
        if canonical:
            new_entry["speaker"] = canonical
        updated.append(new_entry)
    return updated


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def write_vtt(path: Path, segments: Iterable[Dict[str, Any]]) -> None:
    lines = ["WEBVTT", ""]
    for idx, segment in enumerate(sorted(segments, key=lambda seg: seg.get("start", 0.0)), start=1):
        start_ts = format_timestamp(float(segment.get("start", 0.0)))
        end_ts = format_timestamp(float(segment.get("end", 0.0)))
        speaker = str(segment.get("speaker_id") or DEFAULT_UNKNOWN)
        text = (segment.get("text") or "").strip()
        lines.append(str(idx))
        lines.append(f"{start_ts} --> {end_ts}")
        lines.append(f"{speaker}: {text}")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def format_timestamp(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds - (hours * 3600 + minutes * 60)
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


if __name__ == "__main__":
    raise SystemExit(main())
