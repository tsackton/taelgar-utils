#!/usr/bin/env python3

"""Validate cleaned transcripts and derive cleanup artifacts from diffs."""

from __future__ import annotations

import argparse
import difflib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import yaml


LINE_RE = re.compile(r"^(?P<header>\[[^\]]+\])\s(?P<text>.*)$")
UNCERTAIN_RE = re.compile(r"\[\[(.+?)\]\]")
TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build transcript cleanup artifacts from diffs.")
    parser.add_argument("--original", type=Path, required=True, help="Prepared transcript input.")
    parser.add_argument("--cleaned", type=Path, required=True, help="Cleaned transcript output.")
    parser.add_argument("--report-json", type=Path, required=True, help="Path to cleanup_report.json.")
    parser.add_argument(
        "--corrections-yaml",
        type=Path,
        required=True,
        help="Path to session_corrections.yaml.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    original = read_transcript(args.original)
    cleaned = read_transcript(args.cleaned)

    report, corrections = build_reports(original, cleaned)

    args.report_json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    args.corrections_yaml.write_text(
        yaml.safe_dump(corrections, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    if report["validationErrors"]:
        for error in report["validationErrors"]:
            print(f"ERROR: {error}")
        return 1

    print(f"Wrote {args.report_json}")
    print(f"Wrote {args.corrections_yaml}")
    return 0


def read_transcript(path: Path) -> List[Dict[str, str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    parsed: List[Dict[str, str]] = []
    for line_number, raw in enumerate(lines, start=1):
        if not raw.strip():
            continue
        match = LINE_RE.match(raw)
        if not match:
            raise SystemExit(f"Invalid transcript line in {path}:{line_number}: {raw}")
        parsed.append(
            {
                "lineNumber": str(line_number),
                "header": match.group("header"),
                "text": match.group("text"),
            }
        )
    return parsed


def build_reports(
    original: Sequence[Dict[str, str]],
    cleaned: Sequence[Dict[str, str]],
) -> Tuple[Dict[str, object], Dict[str, object]]:
    validation_errors: List[str] = []
    line_diffs: List[Dict[str, object]] = []
    unresolved: List[Dict[str, object]] = []
    replacement_index: Dict[Tuple[str, str], Dict[str, object]] = {}

    if len(original) != len(cleaned):
        validation_errors.append(
            f"Line count changed: original has {len(original)} transcript lines, cleaned has {len(cleaned)}."
        )

    pair_count = min(len(original), len(cleaned))
    for index in range(pair_count):
        before = original[index]
        after = cleaned[index]
        header = before["header"]

        if before["header"] != after["header"]:
            validation_errors.append(
                f"Header mismatch at line {before['lineNumber']}: {before['header']} != {after['header']}"
            )

        if before["text"] != after["text"]:
            line_diffs.append(
                {
                    "header": header,
                    "lineNumber": int(before["lineNumber"]),
                    "originalText": before["text"],
                    "cleanedText": after["text"],
                }
            )
            index_replacements(replacement_index, header, before["text"], after["text"])

        for phrase in UNCERTAIN_RE.findall(after["text"]):
            unresolved.append(
                {
                    "header": header,
                    "lineNumber": int(after["lineNumber"]),
                    "phrase": phrase,
                }
            )

    repeated_replacements = [
        {
            "from": source,
            "to": target,
            "count": entry["count"],
            "headers": sorted(entry["headers"]),
        }
        for (source, target), entry in sorted(
            replacement_index.items(),
            key=lambda item: (-int(item[1]["count"]), item[0][0], item[0][1]),
        )
        if int(entry["count"]) >= 2
    ]

    all_replacements = [
        {
            "from": source,
            "to": target,
            "count": entry["count"],
            "headers": sorted(entry["headers"]),
        }
        for (source, target), entry in sorted(
            replacement_index.items(),
            key=lambda item: (-int(item[1]["count"]), item[0][0], item[0][1]),
        )
    ]

    report = {
        "lineCount": len(original),
        "changedLineCount": len(line_diffs),
        "validationErrors": validation_errors,
        "unresolvedCount": len(unresolved),
        "unresolvedPhrases": unresolved,
        "changedLines": line_diffs,
    }
    corrections = {
        "allReplacements": all_replacements,
        "repeatedReplacements": repeated_replacements,
        "unresolvedPhrases": unresolved,
    }
    return report, corrections


def index_replacements(
    replacement_index: Dict[Tuple[str, str], Dict[str, object]],
    header: str,
    original_text: str,
    cleaned_text: str,
) -> None:
    before_tokens = tokenize(original_text)
    after_tokens = tokenize(cleaned_text)
    matcher = difflib.SequenceMatcher(a=before_tokens, b=after_tokens)

    for opcode, i1, i2, j1, j2 in matcher.get_opcodes():
        if opcode == "equal":
            continue
        source = normalize_diff_span(before_tokens[i1:i2])
        target = normalize_diff_span(after_tokens[j1:j2])
        if not source or not target or source == target:
            continue
        if len(source) > 80 or len(target) > 80:
            continue
        key = (source, target)
        entry = replacement_index.setdefault(key, {"count": 0, "headers": set()})
        entry["count"] = int(entry["count"]) + 1
        entry["headers"].add(header)


def tokenize(text: str) -> List[str]:
    return TOKEN_RE.findall(text)


def normalize_diff_span(tokens: Sequence[str]) -> str:
    text = " ".join(tokens).strip()
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r"\s+\)", ")", text)
    return text.strip()


if __name__ == "__main__":
    raise SystemExit(main())
