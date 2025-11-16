#!/usr/bin/env python3
"""
extract_segments.py
====================

Extracts audio segments from a source audio file based on a JSON segment
definition. The segment JSON must be a list of objects with "start"
and "end" keys expressed in seconds.

This script can operate in several modes:

  - **all**: export all segments that satisfy optional duration
    constraints.
  - **longest N**: export the N longest segments.
  - **sample N**: randomly select N segments to export.

Segments can be further filtered by minimum and maximum duration. Only
non‑overlapping segments are exported; any segment that overlaps with
another in the file is skipped to avoid ambiguous audio boundaries.

Before extracting, the source audio is run through the shared Taelgar
audio processing pipeline, allowing you to apply any of the configured
audio profiles (passthrough, zoom‑audio, voice‑memo, etc.). The pipeline
converts the source into a consistent WAV file that is then sliced using
Python's ``wave`` module.

Usage example:

    python extract_segments.py \
        --segments session1_merged_segments.json \
        --audio-file session1.m4a \
        --output-dir clips/session1 \
        --mode longest \
        --n 5 \
        --min-sec 3.0 \
        --audio-profile voice-memo \
        --max-sec 30.0

This will write the five longest non‑overlapping segments between 3 and
30 seconds from session1.m4a into the output directory.
"""

import argparse
import json
import random
import sys
import wave
from pathlib import Path
from typing import List, Tuple, Optional

from session_pipeline.audio_processing import AUDIO_PROFILES, AudioProcessingError, prepare_clean_audio


def load_segments(path: str) -> List[Tuple[float, float]]:
    """Load start/end pairs from a segment JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    segments: List[Tuple[float, float]] = []
    for entry in data:
        try:
            s = float(entry["start"])
            e = float(entry["end"])
            if e > s:
                segments.append((s, e))
        except Exception:
            continue
    return segments


def filter_non_overlapping(segments: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """
    Return only those segments that do not overlap with any other segment
    in the list. Overlap is considered if start < other_end and
    end > other_start.
    """
    filtered: List[Tuple[float, float]] = []
    for i, (s, e) in enumerate(segments):
        overlaps = False
        for j, (s2, e2) in enumerate(segments):
            if i == j:
                continue
            if s < e2 and e > s2:
                overlaps = True
                break
        if not overlaps:
            filtered.append((s, e))
    return filtered


def extract_wav_segment(
    audio_path: Path,
    start: float,
    end: float,
    output_path: Path,
) -> bool:
    """
    Extract a segment from a WAV file using Python's wave module.
    Returns True if successful, False otherwise.
    """
    try:
        with wave.open(str(audio_path), "rb") as wf:
            framerate = wf.getframerate()
            nchannels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            # Compute frame indices
            start_frame = int(start * framerate)
            end_frame = int(end * framerate)
            if end_frame <= start_frame:
                return False
            wf.setpos(start_frame)
            frames = wf.readframes(end_frame - start_frame)
            # Write out
            with wave.open(str(output_path), "wb") as out:
                out.setnchannels(nchannels)
                out.setsampwidth(sampwidth)
                out.setframerate(framerate)
                out.writeframes(frames)
        return True
    except Exception as exc:
        print(f"Failed to extract WAV segment {start}-{end}: {exc}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="Extract audio clips from segment definitions.")
    parser.add_argument("--segments", required=True, type=str, help="Path to JSON segment list with start/end fields")
    parser.add_argument("--audio-file", required=True, type=str, help="Path to the source audio file")
    parser.add_argument("--output-dir", required=True, type=str, help="Directory to write extracted segments")
    parser.add_argument(
        "--mode",
        type=str,
        default="all",
        choices=["all", "longest", "sample"],
        help="Extraction mode: all segments, N longest, or random sample of N",
    )
    parser.add_argument(
        "--n", type=int, default=0, help="Number of segments for longest or sample modes (ignored for all)"
    )
    parser.add_argument(
        "--min-sec", type=float, default=0.0, help="Minimum segment length in seconds (default: 0)"
    )
    parser.add_argument(
        "--max-sec", type=float, default=0.0, help="Maximum segment length in seconds (0 means no limit)"
    )
    parser.add_argument(
        "--audio-profile",
        choices=sorted(AUDIO_PROFILES.keys()),
        default="passthrough",
        help="Audio processing profile to apply before segment extraction (default: passthrough).",
    )
    parser.add_argument(
        "--sample-rate",
        type=int,
        default=16_000,
        help="Sample rate for processed audio prior to extraction (default: 16000).",
    )
    parser.add_argument(
        "--channels",
        type=int,
        choices=(1, 2),
        default=1,
        help="Channel count for processed audio prior to extraction (default: mono).",
    )
    args = parser.parse_args()

    segments = load_segments(args.segments)
    # Filter by duration
    filtered = []
    for s, e in segments:
        dur = e - s
        if dur < args.min_sec:
            continue
        if args.max_sec > 0.0 and dur > args.max_sec:
            continue
        filtered.append((s, e))
    # Remove overlapping segments
    filtered = filter_non_overlapping(filtered)
    # Selection
    selected: List[Tuple[float, float]] = []
    if args.mode == "all":
        selected = filtered
    elif args.mode == "longest":
        # Sort by length descending and take top N
        selected = sorted(filtered, key=lambda x: (x[1] - x[0]), reverse=True)
        if args.n > 0:
            selected = selected[: args.n]
    elif args.mode == "sample":
        # Randomly sample N segments
        if args.n > 0:
            selected = filtered.copy()
            if args.n < len(selected):
                selected = random.sample(selected, args.n)
        else:
            selected = []
    # Ensure output directory exists
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    audio_path = Path(args.audio_file).expanduser().resolve()
    base = audio_path.stem

    try:
        clean_audio_path, cleanup_path = prepare_clean_audio(
            audio_path,
            profile=args.audio_profile,
            discard=True,
            sample_rate=args.sample_rate,
            channels=args.channels,
            output_format="wav",
        )
    except AudioProcessingError as exc:
        print(f"Failed to preprocess audio '{audio_path}': {exc}", file=sys.stderr)
        return

    extracted_count = 0
    try:
        for idx, (s, e) in enumerate(selected):
            out_name = f"{base}_seg{idx:04d}_{s:.2f}_{e:.2f}.wav"
            out_path = output_dir / out_name
            success = extract_wav_segment(clean_audio_path, s, e, out_path)
            if success:
                extracted_count += 1
            else:
                print(
                    f"Warning: failed to extract segment {s:.2f}-{e:.2f} from {audio_path}",
                    file=sys.stderr,
                )
    finally:
        if cleanup_path and cleanup_path.exists():
            cleanup_path.unlink(missing_ok=True)
    print(f"Extracted {extracted_count} segments into {output_dir}")


if __name__ == "__main__":
    main()
