#!/usr/bin/env python3

"""Aggregate normalized transcripts into per-method bundles."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


DEFAULT_UNKNOWN = "unknown_speaker"


@dataclass
class MethodSpec:
    name: str
    inputs: List[Path]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aggregate normalized transcripts per method.")
    parser.add_argument("--session-id", required=True, help="Session identifier (used as output directory name).")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("."),
        help="Root directory for outputs (defaults to current directory).",
    )
    parser.add_argument(
        "--method",
        action="append",
        nargs="+",
        metavar=("NAME", "INPUT"),
        help="Define a method and its normalized transcript inputs. May be repeated.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    methods = parse_methods(args.method)
    if not methods:
        raise SystemExit("No methods specified. Use --method NAME file1 file2 ...")

    session_dir = (args.out_dir.expanduser().resolve() / args.session_id)
    session_dir.mkdir(parents=True, exist_ok=True)

    for method in methods:
        method_dir = session_dir / method.name
        method_dir.mkdir(parents=True, exist_ok=True)
        bundles = [load_bundle(path) for path in method.inputs]
        if not bundles:
            print(f"Warning: method '{method.name}' has no valid inputs; skipping.")
            continue

        segments, words = aggregate_segments(bundles, method.name)
        if not segments:
            print(f"Warning: method '{method.name}' produced no segments; skipping outputs.")
            continue

        timeline_start = min(seg["abs_start"] for seg in segments)
        normalized_segments = normalize_segments(segments, timeline_start)
        normalized_words = normalize_words(words, timeline_start)

        whisper_payload = build_whisper_payload(method.name, normalized_segments, normalized_words, timeline_start)
        diarization_payload = build_diarization_payload(normalized_segments, method.name, bundles)
        vtt_text = build_vtt_text(normalized_segments)

        whisper_path = method_dir / f"{method.name}.whisper.json"
        diar_path = method_dir / f"{method.name}.diarization.json"
        vtt_path = method_dir / f"{method.name}.vtt"

        write_json(whisper_path, whisper_payload)
        write_json(diar_path, diarization_payload)
        vtt_path.write_text(vtt_text, encoding="utf-8")

        print(f"Wrote method outputs to {method_dir}")

    return 0


def parse_methods(raw_methods: Optional[List[List[str]]]) -> List[MethodSpec]:
    if not raw_methods:
        return []
    specs: List[MethodSpec] = []
    for entry in raw_methods:
        if len(entry) < 2:
            raise SystemExit("Each --method requires a name followed by at least one input path.")
        name = entry[0]
        inputs = [Path(item).expanduser().resolve() for item in entry[1:]]
        specs.append(MethodSpec(name=name, inputs=inputs))
    return specs


def load_bundle(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - defensive
        raise SystemExit(f"Failed to read {path}: {exc}") from exc
    data.setdefault("_bundle_path", str(path))
    return data


def aggregate_segments(bundles: Sequence[Dict[str, Any]], method_name: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    segments_out: List[Dict[str, Any]] = []
    words_out: List[Dict[str, Any]] = []

    for bundle in bundles:
        segments = bundle.get("segments") or []
        source = bundle.get("source") or {}
        offset = float(source.get("offset_seconds") or 0.0)
        source_id = str(source.get("id") or Path(bundle.get("_bundle_path", "")).stem)
        source_path = source.get("path") or bundle.get("_bundle_path")
        method_source_id = f"{method_name}__{source_id}"

        for segment in segments:
            raw_speaker = str(segment.get("speaker_id") or DEFAULT_UNKNOWN)
            namespaced_speaker = f"{method_source_id}__{raw_speaker}"
            abs_start = offset + float(segment.get("start", 0.0))
            abs_end = offset + float(segment.get("end", segment.get("start", 0.0)))
            text = (segment.get("text") or "").strip()

            segments_out.append(
                {
                    "abs_start": abs_start,
                    "abs_end": abs_end,
                    "text": text,
                    "speaker_id": namespaced_speaker,
                    "raw_speaker": raw_speaker,
                    "source_id": source_id,
                    "source_path": source_path,
                }
            )

            words = segment.get("words") or []
            if words:
                word_added = False
                for word in words:
                    word_text = (word.get("text") or word.get("word") or "").strip()
                    if not word_text:
                        continue
                    start_val = float(word.get("start", segment.get("start", 0.0)))
                    end_val = float(word.get("end", word.get("start", start_val)))
                    word_entry = dict(word)
                    word_entry["text"] = word_text
                    word_entry["speaker_id"] = namespaced_speaker
                    word_entry["raw_speaker"] = word.get("speaker_id") or raw_speaker
                    word_entry["source_id"] = source_id
                    word_entry["source_path"] = source_path
                    word_entry["abs_start"] = offset + start_val
                    word_entry["abs_end"] = offset + end_val
                    words_out.append(word_entry)
                    word_added = True
                if not word_added and text:
                    words_out.append(
                        {
                            "text": text,
                            "speaker_id": namespaced_speaker,
                            "raw_speaker": raw_speaker,
                            "source_id": source_id,
                            "source_path": source_path,
                            "abs_start": abs_start,
                            "abs_end": abs_end,
                        }
                    )
            elif text:
                words_out.append(
                    {
                        "text": text,
                        "speaker_id": namespaced_speaker,
                        "raw_speaker": raw_speaker,
                        "source_id": source_id,
                        "source_path": source_path,
                        "abs_start": abs_start,
                        "abs_end": abs_end,
                    }
                )

    segments_out.sort(key=lambda seg: (seg["abs_start"], seg["abs_end"]))
    words_out.sort(key=lambda word: (word["abs_start"], word["abs_end"]))
    return segments_out, words_out


def normalize_segments(segments: Iterable[Dict[str, Any]], timeline_start: float) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for index, segment in enumerate(segments):
        normalized.append(
            {
                "id": f"seg_{index:06d}",
                "start": round(segment["abs_start"] - timeline_start, 6),
                "end": round(segment["abs_end"] - timeline_start, 6),
                "text": segment["text"],
                "speaker_id": segment["speaker_id"],
                "raw_speaker": segment["raw_speaker"],
                "source_id": segment["source_id"],
                "source_path": segment["source_path"],
            }
        )
    return normalized


def normalize_words(words: Iterable[Dict[str, Any]], timeline_start: float) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for word in words:
        entry = dict(word)
        entry["start"] = round(word["abs_start"] - timeline_start, 6)
        entry["end"] = round(word["abs_end"] - timeline_start, 6)
        entry.pop("abs_start", None)
        entry.pop("abs_end", None)
        normalized.append(entry)
    return normalized


def build_whisper_payload(
    method_name: str,
    segments: List[Dict[str, Any]],
    words: List[Dict[str, Any]],
    timeline_start: float,
) -> Dict[str, Any]:
    text = " ".join(segment["text"] for segment in segments if segment["text"])
    duration = max((seg["end"] for seg in segments), default=0.0)
    if words:
        whisper_words = []
        for word in words:
            payload_word = word.get("word") or word.get("text") or ""
            whisper_words.append(
                {
                    "start": word["start"],
                    "end": word["end"],
                    "word": payload_word,
                }
            )
    else:
        whisper_words = [
            {
                "start": seg["start"],
                "end": seg["end"],
                "word": seg["text"],
            }
            for seg in segments
            if seg["text"]
        ]
    return {
        "method": method_name,
        "duration": duration,
        "text": text.strip(),
        "words": whisper_words,
    }


def build_diarization_payload(
    segments: List[Dict[str, Any]],
    method_name: str,
    bundles: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    diarization: List[Dict[str, Any]] = []
    for segment in segments:
        diarization.append(
            {
                "start": segment["start"],
                "end": segment["end"],
                "speaker": segment["speaker_id"],
                "raw_speaker": segment["raw_speaker"],
                "source_id": segment["source_id"],
                "source_path": segment["source_path"],
                "method": method_name,
            }
        )
    return diarization


def build_vtt_text(segments: Iterable[Dict[str, Any]]) -> str:
    lines = ["WEBVTT", ""]
    for index, segment in enumerate(segments, start=1):
        start_ts = format_timestamp(segment["start"])
        end_ts = format_timestamp(segment["end"])
        lines.append(str(index))
        lines.append(f"{start_ts} --> {end_ts}")
        speaker = segment["speaker_id"]
        text = segment["text"]
        lines.append(f"{speaker}: {text}")
        lines.append("")
    return "\n".join(lines)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def format_timestamp(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds - (hours * 3600 + minutes * 60)
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


if __name__ == "__main__":
    raise SystemExit(main())
