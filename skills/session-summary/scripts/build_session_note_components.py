#!/usr/bin/env python3

"""Build recap-driven composable session-note components."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import yaml

from recap_markdown import SessionRecapParseError, parse_session_recap


AI_TAG = "status/check/ai"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build composable session-note components from reviewed session-recap.md.")
    parser.add_argument("--session", type=Path, required=True, help="session.yaml path.")
    parser.add_argument("--session-recap-md", type=Path, required=True, help="Reviewed session-recap.md path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    session_path = args.session.expanduser().resolve()
    recap_path = args.session_recap_md.expanduser().resolve()

    session_payload = read_yaml_mapping(session_path)
    recap_text = recap_path.read_text(encoding="utf-8")
    try:
        recap = parse_session_recap(recap_text)
    except SessionRecapParseError as exc:
        for error in exc.errors:
            print(f"ERROR: {error}")
        return 1

    session_note = validate_session_note_config(session_payload)
    if session_note is None:
        print("ERROR: session.yaml is missing the required sessionNote block.")
        return 1

    vault_root = find_vault_root(session_path)
    generated_root = resolve_vault_path(vault_root, session_note["generatedRoot"])
    published_note_path = resolve_vault_path(vault_root, session_note["publishedNotePath"])
    template_path = resolve_vault_path(vault_root, session_note["templatePath"])
    if not template_path.exists():
        print(f"ERROR: sessionNote.templatePath does not exist: {template_path}")
        return 1

    session_slug = slugify_text(published_note_path.stem or session_path.stem)
    component_dir = generated_root / session_slug
    component_dir.mkdir(parents=True, exist_ok=True)

    note_index = VaultNoteIndex(vault_root, generated_root)
    slots = build_slots(
        recap=recap,
        note_index=note_index,
    )

    write_component_file(
        component_dir / "01-session-info.md",
        title="Session Info",
        session_manifest=str(session_path),
        slots=slots["info"],
    )
    write_component_file(
        component_dir / "02-technical-updates.md",
        title="Technical Updates",
        session_manifest=str(session_path),
        slots=slots["technical"],
    )
    write_component_file(
        component_dir / "03-narrative.md",
        title="Narrative",
        session_manifest=str(session_path),
        slots=slots["narrative"],
    )

    print(f"Wrote {component_dir / '01-session-info.md'}")
    print(f"Wrote {component_dir / '02-technical-updates.md'}")
    print(f"Wrote {component_dir / '03-narrative.md'}")
    print(f"Published note target: {published_note_path}")
    return 0


def validate_session_note_config(session_payload: Dict[str, Any]) -> Optional[Dict[str, str]]:
    raw = session_payload.get("sessionNote")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise SystemExit("sessionNote must be a mapping in session.yaml.")
    data = {
        "templatePath": normalize_optional_string(raw.get("templatePath")),
        "generatedRoot": normalize_optional_string(raw.get("generatedRoot")),
        "publishedNotePath": normalize_optional_string(raw.get("publishedNotePath")),
    }
    missing = [key for key, value in data.items() if value is None]
    if missing:
        raise SystemExit("sessionNote is missing required fields: " + ", ".join(missing))
    return {key: value for key, value in data.items() if value is not None}


def build_slots(
    *,
    recap: Dict[str, Any],
    note_index: "VaultNoteIndex",
) -> Dict[str, Dict[str, str]]:
    review_lines: List[str] = []
    info_slots: Dict[str, str] = {}
    technical_slots: Dict[str, str] = {}
    narrative_slots: Dict[str, str] = {}

    header = recap["header"]
    info_slots["session.title"] = header.get("Title", "")
    info_slots["session.tagline"] = header.get("Tagline", "")
    info_slots["session.summary"] = header.get("One-Sentence Summary", "")
    info_slots["session.dm"] = header.get("DM", "")
    info_slots["session.pcs"] = render_inline_csv_as_bullets(header.get("PCs", ""))
    info_slots["session.dr_date"] = header.get("DR Date", "")
    info_slots["session.real_date"] = header.get("Real Date", "")
    info_slots["timeline"] = render_timeline_slot(recap["timeline"])

    cast_text, cast_reviews = render_entity_slot(
        recap["cast"],
        note_index,
        entity_kind="person",
    )
    info_slots["cast"] = cast_text
    review_lines.extend(cast_reviews)

    locations_text, location_reviews = render_location_slot(recap["locations"], note_index)
    info_slots["locations"] = locations_text
    review_lines.extend(location_reviews)

    combat_text = render_combat_slot(recap["combat"])
    info_slots["combat.summary"] = combat_text

    items_text, item_reviews = render_entity_slot(
        recap["items"],
        note_index,
        entity_kind="object",
        include_history=True,
    )
    info_slots["items.treasure"] = items_text
    review_lines.extend(item_reviews)

    final_timeline = recap["timeline"][-1] if recap["timeline"] else None
    technical_slots["updates.whereabouts.party"] = build_party_whereabouts_slot(final_timeline)
    npc_updates, npc_reviews = build_entity_whereabouts_updates(
        recap["cast"],
        note_index,
        final_timeline,
    )
    technical_slots["updates.whereabouts.npcs"] = npc_updates
    review_lines.extend(npc_reviews)
    technical_slots["updates.timeline"] = build_timeline_updates_slot(recap["timeline"])
    item_updates, item_update_reviews = build_item_updates_slot(recap["items"], note_index, final_timeline)
    technical_slots["updates.items"] = item_updates
    review_lines.extend(item_update_reviews)
    technical_slots["updates.review"] = render_review_lines(review_lines)

    narrative_slots["narrative.short"] = join_recap_zoom(recap["recap"], "short")
    narrative_slots["narrative.intermediate"] = join_recap_zoom(recap["recap"], "intermediate")
    narrative_slots["narrative.long"] = join_recap_zoom(recap["recap"], "long")

    return {"info": info_slots, "technical": technical_slots, "narrative": narrative_slots}


def render_timeline_slot(timeline_blocks: Sequence[Dict[str, Any]]) -> str:
    lines: List[str] = []
    for block in timeline_blocks:
        key = block.get("timelineKey") or block.get("heading") or "undated"
        summary = block.get("short", "")
        if summary:
            lines.append(f"- {key}: {summary}")
    return "\n".join(lines).strip()


def render_entity_slot(
    entries: Sequence[Dict[str, Any]],
    note_index: "VaultNoteIndex",
    *,
    entity_kind: str,
    include_history: bool = False,
) -> Tuple[str, List[str]]:
    lines: List[str] = []
    review_lines: List[str] = []
    for entry in entries:
        resolution = note_index.resolve(entry["name"])
        if resolution.warning:
            review_lines.append(f"- {entry['name']}: {resolution.warning}")
        display_name = resolution.link(entry["name"])
        note_context, context_reviews = build_note_context(entry, resolution, entity_kind=entity_kind)
        review_lines.extend(context_reviews)
        context_text = entry["context"]
        if note_context:
            context_text = f"{context_text}. Existing note context: {note_context}."
        lines.append(f"- {display_name}: {context_text}")
        if include_history:
            for history in entry.get("history", []):
                lines.append(f"  - {history['raw']}")
    return "\n".join(lines).strip(), dedupe_lines(review_lines)


def render_location_slot(entries: Sequence[Dict[str, Any]], note_index: "VaultNoteIndex") -> Tuple[str, List[str]]:
    lines: List[str] = []
    review_lines: List[str] = []
    for entry in entries:
        resolution = note_index.resolve(entry["name"])
        if resolution.warning:
            review_lines.append(f"- {entry['name']}: {resolution.warning}")
        display_name = resolution.link(entry["name"])
        note_context, context_reviews = build_note_context(entry, resolution, entity_kind="place")
        review_lines.extend(context_reviews)
        context_text = entry["context"]
        if note_context:
            context_text = f"{context_text}. Existing note context: {note_context}."
        lines.append(f"- {display_name}: {context_text}")
        for visit in entry.get("visits", []):
            lines.append(f"  - {visit['raw']}")
    return "\n".join(lines).strip(), dedupe_lines(review_lines)


def render_combat_slot(entries: Sequence[Dict[str, Any]]) -> str:
    if not entries:
        return "- none"
    lines: List[str] = []
    for entry in entries:
        enemies = ", ".join(entry.get("enemies", [])) or "none"
        lines.append(f"- {entry['title']}: {enemies}. {entry['contextOutcome']}")
    return "\n".join(lines).strip()


def build_party_whereabouts_slot(final_timeline: Optional[Dict[str, Any]]) -> str:
    if not final_timeline or not final_timeline.get("locations"):
        return "- none"
    final_location = final_timeline["locations"][-1]
    return (
        f"- Candidate party whereabouts: {final_timeline.get('timelineKey') or final_timeline.get('heading')}: "
        f"party ends at {format_wikilink(final_location)}."
    )


def build_entity_whereabouts_updates(
    entries: Sequence[Dict[str, Any]],
    note_index: "VaultNoteIndex",
    final_timeline: Optional[Dict[str, Any]],
) -> Tuple[str, List[str]]:
    if final_timeline is None:
        return "- none", []
    final_npcs = set(final_timeline.get("npcs", []))
    lines: List[str] = []
    review_lines: List[str] = []
    for entry in entries:
        if entry["name"] not in final_npcs:
            continue
        final_location = infer_last_history_location(entry.get("history", []))
        if final_location is None:
            review_lines.append(f"- {entry['name']}: appears in the final timeline block but has no parseable end-state history.")
            continue
        resolution = note_index.resolve(entry["name"])
        display_name = resolution.link(entry["name"])
        lines.append(
            f"- {display_name}: candidate whereabouts update from {final_timeline.get('timelineKey') or final_timeline.get('heading')} -> {format_wikilink(final_location)}."
        )
        metadata_location = resolution.simple_whereabouts()
        if metadata_location and normalize_name(metadata_location) != normalize_name(final_location):
            review_lines.append(
                f"- {display_name}: note currently says whereabouts '{metadata_location}', but the reviewed recap ends them at '{final_location}'."
            )
    return ("\n".join(lines).strip() or "- none"), dedupe_lines(review_lines)


def build_timeline_updates_slot(timeline_blocks: Sequence[Dict[str, Any]]) -> str:
    lines = [
        f"- {block.get('timelineKey') or block.get('heading')}: {block.get('short', '')}"
        for block in timeline_blocks
        if block.get("short")
    ]
    return "\n".join(lines).strip() or "- none"


def build_item_updates_slot(
    items: Sequence[Dict[str, Any]],
    note_index: "VaultNoteIndex",
    final_timeline: Optional[Dict[str, Any]],
) -> Tuple[str, List[str]]:
    lines: List[str] = []
    review_lines: List[str] = []
    for entry in items:
        history = entry.get("history", [])
        if len(history) < 2:
            continue
        final_location = infer_last_history_location(history)
        if not final_location:
            continue
        resolution = note_index.resolve(entry["name"])
        display_name = resolution.link(entry["name"])
        prefix = final_timeline.get("timelineKey") if final_timeline else history[-1]["date"]
        lines.append(f"- {display_name}: candidate item-location update from {prefix} -> {format_wikilink(final_location)}.")
        metadata_location = resolution.simple_whereabouts()
        if metadata_location and normalize_name(metadata_location) != normalize_name(final_location):
            review_lines.append(
                f"- {display_name}: note currently says whereabouts '{metadata_location}', but the reviewed recap last places it at '{final_location}'."
            )
    return ("\n".join(lines).strip() or "- none"), dedupe_lines(review_lines)


def render_review_lines(lines: Sequence[str]) -> str:
    unique = dedupe_lines(lines)
    return ("\n".join(unique).strip() if unique else "- none")


def join_recap_zoom(recap_blocks: Sequence[Dict[str, Any]], field_name: str) -> str:
    parts = [block[field_name].strip() for block in recap_blocks if block.get(field_name)]
    return "\n\n".join(parts).strip()


def build_note_context(
    entry: Dict[str, Any],
    resolution: "ResolutionResult",
    *,
    entity_kind: str,
) -> Tuple[str, List[str]]:
    if resolution.note is None:
        return "", []
    metadata = resolution.note.get("frontmatter", {})
    context_bits: List[str] = []
    review_lines: List[str] = []

    if entity_kind == "person":
        if normalize_optional_string(metadata.get("ancestry")):
            context_bits.append(str(metadata["ancestry"]).strip())
        if normalize_optional_string(metadata.get("species")):
            context_bits.append(str(metadata["species"]).strip())
        if normalize_optional_string(metadata.get("gender")):
            context_bits.append(str(metadata["gender"]).strip())
        if normalize_optional_string(metadata.get("pronunciation")):
            context_bits.append(f"pronounced {str(metadata['pronunciation']).strip()}")
    elif entity_kind == "place":
        if normalize_optional_string(metadata.get("partOf")):
            context_bits.append(f"part of {metadata['partOf']}")
        if normalize_optional_string(metadata.get("whereabouts")):
            context_bits.append(f"located in {metadata['whereabouts']}")
        if normalize_optional_string(metadata.get("typeOf")):
            context_bits.append(str(metadata["typeOf"]).strip())
    elif entity_kind == "object":
        if normalize_optional_string(metadata.get("typeOf")):
            context_bits.append(str(metadata["typeOf"]).strip())
        if normalize_optional_string(metadata.get("owner")):
            context_bits.append(f"owned by {metadata['owner']}")
        if normalize_optional_string(metadata.get("whereabouts")):
            context_bits.append(f"kept in {metadata['whereabouts']}")
    else:
        if normalize_optional_string(metadata.get("typeOf")):
            context_bits.append(str(metadata["typeOf"]).strip())
        if normalize_optional_string(metadata.get("whereabouts")):
            context_bits.append(str(metadata["whereabouts"]).strip())

    return "; ".join(context_bits), review_lines


def infer_last_history_location(history: Sequence[Dict[str, str]]) -> Optional[str]:
    if not history:
        return None
    raw_location = history[-1]["location"]
    if "->" in raw_location:
        return raw_location.split("->")[-1].strip()
    return raw_location.strip() or None


def render_inline_csv_as_bullets(value: str) -> str:
    parts = [part.strip() for part in value.split(",") if part.strip()]
    return "\n".join(f"- {part}" for part in parts) if parts else "- none"


def write_component_file(path: Path, *, title: str, session_manifest: str, slots: Dict[str, str]) -> None:
    lines: List[str] = [
        "---",
        f"tags: [{AI_TAG}]",
        'excludePublish: ["all"]',
        f"sessionManifest: {json.dumps(session_manifest)}",
        "---",
        "",
        f"# {title}",
        "",
    ]
    for slot_name, slot_body in slots.items():
        lines.append(f"<!-- SLOT: {slot_name} -->")
        if slot_body:
            lines.append(slot_body)
        lines.append("<!-- /SLOT -->")
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


class ResolutionResult:
    def __init__(self, name: str, note: Optional[Dict[str, Any]], warning: Optional[str] = None) -> None:
        self.name = name
        self.note = note
        self.warning = warning

    def link(self, display_name: str) -> str:
        if self.note is None:
            return display_name
        basename = self.note["path"].stem
        if basename == display_name:
            return f"[[{basename}]]"
        return f"[[{basename}|{display_name}]]"

    def simple_whereabouts(self) -> Optional[str]:
        if self.note is None:
            return None
        frontmatter = self.note.get("frontmatter", {})
        where = frontmatter.get("whereabouts")
        if isinstance(where, str):
            return normalize_optional_string(where)
        return None


class VaultNoteIndex:
    def __init__(self, vault_root: Path, generated_root: Path) -> None:
        self.vault_root = vault_root
        self.generated_root = generated_root
        self.by_basename: Dict[str, List[Dict[str, Any]]] = {}
        self.by_alias: Dict[str, List[Dict[str, Any]]] = {}
        self._load()

    def _load(self) -> None:
        for path in self.vault_root.rglob("*.md"):
            if not should_index_path(path, self.vault_root, self.generated_root):
                continue
            note = {
                "path": path,
                "frontmatter": read_markdown_frontmatter(path),
            }
            self.by_basename.setdefault(normalize_name(path.stem), []).append(note)
            aliases = note["frontmatter"].get("aliases")
            for alias in normalize_aliases(aliases):
                self.by_alias.setdefault(normalize_name(alias), []).append(note)

    def resolve(self, name: str) -> ResolutionResult:
        key = normalize_name(name)
        candidates = dedupe_notes([*self.by_basename.get(key, []), *self.by_alias.get(key, [])])
        if not candidates:
            return ResolutionResult(name, None, "no matching note found in the vault index")
        if len(candidates) > 1:
            paths = ", ".join(str(note["path"].relative_to(self.vault_root)) for note in candidates[:5])
            return ResolutionResult(name, None, f"multiple matching notes found ({paths})")
        return ResolutionResult(name, candidates[0])


def dedupe_notes(notes: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set[Path] = set()
    result: List[Dict[str, Any]] = []
    for note in notes:
        path = note["path"]
        if path in seen:
            continue
        seen.add(path)
        result.append(note)
    return result


def normalize_aliases(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def should_index_path(path: Path, vault_root: Path, generated_root: Path) -> bool:
    if path.is_relative_to(generated_root):
        return False
    relative = path.relative_to(vault_root)
    for part in relative.parts:
        if part.startswith("."):
            return False
        if part == "_sessions":
            return False
        if part.startswith("_"):
            return False
    return True


def read_markdown_frontmatter(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    try:
        end_index = lines[1:].index("---") + 1
    except ValueError:
        return {}
    payload = yaml.safe_load("\n".join(lines[1:end_index])) or {}
    return payload if isinstance(payload, dict) else {}


def find_vault_root(path: Path) -> Path:
    for parent in [path.parent, *path.parents]:
        if (parent / ".obsidian").exists():
            return parent
    raise SystemExit(f"Could not find vault root above {path}")


def resolve_vault_path(vault_root: Path, raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (vault_root / path).resolve()


def read_yaml_mapping(path: Path) -> Dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise SystemExit(f"Expected a YAML mapping in {path}")
    return payload


def normalize_optional_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def slugify_text(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return re.sub(r"-{2,}", "-", slug)


def format_wikilink(value: str) -> str:
    text = value.strip()
    if not text:
        return text
    return f"[[{text}]]"


def dedupe_lines(lines: Sequence[str]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for line in lines:
        normalized = line.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
