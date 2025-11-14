#!/usr/bin/env python3
"""Report candidate proper nouns from a transcript."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Dict, List

try:
    from wordfreq import zipf_frequency
except ImportError as exc:
    raise SystemExit(
        "find_proper_nouns.py requires the 'wordfreq' package. Install via 'pip install wordfreq'."
    ) from exc

LINE_RE = re.compile(r"^\[(?P<start>[0-9:\.]+)\s*-\s*(?P<end>[0-9:\.]+)\]\s*(?P<speaker>[^:]+):\s*(?P<text>.*)$")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\-]+")
COMMON_FILLERS = {
    "Yeah",
    "And",
    "So",
    "Like",
    "Oh",
    "But",
    "Then",
    "Right",
    "Okay",
    "Ok",
    "Alright",
    "Well",
    "Also",
    "Because",
    "Still",
    "That",
    "This",
    "Those",
    "These",
}
COMMON_FILLERS_LOWER = {w.lower() for w in COMMON_FILLERS}


def parse_transcript(path: Path) -> List[str]:
    entries: List[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        match = LINE_RE.match(raw.strip())
        if match:
            entries.append(match.group("text"))
    return entries


def collect_candidates(lines: List[str]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for text in lines:
        for word in WORD_RE.findall(text):
            if (
                not word
                or not word[0].isupper()
                or word in COMMON_FILLERS
                or word.lower() in COMMON_FILLERS_LOWER
            ):
                continue
            counts[word] += 1
    return counts


def load_known(path: Path | None) -> Dict[str, str]:
    if not path:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[warn] Failed to load known list {path}: {exc}")
        return {}

    if isinstance(data, dict) and ("text" in data or "speakers" in data):
        mapping: Dict[str, str] = {}
        for section in (data.get("text") or {}, data.get("speakers") or {}):
            if isinstance(section, dict):
                mapping.update({str(k): str(v) for k, v in section.items() if str(v)})
        return mapping
    if isinstance(data, dict):
        return {str(k): str(v) for k, v in data.items() if str(v)}
    print(f"[warn] Unexpected format in {path}; ignoring known list.")
    return {}


@lru_cache(maxsize=4096)
def word_zipf(word: str) -> float:
    return zipf_frequency(word, "en")


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract candidate proper nouns from a transcript.")
    parser.add_argument("transcript", type=Path)
    parser.add_argument("--zipf-threshold", type=float, default=4.0, help="Max ZIPF frequency to consider (default: 4.0)")
    parser.add_argument("--min-count", type=int, default=2, help="Only report entries seen this many times (default: 2)")
    parser.add_argument("--json-output", type=Path, help="Optional path to write mistakes JSON")
    parser.add_argument("--known", type=Path, help="Existing mistakes JSON to pre-populate replacements")
    args = parser.parse_args()

    texts = parse_transcript(args.transcript)
    if not texts:
        raise SystemExit("No parseable lines found.")

    counts = collect_candidates(texts)
    known_map = load_known(args.known)

    filtered = {
        word: count
        for word, count in counts.items()
        if count >= args.min_count and word_zipf(word) <= args.zipf_threshold
    }

    width = max((len(word) for word in filtered), default=0)
    if not filtered:
        print("No candidates found.")
    else:
        print("Candidates (count, ZIPF, replacement):")
        for word, count in sorted(filtered.items(), key=lambda kv: (-kv[1], kv[0])):
            replacement = known_map.get(word, "")
            arrow = f" -> {replacement}" if replacement else ""
            print(f"  {word.ljust(width)}  {count:>3}  zipf={word_zipf(word):.2f}{arrow}")

    if args.json_output:
        payload = {
            word: known_map.get(word, "")
            for word in sorted(filtered)
        }
        args.json_output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
