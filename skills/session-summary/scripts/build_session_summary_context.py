#!/usr/bin/env python3

"""Build deterministic session-summary context artifacts."""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import yaml


VALID_TIME_WINDOWS = {"dawn", "morning", "midday", "afternoon", "evening", "night"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build session-summary context artifacts.")
    parser.add_argument("--session", type=Path, required=True, help="session.yaml path.")
    parser.add_argument("--beats-json", type=Path, required=True, help="Beat JSON path.")
    parser.add_argument("--beat-facts-json", type=Path, required=True, help="Beat-facts JSON path.")
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory for session-summary context artifacts.")
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

    session_path = args.session.expanduser().resolve()
    beats_path = args.beats_json.expanduser().resolve()
    beat_facts_path = args.beat_facts_json.expanduser().resolve()

    assert_not_in_sources_dir(session_path, "--session")
    assert_not_in_sources_dir(beats_path, "--beats-json")
    assert_not_in_sources_dir(beat_facts_path, "--beat-facts-json")

    session_payload = read_yaml_mapping(session_path)
    beats = parse_beats_payload(read_json_mapping(beats_path))
    facts = parse_beat_facts_payload(read_json_mapping(beat_facts_path))

    errors = validate_alignment(beats, facts)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    context_payload = build_context_payload(
        session_path=session_path,
        beats_path=beats_path,
        beat_facts_path=beat_facts_path,
        session_payload=session_payload,
        beats=beats,
        facts=facts,
    )

    context_json_path = output_dir / f"{file_prefix}-session-summary-context.json"
    context_json_path.write_text(json.dumps(context_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print_summary(context_payload)
    print(f"Wrote {context_json_path}")
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


def parse_beats_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    beats = payload.get("beats")
    if not isinstance(beats, list) or not beats:
        raise SystemExit("Beat JSON must contain a non-empty 'beats' list.")

    parsed: List[Dict[str, Any]] = []
    for raw in beats:
        if not isinstance(raw, dict):
            raise SystemExit(f"Invalid beat {raw!r}; expected an object.")
        beat_id = required_string(raw, "beatId", "beat")
        time_window = normalize_optional_string(raw.get("timeWindow"))
        if time_window is not None and time_window not in VALID_TIME_WINDOWS:
            raise SystemExit(f"{beat_id} has invalid timeWindow: {time_window}")
        parsed.append(
            {
                "beatId": beat_id,
                "title": required_string(raw, "title", beat_id),
                "startUid": required_string(raw, "startUid", beat_id),
                "endUid": required_string(raw, "endUid", beat_id),
                "dateStart": normalize_optional_string(raw.get("dateStart")),
                "dateEnd": normalize_optional_string(raw.get("dateEnd")),
                "timeWindow": time_window,
                "dateResolution": normalize_optional_string(raw.get("dateResolution")) or ("unknown" if normalize_optional_string(raw.get("dateStart")) is None else "exact"),
                "containsCombat": bool(raw.get("containsCombat", False)),
            }
        )
    return parsed


def parse_beat_facts_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    facts = payload.get("facts")
    if not isinstance(facts, list) or not facts:
        raise SystemExit("Beat-facts JSON must contain a non-empty 'facts' list.")
    parsed: List[Dict[str, Any]] = []
    for raw in facts:
        if not isinstance(raw, dict):
            raise SystemExit(f"Invalid beat fact {raw!r}; expected an object.")
        parsed.append(raw)
    return parsed


def validate_alignment(beats: Sequence[Dict[str, Any]], facts: Sequence[Dict[str, Any]]) -> List[str]:
    errors: List[str] = []
    beat_ids = [beat["beatId"] for beat in beats]
    fact_ids = []
    for index, fact in enumerate(facts, start=1):
        beat_id = normalize_optional_string(fact.get("beatId"))
        if beat_id is None:
            errors.append(f"Fact #{index} is missing beatId.")
            continue
        fact_ids.append(beat_id)
    if beat_ids != fact_ids:
        errors.append("Beat-facts order/content does not match beats.json.")
    return errors


def build_context_payload(
    *,
    session_path: Path,
    beats_path: Path,
    beat_facts_path: Path,
    session_payload: Dict[str, Any],
    beats: Sequence[Dict[str, Any]],
    facts: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    combined = [combine_beat_and_fact(beat, fact) for beat, fact in zip(beats, facts)]
    return {
        "schemaVersion": "1.0",
        "sessionPath": str(session_path),
        "beatsPath": str(beats_path),
        "beatFactsPath": str(beat_facts_path),
        "session": {
            "campaign": normalize_optional_string(session_payload.get("campaign")),
            "scope": normalize_optional_string(session_payload.get("scope")) or "session",
            "sessionNumber": session_payload.get("sessionNumber"),
            "realWorldDate": normalize_optional_string(session_payload.get("realWorldDate")),
            "drStart": normalize_optional_string(session_payload.get("drStart")),
            "drEnd": normalize_optional_string(session_payload.get("drEnd")),
        },
        "timelineBlocks": build_timeline_blocks(combined),
        "recapBlocks": build_recap_blocks(combined),
        "recapExtrasCandidates": build_recap_extras_candidates(combined),
        "worldCandidates": build_world_candidates(combined),
    }


def combine_beat_and_fact(beat: Dict[str, Any], fact: Dict[str, Any]) -> Dict[str, Any]:
    location_refs, location_relation_kinds, location_events, history_location = extract_location_data(fact.get("location", {}))
    npc_refs = extract_encountered_entity_names(fact.get("npcs", []))
    item_refs = extract_encountered_entity_names(fact.get("items", []))
    organization_refs = extract_encountered_entity_names(fact.get("organizations", []))
    return {
        "beatId": beat["beatId"],
        "title": beat["title"],
        "dateStart": beat["dateStart"],
        "dateEnd": beat["dateEnd"],
        "timeWindow": beat["timeWindow"],
        "dateResolution": beat.get("dateResolution") or ("unknown" if beat["dateStart"] is None else "exact"),
        "sourceRange": {"startUid": beat["startUid"], "endUid": beat["endUid"]},
        "shortSummary": required_string(fact, "shortSummary", beat["beatId"]),
        "longSummary": required_string(fact, "longSummary", beat["beatId"]),
        "location": fact.get("location", {}),
        "npcs": list(fact.get("npcs", [])),
        "items": list(fact.get("items", [])),
        "organizations": list(fact.get("organizations", [])),
        "combat": dict(fact.get("combat", {})),
        "locationRefs": location_refs,
        "locationRelationKinds": location_relation_kinds,
        "locationEvents": location_events,
        "locationContextHint": extract_location_context_hint(fact.get("location", {})),
        "historyLocation": history_location,
        "npcRefs": npc_refs,
        "itemRefs": item_refs,
        "organizationRefs": organization_refs,
    }


def build_timeline_blocks(combined: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    blocks: List[Dict[str, Any]] = []
    current_entries: List[Dict[str, Any]] = []
    for entry in combined:
        if not current_entries or should_merge_timeline_entry(current_entries[-1], entry):
            current_entries.append(entry)
            continue
        blocks.append(make_timeline_block(len(blocks) + 1, current_entries))
        current_entries = [entry]
    if current_entries:
        blocks.append(make_timeline_block(len(blocks) + 1, current_entries))
    return blocks


def should_merge_timeline_entry(previous: Dict[str, Any], current: Dict[str, Any]) -> bool:
    if previous["dateStart"] is None or current["dateStart"] is None:
        return previous["dateStart"] is None and current["dateStart"] is None and previous.get("timeWindow") == current.get("timeWindow")
    return (
        previous["dateStart"] == current["dateStart"]
        and effective_date_end(previous) == effective_date_end(current)
        and previous.get("timeWindow") == current.get("timeWindow")
    )


def make_timeline_block(index: int, entries: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    first = entries[0]
    last = entries[-1]
    time_window = first.get("timeWindow")
    date_start = first.get("dateStart")
    date_end = normalize_date_end(date_start, effective_date_end(last))
    return {
        "blockId": f"timeline-{index:03d}",
        "dateStart": date_start,
        "dateEnd": date_end,
        "timeWindow": time_window,
        "resolution": infer_resolution(date_start, effective_date_end(last), time_window),
        "beatIds": [entry["beatId"] for entry in entries],
        "locationRefs": unique_flatten(entry["locationRefs"] for entry in entries),
        "npcRefs": unique_flatten(entry["npcRefs"] for entry in entries),
        "organizationRefs": unique_flatten(entry["organizationRefs"] for entry in entries),
        "itemRefs": unique_flatten(entry["itemRefs"] for entry in entries),
        "combatBeatIds": [entry["beatId"] for entry in entries if entry["combat"].get("isCombat")],
        "sourceShortSummaries": [entry["shortSummary"] for entry in entries],
        "sourceLongSummaries": [entry["longSummary"] for entry in entries],
    }


def build_recap_blocks(combined: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    blocks: List[Dict[str, Any]] = []
    index = 1
    position = 0
    while position < len(combined):
        current = combined[position]
        if current["combat"].get("isCombat"):
            group = [current]
            position += 1
            while position < len(combined) and combined[position]["combat"].get("isCombat"):
                group.append(combined[position])
                position += 1
            blocks.append(make_recap_block(index, "combat", group))
        else:
            blocks.append(make_recap_block(index, "beat", [current]))
            position += 1
        index += 1
    return blocks


def make_recap_block(index: int, kind: str, entries: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    first = entries[0]
    last = entries[-1]
    return {
        "blockId": f"recap-{index:03d}",
        "kind": kind,
        "title": first["title"] if len(entries) == 1 else f"{first['title']} to {last['title']}",
        "beatIds": [entry["beatId"] for entry in entries],
        "sourceRange": {
            "startUid": first["sourceRange"]["startUid"],
            "endUid": last["sourceRange"]["endUid"],
        },
        "sourceRanges": [entry["sourceRange"] for entry in entries],
        "dateStart": first["dateStart"],
        "dateEnd": normalize_date_end(first["dateStart"], effective_date_end(last)),
        "timeWindow": first.get("timeWindow") if all(first.get("timeWindow") == entry.get("timeWindow") for entry in entries) else None,
        "resolution": infer_resolution(first["dateStart"], effective_date_end(last), first.get("timeWindow")),
        "locationRefs": unique_flatten(entry["locationRefs"] for entry in entries),
        "npcRefs": unique_flatten(entry["npcRefs"] for entry in entries),
        "organizationRefs": unique_flatten(entry["organizationRefs"] for entry in entries),
        "itemRefs": unique_flatten(entry["itemRefs"] for entry in entries),
        "combatEnemyRefs": unique_flatten(
            [
                [enemy.get("name") for enemy in entry["combat"].get("mainEnemies", []) if enemy.get("name")]
                for entry in entries
            ]
        ),
        "sourceShortSummaries": [entry["shortSummary"] for entry in entries],
        "sourceLongSummaries": [entry["longSummary"] for entry in entries],
    }


def build_recap_extras_candidates(combined: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    world_candidates = build_world_candidates(combined)
    combat_blocks = [block for block in build_recap_blocks(combined) if block["kind"] == "combat"]
    return {
        "cast": [
            {"name": entry["name"], "beatIds": entry["beatIds"], "relationKinds": entry["relationKinds"]}
            for entry in world_candidates["encountered"]["npcs"]
        ],
        "combats": [
            {
                "blockId": block["blockId"],
                "beatIds": block["beatIds"],
                "enemyRefs": block["combatEnemyRefs"],
                "dateStart": block["dateStart"],
                "dateEnd": block["dateEnd"],
            }
            for block in combat_blocks
        ],
        "majorLocations": [
            {"name": entry["name"], "beatIds": entry["beatIds"], "relationKinds": entry["relationKinds"]}
            for entry in world_candidates["encountered"]["locations"]
        ],
    }


def build_world_candidates(combined: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    encountered = {
        "npcs": build_entity_candidates(combined, "npcs", map_npc_relation_kind),
        "locations": build_location_candidates(combined),
        "organizations": build_entity_candidates(combined, "organizations", map_generic_relation_kind),
        "items": build_entity_candidates(combined, "items", map_generic_relation_kind),
    }
    mentioned = {
        "npcs": build_mentioned_names(combined, "npcs", encountered["npcs"]),
        "locations": [],
        "organizations": build_mentioned_names(combined, "organizations", encountered["organizations"]),
        "items": build_mentioned_names(combined, "items", encountered["items"]),
    }
    return {"encountered": encountered, "mentioned": mentioned}


def build_entity_candidates(
    combined: Sequence[Dict[str, Any]],
    field_name: str,
    relation_mapper,
) -> List[Dict[str, Any]]:
    entries: Dict[str, Dict[str, Any]] = {}
    for beat in combined:
        for entity in beat[field_name]:
            name = normalize_optional_string(entity.get("name"))
            role = normalize_optional_string(entity.get("role"))
            if name is None or role == "mentioned":
                continue
            if name not in entries:
                entries[name] = {
                    "name": name,
                    "relationKinds": [],
                    "contextHint": normalize_optional_string(entity.get("context")),
                    "beatIds": [],
                    "history": [],
                }
            if normalize_optional_string(entries[name].get("contextHint")) is None:
                entries[name]["contextHint"] = normalize_optional_string(entity.get("context"))
            relation_kind = relation_mapper(entity, beat)
            append_unique(entries[name]["relationKinds"], relation_kind)
            append_unique(entries[name]["beatIds"], beat["beatId"])
            if beat["dateStart"] is not None:
                entries[name]["history"] = merge_history_entries(
                    entries[name]["history"],
                    make_history_entry(beat["historyLocation"], beat["dateStart"], effective_date_end(beat)),
                )
    return list(entries.values())


def build_location_candidates(combined: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    entries: Dict[str, Dict[str, Any]] = {}
    for beat in combined:
        for location_event in beat["locationEvents"]:
            name = location_event["name"]
            if name not in entries:
                entries[name] = {
                    "name": name,
                    "relationKinds": [],
                    "contextHint": beat.get("locationContextHint"),
                    "beatIds": [],
                    "visits": [],
                }
            if normalize_optional_string(entries[name].get("contextHint")) is None:
                entries[name]["contextHint"] = beat.get("locationContextHint")
            append_unique(entries[name]["relationKinds"], location_event["relationKind"])
            append_unique(entries[name]["beatIds"], beat["beatId"])
            if beat["dateStart"] is not None:
                entries[name]["visits"] = merge_visits(
                    entries[name]["visits"],
                    {
                        "dateStart": beat["dateStart"],
                        "dateEnd": normalize_date_end(beat["dateStart"], effective_date_end(beat)),
                        "kind": location_event["relationKind"],
                    },
                )
    return list(entries.values())


def build_mentioned_names(
    combined: Sequence[Dict[str, Any]],
    field_name: str,
    encountered_entries: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    encountered_names = {entry["name"] for entry in encountered_entries}
    names: List[Dict[str, Any]] = []
    for beat in combined:
        for entity in beat[field_name]:
            name = normalize_optional_string(entity.get("name"))
            role = normalize_optional_string(entity.get("role"))
            if name is None or role != "mentioned" or name in encountered_names:
                continue
            if not any(entry["name"] == name for entry in names):
                names.append({"name": name, "contextHint": normalize_optional_string(entity.get("context"))})
    return names


def make_history_entry(
    location: Optional[str],
    date_start: str,
    date_end: str,
) -> Dict[str, Any]:
    return {
        "location": location,
        "dateStart": date_start,
        "dateEnd": normalize_date_end(date_start, date_end),
    }


def merge_history_entries(
    existing: Sequence[Dict[str, Any]],
    new_entry: Dict[str, Any],
) -> List[Dict[str, Any]]:
    merged = [dict(entry) for entry in existing]
    if not merged:
        return [dict(new_entry)]

    previous = merged[-1]
    previous_end = normalize_optional_string(previous.get("dateEnd")) or required_string(previous, "dateStart", "history")
    current_start = required_string(new_entry, "dateStart", "history")
    current_end = normalize_optional_string(new_entry.get("dateEnd")) or current_start
    if previous.get("location") == new_entry.get("location") and are_dates_contiguous(previous_end, current_start):
        previous["dateEnd"] = normalize_date_end(required_string(previous, "dateStart", "history"), current_end)
        return merged
    merged.append(dict(new_entry))
    return merged


def merge_visits(
    existing: Sequence[Dict[str, Any]],
    new_entry: Dict[str, Any],
) -> List[Dict[str, Any]]:
    merged = [dict(entry) for entry in existing]
    if not merged:
        return [dict(new_entry)]

    current_start = required_string(new_entry, "dateStart", "visit")
    current_end = normalize_optional_string(new_entry.get("dateEnd")) or current_start
    for entry in merged:
        entry_end = normalize_optional_string(entry.get("dateEnd")) or required_string(entry, "dateStart", "visit")
        if entry.get("kind") == new_entry.get("kind") and are_dates_contiguous(entry_end, current_start):
            entry["dateEnd"] = normalize_date_end(required_string(entry, "dateStart", "visit"), current_end)
            return merged
    merged.append(dict(new_entry))
    return merged


def are_dates_contiguous(previous_end: str, current_start: str) -> bool:
    previous = date.fromisoformat(previous_end)
    current = date.fromisoformat(current_start)
    return current == previous or current == previous + timedelta(days=1)


def extract_encountered_entity_names(entities: Sequence[Dict[str, Any]]) -> List[str]:
    return unique_flatten(
        [
            [normalize_optional_string(entity.get("name"))]
            for entity in entities
            if normalize_optional_string(entity.get("role")) != "mentioned"
        ]
    )


def extract_location_context_hint(location: Dict[str, Any]) -> Optional[str]:
    return normalize_optional_string(location.get("context"))


def extract_location_data(location: Dict[str, Any]) -> Tuple[List[str], List[str], List[Dict[str, str]], Optional[str]]:
    refs: List[str] = []
    relation_kinds: List[str] = []
    events: List[Dict[str, str]] = []
    history_location: Optional[str] = None
    kind = normalize_optional_string(location.get("kind"))
    if kind == "fixed":
        primary = canonicalize_location_name(normalize_optional_string(location.get("primary")))
        append_unique(refs, primary)
        append_unique(relation_kinds, "visited")
        if primary is not None:
            events.append({"name": primary, "relationKind": "visited"})
        history_location = primary
    elif kind == "journey":
        from_name = canonicalize_location_name(normalize_optional_string(location.get("from")))
        to_name = canonicalize_location_name(normalize_optional_string(location.get("to")))
        append_unique(refs, from_name)
        append_unique(refs, to_name)
        if from_name is not None:
            append_unique(relation_kinds, "traveled-through")
            events.append({"name": from_name, "relationKind": "traveled-through"})
        if to_name is not None:
            append_unique(relation_kinds, "visited")
            events.append({"name": to_name, "relationKind": "visited"})
        history_location = format_history_location(from_name, to_name)
    return refs, relation_kinds, events, history_location


def format_history_location(from_name: Optional[str], to_name: Optional[str]) -> Optional[str]:
    if from_name and to_name and from_name != to_name:
        return f"{from_name} -> {to_name}"
    return from_name or to_name


def canonicalize_location_name(value: Optional[str]) -> Optional[str]:
    text = normalize_optional_string(value)
    if text is None:
        return None
    if " (" not in text or not text.endswith(")"):
        return text
    before, inside = text[:-1].split(" (", 1)
    before = before.strip()
    inside = inside.strip()
    sublocation_markers = {
        "chamber",
        "corridor",
        "corridors",
        "room",
        "rooms",
        "tunnel",
        "tunnels",
        "passage",
        "passages",
        "bridge",
        "entrance",
        "exit",
        "fork",
        "fissure",
        "camp",
        "road",
        "path",
        "hall",
        "halls",
    }
    before_words = {word.strip(" ,.-").lower() for word in before.split()}
    if before_words & sublocation_markers:
        return inside or before
    return before or inside


def map_npc_relation_kind(entity: Dict[str, Any], beat: Dict[str, Any]) -> Optional[str]:
    role = normalize_optional_string(entity.get("role"))
    if role == "companion":
        return "companion"
    if role == "enemy":
        return "fought" if beat["combat"].get("isCombat") else "met"
    if role == "encountered":
        return "met"
    if role == "mentioned":
        return "mentioned"
    return None


def map_generic_relation_kind(entity: Dict[str, Any], beat: Dict[str, Any]) -> Optional[str]:
    role = normalize_optional_string(entity.get("role"))
    if role == "encountered":
        return "encountered"
    if role == "mentioned":
        return "mentioned"
    return None


def effective_date_end(entry: Dict[str, Any]) -> Optional[str]:
    return normalize_optional_string(entry.get("dateEnd")) or normalize_optional_string(entry.get("dateStart"))


def normalize_date_end(date_start: Optional[str], date_end: Optional[str]) -> Optional[str]:
    if date_start is None or date_end is None:
        return date_end
    return None if date_start == date_end else date_end


def infer_resolution(date_start: Optional[str], date_end: Optional[str], time_window: Optional[str]) -> str:
    if date_start is None:
        return "undated"
    if date_end != date_start:
        return "date-range"
    if time_window is not None:
        return "part-of-day"
    return "day"


def append_unique(values: List[Any], value: Any) -> None:
    if value is None:
        return
    if value not in values:
        values.append(value)


def extend_unique(values: List[Any], new_values: Sequence[Any]) -> None:
    for value in new_values:
        append_unique(values, value)


def unique_flatten(groups: Sequence[Sequence[Any]]) -> List[Any]:
    flattened: List[Any] = []
    for group in groups:
        extend_unique(flattened, group)
    return flattened


def print_summary(payload: Dict[str, Any]) -> None:
    print(
        f"Summary: {len(payload['timelineBlocks'])} timeline blocks, "
        f"{len(payload['recapBlocks'])} recap blocks, "
        f"{len(payload['worldCandidates']['encountered']['npcs'])} NPC entries, "
        f"{len(payload['worldCandidates']['encountered']['locations'])} location entries."
    )


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
