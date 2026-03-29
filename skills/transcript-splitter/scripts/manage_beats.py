#!/usr/bin/env python3

"""Validate and render transcript beat artifacts."""

from __future__ import annotations

import argparse
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import yaml


TRANSCRIPT_LINE_RE = re.compile(r"^(?P<header>\[(?P<uid>u\d{4,})\s*\|[^\]]+\])\s(?P<text>.*)$")
VALID_TIME_WINDOWS = {"dawn", "morning", "midday", "afternoon", "evening", "night"}
TARGET_MIN_LINES = 150
TARGET_MAX_LINES = 500
TITLE_WORD_TARGET = 6


@dataclass(frozen=True)
class TranscriptLine:
    uid: str
    text: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate and render beat artifacts.")
    parser.add_argument("--transcript", type=Path, required=True, help="Cleaned transcript path.")
    parser.add_argument("--session", type=Path, required=True, help="session.yaml path.")
    parser.add_argument("--beats-json", type=Path, required=True, help="Beat JSON path.")
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory for final beat artifacts.")
    parser.add_argument(
        "--file-prefix",
        type=str,
        required=True,
        help="Unique lowercase prefix for generated artifacts, e.g. 'addermarch-campaign-007'.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    file_prefix = args.file_prefix.strip()
    if not file_prefix:
        raise SystemExit("--file-prefix must be non-empty.")

    transcript_path = args.transcript.expanduser().resolve()
    session_path = args.session.expanduser().resolve()
    beats_input_path = args.beats_json.expanduser().resolve()

    assert_not_in_sources_dir(transcript_path, "--transcript")
    assert_not_in_sources_dir(session_path, "--session")
    assert_not_in_sources_dir(beats_input_path, "--beats-json")

    transcript_lines = read_transcript(transcript_path)
    session_payload = read_yaml_mapping(session_path)
    beats_payload = read_json_mapping(beats_input_path)
    beats = finalize_beats(parse_beats_payload(beats_payload), transcript_lines)

    validation_errors, warnings = validate_beats(
        beats=beats,
        transcript_lines=transcript_lines,
        session_payload=session_payload,
    )
    if validation_errors:
        for error in validation_errors:
            print(f"ERROR: {error}")
        return 1

    beats_json_path = output_dir / f"{file_prefix}-beats.json"
    preview_path = output_dir / f"{file_prefix}-beats-preview.md"

    final_payload = {
        "schemaVersion": "1.0",
        "sourceTranscriptPath": str(transcript_path),
        "sessionPath": str(session_path),
        "beats": beats,
    }
    beats_json_path.write_text(json.dumps(final_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    preview_path.write_text(render_preview(final_payload, warnings), encoding="utf-8")

    print_summary(beats, warnings)
    print(f"Wrote {beats_json_path}")
    print(f"Wrote {preview_path}")
    return 0


def read_transcript(path: Path) -> List[TranscriptLine]:
    lines: List[TranscriptLine] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        match = TRANSCRIPT_LINE_RE.match(raw)
        if not match:
            raise SystemExit(f"Invalid cleaned transcript line in {path}:{line_number}: {raw}")
        lines.append(TranscriptLine(uid=match.group("uid"), text=match.group("text")))
    return lines


def assert_not_in_sources_dir(path: Path, arg_name: str) -> None:
    if "sources" in path.parts:
        raise SystemExit(
            f"{arg_name} must not point inside a bundle 'sources' directory: {path}"
        )


def read_yaml_mapping(path: Path) -> Dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise SystemExit(f"Expected a YAML mapping in {path}")
    return payload


def read_json_mapping(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"Expected a JSON object in {path}")
    return payload


def parse_beats_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    beats = payload.get("beats")
    if not isinstance(beats, list) or not beats:
        raise SystemExit("Beat JSON must contain a non-empty 'beats' list.")

    parsed: List[Dict[str, Any]] = []
    for raw in beats:
        if not isinstance(raw, dict):
            raise SystemExit(f"Invalid beat {raw!r}; expected an object.")
        beat = {
            "beatId": str(raw.get("beatId", "")).strip(),
            "title": str(raw.get("title", "")).strip(),
            "startUid": str(raw.get("startUid", "")).strip(),
            "endUid": str(raw.get("endUid", "")).strip(),
            "lineCount": raw.get("lineCount"),
            "dateStart": normalize_optional_string(raw.get("dateStart")),
            "dateEnd": normalize_optional_string(raw.get("dateEnd")),
            "timeWindow": normalize_optional_string(raw.get("timeWindow")),
            "containsCombat": bool(raw.get("containsCombat", False)),
            "boundaryReason": str(raw.get("boundaryReason", "")).strip(),
            "dateEvidence": normalize_string_list(raw.get("dateEvidence")),
        }
        if not beat["beatId"] or not beat["title"] or not beat["startUid"] or not beat["endUid"]:
            raise SystemExit(f"Beat is missing required fields: {raw!r}")
        parsed.append(beat)
    return parsed


def normalize_optional_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise SystemExit(f"Expected a list of strings, got {value!r}")
    return [str(item).strip() for item in value if str(item).strip()]


def finalize_beats(
    beats: Sequence[Dict[str, Any]],
    transcript_lines: Sequence[TranscriptLine],
) -> List[Dict[str, Any]]:
    uid_to_index = build_uid_index(transcript_lines)
    finalized: List[Dict[str, Any]] = []
    for beat in beats:
        start_index = uid_to_index.get(beat["startUid"])
        end_index = uid_to_index.get(beat["endUid"])
        if start_index is None or end_index is None:
            raise SystemExit(f"Beat references unknown transcript uid: {beat['beatId']}")
        if start_index > end_index:
            raise SystemExit(f"Beat has inverted uid range: {beat['beatId']}")
        finalized_beat = deepcopy(beat)
        finalized_beat["lineCount"] = end_index - start_index + 1
        finalized_beat["dateEvidence"] = dedupe_preserve_order(finalized_beat["dateEvidence"])
        finalized.append(finalized_beat)
    return finalized


def validate_beats(
    *,
    beats: Sequence[Dict[str, Any]],
    transcript_lines: Sequence[TranscriptLine],
    session_payload: Dict[str, Any],
) -> tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []
    uid_to_index = build_uid_index(transcript_lines)
    covered_indices: List[int] = []

    previous_end_index: Optional[int] = None
    previous_end_date: Optional[date] = parse_optional_date(session_payload.get("drStart"))
    previous_date_end: Optional[date] = None

    seen_ids: set[str] = set()
    for beat in beats:
        beat_id = beat["beatId"]
        if beat_id in seen_ids:
            errors.append(f"Duplicate beatId: {beat_id}")
        seen_ids.add(beat_id)

        start_index = uid_to_index.get(beat["startUid"])
        end_index = uid_to_index.get(beat["endUid"])
        if start_index is None or end_index is None:
            errors.append(f"{beat_id} references unknown transcript uid.")
            continue
        if start_index > end_index:
            errors.append(f"{beat_id} has startUid after endUid.")
            continue

        expected_line_count = end_index - start_index + 1
        if int(beat["lineCount"]) != expected_line_count:
            errors.append(
                f"{beat_id} has incorrect lineCount {beat['lineCount']} (expected {expected_line_count})."
            )
        if previous_end_index is not None and start_index != previous_end_index + 1:
            errors.append(f"{beat_id} does not continue contiguously after the previous beat.")
        previous_end_index = end_index
        covered_indices.extend(range(start_index, end_index + 1))

        title_word_count = len(beat["title"].split())
        if title_word_count > TITLE_WORD_TARGET:
            warnings.append(
                f"{beat_id} title is {title_word_count} words; aim for {TITLE_WORD_TARGET} or fewer unless clarity requires more."
            )

        time_window = beat.get("timeWindow")
        if time_window is not None and time_window not in VALID_TIME_WINDOWS:
            errors.append(f"{beat_id} has invalid timeWindow: {time_window}")

        date_start = parse_optional_date(beat.get("dateStart"))
        if date_start is None:
            errors.append(f"{beat_id} is missing dateStart.")
            continue
        date_end = parse_optional_date(beat.get("dateEnd")) or date_start
        if date_end < date_start:
            errors.append(f"{beat_id} has dateEnd before dateStart.")
        if previous_end_date is not None:
            if date_start != previous_end_date and date_start != previous_end_date + timedelta(days=1):
                errors.append(
                    f"{beat_id} violates day sequencing: {date_start.isoformat()} does not match "
                    f"{previous_end_date.isoformat()} or the next day."
                )
        previous_end_date = date_end

        if not beat.get("boundaryReason"):
            errors.append(f"{beat_id} is missing boundaryReason.")
        if not beat.get("dateEvidence"):
            errors.append(f"{beat_id} is missing dateEvidence.")

        if bool(beat.get("containsCombat")) and expected_line_count > TARGET_MAX_LINES:
            errors.append(f"{beat_id} is a combat beat with {expected_line_count} lines (> {TARGET_MAX_LINES}).")

        if expected_line_count < TARGET_MIN_LINES:
            if previous_date_end is None or date_start == previous_date_end:
                warnings.append(
                    f"{beat_id} is short at {expected_line_count} lines; consider merging unless a strong scene break or day transition justifies it."
                )
            else:
                warnings.append(
                    f"{beat_id} is short at {expected_line_count} lines, but a day transition may justify it."
                )
        elif expected_line_count > TARGET_MAX_LINES:
            warnings.append(
                f"{beat_id} is long at {expected_line_count} lines; consider splitting unless a strong scene break or date structure justifies it."
            )

        previous_date_end = date_end

    if len(covered_indices) != len(transcript_lines):
        errors.append(
            f"Transcript coverage mismatch: beats cover {len(covered_indices)} lines, transcript has {len(transcript_lines)}."
        )
    elif sorted(covered_indices) != list(range(len(transcript_lines))):
        errors.append("Transcript coverage has gaps or overlaps.")

    return errors, warnings


def build_uid_index(transcript_lines: Sequence[TranscriptLine]) -> Dict[str, int]:
    return {line.uid: index for index, line in enumerate(transcript_lines)}


def parse_optional_date(value: Any) -> Optional[date]:
    text = normalize_optional_string(value)
    if text is None:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise SystemExit(f"Invalid ISO date: {text}") from exc


def dedupe_preserve_order(values: Sequence[str]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def render_preview(payload: Dict[str, Any], warnings: Sequence[str]) -> str:
    beats = payload["beats"]
    lines = [
        "# Beats Preview",
        "",
        f"- Source transcript: {payload['sourceTranscriptPath']}",
        f"- Session file: {payload['sessionPath']}",
        f"- Beat count: {len(beats)}",
        "",
    ]
    if warnings:
        lines.append("## Warnings")
        lines.append("")
        for warning in warnings:
            lines.append(f"- {warning}")
        lines.append("")
    for beat in beats:
        lines.append(f"## {beat['beatId']} — {beat['title']}")
        lines.append("")
        lines.append(f"- Range: `{beat['startUid']}` → `{beat['endUid']}`")
        lines.append(f"- Lines: {beat['lineCount']}")
        if beat.get("dateEnd"):
            lines.append(f"- Date: {beat['dateStart']} to {beat['dateEnd']}")
        else:
            lines.append(f"- Date: {beat['dateStart']}")
        lines.append(f"- Time Window: {beat.get('timeWindow') or 'unknown'}")
        lines.append(f"- Combat: {'yes' if beat.get('containsCombat') else 'no'}")
        lines.append(f"- Boundary Reason: {beat['boundaryReason']}")
        lines.append("- Date Evidence:")
        for item in beat["dateEvidence"]:
            lines.append(f"  - {item}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def print_summary(beats: Sequence[Dict[str, Any]], warnings: Sequence[str]) -> None:
    combat_count = sum(1 for beat in beats if beat.get("containsCombat"))
    print(
        f"Summary: {len(beats)} beats, {combat_count} combat beats, "
        f"{sum(int(beat['lineCount']) for beat in beats)} transcript lines covered."
    )
    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"  - {warning}")


if __name__ == "__main__":
    raise SystemExit(main())
