#!/usr/bin/env python3

"""Validate and preview an approved recap-scene grouping."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Sequence


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate recap scene groups against finalized beats and facts.")
    parser.add_argument("--beats-json", type=Path, required=True, help="Finalized beats JSON path.")
    parser.add_argument("--beat-facts-json", type=Path, required=True, help="Finalized beat-facts JSON path.")
    parser.add_argument("--recap-scenes-json", type=Path, required=True, help="Proposed or approved recap-scenes JSON path.")
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory for the recap-scenes preview.")
    parser.add_argument("--file-prefix", type=str, required=True, help="Stable session bundle prefix.")
    parser.add_argument("--validate-only", action="store_true", help="Validate without rewriting the preview.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    beats_path = args.beats_json.expanduser().resolve()
    beat_facts_path = args.beat_facts_json.expanduser().resolve()
    recap_scenes_path = args.recap_scenes_json.expanduser().resolve()
    for path, argument in (
        (beats_path, "--beats-json"),
        (beat_facts_path, "--beat-facts-json"),
        (recap_scenes_path, "--recap-scenes-json"),
    ):
        assert_not_in_sources_dir(path, argument)

    beats_payload = read_json_mapping(beats_path)
    facts_payload = read_json_mapping(beat_facts_path)
    scenes_payload = read_json_mapping(recap_scenes_path)
    beats = parse_beats(beats_payload)
    facts = parse_facts(facts_payload)
    errors = validate_recap_scenes(scenes_payload, beats, facts)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    if not args.validate_only:
        output_dir = args.output_dir.expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        file_prefix = args.file_prefix.strip()
        if not file_prefix:
            raise SystemExit("--file-prefix must be non-empty.")
        preview_path = output_dir / f"{file_prefix}-recap-scenes-preview.md"
        preview_path.write_text(render_preview(scenes_payload, beats, facts), encoding="utf-8")
        print(f"Wrote {preview_path}")

    print(f"Validated {recap_scenes_path}")
    return 0


def read_json_mapping(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"Expected a JSON object in {path}")
    return payload


def parse_beats(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw_beats = payload.get("beats")
    if not isinstance(raw_beats, list) or not raw_beats:
        raise SystemExit("Beat JSON must contain a non-empty 'beats' list.")
    beats: List[Dict[str, Any]] = []
    for raw in raw_beats:
        if not isinstance(raw, dict):
            raise SystemExit("Each beat must be an object.")
        beat_id = normalize_optional_string(raw.get("beatId"))
        title = normalize_optional_string(raw.get("title"))
        if beat_id is None or title is None:
            raise SystemExit("Each beat must contain beatId and title.")
        beats.append({"beatId": beat_id, "title": title})
    return beats


def parse_facts(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw_facts = payload.get("facts")
    if not isinstance(raw_facts, list) or not raw_facts:
        raise SystemExit("Beat-facts JSON must contain a non-empty 'facts' list.")
    return [fact for fact in raw_facts if isinstance(fact, dict)]


def validate_recap_scenes(
    payload: Dict[str, Any],
    beats: Sequence[Dict[str, Any]],
    facts: Sequence[Dict[str, Any]],
) -> List[str]:
    errors: List[str] = []
    if normalize_optional_string(payload.get("schemaVersion")) != "1.0":
        errors.append("recap-scenes.json schemaVersion must be '1.0'.")

    scenes = payload.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        return [*errors, "recap-scenes.json must contain a non-empty 'scenes' list."]

    expected_beat_ids = [str(beat["beatId"]) for beat in beats]
    fact_beat_ids = [normalize_optional_string(fact.get("beatId")) for fact in facts]
    if fact_beat_ids != expected_beat_ids:
        errors.append("Beat-facts order/content does not match beats.json.")

    flattened: List[str] = []
    for index, raw_scene in enumerate(scenes, start=1):
        label = f"scene #{index}"
        if not isinstance(raw_scene, dict):
            errors.append(f"{label} must be an object.")
            continue
        expected_scene_id = f"scene-{index:03d}"
        if normalize_optional_string(raw_scene.get("sceneId")) != expected_scene_id:
            errors.append(f"{label} sceneId must be {expected_scene_id}.")
        if normalize_optional_string(raw_scene.get("title")) is None:
            errors.append(f"{expected_scene_id} must include a title.")
        if normalize_optional_string(raw_scene.get("rationale")) is None:
            errors.append(f"{expected_scene_id} must include a concise rationale.")
        beat_ids = raw_scene.get("beatIds")
        if not isinstance(beat_ids, list) or not beat_ids:
            errors.append(f"{expected_scene_id} must include one or more beatIds.")
            continue
        normalized_ids: List[str] = []
        for beat_id in beat_ids:
            normalized = normalize_optional_string(beat_id)
            if normalized is None:
                errors.append(f"{expected_scene_id} contains an empty beatId.")
                continue
            normalized_ids.append(normalized)
        if len(normalized_ids) != len(set(normalized_ids)):
            errors.append(f"{expected_scene_id} repeats a beatId.")
        flattened.extend(normalized_ids)

    if flattened != expected_beat_ids:
        errors.append(
            "Scene beatIds must cover every beat exactly once in original order; "
            f"expected {', '.join(expected_beat_ids)}, got {', '.join(flattened) or 'none'}."
        )
    return errors


def scene_groups(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        {
            "sceneId": str(scene["sceneId"]),
            "title": str(scene["title"]).strip(),
            "rationale": str(scene["rationale"]).strip(),
            "beatIds": [str(beat_id).strip() for beat_id in scene["beatIds"]],
        }
        for scene in payload["scenes"]
    ]


def render_preview(
    scenes_payload: Dict[str, Any],
    beats: Sequence[Dict[str, Any]],
    facts: Sequence[Dict[str, Any]],
) -> str:
    beat_by_id = {str(beat["beatId"]): beat for beat in beats}
    fact_by_id = {str(fact.get("beatId")): fact for fact in facts}
    groups = scene_groups(scenes_payload)
    lines = [
        "# Recap Scene Proposal",
        "",
        f"- Scene Count: {len(groups)}",
        f"- Beat Coverage: {sum(len(group['beatIds']) for group in groups)}/{len(beats)}",
        "",
    ]
    for group in groups:
        lines.extend(
            [
                f"## {group['sceneId']} | {group['title']}",
                "",
                f"- Beat IDs: {', '.join(group['beatIds'])}",
                f"- Rationale: {group['rationale']}",
                "",
                "### Beats",
                "",
            ]
        )
        for beat_id in group["beatIds"]:
            beat = beat_by_id[beat_id]
            fact = fact_by_id.get(beat_id, {})
            summary = normalize_optional_string(fact.get("shortSummary")) or "No short summary available."
            lines.append(f"- {beat_id} | {beat['title']}: {summary}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def assert_not_in_sources_dir(path: Path, arg_name: str) -> None:
    if "sources" in path.parts:
        raise SystemExit(f"{arg_name} must not point inside a bundle 'sources' directory: {path}")


def normalize_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


if __name__ == "__main__":
    raise SystemExit(main())
