#!/usr/bin/env python3
"""Split a Zoom VTT transcript into scene files and a summary."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Iterable, List, Tuple

CHAPTER_RE = re.compile(r"^---\s*(.+?)\s*---\s*$")
TIMESTAMP_RE = re.compile(r"^\[\d{2}:\d{2}:\d{2}\.\d{2}\s*-\s*\d{2}:\d{2}:\d{2}\.\d{2}\]\s*")


def strip_timestamp(line: str) -> str:
    """Remove the leading timestamp block, if present."""
    return TIMESTAMP_RE.sub("", line, count=1).lstrip()


def clean_speaker(speaker: str) -> str:
    """Convert 'Name (Role)' -> 'Role', keep unknown_speaker as-is."""
    speaker_name = speaker.strip()
    if speaker_name == "unknown_speaker":
        return speaker_name

    match = re.search(r"\(([^()]*)\)\s*$", speaker_name)
    if match:
        role = match.group(1).strip()
        if role:
            return role

    return speaker_name


def clean_line(line: str) -> str:
    """Strip timestamps and normalize the speaker label when present."""
    without_ts = strip_timestamp(line)
    if not without_ts:
        return ""

    speaker, sep, rest = without_ts.partition(":")
    if not sep:
        return without_ts

    cleaned_speaker = clean_speaker(speaker)
    return f"{cleaned_speaker}:{rest}"


def parse_scenes(lines: Iterable[str]) -> Tuple[List[str], List[List[str]]]:
    titles: List[str] = []
    scenes: List[List[str]] = []
    current: List[str] | None = None

    for raw_line in lines:
        line = raw_line.rstrip("\n")
        chapter_match = CHAPTER_RE.match(line)
        if chapter_match:
            titles.append(chapter_match.group(1))
            if current is not None:
                scenes.append(current)
            current = []
            continue

        if current is None:
            continue

        current.append(clean_line(line))

    if current is not None:
        scenes.append(current)

    return titles, scenes


def write_outputs(input_path: Path) -> None:
    lines = input_path.read_text(encoding="utf-8").splitlines()
    titles, scenes = parse_scenes(lines)

    if not titles or not scenes:
        raise SystemExit("No chapters found in the input file.")

    base_dir = input_path.parent

    for idx, scene_lines in enumerate(scenes, start=1):
        scene_text = "\n".join(scene_lines).rstrip() + "\n"
        scene_file = base_dir / f"scene{idx}.txt"
        cleaned_placeholder = base_dir / f"scene{idx}-cleaned.txt"
        scene_file.write_text(scene_text, encoding="utf-8")
        cleaned_placeholder.write_text("", encoding="utf-8")

    summary = "\n\n".join(f"## {title}" for title in titles) + "\n"
    (base_dir / "summary.md").write_text(summary, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Split a transcript at chapter markers and clean speaker labels."
    )
    parser.add_argument(
        "input_file",
        nargs="?",
        type=Path,
        default=Path("zoom-vtt.transcript.txt"),
        help="Path to the transcript file (default: zoom-vtt.transcript.txt)",
    )
    args = parser.parse_args()

    write_outputs(args.input_file)


if __name__ == "__main__":
    main()
