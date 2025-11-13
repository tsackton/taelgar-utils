#!/usr/bin/env python3
import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple
from difflib import SequenceMatcher

LINE_RE = re.compile(r"^\[(?P<start>[0-9:\.]+)\s*-\s*(?P<end>[0-9:\.]+)\]\s*(?P<speaker>[^:]+):\s*(?P<text>.*)$")

@dataclass
class LineEntry:
    idx: int
    start: str
    end: str
    speaker: str
    text: str

    def timestamp(self) -> str:
        return f"{self.start} - {self.end}"


def parse_transcript(path: Path) -> List[LineEntry]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        raise SystemExit(f"Transcript not found: {path}")
    parsed: List[LineEntry] = []
    for i, raw in enumerate(lines):
        match = LINE_RE.match(raw.strip())
        if not match:
            sys.stderr.write(f"[warn] Unable to parse line {i+1} in {path}: {raw}\n")
            continue
        data = match.groupdict()
        parsed.append(
            LineEntry(
                idx=i,
                start=data["start"],
                end=data["end"],
                speaker=data["speaker"].strip(),
                text=data["text"].strip(),
            )
        )
    return parsed


def tokenize(text: str) -> List[str]:
    cleaned = re.sub(r"[^\w']+", " ", text.lower()).strip()
    return cleaned.split() if cleaned else []


def diff_words(old: str, new: str) -> List[Tuple[str, str]]:
    old_tokens = tokenize(old)
    new_tokens = tokenize(new)
    matcher = SequenceMatcher(None, old_tokens, new_tokens)
    changes: List[Tuple[str, str]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        old_segment = " ".join(old_tokens[i1:i2]) if i2 > i1 else "∅"
        new_segment = " ".join(new_tokens[j1:j2]) if j2 > j1 else "∅"
        changes.append((old_segment, new_segment))
    return changes


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare two cleaned transcripts and report word-level differences.")
    parser.add_argument("old", type=Path, help="Path to baseline transcript")
    parser.add_argument("new", type=Path, help="Path to updated transcript")
    args = parser.parse_args()

    old_lines = parse_transcript(args.old)
    new_lines = parse_transcript(args.new)

    if not old_lines or not new_lines:
        sys.stderr.write("[error] One of the transcripts could not be parsed; aborting.\n")
        raise SystemExit(1)

    limit = min(len(old_lines), len(new_lines))
    if len(old_lines) != len(new_lines):
        sys.stderr.write(
            f"[warn] Line counts differ ({len(old_lines)} vs {len(new_lines)}); only comparing first {limit} lines.\n"
        )

    for idx in range(limit):
        old_entry = old_lines[idx]
        new_entry = new_lines[idx]

        ts_match = old_entry.start == new_entry.start and old_entry.end == new_entry.end
        speaker_match = old_entry.speaker == new_entry.speaker

        if not ts_match and not speaker_match:
            sys.stderr.write(
                f"[warn] Line {idx+1}: timestamp and speaker mismatch; skipping comparison.\n"
            )
            continue

        if ts_match and not speaker_match:
            sys.stderr.write(
                f"[info] Line {idx+1}: speaker changed {old_entry.speaker} -> {new_entry.speaker}.\n"
            )

        if speaker_match and not ts_match:
            sys.stderr.write(
                f"[warn] Line {idx+1}: timestamps differ ({old_entry.timestamp()} vs {new_entry.timestamp()}); proceeding.\n"
            )

        word_changes = diff_words(old_entry.text, new_entry.text)
        if not word_changes and speaker_match:
            continue

        header = f"[{new_entry.timestamp()}] {new_entry.speaker}: "
        updates: List[str] = []
        if not speaker_match:
            updates.append(f"SPEAKER {old_entry.speaker} -> {new_entry.speaker}")
        for old_seg, new_seg in word_changes:
            updates.append(f"{old_seg} -> {new_seg}")

        if updates:
            print(header + "; ".join(updates))

    if len(old_lines) > limit:
        sys.stderr.write(f"[warn] {len(old_lines) - limit} trailing lines only exist in {args.old}.\n")
    if len(new_lines) > limit:
        sys.stderr.write(f"[warn] {len(new_lines) - limit} trailing lines only exist in {args.new}.\n")


if __name__ == "__main__":
    main()
