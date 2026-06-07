#!/usr/bin/env python3

"""Validate a structured machine-parseable markdown session recap."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import yaml

from participant_inference import infer_session_header_participants
from recap_markdown import SessionRecapParseError, parse_session_recap

REQUIRED_BODY_SECTIONS = (
    "## Timeline",
    "## Recap",
    "## Cast",
    "## Locations",
    "## Organizations And Items",
    "## Combat",
    "## Source Files",
)

RECAP_META_OPENERS = (
    r"^the opening\b",
    r"^this combat\b",
    r"^the conversation shifts\b",
    r"^the final stretch\b",
    r"^this scene\b",
    r"^this beat\b",
    r"^this section\b",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a structured machine-parseable markdown session recap.")
    parser.add_argument("--context-json", type=Path, required=True, help="session-summary-context JSON path.")
    parser.add_argument("--session-recap-md", type=Path, required=True, help="Session recap markdown path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    context = read_json_mapping(args.context_json.expanduser().resolve())
    recap_path = args.session_recap_md.expanduser().resolve()
    recap_text = recap_path.read_text(encoding="utf-8")

    errors = validate_recap(context, recap_text)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    print(f"Validated {recap_path}")
    return 0


def validate_recap(context: Dict[str, Any], text: str) -> List[str]:
    errors: List[str] = []
    if "TODO" in text:
        errors.append("session-recap.md still contains TODO placeholders.")

    body_lines = text.splitlines()
    session_payload = read_yaml_mapping(Path(context["sessionPath"]))
    validate_sections(body_lines, session_payload, errors)
    validate_session_header(body_lines, session_payload, errors)
    validate_timeline_blocks(context, body_lines, errors)
    validate_recap_blocks(context, body_lines, errors)
    validate_combat_blocks(context, body_lines, errors)
    try:
        parse_session_recap(text)
    except SessionRecapParseError as exc:
        errors.extend(exc.errors)
    return errors


def validate_sections(lines: Sequence[str], session_payload: Dict[str, Any], errors: List[str]) -> None:
    headings = [line.strip() for line in lines if line.startswith("## ")]
    required_sections = [
        "## Arc Header" if normalize_optional_string(session_payload.get("scope")) == "arc" else "## Session Header",
        *REQUIRED_BODY_SECTIONS,
    ]
    position = 0
    for required in required_sections:
        try:
            index = headings.index(required, position)
        except ValueError:
            errors.append(f"Missing required section: {required}")
            continue
        position = index + 1


def validate_session_header(lines: Sequence[str], session_payload: Dict[str, Any], errors: List[str]) -> None:
    header_heading = "## Arc Header" if normalize_optional_string(session_payload.get("scope")) == "arc" else "## Session Header"
    required_fields = {
        "Title": None,
        "Desc Title": None,
        "Tagline": None,
        "One-Sentence Summary": None,
        "DM": None,
        "PCs": None,
    }
    in_header = False
    for line in lines:
        stripped = line.strip()
        if stripped == header_heading:
            in_header = True
            continue
        if in_header and stripped.startswith("## "):
            break
        if not in_header or not stripped.startswith("- "):
            continue
        for field_name in list(required_fields):
            prefix = f"- {field_name}:"
            if stripped.startswith(prefix):
                required_fields[field_name] = stripped[len(prefix):].strip()
    for field_name, value in required_fields.items():
        if normalize_optional_string(value) is None:
            errors.append(f"Session Header is missing {field_name}.")
    tagline = normalize_optional_string(required_fields["Tagline"])
    if tagline:
        if not tagline.lower().startswith("in which "):
            errors.append("Session Header Tagline must start with 'in which'.")
    one_sentence_summary = normalize_optional_string(required_fields["One-Sentence Summary"])
    if one_sentence_summary and count_sentences(one_sentence_summary) != 1:
        errors.append("Session Header One-Sentence Summary must be exactly one sentence.")

    participant_info = infer_session_header_participants(session_payload)
    expected_dm = normalize_optional_string(participant_info.get("dmName"))
    expected_pcs = participant_info.get("pcs", [])
    actual_dm = normalize_optional_string(required_fields["DM"])
    actual_pcs = parse_pc_line(required_fields["PCs"])
    if expected_dm is not None and actual_dm != expected_dm:
        errors.append("Session Header DM does not match session.yaml participants.")
    if expected_pcs:
        if participant_info.get("strictValidation", True):
            if actual_pcs != expected_pcs:
                errors.append("Session Header PCs do not match inferred session PCs.")
        else:
            allowed = {str(item).casefold() for item in participant_info.get("allowedFallbackPcs", [])}
            if not actual_pcs:
                errors.append("Session Header PCs must list one or more PCs.")
            invalid = [item for item in actual_pcs if item.casefold() not in allowed]
            if invalid:
                errors.append(
                    "Session Header PCs contain names outside the session participant roster: "
                    + ", ".join(invalid)
                )


def validate_timeline_blocks(context: Dict[str, Any], lines: Sequence[str], errors: List[str]) -> None:
    expected_ids = [block["blockId"] for block in context.get("timelineBlocks", [])]
    timeline_lines = get_section_lines(lines, "## Timeline")
    actual_blocks = collect_timeline_blocks(timeline_lines)
    actual_ids = [block_id for block_id, _, _ in actual_blocks]
    if expected_ids and not actual_ids:
        errors.append("Timeline section must include at least one context timeline block.")
        return
    validate_context_ordered_subset(actual_ids, expected_ids, "Timeline", errors)
    context_blocks = {block["blockId"]: block for block in context.get("timelineBlocks", [])}
    for block_id, start, end in actual_blocks:
        if block_id not in context_blocks:
            continue
        block_lines = timeline_lines[start:end]
        validate_timeline_heading_and_key(block_lines, context_blocks[block_id], errors)
        validate_subsection(block_lines, "#### Short", f"timeline {block_id}", errors)
        validate_subsection(block_lines, "#### Long", f"timeline {block_id}", errors)


def validate_recap_blocks(context: Dict[str, Any], lines: Sequence[str], errors: List[str]) -> None:
    expected_ids = [block["blockId"] for block in context.get("recapBlocks", [])]
    recap_lines = get_section_lines(lines, "## Recap")
    actual_blocks = collect_level3_blocks(recap_lines, "recap-")
    actual_ids = [block_id for block_id, _, _ in actual_blocks]
    if expected_ids and not actual_ids:
        errors.append("Recap section must include at least one context recap block.")
        return
    validate_context_ordered_subset(actual_ids, expected_ids, "Recap", errors)
    for block_id, start, end in actual_blocks:
        block_lines = recap_lines[start:end]
        short_text = validate_subsection(block_lines, "#### Short", f"recap {block_id}", errors)
        intermediate_text = validate_subsection(block_lines, "#### Intermediate", f"recap {block_id}", errors)
        long_text = validate_subsection(block_lines, "#### Long", f"recap {block_id}", errors)
        if short_text:
            validate_recap_prose(short_text, f"recap {block_id} #### Short", errors)
        if intermediate_text:
            validate_recap_prose(intermediate_text, f"recap {block_id} #### Intermediate", errors)
        if long_text:
            validate_recap_prose(long_text, f"recap {block_id} #### Long", errors)


def validate_combat_blocks(context: Dict[str, Any], lines: Sequence[str], errors: List[str]) -> None:
    expected_ids = [block["blockId"] for block in context.get("recapBlocks", []) if block.get("kind") == "combat"]
    if not expected_ids:
        return
    combat_lines = get_section_lines(lines, "## Combat")
    actual_blocks = collect_level3_blocks(combat_lines, "recap-")
    combat_ids = [block_id for block_id, _, _ in actual_blocks]
    if not combat_ids:
        errors.append("Combat section must include at least one context combat block.")
        return
    validate_context_ordered_subset(combat_ids, expected_ids, "Combat", errors)
    context_blocks = {block["blockId"]: block for block in context.get("recapBlocks", []) if block.get("kind") == "combat"}
    for block_id, start, end in actual_blocks:
        if block_id not in context_blocks:
            continue
        block_lines = combat_lines[start:end]
        validate_combat_block(block_lines, context_blocks[block_id], errors)


def validate_context_ordered_subset(
    actual_ids: Sequence[str],
    expected_ids: Sequence[str],
    label: str,
    errors: List[str],
) -> None:
    expected_positions = {block_id: index for index, block_id in enumerate(expected_ids)}
    seen: set[str] = set()
    last_position = -1
    for block_id in actual_ids:
        if block_id in seen:
            errors.append(f"{label} block {block_id} appears more than once.")
            continue
        seen.add(block_id)
        position = expected_positions.get(block_id)
        if position is None:
            errors.append(f"{label} block {block_id} is not present in context.")
            continue
        if position < last_position:
            errors.append(f"{label} blocks in session-recap.md are not in context order.")
            continue
        last_position = position


def validate_timeline_heading_and_key(lines: Sequence[str], context_block: Dict[str, Any], errors: List[str]) -> None:
    heading = next((line.strip() for line in lines if line.startswith("### ")), None)
    expected_heading = f"### {format_display_date_span(context_block.get('dateStart'), context_block.get('dateEnd'))}{format_time_window(context_block.get('timeWindow'))}"
    if heading != expected_heading:
        errors.append(f"timeline {context_block['blockId']} heading does not match required display date format.")
    key_line = next((line.strip() for line in lines if line.startswith("- Timeline Key: ")), None)
    expected_key = (
        f"- Timeline Key: "
        f"{format_timeline_key(context_block.get('dateStart'), context_block.get('dateEnd'), context_block.get('timeWindow'))}"
    )
    if key_line != expected_key:
        errors.append(f"timeline {context_block['blockId']} Timeline Key does not match context.")


def validate_combat_block(lines: Sequence[str], context_block: Dict[str, Any], errors: List[str]) -> None:
    heading = next((line.strip() for line in lines if line.startswith("### ")), None)
    if heading is None or not re.match(rf"^### {re.escape(context_block['blockId'])}\s+\|\s+\S", heading):
        errors.append(f"combat {context_block['blockId']} heading must include a short title.")
    enemies_line = next((line.strip() for line in lines if line.startswith("- Enemies: ")), None)
    expected_enemies = ", ".join(context_block.get("combatEnemyRefs", [])) if context_block.get("combatEnemyRefs") else "none"
    if enemies_line != f"- Enemies: {expected_enemies}":
        errors.append(f"combat {context_block['blockId']} Enemies line does not match context.")
    context_line = next((line.strip() for line in lines if line.startswith("- Context / Outcome: ")), None)
    if context_line is None or not normalize_optional_string(context_line.split(": ", 1)[1] if ": " in context_line else None):
        errors.append(f"combat {context_block['blockId']} is missing Context / Outcome.")


def collect_level3_blocks(lines: Sequence[str], prefix: str) -> List[Tuple[str, int, int]]:
    headings: List[Tuple[str, int]] = []
    for index, line in enumerate(lines):
        match = re.match(rf"^### ({re.escape(prefix)}\d+)\s+\|", line.strip())
        if match:
            headings.append((match.group(1), index))
    blocks: List[Tuple[str, int, int]] = []
    for position, (block_id, start) in enumerate(headings):
        end = headings[position + 1][1] if position + 1 < len(headings) else len(lines)
        blocks.append((block_id, start, end))
    return blocks


def collect_timeline_blocks(lines: Sequence[str]) -> List[Tuple[str, int, int]]:
    blocks: List[Tuple[str, int]] = []
    current_heading_index: Optional[int] = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("### "):
            current_heading_index = index
            continue
        if not stripped.startswith("- Timeline Segment: "):
            continue
        block_id = stripped.split(": ", 1)[1].strip()
        start_index = current_heading_index if current_heading_index is not None else index
        blocks.append((block_id, start_index))
    resolved: List[Tuple[str, int, int]] = []
    for position, (block_id, start) in enumerate(blocks):
        end = blocks[position + 1][1] if position + 1 < len(blocks) else len(lines)
        resolved.append((block_id, start, end))
    return resolved


def get_section_lines(lines: Sequence[str], heading: str) -> List[str]:
    start_index: Optional[int] = None
    for index, line in enumerate(lines):
        if line.strip() == heading:
            start_index = index + 1
            break
    if start_index is None:
        return []
    end_index = len(lines)
    for index in range(start_index, len(lines)):
        if lines[index].startswith("## "):
            end_index = index
            break
    return list(lines[start_index:end_index])


def validate_subsection(lines: Sequence[str], heading: str, label: str, errors: List[str]) -> Optional[str]:
    for index, line in enumerate(lines):
        if line.strip() != heading:
            continue
        content_lines: List[str] = []
        for next_line in lines[index + 1:]:
            if next_line.startswith("#### ") or next_line.startswith("### "):
                break
            if next_line.strip():
                content_lines.append(next_line.strip())
        content = " ".join(content_lines).strip()
        if not content or content == "TODO":
            errors.append(f"{label} subsection {heading} must be filled in.")
            return None
        return content
    errors.append(f"{label} is missing subsection {heading}.")
    return None


def validate_recap_prose(text: str, label: str, errors: List[str]) -> None:
    lowered = text.lower().strip()
    for pattern in RECAP_META_OPENERS:
        if re.match(pattern, lowered):
            errors.append(f"{label} starts with analytical framing instead of direct recap prose.")
    if "this session" in lowered or "this recap" in lowered:
        errors.append(f"{label} uses meta recap language.")

def parse_pc_line(value: Any) -> List[str]:
    text = normalize_optional_string(value)
    if text is None or text in {"none", "unknown"}:
        return []
    return [part.strip() for part in text.split(",") if part.strip()]


def count_sentences(text: str) -> int:
    matches = re.findall(r"[.!?](?=\s|$)", text)
    return len(matches)


def format_time_window(value: Optional[str]) -> str:
    return f" ({value})" if normalize_optional_string(value) else ""


def format_timeline_key(date_start: Optional[str], date_end: Optional[str], time_window: Optional[str]) -> str:
    if not date_start:
        return "undated"
    key = f"(DR:: {date_start})"
    if normalize_optional_string(date_end) and date_end != date_start:
        key += f" - (DR_end:: {date_end})"
    if normalize_optional_string(time_window):
        key += f", {time_window}"
    return key


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


def read_json_mapping(path: Path) -> Dict[str, Any]:
    import json

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"Expected a JSON object in {path}")
    return payload


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


if __name__ == "__main__":
    raise SystemExit(main())
