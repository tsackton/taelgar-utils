#!/usr/bin/env python3

"""Compute cumulative offsets for a sequence of audio files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from pydub import AudioSegment


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compute offsets for audio files.")
    parser.add_argument("audio_files", nargs="+", type=Path, help="Audio files in playback order.")
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path to write the offsets JSON (defaults to stdout).",
    )
    return parser.parse_args()


def expand_inputs(paths: List[Path]) -> List[Path]:
    expanded: List[Path] = []
    for original in paths:
        path = original.expanduser().resolve()
        if not path.exists():
            raise SystemExit(f"Path not found: {original}")

        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                candidate = line.strip()
                if not candidate or candidate.startswith("#"):
                    continue
                candidate_path = Path(candidate).expanduser()
                if not candidate_path.is_absolute():
                    candidate_path = Path.cwd() / candidate_path
                candidate_path = candidate_path.resolve()
                if not candidate_path.exists():
                    raise SystemExit(f"Audio file listed in {path} not found: {candidate}")
                expanded.append(candidate_path)
        else:
            expanded.append(path)

    return expanded


def main() -> int:
    args = parse_args()
    entries: List[Dict[str, Any]] = []
    offset_seconds = 0.0

    audio_paths = expand_inputs(args.audio_files)

    for audio_path in audio_paths:
        audio = AudioSegment.from_file(audio_path)
        duration = len(audio) / 1000.0

        entries.append(
            {
                "path": str(audio_path),
                "duration_seconds": round(duration, 6),
                "offset_seconds": round(offset_seconds, 6),
            }
        )

        offset_seconds += duration

    payload = {
        "files": entries,
        "total_duration_seconds": round(offset_seconds, 6),
    }

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Wrote offsets to {args.output}")
    else:
        print(json.dumps(payload, indent=2, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
