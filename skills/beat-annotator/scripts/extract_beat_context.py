#!/usr/bin/env python3

"""Extract beat-scoped transcript context for annotation workflows."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import yaml


TRANSCRIPT_LINE_RE = re.compile(r"^(?P<header>\[(?P<uid>u\d{4,})\s*\|[^\]]+\])\s(?P<text>.*)$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract beat transcript context for annotation.")
    parser.add_argument("--transcript", type=Path, required=True, help="Cleaned transcript path.")
    parser.add_argument("--session", type=Path, required=True, help="session.yaml path.")
    parser.add_argument("--beats-json", type=Path, required=True, help="Finalized beats.json path.")
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory for extracted context files.")
    parser.add_argument(
        "--file-prefix",
        type=str,
        required=True,
        help="Unique lowercase prefix for generated artifacts, e.g. 'addermarch-campaign-007'.",
    )
    parser.add_argument(
        "--beat-id",
        type=str,
        default=None,
        help="Optional beatId to extract. If omitted, extract all beats.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    transcript_path = args.transcript.expanduser().resolve()
    session_path = args.session.expanduser().resolve()
    beats_path = args.beats_json.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    contexts_dir = output_dir / "contexts"
    output_dir.mkdir(parents=True, exist_ok=True)
    contexts_dir.mkdir(parents=True, exist_ok=True)

    file_prefix = args.file_prefix.strip()
    if not file_prefix:
        raise SystemExit("--file-prefix must be non-empty.")

    assert_not_in_sources_dir(transcript_path, "--transcript")
    assert_not_in_sources_dir(session_path, "--session")
    assert_not_in_sources_dir(beats_path, "--beats-json")

    transcript_lines = read_transcript(transcript_path)
    session_payload = read_yaml_mapping(session_path)
    beats = parse_beats_payload(read_json_mapping(beats_path))
    uid_to_index = build_uid_index(transcript_lines)

    selected_beats = select_beats(beats, args.beat_id)
    contexts = [
        build_beat_context(
            beat=beat,
            transcript_lines=transcript_lines,
            uid_to_index=uid_to_index,
            session_payload=session_payload,
        )
        for beat in selected_beats
    ]

    json_path = output_dir / f"{file_prefix}-beat-contexts.json"
    index_path = output_dir / f"{file_prefix}-beat-context-index.md"
    payload = {
        "schemaVersion": "1.0",
        "sourceTranscriptPath": str(transcript_path),
        "sessionPath": str(session_path),
        "beatsPath": str(beats_path),
        "selectedBeatIds": [context["beat"]["beatId"] for context in contexts],
        "contexts": contexts,
    }
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    index_path.write_text(render_index(payload), encoding="utf-8")

    for context in contexts:
        beat_id = context["beat"]["beatId"]
        markdown_path = contexts_dir / f"{safe_slug(beat_id)}.md"
        markdown_path.write_text(render_context_markdown(context), encoding="utf-8")

    print(f"Extracted {len(contexts)} beat context file(s).")
    print(f"Wrote {json_path}")
    print(f"Wrote {index_path}")
    print(f"Wrote context markdown under {contexts_dir}")
    return 0


def assert_not_in_sources_dir(path: Path, arg_name: str) -> None:
    if "sources" in path.parts:
        raise SystemExit(f"{arg_name} must not point inside a bundle 'sources' directory: {path}")


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


def read_transcript(path: Path) -> List[Dict[str, str]]:
    lines: List[Dict[str, str]] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        match = TRANSCRIPT_LINE_RE.match(raw)
        if not match:
            raise SystemExit(f"Invalid cleaned transcript line in {path}:{line_number}: {raw}")
        lines.append(
            {
                "uid": match.group("uid"),
                "header": match.group("header"),
                "text": match.group("text"),
                "raw": raw,
            }
        )
    return lines


def parse_beats_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    beats = payload.get("beats")
    if not isinstance(beats, list) or not beats:
        raise SystemExit("Beat JSON must contain a non-empty 'beats' list.")

    parsed: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw in beats:
        if not isinstance(raw, dict):
            raise SystemExit(f"Invalid beat {raw!r}; expected an object.")
        beat = {
            "beatId": required_string(raw, "beatId"),
            "title": required_string(raw, "title"),
            "startUid": required_string(raw, "startUid"),
            "endUid": required_string(raw, "endUid"),
            "lineCount": raw.get("lineCount"),
            "dateStart": optional_string(raw.get("dateStart")),
            "dateEnd": optional_string(raw.get("dateEnd")),
            "timeWindow": optional_string(raw.get("timeWindow")),
            "containsCombat": bool(raw.get("containsCombat", False)),
            "boundaryReason": required_string(raw, "boundaryReason"),
            "dateEvidence": normalize_string_list(raw.get("dateEvidence")),
        }
        beat_id = beat["beatId"]
        if beat_id in seen_ids:
            raise SystemExit(f"Duplicate beatId in beats payload: {beat_id}")
        seen_ids.add(beat_id)
        parsed.append(beat)
    return parsed


def required_string(raw: Dict[str, Any], field_name: str) -> str:
    value = optional_string(raw.get(field_name))
    if value is None:
        raise SystemExit(f"Beat is missing required field {field_name!r}: {raw!r}")
    return value


def optional_string(value: Any) -> Optional[str]:
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


def build_uid_index(transcript_lines: Sequence[Dict[str, str]]) -> Dict[str, int]:
    return {line["uid"]: index for index, line in enumerate(transcript_lines)}


def select_beats(beats: Sequence[Dict[str, Any]], beat_id: Optional[str]) -> List[Dict[str, Any]]:
    if beat_id is None:
        return list(beats)
    selected = [beat for beat in beats if beat["beatId"] == beat_id]
    if not selected:
        raise SystemExit(f"Unknown beatId: {beat_id}")
    return selected


def build_beat_context(
    *,
    beat: Dict[str, Any],
    transcript_lines: Sequence[Dict[str, str]],
    uid_to_index: Dict[str, int],
    session_payload: Dict[str, Any],
) -> Dict[str, Any]:
    start_index = uid_to_index.get(beat["startUid"])
    end_index = uid_to_index.get(beat["endUid"])
    if start_index is None or end_index is None:
        raise SystemExit(f"Beat references unknown transcript uid: {beat['beatId']}")
    if start_index > end_index:
        raise SystemExit(f"Beat has inverted uid range: {beat['beatId']}")

    beat_lines = list(transcript_lines[start_index : end_index + 1])
    line_count = end_index - start_index + 1
    if beat.get("lineCount") is not None and int(beat["lineCount"]) != line_count:
        raise SystemExit(
            f"Beat {beat['beatId']} lineCount mismatch: expected {line_count}, got {beat['lineCount']}"
        )

    return {
        "beat": {
            **beat,
            "lineCount": line_count,
            "startIndex": start_index,
            "endIndex": end_index,
        },
        "session": summarize_session(session_payload),
        "transcriptLines": beat_lines,
    }


def summarize_session(session_payload: Dict[str, Any]) -> Dict[str, Any]:
    participants = session_payload.get("participants")
    if isinstance(participants, list):
        participants_summary = [
            {
                "name": optional_string(entry.get("name")) if isinstance(entry, dict) else None,
                "role": optional_string(entry.get("role")) if isinstance(entry, dict) else None,
                "gameRole": optional_string(entry.get("gameRole")) if isinstance(entry, dict) else None,
            }
            for entry in participants
        ]
    else:
        participants_summary = []

    return {
        "title": optional_string(session_payload.get("title")),
        "campaign": optional_string(session_payload.get("campaign")),
        "sessionNumber": session_payload.get("sessionNumber"),
        "drStart": optional_string(session_payload.get("drStart")),
        "drEnd": optional_string(session_payload.get("drEnd")),
        "realWorldDate": optional_string(session_payload.get("realWorldDate")),
        "participants": [entry for entry in participants_summary if any(entry.values())],
    }


def render_index(payload: Dict[str, Any]) -> str:
    lines = [
        "# Beat Context Index",
        "",
        f"- Source transcript: {payload['sourceTranscriptPath']}",
        f"- Session file: {payload['sessionPath']}",
        f"- Beats file: {payload['beatsPath']}",
        f"- Selected beats: {len(payload['contexts'])}",
        "",
    ]
    for context in payload["contexts"]:
        beat = context["beat"]
        lines.append(f"## {beat['beatId']} - {beat['title']}")
        lines.append("")
        lines.append(f"- Lines: {beat['lineCount']}")
        lines.append(f"- Range: `{beat['startUid']}` -> `{beat['endUid']}`")
        if beat.get("dateEnd"):
            lines.append(f"- Date: {beat['dateStart']} to {beat['dateEnd']}")
        else:
            lines.append(f"- Date: {beat.get('dateStart') or 'unknown'}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_context_markdown(context: Dict[str, Any]) -> str:
    beat = context["beat"]
    session = context["session"]
    lines = [
        f"# Beat Context: {beat['beatId']} - {beat['title']}",
        "",
        "This file is only for extracting `npcs`, `locations`, and `items` into a separate annotation file.",
        "Do not edit `beats.json`.",
        "",
        "## Session",
        "",
        f"- Campaign: {session.get('campaign') or 'unknown'}",
        f"- Session Number: {session.get('sessionNumber') if session.get('sessionNumber') is not None else 'unknown'}",
        "",
        "## Beat Metadata",
        "",
        f"- Beat ID: {beat['beatId']}",
        f"- Title: {beat['title']}",
        f"- Range: `{beat['startUid']}` -> `{beat['endUid']}`",
        f"- Lines: {beat['lineCount']}",
        f"- Date Start: {beat.get('dateStart') or 'unknown'}",
        f"- Date End: {beat.get('dateEnd') or 'same day'}",
        "",
        "## Output Shape",
        "",
        "```json",
        "{",
        f'  "beatId": "{beat["beatId"]}",',
        '  "npcs": [],',
        '  "locations": [],',
        '  "items": []',
        "}",
        "```",
    ]

    if session["participants"]:
        lines.extend(["", "## Participants", ""])
        for entry in session["participants"]:
            label = entry.get("gameRole") or entry.get("role") or entry.get("name") or "unknown"
            details = []
            if entry.get("name"):
                details.append(f"name={entry['name']}")
            if entry.get("role"):
                details.append(f"role={entry['role']}")
            if entry.get("gameRole"):
                details.append(f"gameRole={entry['gameRole']}")
            lines.append(f"- {label}: {', '.join(details)}")

    lines.extend(["", "## Transcript", ""])
    for line in context["transcriptLines"]:
        lines.append(line["raw"])
    lines.append("")
    return "\n".join(lines)


def safe_slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-") or "beat"


if __name__ == "__main__":
    raise SystemExit(main())
