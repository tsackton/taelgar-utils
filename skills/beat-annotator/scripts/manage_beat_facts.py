#!/usr/bin/env python3

"""Validate and render beat-facts artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import yaml


VALID_TIME_WINDOWS = {"dawn", "morning", "midday", "afternoon", "evening", "night"}
NPC_ROLES = {"companion", "enemy", "mentioned", "encountered"}
MENTION_ROLES = {"mentioned", "encountered"}
COMBAT_PHASES = {"start", "middle", "end", "full"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate and render beat-facts artifacts.")
    parser.add_argument("--session", type=Path, required=True, help="session.yaml path.")
    parser.add_argument("--beats-json", type=Path, required=True, help="Beat JSON path.")
    parser.add_argument("--beat-facts-json", type=Path, required=True, help="Draft beat-facts JSON path.")
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory for final beat-facts artifacts.")
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
    facts_input_path = args.beat_facts_json.expanduser().resolve()

    assert_not_in_sources_dir(session_path, "--session")
    assert_not_in_sources_dir(beats_path, "--beats-json")

    session_payload = read_yaml_mapping(session_path)
    beats = parse_beats_payload(read_json_mapping(beats_path))
    raw_facts = parse_beat_facts_payload(read_json_mapping(facts_input_path))

    final_facts, validation_errors, warnings = finalize_and_validate_facts(
        beats=beats,
        raw_facts=raw_facts,
        session_payload=session_payload,
    )
    if validation_errors:
        for error in validation_errors:
            print(f"ERROR: {error}")
        return 1

    final_payload = {
        "schemaVersion": "1.0",
        "beatsPath": str(beats_path),
        "facts": final_facts,
    }
    facts_json_path = output_dir / f"{file_prefix}-beat-facts.json"
    preview_path = output_dir / f"{file_prefix}-beat-facts-preview.md"

    facts_json_path.write_text(json.dumps(final_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    preview_path.write_text(render_preview(final_payload, beats, warnings), encoding="utf-8")

    print_summary(final_facts, warnings)
    print(f"Wrote {facts_json_path}")
    print(f"Wrote {preview_path}")
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
        title = required_string(raw, "title", beat_id)
        date_start = normalize_optional_string(raw.get("dateStart"))
        time_window = normalize_optional_string(raw.get("timeWindow"))
        if time_window is not None and time_window not in VALID_TIME_WINDOWS:
            raise SystemExit(f"{beat_id} has invalid timeWindow: {time_window}")
        parsed.append(
            {
                "beatId": beat_id,
                "title": title,
                "dateStart": date_start,
                "dateEnd": normalize_optional_string(raw.get("dateEnd")),
                "timeWindow": time_window,
                "dateResolution": normalize_optional_string(raw.get("dateResolution")) or ("unknown" if date_start is None else "exact"),
                "containsCombat": bool(raw.get("containsCombat", False)),
            }
        )
    return parsed


def parse_beat_facts_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    facts = payload.get("facts")
    if not isinstance(facts, list):
        raise SystemExit("Beat-facts JSON must contain a 'facts' list.")
    return facts


def finalize_and_validate_facts(
    *,
    beats: Sequence[Dict[str, Any]],
    raw_facts: Sequence[Dict[str, Any]],
    session_payload: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []
    expected_ids = [beat["beatId"] for beat in beats]
    beats_by_id = {beat["beatId"]: beat for beat in beats}
    facts_by_id: Dict[str, Dict[str, Any]] = {}
    raw_ids: List[str] = []
    seen_ids: set[str] = set()

    for index, raw_fact in enumerate(raw_facts, start=1):
        if not isinstance(raw_fact, dict):
            errors.append(f"Fact #{index} is not an object.")
            continue
        beat_id = normalize_optional_string(raw_fact.get("beatId"))
        if beat_id is None:
            errors.append(f"Fact #{index} is missing beatId.")
            continue
        raw_ids.append(beat_id)
        if beat_id in seen_ids:
            errors.append(f"Duplicate beatId in beat-facts: {beat_id}")
            continue
        seen_ids.add(beat_id)
        if beat_id not in beats_by_id:
            errors.append(f"Unknown beatId in beat-facts: {beat_id}")
            continue
        facts_by_id[beat_id] = raw_fact

    for beat_id in expected_ids:
        if beat_id not in facts_by_id:
            errors.append(f"Missing beat fact for {beat_id}")

    ordered_known_ids = [beat_id for beat_id in raw_ids if beat_id in beats_by_id]
    if not errors and ordered_known_ids != expected_ids:
        errors.append("Beat facts are out of order relative to beats.json.")

    if errors:
        return [], errors, warnings

    participant_names = build_participant_name_set(session_payload)
    final_facts: List[Dict[str, Any]] = []
    for beat in beats:
        fact, fact_errors, fact_warnings = finalize_fact(
            beat=beat,
            raw_fact=facts_by_id[beat["beatId"]],
            participant_names=participant_names,
        )
        errors.extend(fact_errors)
        warnings.extend(fact_warnings)
        if not fact_errors:
            final_facts.append(fact)

    return final_facts, errors, warnings


def finalize_fact(
    *,
    beat: Dict[str, Any],
    raw_fact: Dict[str, Any],
    participant_names: set[str],
) -> Tuple[Dict[str, Any], List[str], List[str]]:
    beat_id = beat["beatId"]
    errors: List[str] = []
    warnings: List[str] = []

    short_summary = required_string(raw_fact, "shortSummary", beat_id, errors)
    long_summary = required_string(raw_fact, "longSummary", beat_id, errors)
    location = finalize_location(raw_fact.get("location"), beat_id, errors, warnings)
    npcs = finalize_entities(raw_fact.get("npcs"), beat_id, "npcs", NPC_ROLES, errors)
    items = finalize_entities(raw_fact.get("items"), beat_id, "items", MENTION_ROLES, errors)
    organizations = finalize_entities(
        raw_fact.get("organizations"),
        beat_id,
        "organizations",
        MENTION_ROLES,
        errors,
    )
    combat = finalize_combat(raw_fact.get("combat"), beat_id, errors)
    timeline = finalize_timeline(raw_fact.get("timeline"), beat, beat_id, errors)

    for npc in npcs:
        if npc["name"].casefold() in participant_names:
            warnings.append(f"{beat_id} tags participant/game role as NPC: {npc['name']}")

    if combat.get("isCombat") != beat.get("containsCombat"):
        warnings.append(
            f"{beat_id} combat mismatch: beats.json containsCombat={beat.get('containsCombat')} "
            f"but beat-facts combat.isCombat={combat.get('isCombat')}"
        )

    final_fact = {
        "beatId": beat_id,
        "dateStart": beat["dateStart"],
        "dateEnd": beat["dateEnd"],
        "timeWindow": beat["timeWindow"],
        "shortSummary": short_summary,
        "longSummary": long_summary,
        "location": location,
        "npcs": npcs,
        "items": items,
        "organizations": organizations,
        "combat": combat,
    }
    if timeline is not None:
        final_fact["timeline"] = timeline
    return final_fact, errors, warnings


def finalize_location(
    raw_location: Any,
    beat_id: str,
    errors: List[str],
    warnings: List[str],
) -> Dict[str, Any]:
    if not isinstance(raw_location, dict):
        warnings.append(f"{beat_id} is missing location; defaulting to unknown.")
        return {"kind": "unknown", "context": "Location is not established in the source."}

    kind = normalize_optional_string(raw_location.get("kind"))
    notes = normalize_optional_string(raw_location.get("notes"))
    context = normalize_optional_string(raw_location.get("context"))
    if kind == "unknown":
        result = {"kind": "unknown", "context": context or "Location is not established in the source."}
        if notes is not None:
            result["notes"] = notes
        return result
    if kind == "fixed":
        primary = required_string(raw_location, "primary", beat_id, errors, "location.")
        required_context = required_string(raw_location, "context", beat_id, errors, "location.")
        result = {"kind": "fixed", "primary": primary, "context": required_context}
        if notes is not None:
            result["notes"] = notes
        return result
    if kind == "journey":
        start = required_string(raw_location, "from", beat_id, errors, "location.")
        end = required_string(raw_location, "to", beat_id, errors, "location.")
        required_context = required_string(raw_location, "context", beat_id, errors, "location.")
        result = {"kind": "journey", "from": start, "to": end, "context": required_context}
        if notes is not None:
            result["notes"] = notes
        return result

    errors.append(f"{beat_id} has invalid location.kind: {kind!r}")
    return {"kind": "unknown", "context": "Location is not established in the source."}


def finalize_entities(
    raw_entities: Any,
    beat_id: str,
    field_name: str,
    allowed_roles: set[str],
    errors: List[str],
) -> List[Dict[str, Any]]:
    if not isinstance(raw_entities, list):
        errors.append(f"{beat_id} is missing {field_name}.")
        return []

    finalized: List[Dict[str, Any]] = []
    for index, raw_entity in enumerate(raw_entities, start=1):
        if not isinstance(raw_entity, dict):
            errors.append(f"{beat_id} {field_name}[{index}] is not an object.")
            continue
        name = required_string(raw_entity, "name", beat_id, errors, f"{field_name}[{index}].")
        role = required_string(raw_entity, "role", beat_id, errors, f"{field_name}[{index}].")
        if role not in allowed_roles:
            errors.append(f"{beat_id} {field_name}[{index}] has invalid role: {role}")
        entity = {"name": name, "role": role}
        context = normalize_optional_string(raw_entity.get("context"))
        notes = normalize_optional_string(raw_entity.get("notes"))
        if field_name == "npcs" and context is not None:
            entity["context"] = context
        if notes is not None:
            entity["notes"] = notes
        finalized.append(entity)
    return finalized


def finalize_main_enemies(raw_entities: Any, beat_id: str, errors: List[str]) -> List[Dict[str, Any]]:
    if not isinstance(raw_entities, list):
        errors.append(f"{beat_id} is missing mainEnemies.")
        return []

    finalized: List[Dict[str, Any]] = []
    for index, raw_entity in enumerate(raw_entities, start=1):
        if not isinstance(raw_entity, dict):
            errors.append(f"{beat_id} mainEnemies[{index}] is not an object.")
            continue
        name = required_string(raw_entity, "name", beat_id, errors, f"mainEnemies[{index}].")
        entity = {"name": name}
        notes = normalize_optional_string(raw_entity.get("notes"))
        if notes is not None:
            entity["notes"] = notes
        finalized.append(entity)
    return finalized


def finalize_combat(raw_combat: Any, beat_id: str, errors: List[str]) -> Dict[str, Any]:
    if not isinstance(raw_combat, dict):
        errors.append(f"{beat_id} is missing combat.")
        return {}

    is_combat = raw_combat.get("isCombat")
    if not isinstance(is_combat, bool):
        errors.append(f"{beat_id} combat.isCombat must be a boolean.")
        return {}
    if not is_combat:
        return {"isCombat": False}

    phase = required_string(raw_combat, "phase", beat_id, errors, "combat.")
    if phase not in COMBAT_PHASES:
        errors.append(f"{beat_id} combat.phase has invalid value: {phase}")
    main_enemies = finalize_main_enemies(raw_combat.get("mainEnemies", []), beat_id, errors)
    combat = {"isCombat": True, "phase": phase}
    if main_enemies:
        combat["mainEnemies"] = main_enemies
    notes = normalize_optional_string(raw_combat.get("notes"))
    if notes is not None:
        combat["notes"] = notes
    return combat


def finalize_timeline(
    raw_timeline: Any,
    beat: Dict[str, Any],
    beat_id: str,
    errors: List[str],
) -> Optional[List[Dict[str, Any]]]:
    if raw_timeline is None:
        return None
    if not isinstance(raw_timeline, list) or not raw_timeline:
        errors.append(f"{beat_id} timeline must be a non-empty list when present.")
        return None

    finalized: List[Dict[str, Any]] = []
    for index, raw_entry in enumerate(raw_timeline, start=1):
        if not isinstance(raw_entry, dict):
            errors.append(f"{beat_id} timeline[{index}] is not an object.")
            continue
        label = f"timeline[{index}]."
        date_start = normalize_optional_string(raw_entry.get("dateStart")) or beat.get("dateStart")
        date_end = normalize_optional_string(raw_entry.get("dateEnd"))
        time_window = normalize_optional_string(raw_entry.get("timeWindow"))
        if time_window is not None and time_window not in VALID_TIME_WINDOWS:
            errors.append(f"{beat_id} {label}timeWindow has invalid value: {time_window}")
        short_summary = required_string(raw_entry, "shortSummary", beat_id, errors, label)
        long_summary = required_string(raw_entry, "longSummary", beat_id, errors, label)
        entry: Dict[str, Any] = {
            "dateStart": date_start,
            "dateEnd": date_end,
            "timeWindow": time_window,
            "shortSummary": short_summary,
            "longSummary": long_summary,
        }
        for field_name in ("locationRefs", "npcRefs", "organizationRefs", "itemRefs", "combatBeatIds"):
            refs = finalize_string_list(raw_entry.get(field_name), beat_id, f"{label}{field_name}", errors)
            if refs is not None:
                entry[field_name] = refs
        finalized.append(entry)
    return finalized


def finalize_string_list(
    raw_values: Any,
    beat_id: str,
    field_name: str,
    errors: List[str],
) -> Optional[List[str]]:
    if raw_values is None:
        return None
    if not isinstance(raw_values, list):
        errors.append(f"{beat_id} {field_name} must be a list when present.")
        return None
    values: List[str] = []
    for index, raw_value in enumerate(raw_values, start=1):
        value = normalize_optional_string(raw_value)
        if value is None:
            errors.append(f"{beat_id} {field_name}[{index}] must be a non-empty string.")
            continue
        if value not in values:
            values.append(value)
    return values


def required_string(
    raw: Dict[str, Any],
    field_name: str,
    context: str,
    errors: Optional[List[str]] = None,
    prefix: str = "",
) -> str:
    value = normalize_optional_string(raw.get(field_name))
    if value is None:
        message = f"{context} is missing {prefix}{field_name}"
        if errors is None:
            raise SystemExit(message)
        errors.append(message)
        return ""
    return value


def normalize_optional_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def build_participant_name_set(session_payload: Dict[str, Any]) -> set[str]:
    names: set[str] = set()
    participants = session_payload.get("participants")
    if not isinstance(participants, list):
        return names
    for entry in participants:
        if not isinstance(entry, dict):
            continue
        for field_name in ("name", "gameRole"):
            value = normalize_optional_string(entry.get(field_name))
            if value is not None:
                names.add(value.casefold())
    return names


def render_preview(
    payload: Dict[str, Any],
    beats: Sequence[Dict[str, Any]],
    warnings: Sequence[str],
) -> str:
    beat_titles = {beat["beatId"]: beat["title"] for beat in beats}
    lines = [
        "# Beat Facts Preview",
        "",
        f"- Beats file: {payload['beatsPath']}",
        f"- Beat count: {len(payload['facts'])}",
        "",
    ]
    if warnings:
        lines.append("## Warnings")
        lines.append("")
        for warning in warnings:
            lines.append(f"- {warning}")
        lines.append("")

    for fact in payload["facts"]:
        beat_id = fact["beatId"]
        lines.append(f"## {beat_titles.get(beat_id, beat_id)}")
        lines.append(f"*{beat_id}*")
        lines.append("")
        if fact.get("dateStart") is None:
            lines.append("**Date**: unknown")
        elif fact.get("dateEnd"):
            lines.append(f"**Date**: {fact['dateStart']} to {fact['dateEnd']}")
        else:
            lines.append(f"**Date**: {fact['dateStart']}")
        lines.append(f"**Time Window**: {fact.get('timeWindow') or 'unknown'}")
        lines.extend(render_combat_section(fact["combat"]))
        lines.append(f"**Short Summary**: {fact['shortSummary']}")
        lines.append(f"**Long Summary**: {fact['longSummary']}")
        lines.append("**Location**:")
        lines.extend(render_location_lines(fact["location"]))
        lines.extend(render_entity_section("NPCs", fact["npcs"]))
        lines.extend(render_entity_section("Items", fact["items"]))
        lines.extend(render_entity_section("Organizations", fact["organizations"]))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_location_lines(location: Dict[str, Any]) -> List[str]:
    if location.get("kind") == "unknown":
        summary = f"- unknown: {location.get('context') or 'Location is not established in the source.'}"
        lines = [summary]
        if location.get("notes"):
            lines.append(f"  Note: {location['notes']}")
        return lines
    if location.get("kind") == "fixed":
        summary = f"- {location['primary']}: {location['context']}"
    else:
        summary = f"- {location['from']} -> {location['to']}: {location['context']}"
    lines = [summary]
    if location.get("notes"):
        lines.append(f"  Note: {location['notes']}")
    return lines


def render_entity_section(label: str, entities: Sequence[Dict[str, Any]]) -> List[str]:
    if not entities:
        return [f"**{label}**: none"]

    lines = [f"**{label}**:"]
    for entity in entities:
        line = f"- {entity['name']}"
        if entity.get("role"):
            line += f" ({entity['role']})"
        details: List[str] = []
        if entity.get("context"):
            details.append(entity["context"])
        if entity.get("notes"):
            details.append(entity["notes"])
        if details:
            line += f": {join_detail_parts(details)}"
        lines.append(line)
    return lines


def render_combat_section(combat: Dict[str, Any]) -> List[str]:
    if not combat.get("isCombat"):
        return ["**Combat**: no"]

    lines = [f"**Combat**: yes ({combat['phase']})"]
    enemies = combat.get("mainEnemies", [])
    if enemies:
        lines.extend(render_entity_section("Main Enemies", enemies))
    if combat.get("notes"):
        lines.append(f"**Combat Notes**: {combat['notes']}")
    return lines


def join_detail_parts(parts: Sequence[str]) -> str:
    cleaned = [part.strip() for part in parts if part and part.strip()]
    if not cleaned:
        return ""
    joined = cleaned[0]
    for part in cleaned[1:]:
        if joined.endswith((".", "!", "?")):
            joined += f" {part}"
        else:
            joined += f". {part}"
    return joined


def print_summary(facts: Sequence[Dict[str, Any]], warnings: Sequence[str]) -> None:
    combat_count = sum(1 for fact in facts if fact.get("combat", {}).get("isCombat"))
    print(f"Summary: {len(facts)} beat facts, {combat_count} combat beats.")
    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"  - {warning}")


if __name__ == "__main__":
    raise SystemExit(main())
