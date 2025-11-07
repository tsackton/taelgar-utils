#!/usr/bin/env python3

"""Assign canonical speaker names to a synchronized transcript bundle."""

from __future__ import annotations

import argparse
import json
import textwrap
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


DEFAULT_MIN_SPEAKER_FRACTION = 0.01
DEFAULT_UNKNOWN = "unknown_speaker"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Name speakers in a synchronized transcript bundle.")
    parser.add_argument("sync_dir", type=Path, help="Directory containing synchronized outputs.")
    parser.add_argument(
        "--bundle",
        type=Path,
        help="Optional explicit path to the canonical bundle JSON (defaults to *.synced.json inside sync_dir).",
    )
    parser.add_argument(
        "--roster",
        type=Path,
        help="Optional JSON mapping from raw speakers to canonical names.",
    )
    parser.add_argument(
        "--min-speaker-fraction",
        type=float,
        default=DEFAULT_MIN_SPEAKER_FRACTION,
        help="Minimum fraction of total speaking time before prompting for a speaker (default: 0.01).",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_false",
        dest="interactive",
        default=True,
        help="Disable interactive speaker assignment prompts.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    bundle_path = resolve_bundle_path(args.sync_dir, args.bundle)
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    roster = load_roster(args.roster) if args.roster else {}

    segments = bundle.get("segments") or []
    if not segments:
        raise SystemExit("No segments found in canonical bundle.")

    speaker_stats = compute_speaker_stats(segments)
    total_duration = sum(item["duration"] for item in speaker_stats.values()) or 1.0

    # Auto-map speakers using roster
    speaker_mapping: Dict[str, str] = {}
    for speaker_id in speaker_stats:
        roster_match = roster.get(speaker_id)
        if roster_match:
            speaker_mapping[speaker_id] = roster_match

    unresolved = [speaker for speaker in speaker_stats if speaker not in speaker_mapping]

    if unresolved and args.interactive:
        interactive_mapping = prompt_for_speakers(
            segments,
            speaker_stats,
            unresolved,
            total_duration,
            min_fraction=args.min_speaker_fraction,
        )
        speaker_mapping.update(interactive_mapping)

    # Default unresolved speakers to their raw IDs
    for speaker_id in speaker_stats:
        speaker_mapping.setdefault(speaker_id, speaker_id)

    transcript_lines = build_transcript_lines(segments, speaker_mapping)
    report = build_report(speaker_stats, speaker_mapping, total_duration, roster)

    out_dir = args.sync_dir.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    prefix = bundle_path.stem.replace(".synced", "")
    mapping_path = out_dir / f"{prefix}.speaker_mapping.json"
    report_path = out_dir / f"{prefix}.speaker_report.json"
    transcript_path = out_dir / f"{prefix}.transcript.txt"

    write_json(mapping_path, speaker_mapping)
    write_json(report_path, report)
    transcript_path.write_text("\n".join(transcript_lines) + "\n", encoding="utf-8")

    print(f"Wrote speaker mapping to {mapping_path}")
    print(f"Wrote report to {report_path}")
    print(f"Wrote transcript to {transcript_path}")
    return 0


def load_roster(path: Path) -> Dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    roster: Dict[str, str] = {}

    if isinstance(data, list):
        for entry in data:
            if not isinstance(entry, dict):
                continue
            raw = entry.get("raw") or entry.get("speaker")
            canonical = entry.get("canonical") or entry.get("name")
            if raw and canonical:
                roster[str(raw)] = str(canonical)
        return roster

    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, str):
                roster[str(key)] = value
            elif isinstance(value, (list, tuple)):
                canonical = str(key)
                roster[canonical] = canonical
                for alias in value:
                    roster[str(alias)] = canonical
            elif isinstance(value, dict):
                canonical = str(value.get("canonical") or value.get("name") or key)
                roster[str(key)] = canonical
                aliases = value.get("aliases") or value.get("raw") or []
                if isinstance(aliases, (str, bytes)):
                    aliases = [aliases]
                for alias in aliases:
                    roster[str(alias)] = canonical
    return roster


def compute_speaker_stats(segments: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    stats: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "duration": 0.0,
        "words": 0,
    })

    for segment in segments:
        speaker_id = str(segment.get("speaker_id") or DEFAULT_UNKNOWN)
        start = float(segment.get("start", 0.0))
        end = float(segment.get("end", start))
        duration = max(0.0, end - start)
        words = segment.get("words") or []
        if words:
            word_count = sum(len((word.get("text") or "").split()) for word in words if word.get("text"))
        else:
            word_count = len((segment.get("text") or "").split())

        segment["_duration"] = duration
        segment["_word_count"] = word_count

        stats[speaker_id]["duration"] += duration
        stats[speaker_id]["words"] += word_count
    # No segment count stored; the timestamps/text remain in the canonical bundle

    return stats


