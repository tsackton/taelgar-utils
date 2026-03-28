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
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory where cleanup artifacts will be written.",
    )
    parser.add_argument(
        "--file-prefix",
        type=str,
        required=True,
        help="Unique lowercase prefix for all generated cleanup artifacts, e.g. 'addermarch-007'.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    original = read_transcript(args.original)
    cleaned = read_transcript(args.cleaned)
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    file_prefix = args.file_prefix.strip()
    if not file_prefix:
        raise SystemExit("--file-prefix must be non-empty.")

    report_json_path = output_dir / f"{file_prefix}-cleanup-report.json"
    corrections_yaml_path = output_dir / f"{file_prefix}-session-corrections.yaml"
    human_transcript_path = output_dir / f"{file_prefix}-human-transcript.md"
    cleanup_summary_path = output_dir / f"{file_prefix}-cleanup-summary.md"

    report, corrections = build_reports(original, cleaned)

    report_json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    corrections_yaml_path.write_text(
        yaml.safe_dump(corrections, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    human_transcript_path.write_text(build_human_transcript(cleaned), encoding="utf-8")
    cleanup_summary_path.write_text(
        build_cleanup_summary_markdown(report, corrections),
        encoding="utf-8",
    )

    if report["validationErrors"]:
        for error in report["validationErrors"]:
            print(f"ERROR: {error}")
        return 1

    print_summary(report)
    print(f"Wrote {report_json_path}")
    print(f"Wrote {corrections_yaml_path}")
    print(f"Wrote {human_transcript_path}")
    print(f"Wrote {cleanup_summary_path}")
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
                "speaker": extract_speaker(match.group("header")),
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
        "summary": build_summary(line_diffs, all_replacements, repeated_replacements, unresolved),
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


def build_summary(
    line_diffs: Sequence[Dict[str, object]],
    all_replacements: Sequence[Dict[str, object]],
    repeated_replacements: Sequence[Dict[str, object]],
    unresolved: Sequence[Dict[str, object]],
) -> Dict[str, object]:
    unique_unresolved = sorted({str(item["phrase"]) for item in unresolved})
    return {
        "changedLineCount": len(line_diffs),
        "replacementCount": len(all_replacements),
        "repeatedReplacementCount": len(repeated_replacements),
        "topReplacements": list(all_replacements[:10]),
        "uniqueUnresolvedPhrases": unique_unresolved,
    }


def print_summary(report: Dict[str, object]) -> None:
    summary = report["summary"]
    print(
        "Summary: "
        f"{summary['changedLineCount']} changed lines, "
        f"{summary['replacementCount']} replacement patterns, "
        f"{summary['repeatedReplacementCount']} repeated replacements, "
        f"{report['unresolvedCount']} unresolved phrases."
    )
    top_replacements = summary["topReplacements"]
    if top_replacements:
        print("Top replacements:")
        for item in top_replacements[:5]:
            print(f"  {item['from']} -> {item['to']} ({item['count']}x)")
    unique_unresolved = summary["uniqueUnresolvedPhrases"]
    if unique_unresolved:
        print("Unresolved phrases:")
        for phrase in unique_unresolved[:10]:
            print(f"  [[{phrase}]]")


def build_human_transcript(cleaned: Sequence[Dict[str, str]]) -> str:
    condensed: List[Tuple[str, List[str]]] = []
    for line in cleaned:
        speaker = line["speaker"]
        text = line["text"].strip()
        if condensed and condensed[-1][0] == speaker:
            condensed[-1][1].append(text)
        else:
            condensed.append((speaker, [text]))

    paragraphs = ["# Human-Readable Transcript", ""]
    for speaker, texts in condensed:
        merged_text = " ".join(texts).strip()
        paragraphs.append(f"**{speaker}:** {merged_text}")
        paragraphs.append("")
    return "\n".join(paragraphs).rstrip() + "\n"


def build_cleanup_summary_markdown(
    report: Dict[str, object],
    corrections: Dict[str, object],
) -> str:
    summary = report["summary"]
    replacement_groups: Dict[str, List[Dict[str, object]]] = defaultdict(list)
    for item in corrections["allReplacements"]:
        replacement_groups[str(item["to"])].append(item)

    lines = [
        "# Cleanup Summary",
        "",
        f"- Transcript lines: {report['lineCount']}",
        f"- Changed lines: {report['changedLineCount']}",
        f"- Replacement patterns: {summary['replacementCount']}",
        f"- Repeated replacements: {summary['repeatedReplacementCount']}",
        f"- Unresolved phrases: {report['unresolvedCount']}",
        "",
        "## Replacements By Correct Term",
        "",
    ]

    if not replacement_groups:
        lines.append("No replacements recorded.")
        lines.append("")
    else:
        for target in sorted(replacement_groups, key=str.lower):
            lines.append(f"### {target}")
            for item in sorted(
                replacement_groups[target],
                key=lambda entry: (-int(entry["count"]), str(entry["from"]).lower()),
            ):
                lines.append(f"- {item['from']} ({item['count']}x)")
            lines.append("")

    unresolved = report["unresolvedPhrases"]
    if unresolved:
        lines.append("## Unresolved Phrases")
        lines.append("")
        for item in unresolved:
            lines.append(f"- [[{item['phrase']}]] at {item['header']}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


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


def extract_speaker(header: str) -> str:
    inner = header.strip()[1:-1]
    parts = [part.strip() for part in inner.split("|")]
    if len(parts) < 3:
        raise SystemExit(f"Invalid transcript header: {header}")
    return parts[-1]


if __name__ == "__main__":
    raise SystemExit(main())
