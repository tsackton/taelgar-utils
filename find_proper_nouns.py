#!/usr/bin/env python3
"""Report candidate proper nouns from a transcript."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Iterable, List

LINE_RE = re.compile(r"^\[(?P<start>[0-9:\.]+)\s*-\s*(?P<end>[0-9:\.]+)\]\s*(?P<speaker>[^:]+):\s*(?P<text>.*)$")
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'\-]+")
STOPWORDS = {"The", "A", "An", "I", "We", "You", "He", "She", "They", "It"}


def parse_transcript(path: Path) -> List[str]:
    entries: List[str] = []
    for idx, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        match = LINE_RE.match(raw.strip())
        if not match:
            continue
        entries.append(match.group("text"))
    return entries


def iterate_candidates(text: str) -> Iterable[List[str]]:
    tokens = TOKEN_RE.findall(text)
    seq: List[str] = []
    for token in tokens:
        if token in STOPWORDS:
            if seq:
                yield seq
                seq = []
            continue
        if token[0].isupper() and not token.isupper():
            seq.append(token)
        else:
            if seq:
                yield seq
                seq = []
    if seq:
        yield seq


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract candidate proper nouns from a transcript.")
    parser.add_argument("transcript", type=Path)
    parser.add_argument("--min-count", type=int, default=2, help="Only report entries seen this many times (default: 2)")
    parser.add_argument("--json-output", type=Path, help="Optional path to write JSON report")
    args = parser.parse_args()

    texts = parse_transcript(args.transcript)
    if not texts:
        raise SystemExit("No parseable lines found.")

    singles: Counter[str] = Counter()
    multi: Counter[str] = Counter()
    for line in texts:
        for seq in iterate_candidates(line):
            if len(seq) == 1:
                singles[seq[0]] += 1
            else:
                multi[" ".join(seq)] += 1

    report = {
        "single_tokens": [item for item in singles.most_common() if item[1] >= args.min_count],
        "multi_tokens": [item for item in multi.most_common() if item[1] >= args.min_count],
    }

    if args.json_output:
        args.json_output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    else:
        print("Single-word candidates:")
        for word, count in report["single_tokens"]:
            print(f"  {word}: {count}")
        print("\nMulti-word candidates:")
        for phrase, count in report["multi_tokens"]:
            print(f"  {phrase}: {count}")


if __name__ == "__main__":
    main()
