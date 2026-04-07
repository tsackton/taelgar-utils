#!/usr/bin/env python3

"""Extract beat-scoped source context for annotation workflows."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import yaml


SOURCE_LINE_RE = re.compile(r"^(?P<header>\[(?P<uid>u\d{4,})(?:\s*\|[^\]]+)?\])\s*(?P<text>.*)$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract beat source context for annotation.")
    parser.add_argument("--transcript", type=Path, required=True, help="Cleaned source path.")
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

    transcript_lines = read_source_lines(transcript_path)
    session_payload = read_yaml_mapping(session_path)
    beats = parse_beats_payload(read_json_mapping(beats_path))
    uid_to_index = build_uid_index(transcript_lines)
    supplemental_sources = load_supplemental_sources(
        cleaned_dir=session_path.parent,
        file_prefix=file_prefix,
    )

    selected_beats = select_beats(beats, args.beat_id)
    contexts = []
    for beat in selected_beats:
        beat_index = beats.index(beat)
        previous_beat = beats[beat_index - 1] if beat_index > 0 else None
        next_beat = beats[beat_index + 1] if beat_index + 1 < len(beats) else None
        contexts.append(
            build_beat_context(
                beat=beat,
                previous_beat=previous_beat,
                next_beat=next_beat,
                transcript_lines=transcript_lines,
                uid_to_index=uid_to_index,
                session_payload=session_payload,
                supplemental_sources=supplemental_sources,
            )
        )

    json_path = output_dir / f"{file_prefix}-beat-contexts.json"
    index_path = output_dir / f"{file_prefix}-beat-context-index.md"
    payload = {
        "schemaVersion": "1.0",
        "sourceTranscriptPath": str(transcript_path),
        "sessionPath": str(session_path),
        "beatsPath": str(beats_path),
        "selectedBeatIds": [context["beat"]["beatId"] for context in contexts],
        "supplementalSources": supplemental_sources,
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


def read_source_lines(path: Path) -> List[Dict[str, str]]:
    lines: List[Dict[str, str]] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        match = SOURCE_LINE_RE.match(raw)
        if not match:
            raise SystemExit(f"Invalid cleaned source line in {path}:{line_number}: {raw}")
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
    previous_beat: Optional[Dict[str, Any]],
    next_beat: Optional[Dict[str, Any]],
    transcript_lines: Sequence[Dict[str, str]],
    uid_to_index: Dict[str, int],
    session_payload: Dict[str, Any],
    supplemental_sources: Sequence[Dict[str, Any]],
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
        "previousBeat": summarize_adjacent_beat(previous_beat),
        "nextBeat": summarize_adjacent_beat(next_beat),
        "session": summarize_session(session_payload),
        "sourceLines": beat_lines,
        "supplementalSources": list(supplemental_sources),
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
        "scope": optional_string(session_payload.get("scope")),
        "sourceType": optional_string(session_payload.get("sourceType")),
        "sessionNumber": session_payload.get("sessionNumber"),
        "drStart": optional_string(session_payload.get("drStart")),
        "drEnd": optional_string(session_payload.get("drEnd")),
        "realWorldDate": optional_string(session_payload.get("realWorldDate")),
        "participants": [entry for entry in participants_summary if any(entry.values())],
    }


def summarize_adjacent_beat(beat: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if beat is None:
        return None
    return {
        "beatId": beat["beatId"],
        "title": beat["title"],
        "dateStart": beat.get("dateStart"),
        "dateEnd": beat.get("dateEnd"),
    }


def render_index(payload: Dict[str, Any]) -> str:
    lines = [
        "# Beat Context Index",
        "",
        f"- Source: {payload['sourceTranscriptPath']}",
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
        lines.append(f"- Date Start: {beat.get('dateStart') or 'unknown'}")
        lines.append(f"- Date End: {beat.get('dateEnd') or 'same day'}")
        lines.append(f"- Time Window: {beat.get('timeWindow') or 'unknown'}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_context_markdown(context: Dict[str, Any]) -> str:
    beat = context["beat"]
    previous_beat = context.get("previousBeat")
    next_beat = context.get("nextBeat")
    session = context["session"]
    lines = [
        f"# Beat Context: {beat['beatId']} - {beat['title']}",
        "",
        "This file is only for producing `beat-facts.json`.",
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
        f"- Time Window: {beat.get('timeWindow') or 'unknown'}",
        "",
        "## Output Shape",
        "",
        "```json",
        "{",
        f'  "beatId": "{beat["beatId"]}",',
        f'  "dateStart": "{beat.get("dateStart") or ""}",',
        f'  "dateEnd": {json.dumps(beat.get("dateEnd"))},',
        f'  "timeWindow": {json.dumps(beat.get("timeWindow"))},',
        '  "shortSummary": "",',
        '  "longSummary": "",',
        '  "location": {',
        '    "kind": "fixed",',
        '    "primary": "",',
        '    "context": "",',
        '    "notes": ""',
        "  },",
        '  "npcs": [',
        '    {',
        '      "name": "",',
        '      "role": "encountered",',
        '      "context": "",',
        '      "notes": ""',
        "    }",
        "  ],",
        '  "items": [',
        '    {',
        '      "name": "",',
        '      "role": "mentioned",',
        '      "notes": ""',
        "    }",
        "  ],",
        '  "organizations": [',
        '    {',
        '      "name": "",',
        '      "role": "mentioned",',
        '      "notes": ""',
        "    }",
        "  ],",
        '  "combat": {',
        '    "isCombat": false',
        "  }",
        "}",
        "```",
    ]

    if previous_beat or next_beat:
        lines.extend(["", "## Adjacent Beats", ""])
        if previous_beat:
            previous_date = previous_beat.get("dateEnd") or previous_beat.get("dateStart") or "unknown"
            lines.append(f"- Previous: {previous_beat['beatId']} - {previous_beat['title']} ({previous_date})")
        if next_beat:
            next_date = next_beat.get("dateStart") or "unknown"
            lines.append(f"- Next: {next_beat['beatId']} - {next_beat['title']} ({next_date})")
        lines.extend(
            [
                "",
                "If the transcript does not clearly restate the location, prefer inheriting the prior beat's location unless there is a clear move or travel transition.",
            ]
        )

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

    lines.extend(["", "## Source", ""])
    for line in context["sourceLines"]:
        lines.append(line["raw"])
    if context.get("supplementalSources"):
        lines.extend(["", "## Supplemental Sources", ""])
        for source in context["supplementalSources"]:
            lines.append(f"### {source.get('label') or 'Supplemental'}")
            lines.append("")
            if source.get("original"):
                lines.append(f"- Original: {source['original']}")
            for line in source.get("lines", []):
                lines.append(line)
            lines.append("")
    lines.append("")
    return "\n".join(lines)


def load_supplemental_sources(*, cleaned_dir: Path, file_prefix: str) -> List[Dict[str, Any]]:
    structure_path = cleaned_dir / "normalization-artifacts" / f"{file_prefix}-source-structure.json"
    if not structure_path.exists():
        return []
    payload = read_json_mapping(structure_path)
    supplemental_sources = payload.get("supplementalSources")
    if not isinstance(supplemental_sources, list):
        return []
    loaded: List[Dict[str, Any]] = []
    for item in supplemental_sources:
        if not isinstance(item, dict):
            continue
        path_text = optional_string(item.get("path"))
        if path_text is None:
            continue
        source_path = Path(path_text).expanduser().resolve()
        if not source_path.exists():
            continue
        loaded.append(
            {
                "label": optional_string(item.get("label")),
                "original": optional_string(item.get("original")),
                "lines": source_path.read_text(encoding="utf-8").splitlines(),
            }
        )
    return loaded


def safe_slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-") or "beat"


if __name__ == "__main__":
    raise SystemExit(main())