def prompt_for_speakers(
    segments: Sequence[Dict[str, Any]],
    stats: Dict[str, Dict[str, Any]],
    unresolved: Iterable[str],
    total_duration: float,
    *,
    min_fraction: float,
) -> Dict[str, str]:
    prompts: List[Tuple[str, float, int]] = []
    for speaker_id in unresolved:
        duration = stats[speaker_id]["duration"]
        fraction = duration / total_duration if total_duration else 0.0
        usable_words = stats[speaker_id]["words"]
        if fraction >= min_fraction:
            prompts.append((speaker_id, fraction, usable_words))

    prompts.sort(key=lambda item: item[1], reverse=True)

    mapping: Dict[str, str] = {}

    print(
        f"Interactive speaker assignment queued for {len(prompts)} "
        f"speakers (> {min_fraction:.2%} duration)."
    )

    segments_by_speaker: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for segment in segments:
        segments_by_speaker[str(segment.get("speaker_id") or DEFAULT_UNKNOWN)].append(segment)

    for speaker_id, fraction, usable_words in prompts:
        excerpt = build_excerpt(segments_by_speaker[speaker_id])
        excerpt_words = sum(len(paragraph.split()) for paragraph in excerpt)
        print("-----")
        print(
            f"Speaker {speaker_id} excerpt (~{excerpt_words} words, {fraction:.2%} of time)"
        )
        if excerpt:
            for paragraph in excerpt:
                print(textwrap.fill(paragraph, width=100))
                print()
        else:
            print("  (No sample text available for this speaker)\n")

        choice = input("Map this speaker to which canonical name? (leave blank to skip): ").strip()
        if choice:
            mapping[speaker_id] = choice
        print()

    return mapping


def build_excerpt(segments: Sequence[Dict[str, Any]], *, target_words: int = 280, max_words: int = 320) -> List[str]:
    sorted_segments = sorted(
        segments,
        key=lambda seg: (
            seg.get("_word_count", 0),
            seg.get("_duration", 0.0),
        ),
        reverse=True,
    )
    merged: List[str] = []
    accumulated = 0

    for segment in sorted_segments:
        text = (segment.get("text") or "").strip()
        if not text:
            continue
        words = text.split()
        if len(words) < 5 and accumulated > 0:
            continue
        merged.append(text)
        accumulated += len(words)
        if accumulated >= target_words:
            break

    if not merged:
        for segment in sorted_segments:
            text = (segment.get("text") or "").strip()
            if text:
                merged.append(text)
                accumulated += len(text.split())
                if accumulated >= target_words:
                    break

    trimmed: List[str] = []
    running = 0
    for paragraph in merged:
        words = paragraph.split()
        if running + len(words) <= max_words:
            trimmed.append(paragraph)
            running += len(words)
        else:
            remaining = max_words - running
            if remaining > 0:
                trimmed.append(" ".join(words[:remaining]))
            break

    return trimmed


def resolve_bundle_path(sync_dir: Path, explicit: Optional[Path]) -> Path:
    sync_dir = sync_dir.expanduser().resolve()
    if explicit:
        bundle_path = explicit.expanduser().resolve()
        if not bundle_path.exists():
            raise SystemExit(f"Canonical bundle not found: {bundle_path}")
        return bundle_path

    candidates = sorted(sync_dir.glob("*.synced.json"))
    if not candidates:
        raise SystemExit(f"No *.synced.json files found in {sync_dir}")
    if len(candidates) > 1:
        raise SystemExit("Multiple *.synced.json files found; specify one with --bundle.")
    return candidates[0]


def build_transcript_lines(
    segments: Sequence[Dict[str, Any]],
    mapping: Dict[str, str],
) -> List[str]:
    lines: List[str] = []
    for segment in sorted(segments, key=lambda seg: seg.get("start", 0.0)):
        speaker = mapping.get(str(segment.get("speaker_id") or DEFAULT_UNKNOWN), DEFAULT_UNKNOWN)
        text = (segment.get("text") or "").strip()
        timestamp = format_timestamp(float(segment.get("start", 0.0)))
        lines.append(f"[{timestamp}] {speaker}: {text}")
    return lines


def build_report(
    stats: Dict[str, Dict[str, Any]],
    mapping: Dict[str, str],
    total_duration: float,
    roster: Dict[str, str],
) -> Dict[str, Any]:
    report_entries: Dict[str, Any] = {}
    for speaker_id, values in stats.items():
        mapped = mapping.get(speaker_id, speaker_id)
        entry = {
            "duration_seconds": round(values["duration"], 3),
            "fraction": round(values["duration"] / total_duration if total_duration else 0.0, 4),
            "words": values["words"],
            "mapped_to": mapped,
            "roster_match": roster.get(speaker_id),
        }
        report_entries[speaker_id] = entry

    return {
        "total_duration": total_duration,
        "speakers": report_entries,
    }


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
