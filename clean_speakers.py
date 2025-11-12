#!/usr/bin/env python3

"""Assign canonical speaker names to a synchronized transcript bundle."""

from __future__ import annotations

import argparse
import json
import textwrap
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from webvtt import WebVTT


DEFAULT_MIN_SPEAKER_FRACTION = 0.01
DEFAULT_UNKNOWN = "unknown_speaker"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Name speakers in a synchronized transcript bundle.")
    parser.add_argument("sync_dir", type=Path, help="Session or method directory produced by synchronize_transcripts.")
    parser.add_argument(
        "--bundle",
        type=Path,
        help="Optional explicit path to a legacy *.synced.json bundle (skips VTT parsing).",
    )
    parser.add_argument(
        "--method",
        help="Optional method/prefix inside sync_dir (required when sync_dir contains multiple methods).",
    )
    parser.add_argument(
        "--vtt",
        type=Path,
        help="Explicit path to the WebVTT file (defaults to <method>/<method>.vtt).",
    )
    parser.add_argument(
        "--prefix",
        help="Override output prefix (defaults to method/prefix inferred from inputs).",
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

    segments, out_dir, prefix, default_roster = load_segments_and_context(args)
    roster_path = args.roster or default_roster
    roster = load_roster(roster_path) if roster_path else {}

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

    out_dir.mkdir(parents=True, exist_ok=True)

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


def load_segments_and_context(args: argparse.Namespace) -> Tuple[List[Dict[str, Any]], Path, str, Optional[Path]]:
    base_dir = args.sync_dir.expanduser().resolve()
    if args.bundle:
        bundle_path = resolve_bundle_path(base_dir, args.bundle)
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        prefix = args.prefix or bundle_path.stem.replace(".synced", "")
        return bundle.get("segments") or [], base_dir, prefix, None

    method_dir, inferred_prefix = resolve_method_dir(base_dir, args.method)
    vtt_path = resolve_vtt_path(method_dir, inferred_prefix, args.vtt)
    segments = load_segments_from_vtt(vtt_path)
    prefix = args.prefix or inferred_prefix
    blank_roster = find_blank_roster(method_dir, prefix)
    return segments, method_dir, prefix, blank_roster


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


def resolve_method_dir(base_dir: Path, method: Optional[str]) -> Tuple[Path, str]:
    base_dir = base_dir.expanduser().resolve()
    if method:
        method_path = Path(method).expanduser()
        if not method_path.is_absolute():
            method_dir = (base_dir / method_path).resolve()
        else:
            method_dir = method_path.resolve()
        if not method_dir.is_dir():
            raise SystemExit(f"Method directory not found: {method_dir}")
        return method_dir, method_dir.name

    vtt_candidates = list(base_dir.glob("*.vtt"))
    if len(vtt_candidates) == 1:
        return base_dir, vtt_candidates[0].stem
    if len(vtt_candidates) > 1:
        raise SystemExit(
            f"Multiple VTT files found in {base_dir}; specify --method or --vtt explicitly."
        )

    method_dirs = [
        child
        for child in base_dir.iterdir()
        if child.is_dir() and (child / f"{child.name}.vtt").exists()
    ]
    if len(method_dirs) == 1:
        return method_dirs[0], method_dirs[0].name
    if not method_dirs:
        raise SystemExit(
            f"No method directories with VTT outputs found in {base_dir}. "
            "Provide --method or point sync_dir to the desired method directory."
        )
    raise SystemExit("Multiple method directories detected; specify --method to disambiguate.")


def resolve_vtt_path(method_dir: Path, method_prefix: str, explicit: Optional[Path]) -> Path:
    if explicit:
        vtt_path = explicit.expanduser().resolve()
    else:
        vtt_path = method_dir / f"{method_prefix}.vtt"
        if not vtt_path.exists():
            candidates = sorted(method_dir.glob("*.vtt"))
            if len(candidates) == 1:
                vtt_path = candidates[0]
    if not vtt_path.exists():
        raise SystemExit(f"WebVTT file not found: {vtt_path}")
    return vtt_path


def find_blank_roster(method_dir: Path, prefix: str) -> Optional[Path]:
    candidate = method_dir / f"{prefix}.speakers.blank.json"
    if candidate.exists():
        return candidate
    return None


def load_segments_from_vtt(path: Path) -> List[Dict[str, Any]]:
    vtt = WebVTT().read(str(path))
    segments: List[Dict[str, Any]] = []
    for index, caption in enumerate(vtt):
        merged_text = " ".join((caption.text or "").splitlines()).strip()
        speaker, text = split_speaker_text(merged_text)
        segments.append(
            {
                "id": f"seg_{index:06d}",
                "start": float(caption.start_in_seconds or 0.0),
                "end": float(caption.end_in_seconds or caption.start_in_seconds or 0.0),
                "speaker_id": speaker,
                "text": text,
            }
        )
    return segments


def split_speaker_text(text: str) -> Tuple[str, str]:
    if not text:
        return DEFAULT_UNKNOWN, ""
    if ":" in text:
        speaker, remainder = text.split(":", 1)
        speaker = speaker.strip() or DEFAULT_UNKNOWN
        return speaker, remainder.strip()
    return DEFAULT_UNKNOWN, text.strip()


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
    last_speaker: Optional[str] = None
    buffer: List[str] = []

    def flush_buffer(current_speaker: Optional[str]) -> None:
        if current_speaker is None or not buffer:
            return
        merged_text = " ".join(buffer).strip()
        if merged_text:
            lines.append(f"{current_speaker}: {merged_text}")
        buffer.clear()

    for segment in sorted(segments, key=lambda seg: seg.get("start", 0.0)):
        speaker = mapping.get(str(segment.get("speaker_id") or DEFAULT_UNKNOWN), DEFAULT_UNKNOWN)
        text = (segment.get("text") or "").strip()
        if not text:
            continue
        if speaker != last_speaker:
            flush_buffer(last_speaker)
            last_speaker = speaker
        buffer.append(text)

    flush_buffer(last_speaker)
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

if __name__ == "__main__":
    raise SystemExit(main())
