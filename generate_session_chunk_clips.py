#!/usr/bin/env python3
"""
generate_session_chunk_clips.py
================================

Helper utility for sampling audio clips from the organized Taelgar
session directories. For each "Session NNN" directory located under the
sessions root it will:

  * look for per-chunk segment definitions
  * pair them with the corresponding processed chunk audio file
  * allocate clip counts so that every chunk gets at least ``min_per_chunk``
    samples (default: 5) while targeting ``per_session_target`` clips in
    total (default: 50)
  * call ``extract_segments.py`` in ``sample`` mode against the chunk file
    so that clips land under ``speaker_clips/session-NNN/chunk-NNN``

Because we invoke ``extract_segments.py`` under the hood, this script
inherits its dependencies (FFmpeg, the Taelgar audio pipeline, etc.).

Typical usage from the repo root:

    python generate_session_chunk_clips.py --sessions-root .. --output-root ../speaker_clips
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from extract_segments import filter_non_overlapping, load_segments


DEFAULT_SESSIONS_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_ROOT = DEFAULT_SESSIONS_ROOT / "speaker_clips"
EXTRACT_SCRIPT = Path(__file__).resolve().parent / "extract_segments.py"


@dataclass
class ChunkSpec:
    """Metadata about a per-chunk segment file and the associated audio."""

    name: str
    segments_path: Path
    audio_path: Path
    available_segments: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sample per-chunk clips for every Session directory.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--sessions-root",
        type=Path,
        default=DEFAULT_SESSIONS_ROOT,
        help="Directory that holds the 'Session NNN' folders.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Destination root for clips (session/chunk folders are created under this path).",
    )
    parser.add_argument(
        "--per-session-target",
        type=int,
        default=50,
        help="Total clips to export for each session.",
    )
    parser.add_argument(
        "--min-per-chunk",
        type=int,
        default=5,
        help="Minimum clips to export from each chunk (if available).",
    )
    parser.add_argument(
        "--min-sec",
        type=float,
        default=2.0,
        help="Minimum segment duration to pass to extract_segments.",
    )
    parser.add_argument(
        "--max-sec",
        type=float,
        default=5.0,
        help="Maximum segment duration to pass to extract_segments (0 disables the cap).",
    )
    parser.add_argument(
        "--audio-profile",
        type=str,
        default="voice-memo",
        help="Audio profile to pass to extract_segments.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the planned commands without invoking extract_segments.",
    )
    return parser.parse_args()


def discover_sessions(root: Path) -> List[Path]:
    """Return candidate session directories under the root."""
    sessions: List[Path] = []
    for path in sorted(root.iterdir()):
        if not path.is_dir():
            continue
        if not path.name.startswith("Session"):
            continue
        sessions.append(path)
    return sessions


def load_available_segments(path: Path, min_sec: float, max_sec: float) -> int:
    """Return the number of usable segments in the JSON definition."""
    segments: List[Tuple[float, float]] = load_segments(str(path))
    filtered: List[Tuple[float, float]] = []
    for start, end in segments:
        duration = end - start
        if duration < min_sec:
            continue
        if max_sec > 0.0 and duration > max_sec:
            continue
        filtered.append((start, end))
    filtered = filter_non_overlapping(filtered)
    return len(filtered)


def find_audio_path(audio_dir: Path, base_name: str) -> Optional[Path]:
    """Return the audio chunk that matches the per-chunk segments."""
    preferred_exts = (".wav", ".mp3", ".m4a", ".flac")
    for ext in preferred_exts:
        candidate = audio_dir / f"{base_name}{ext}"
        if candidate.exists():
            return candidate
    matches = sorted(audio_dir.glob(f"{base_name}.*"))
    if matches:
        return matches[0]
    return None


def collect_chunk_specs(session_dir: Path, min_sec: float, max_sec: float) -> List[ChunkSpec]:
    """Gather segment/audio pairs for a session."""
    per_chunk_dir = session_dir / "per_chunk"
    audio_dir = session_dir / "audio_chunks"
    if not per_chunk_dir.exists() or not audio_dir.exists():
        print(f"Skipping {session_dir.name}: missing per_chunk or audio_chunks directories")
        return []

    specs: List[ChunkSpec] = []
    for entry in sorted(per_chunk_dir.glob("*.json")):
        if entry.name.startswith("."):
            continue
        if not entry.name.endswith("_segments.json"):
            continue
        base_name = entry.name[: -len("_segments.json")]
        audio_path = find_audio_path(audio_dir, base_name)
        if not audio_path:
            print(f"  ! No audio chunk found for {entry.name} in {audio_dir}")
            continue
        available = load_available_segments(entry, min_sec, max_sec)
        if available == 0:
            print(f"  ! No usable segments in {entry.name}; skipping chunk")
            continue
        specs.append(ChunkSpec(base_name, entry, audio_path, available))
    return specs


def allocate_targets(chunks: Sequence[ChunkSpec], goal: int, min_per_chunk: int) -> Tuple[List[int], int]:
    """
    Compute how many clips to request from each chunk.

    Returns (targets, remaining) where remaining is the number of clips
    we could not allocate because the available pool was too small.
    """
    if not chunks:
        return ([], goal)
    chunk_count = len(chunks)
    if chunk_count * min_per_chunk > goal:
        raise ValueError(
            f"Cannot satisfy {goal} clips while keeping >= {min_per_chunk} per chunk "
            f"(session has {chunk_count} chunks)."
        )

    targets = [0 for _ in range(chunk_count)]
    remaining = goal
    for idx, chunk in enumerate(chunks):
        base = min(min_per_chunk, chunk.available_segments)
        if chunk.available_segments < min_per_chunk:
            print(
                f"  ! {chunk.name} only has {chunk.available_segments} usable segments; "
                f"requesting {base} clips instead of {min_per_chunk}"
            )
        targets[idx] = base
        remaining -= base

    if remaining < 0:
        raise ValueError(
            f"Allocated {sum(targets)} clips which exceeds the requested total of {goal}. "
            "Reduce min_per_chunk or increase the per-session goal."
        )

    while remaining > 0:
        made_progress = False
        for idx, chunk in enumerate(chunks):
            spare = chunk.available_segments - targets[idx]
            if spare <= 0:
                continue
            add = min(spare, 1, remaining)
            targets[idx] += add
            remaining -= add
            made_progress = True
            if remaining == 0:
                break
        if not made_progress:
            break
    return targets, remaining


def session_identifier(name: str) -> str:
    """Return the zero-padded numeric session identifier used in output paths."""
    digits = "".join(ch for ch in name if ch.isdigit())
    if digits:
        return f"{int(digits):03d}"
    sanitized = name.strip().replace(" ", "-").lower()
    return sanitized or "unknown"


def chunk_identifier(index: int) -> str:
    """Return the chunk identifier portion for output directories."""
    return f"{index:03d}"


def invoke_extract_segments(
    chunk: ChunkSpec,
    target_count: int,
    output_dir: Path,
    args: argparse.Namespace,
    dry_run: bool,
) -> None:
    """Run extract_segments.py for a chunk."""
    cmd = [
        sys.executable,
        str(EXTRACT_SCRIPT),
        "--segments",
        str(chunk.segments_path),
        "--audio-file",
        str(chunk.audio_path),
        "--output-dir",
        str(output_dir),
        "--mode",
        "sample",
        "--n",
        str(target_count),
        "--min-sec",
        str(args.min_sec),
        "--max-sec",
        str(args.max_sec),
        "--audio-profile",
        args.audio_profile,
    ]
    print(f"    -> {chunk.name}: requesting {target_count} clips into {output_dir}")
    if dry_run:
        return
    subprocess.run(cmd, check=True)


def main() -> None:
    args = parse_args()
    sessions_root = args.sessions_root.expanduser().resolve()
    output_root = args.output_root.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    sessions = discover_sessions(sessions_root)
    if not sessions:
        print(f"No session directories found under {sessions_root}")
        return

    for session_dir in sessions:
        print(f"Processing {session_dir.name}...")
        chunks = collect_chunk_specs(session_dir, args.min_sec, args.max_sec)
        if not chunks:
            print(f"  ! No usable chunks found in {session_dir.name}; skipping")
            continue
        try:
            targets, remaining = allocate_targets(chunks, args.per_session_target, args.min_per_chunk)
        except ValueError as exc:
            print(f"  ! {exc}")
            continue

        if remaining > 0:
            print(
                f"  ! Only {args.per_session_target - remaining} clips available "
                f"out of requested {args.per_session_target}; continuing anyway."
            )

        session_id = session_identifier(session_dir.name)
        for idx, (chunk, target) in enumerate(zip(chunks, targets), start=1):
            if target <= 0:
                continue
            chunk_id = chunk_identifier(idx)
            chunk_output = output_root / f"session-{session_id}" / f"chunk-{chunk_id}"
            chunk_output.mkdir(parents=True, exist_ok=True)
            invoke_extract_segments(chunk, target, chunk_output, args, args.dry_run)


if __name__ == "__main__":
    main()
