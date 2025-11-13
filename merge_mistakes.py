#!/usr/bin/env python3
"""Merge multiple mistakes.json files, warning on conflicts and blank replacements."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple


def load_mistakes(path: Path) -> Tuple[Dict[str, str], Dict[str, str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[error] Failed to parse {path}: {exc}", file=sys.stderr)
        return {}, {}

    text_map: Dict[str, str] = {}
    speaker_map: Dict[str, str] = {}

    if isinstance(data, dict) and ("text" in data or "speakers" in data):
        if isinstance(data.get("text"), dict):
            text_map.update({str(k): str(v) for k, v in data["text"].items()})
        if isinstance(data.get("speakers"), dict):
            speaker_map.update({str(k): str(v) for k, v in data["speakers"].items()})
    elif isinstance(data, dict):
        text_map.update({str(k): str(v) for k, v in data.items()})
    else:
        print(f"[warn] Unexpected format in {path}; skipping.", file=sys.stderr)
    return text_map, speaker_map


def merge_section(paths: List[Path], section: str) -> Dict[str, str]:
    merged: Dict[str, str] = {}
    for path in paths:
        text_map, speaker_map = load_mistakes(path)
        source = text_map if section == "text" else speaker_map
        for wrong, right in source.items():
            if not right:
                continue
            if wrong in merged and merged[wrong] != right:
                print(
                    f"[warn] Conflict for '{wrong}' in {section}: '{merged[wrong]}' vs '{right}' (keeping first from earlier file)",
                    file=sys.stderr,
                )
                continue
            merged.setdefault(wrong, right)
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge mistakes.json files (skipping blank replacements).")
    parser.add_argument("output", type=Path, help="Destination JSON file")
    parser.add_argument("inputs", nargs="+", type=Path, help="Input mistakes JSON files")
    args = parser.parse_args()

    merged_text = merge_section(args.inputs, "text")
    merged_speakers = merge_section(args.inputs, "speakers")

    if merged_speakers:
        payload = {
            "text": dict(sorted(merged_text.items())),
            "speakers": dict(sorted(merged_speakers.items())),
        }
    else:
        payload = dict(sorted(merged_text.items()))

    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    total_entries = len(merged_text) + len(merged_speakers)
    print(f"Merged {len(args.inputs)} files into {args.output} ({total_entries} entries).")


if __name__ == "__main__":
    main()
