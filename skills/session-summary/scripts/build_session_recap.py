#!/usr/bin/env python3

"""Build a structured machine-parseable markdown session recap scaffold."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import yaml

from participant_inference import infer_session_header_participants

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a structured markdown session recap scaffold.")
    parser.add_argument("--context-json", type=Path, required=True, help="session-summary-context JSON path.")
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory for generated recap artifacts.")
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

    context_path = args.context_json.expanduser().resolve()
    context = read_json_mapping(context_path)
    session_path = Path(required_string(context, "sessionPath", "context")).expanduser().resolve()
    beats_path = Path(required_string(context, "beatsPath", "context")).expanduser().resolve()
    beat_facts_path = Path(required_string(context, "beatFactsPath", "context")).expanduser().resolve()
    session_payload = read_yaml_mapping(session_path)
    beats_payload = read_json_mapping(beats_path)
    participant_info = infer_session_header_participants(session_payload)

    recap_path = output_dir / f"{file_prefix}-session-recap.md"
    recap_path.write_text(
        render_recap(
            context_path=context_path,
            context=context,
            session_path=session_path,
            beats_path=beats_path,
            beat_facts_path=beat_facts_path,
            session_payload=session_payload,
            beats_payload=beats_payload,
            participant_info=participant_info,
        ),
        encoding="utf-8",
    )

    for warning in participant_info.get("warnings", []):
        print(f"WARNING: {warning}")
    print(f"Wrote {recap_path}")
    return 0


def render_recap(
    *,
    context_path: Path,
    context: Dict[str, Any],
    session_path: Path,
    beats_path: Path,
    beat_facts_path: Path,
    session_payload: Dict[str, Any],
    beats_payload: Dict[str, Any],
    participant_info: Dict[str, Any],
) -> str:
    session = context["session"]
    scope = normalize_optional_string(session.get("scope")) or "session"
    transcript_path = normalize_optional_string(beats_payload.get("sourceTranscriptPath"))
    lines = ["# Session Recap", ""]
    lines.extend(
        render_session_header(
            session,
            participant_info.get("dmName"),
            participant_info.get("pcs", []),
            scope=scope,
        )
    )
    lines.extend(render_timeline(context.get("timelineBlocks", [])))
    lines.extend(render_recap_blocks(context.get("recapBlocks", [])))
    lines.extend(render_cast(context.get("worldCandidates", {})))
    lines.extend(render_locations(context.get("worldCandidates", {})))
    lines.extend(render_orgs_and_items(context.get("worldCandidates", {})))
    lines.extend(render_combat(context.get("recapBlocks", [])))
    lines.extend(render_source_files(context_path, beats_path, beat_facts_path, transcript_path))
    return "\n".join(lines).rstrip() + "\n"


def render_session_header(
    session: Dict[str, Any],
    dm_name: Optional[str],
    players: Sequence[str],
    *,
    scope: str,
) -> List[str]:
    heading = "## Arc Header" if scope == "arc" else "## Session Header"
    return [
        heading,
        "",
        f"- Title: TODO",
        f"- Tagline: TODO",
        f"- One-Sentence Summary: TODO",
        f"- Campaign: {render_scalar(session.get('campaign'))}",
        f"- Scope: {scope}",
        f"- Session Number: {render_scalar(session.get('sessionNumber'))}",
        f"- DR Date: {format_date_span(normalize_optional_string(session.get('drStart')), normalize_optional_string(session.get('drEnd')))}",
        f"- Real Date: {render_scalar(session.get('realWorldDate'))}",
        f"- DM: {render_scalar(dm_name)}",
        f"- PCs: {', '.join(players) if players else 'none'}",
        "",
    ]


def render_timeline(blocks: Sequence[Dict[str, Any]]) -> List[str]:
    lines = ["## Timeline", ""]
    for block in blocks:
        lines.append(f"### {format_display_date_span(block.get('dateStart'), block.get('dateEnd'))}{format_time_window(block.get('timeWindow'))}")
        lines.append("")
        lines.append(f"- Timeline Segment: {block['blockId']}")
        lines.append(f"- Timeline Key: {format_timeline_key(block.get('dateStart'), block.get('timeWindow'))}")
        lines.append(f"- Resolution: {block['resolution']}")
        lines.append(f"- Beat IDs: {', '.join(block['beatIds'])}")
        lines.append(f"- Locations: {render_name_list(block.get('locationRefs', []))}")
        lines.append(f"- NPCs: {render_name_list(block.get('npcRefs', []))}")
        lines.append(f"- Organizations: {render_name_list(block.get('organizationRefs', []))}")
        lines.append(f"- Items: {render_name_list(block.get('itemRefs', []))}")
        lines.append(f"- Combat Beats: {render_name_list(block.get('combatBeatIds', []))}")
        lines.append("")
        lines.append("#### Short")
        lines.append(f"TODO: {format_display_date_span(block.get('dateStart'), block.get('dateEnd'))}{format_time_window_csv(block.get('timeWindow'))}: one short event-log line.")
        lines.append("")
        lines.append("#### Long")
        lines.append("TODO: one or two tighter event-log sentences covering the whole segment.")
        lines.append("")
    return lines


def render_recap_blocks(blocks: Sequence[Dict[str, Any]]) -> List[str]:
    lines = ["## Recap", ""]
    for block in blocks:
        lines.append(f"### {block['blockId']} | {block['title']}")
        lines.append("")
        lines.append(f"- Kind: {block['kind']}")
        lines.append(f"- Beat IDs: {', '.join(block['beatIds'])}")
        lines.append(f"- Date: {format_date_span(block.get('dateStart'), block.get('dateEnd'))}")
        lines.append(f"- Time: {render_scalar(block.get('timeWindow'))}")
        lines.append(f"- Source Range: {block['sourceRange']['startUid']} -> {block['sourceRange']['endUid']}")
        lines.append(f"- Locations: {render_name_list(block.get('locationRefs', []))}")
        lines.append(f"- NPCs: {render_name_list(block.get('npcRefs', []))}")
        lines.append(f"- Organizations: {render_name_list(block.get('organizationRefs', []))}")
        lines.append(f"- Items: {render_name_list(block.get('itemRefs', []))}")
        lines.append(f"- Enemies: {render_name_list(block.get('combatEnemyRefs', []))}")
        lines.append("")
        lines.append("#### Short")
        lines.append("TODO")
        lines.append("")
        lines.append("#### Intermediate")
        lines.append("TODO")
        lines.append("")
        lines.append("#### Long")
        lines.append("TODO")
        lines.append("")
    return lines


def render_cast(world: Dict[str, Any]) -> List[str]:
    encountered = world.get("encountered", {})
    mentioned = world.get("mentioned", {})
    lines = ["## Cast", "", "### NPCs", ""]
    lines.extend(render_history_entries(encountered.get("npcs", [])))
    lines.extend(render_mentioned_entries(mentioned.get("npcs", []), "mentioned"))
    lines.append("")
    return lines


def render_locations(world: Dict[str, Any]) -> List[str]:
    encountered = world.get("encountered", {})
    mentioned = world.get("mentioned", {})
    lines = ["## Locations", ""]
    lines.extend(render_location_entries(encountered.get("locations", [])))
    lines.extend(render_mentioned_entries(mentioned.get("locations", []), "mentioned"))
    lines.append("")
    return lines


def render_orgs_and_items(world: Dict[str, Any]) -> List[str]:
    encountered = world.get("encountered", {})
    mentioned = world.get("mentioned", {})
    lines = ["## Organizations And Items", "", "### Organizations", ""]
    lines.extend(render_history_entries(encountered.get("organizations", [])))
    lines.extend(render_mentioned_entries(mentioned.get("organizations", []), "mentioned"))
    lines.extend(["", "### Items", ""])
    lines.extend(render_history_entries(encountered.get("items", [])))
    lines.extend(render_mentioned_entries(mentioned.get("items", []), "mentioned"))
    lines.append("")
    return lines


def render_combat(recap_blocks: Sequence[Dict[str, Any]]) -> List[str]:
    lines = ["## Combat", ""]
    combat_blocks = [block for block in recap_blocks if block.get("kind") == "combat"]
    if not combat_blocks:
        lines.append("- none")
        lines.append("")
        return lines
    for block in combat_blocks:
        lines.append(f"### {block['blockId']} | TODO")
        lines.append("")
        lines.append(f"- Beat IDs: {', '.join(block['beatIds'])}")
        lines.append(f"- Enemies: {render_name_list(block.get('combatEnemyRefs', []))}")
        lines.append("- Context / Outcome: TODO")
        lines.append("")
    lines.append("")
    return lines


def render_source_files(
    context_path: Path,
    beats_path: Path,
    beat_facts_path: Path,
    transcript_path: Optional[str],
) -> List[str]:
    lines = ["## Source Files", ""]
    lines.append(f"- Context JSON: {context_path}")
    lines.append(f"- Beats JSON: {beats_path}")
    lines.append(f"- Beat Facts JSON: {beat_facts_path}")
    lines.append(f"- Cleaned Source: {transcript_path or 'unknown'}")
    lines.append("")
    return lines


def render_history_entries(entries: Sequence[Dict[str, Any]]) -> List[str]:
    if not entries:
        return []
    lines: List[str] = []
    for entry in entries:
        context_text = normalize_optional_string(entry.get("contextHint")) or "TODO"
        lines.append(f"- {entry['name']}{format_relation_kinds(entry.get('relationKinds', []))}: {context_text}")
        for history in entry.get("history", []):
            lines.append(f"  - {history['location']}, {format_date_span(history.get('dateStart'), history.get('dateEnd'))}")
    return lines


def render_location_entries(entries: Sequence[Dict[str, Any]]) -> List[str]:
    if not entries:
        return []
    lines: List[str] = []
    for entry in entries:
        context_text = normalize_optional_string(entry.get("contextHint")) or "TODO"
        lines.append(f"- {entry['name']}: {context_text}")
        for visit in entry.get("visits", []):
            lines.append(f"  - {visit['kind']} on {format_date_span(visit.get('dateStart'), visit.get('dateEnd'))}")
    return lines


def render_mentioned_entries(entries: Sequence[Dict[str, Any]], relation_label: str) -> List[str]:
    if not entries:
        return []
    lines: List[str] = []
    for entry in entries:
        context_text = normalize_optional_string(entry.get("contextHint")) or "TODO"
        lines.append(f"- {entry['name']} ({relation_label}): {context_text}")
    return lines

def render_name_list(values: Sequence[str]) -> str:
    return ", ".join(values) if values else "none"


def format_relation_kinds(values: Sequence[str]) -> str:
    return f" ({', '.join(values)})" if values else ""


def format_time_window(value: Optional[str]) -> str:
    return f" ({value})" if normalize_optional_string(value) else ""


def format_time_window_csv(value: Optional[str]) -> str:
    return f", {value}" if normalize_optional_string(value) else ""


def format_date_span(date_start: Optional[str], date_end: Optional[str]) -> str:
    if not date_start:
        return "unknown"
    if not date_end or date_end == date_start:
        return date_start
    return f"{date_start} to {date_end}"


def format_display_date_span(date_start: Optional[str], date_end: Optional[str]) -> str:
    if not date_start:
        return "Undated (ordered)"
    if not date_end or date_end == date_start:
        return format_display_date(date_start)
    return f"{format_display_date(date_start)} to {format_display_date(date_end)}"


def format_display_date(date_text: str) -> str:
    year_text, month_text, day_text = date_text.split("-")
    month_names = {
        "01": "Jan",
        "02": "Feb",
        "03": "Mar",
        "04": "Apr",
        "05": "May",
        "06": "Jun",
        "07": "Jul",
        "08": "Aug",
        "09": "Sep",
        "10": "Oct",
        "11": "Nov",
        "12": "Dec",
    }
    day = int(day_text)
    suffix = "th"
    if day % 100 not in {11, 12, 13}:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{month_names[month_text]} {day}{suffix}, {year_text}"


def format_timeline_key(date_start: Optional[str], time_window: Optional[str]) -> str:
    if not date_start:
        return "undated"
    if normalize_optional_string(time_window):
        return f"(DR:: {date_start}), {time_window}"
    return f"(DR:: {date_start})"


def render_scalar(value: Any) -> str:
    text = normalize_optional_string(value)
    return text if text is not None else "unknown"


def read_json_mapping(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"Expected a JSON object in {path}")
    return payload


def read_yaml_mapping(path: Path) -> Dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise SystemExit(f"Expected a YAML mapping in {path}")
    return payload


def required_string(raw: Dict[str, Any], field_name: str, context: str) -> str:
    value = normalize_optional_string(raw.get(field_name))
    if value is None:
        raise SystemExit(f"{context} is missing {field_name}")
    return value


def normalize_optional_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


if __name__ == "__main__":
    raise SystemExit(main())
