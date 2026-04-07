#!/usr/bin/env python3

"""Normalize non-transcript source notes into a cleaned source artifact."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.error import URLError
from urllib.request import urlopen

import yaml


SOURCE_LINE_PREFIX = "source"
RAW_NOTES_BLOCK_RE = re.compile(r"%%\s*RAW notes\b(?P<body>.*?)(?:\n%%|\Z)", re.IGNORECASE | re.DOTALL)
SESSION_HEADING_RE = re.compile(r"^###\s+Session\b", re.IGNORECASE)
SECTION_HEADING_RE = re.compile(r"^(##+)\s+(.*)$")
BULLET_LINE_RE = re.compile(r"^\s*[-*+]\s+")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize non-transcript source material into a cleaned source artifact.")
    parser.add_argument("--session", type=Path, required=True, help="session.yaml path.")
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory for normalization artifacts.")
    parser.add_argument(
        "--file-prefix",
        type=str,
        required=True,
        help="Unique lowercase prefix for generated artifacts, e.g. 'addermarch-campaign-007'.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    file_prefix = args.file_prefix.strip()
    if not file_prefix:
        raise SystemExit("--file-prefix must be non-empty.")

    session_path = args.session.expanduser().resolve()
    session_payload = read_yaml_mapping(session_path)
    source_type = normalize_optional_string(session_payload.get("sourceType"))
    if source_type == "transcript":
        raise SystemExit("normalize-source is only for non-transcript bundles.")

    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    supplemental_dir = output_dir / "supplemental"
    artifacts_dir = output_dir / "normalization-artifacts"
    supplemental_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    source_input = required_string(session_payload, "sourceInputPath", "session")
    primary_text = load_source_text(source_input)
    primary_result = normalize_primary_source(
        text=primary_text,
        source_type=source_type or "narrative",
        scope=normalize_optional_string(session_payload.get("scope")) or "session",
    )

    supplemental_results: List[Dict[str, Any]] = []
    for index, embedded in enumerate(primary_result["embeddedSupplements"], start=1):
        label = f"embedded-raw-notes-{index:02d}"
        supplemental_results.append(
            build_supplemental_result(
                label=label,
                original=embedded["original"],
                text=embedded["text"],
            )
        )

    for index, narrative in enumerate(primary_result["derivedSupplements"], start=1):
        label = f"derived-{index:02d}"
        supplemental_results.append(
            build_supplemental_result(
                label=label,
                original=narrative["original"],
                text=narrative["text"],
            )
        )

    for index, supplemental in enumerate(session_payload.get("supplementalSources", []), start=1):
        if not isinstance(supplemental, dict):
            continue
        original = normalize_optional_string(supplemental.get("original")) or f"supplemental-{index:02d}"
        source_ref = normalize_optional_string(supplemental.get("archivedPath")) or normalize_optional_string(supplemental.get("sourcePath"))
        if source_ref is None:
            continue
        supplemental_results.append(
            build_supplemental_result(
                label=f"supplemental-{index:02d}",
                original=original,
                text=load_source_text(source_ref),
            )
        )

    cleaned_path = output_dir / f"{file_prefix}-source-cleaned.md"
    structure_path = artifacts_dir / f"{file_prefix}-source-structure.json"
    report_path = artifacts_dir / f"{file_prefix}-normalization-report.md"

    cleaned_path.write_text(render_units(primary_result["units"]) + "\n", encoding="utf-8")

    rendered_supplemental = []
    for item in supplemental_results:
        path = supplemental_dir / f"{item['label']}-source-cleaned.md"
        path.write_text(render_units(item["units"]) + "\n", encoding="utf-8")
        rendered_supplemental.append(
            {
                "label": item["label"],
                "original": item["original"],
                "path": str(path),
                "unitCount": len(item["units"]),
            }
        )

    structure_payload = {
        "schemaVersion": "1.0",
        "sessionPath": str(session_path),
        "primarySourcePath": str(cleaned_path),
        "sourceType": source_type,
        "scope": normalize_optional_string(session_payload.get("scope")) or "session",
        "detectedShape": primary_result["detectedShape"],
        "primaryUnits": primary_result["units"],
        "supplementalSources": rendered_supplemental,
        "notes": primary_result["notes"],
    }
    structure_path.write_text(json.dumps(structure_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report_path.write_text(render_report(structure_payload), encoding="utf-8")

    print(f"Wrote {cleaned_path}")
    print(f"Wrote {structure_path}")
    print(f"Wrote {report_path}")
    if rendered_supplemental:
        print(f"Wrote {len(rendered_supplemental)} supplemental cleaned source file(s) under {supplemental_dir}")
    return 0


def load_source_text(source_ref: str) -> str:
    if re.match(r"^https?://", source_ref, re.IGNORECASE):
        try:
            with urlopen(source_ref, timeout=20) as response:
                return response.read().decode("utf-8", errors="replace")
        except URLError as exc:
            raise SystemExit(f"Failed to fetch supplemental URL {source_ref}: {exc}") from exc
    return Path(source_ref).expanduser().resolve().read_text(encoding="utf-8")


def build_supplemental_result(*, label: str, original: str, text: str) -> Dict[str, Any]:
    if looks_like_sparse_notes(text, source_type="raw_notes"):
        units = [make_unit(index, "notes", item) for index, item in enumerate(extract_note_units(text), start=1)]
    else:
        units = normalize_freeform_text(text)["units"]
    return {
        "label": label,
        "original": original,
        "units": units,
    }


def normalize_primary_source(*, text: str, source_type: str, scope: str) -> Dict[str, Any]:
    body_text = strip_frontmatter(text)
    embedded_raw_blocks = extract_raw_notes_blocks(body_text)
    body_without_raw = embedded_raw_blocks["cleanedText"]
    notes = list(embedded_raw_blocks["notes"])

    if scope == "arc" and has_session_headings(body_without_raw):
        units = normalize_session_heading_sections(body_without_raw)
        detected_shape = "arc-session-headings"
        derived_supplements: List[Dict[str, str]] = []
    elif has_timeline_section(body_without_raw):
        timeline_units = extract_timeline_units(body_without_raw)
        narrative_sections = extract_named_sections(body_without_raw, {"narrative"})
        units = [make_unit(index, "timeline", item) for index, item in enumerate(timeline_units, start=1)]
        detected_shape = "timeline-structured-note"
        derived_supplements = [
            {"original": "Narrative section", "text": "\n\n".join(narrative_sections)}
        ] if narrative_sections else []
        if narrative_sections:
            notes.append("Narrative section preserved as supplemental material because Timeline was used as the primary source.")
    elif looks_like_sparse_notes(body_without_raw, source_type=source_type):
        note_units = extract_note_units(body_without_raw)
        units = [make_unit(index, "notes", item) for index, item in enumerate(note_units, start=1)]
        detected_shape = "sparse-notes"
        derived_supplements = []
    else:
        normalized = normalize_freeform_text(body_without_raw)
        units = normalized["units"]
        detected_shape = "prose-narrative"
        derived_supplements = []

    return {
        "detectedShape": detected_shape,
        "units": units,
        "embeddedSupplements": embedded_raw_blocks["supplements"],
        "derivedSupplements": derived_supplements,
        "notes": notes,
    }


def normalize_freeform_text(text: str) -> Dict[str, Any]:
    paragraphs = [
        clean_unit_text(block)
        for block in re.split(r"\n\s*\n", text)
        if clean_unit_text(block)
    ]
    units = [make_unit(index, SOURCE_LINE_PREFIX, paragraph) for index, paragraph in enumerate(paragraphs, start=1)]
    return {"units": units}


def normalize_session_heading_sections(text: str) -> List[Dict[str, str]]:
    lines = text.splitlines()
    sections: List[Tuple[str, List[str]]] = []
    current_heading: Optional[str] = None
    current_lines: List[str] = []
    for raw in lines:
        heading_match = SESSION_HEADING_RE.match(raw.strip())
        if heading_match:
            if current_heading is not None:
                sections.append((current_heading, current_lines))
            current_heading = raw.strip().lstrip("#").strip()
            current_lines = []
            continue
        if current_heading is not None:
            current_lines.append(raw)
    if current_heading is not None:
        sections.append((current_heading, current_lines))

    units: List[Dict[str, str]] = []
    for index, (heading, body_lines) in enumerate(sections, start=1):
        body = strip_events_subsections("\n".join(body_lines))
        summary = summarize_section_body(body) or heading
        units.append(make_unit(index, "session", f"{heading}: {summary}"))
    return units


def strip_events_subsections(text: str) -> str:
    kept: List[str] = []
    skip = False
    for raw in text.splitlines():
        stripped = raw.strip()
        heading_match = SECTION_HEADING_RE.match(stripped)
        if heading_match:
            heading_name = heading_match.group(2).strip().casefold()
            skip = heading_name == "events"
            continue
        if skip:
            if stripped.startswith("### ") or stripped.startswith("## "):
                skip = False
            else:
                continue
        kept.append(raw)
    return "\n".join(kept)


def summarize_section_body(text: str) -> str:
    paragraphs = [
        clean_unit_text(block)
        for block in re.split(r"\n\s*\n", text)
        if clean_unit_text(block)
    ]
    if not paragraphs:
        return ""
    return " ".join(paragraphs[:2]).strip()


def has_timeline_section(text: str) -> bool:
    return bool(re.search(r"^##\s+Timeline\b", text, re.IGNORECASE | re.MULTILINE))


def extract_timeline_units(text: str) -> List[str]:
    lines = text.splitlines()
    in_timeline = False
    units: List[str] = []
    for raw in lines:
        stripped = raw.strip()
        if re.match(r"^##\s+Timeline\b", stripped, re.IGNORECASE):
            in_timeline = True
            continue
        if in_timeline and stripped.startswith("## "):
            break
        if not in_timeline:
            continue
        if BULLET_LINE_RE.match(raw):
            unit = clean_unit_text(strip_bullet_prefix(raw))
            if unit:
                units.append(unit)
    return units


def extract_named_sections(text: str, names: set[str]) -> List[str]:
    sections: List[str] = []
    current_name: Optional[str] = None
    current_lines: List[str] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        heading_match = SECTION_HEADING_RE.match(stripped)
        if heading_match:
            if current_name in names and current_lines:
                sections.append("\n".join(current_lines).strip())
            current_name = heading_match.group(2).strip().casefold()
            current_lines = []
            continue
        if current_name in names:
            current_lines.append(raw)
    if current_name in names and current_lines:
        sections.append("\n".join(current_lines).strip())
    return [section for section in sections if section.strip()]


def looks_like_sparse_notes(text: str, *, source_type: str) -> bool:
    if source_type == "raw_notes":
        return True
    non_empty_lines = [line for line in text.splitlines() if line.strip()]
    if not non_empty_lines:
        return False
    bullet_count = sum(1 for line in non_empty_lines if BULLET_LINE_RE.match(line))
    return bullet_count >= max(3, len(non_empty_lines) // 3)


def extract_note_units(text: str) -> List[str]:
    units: List[str] = []
    continuation: List[str] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            if continuation:
                units.append(clean_unit_text(" ".join(continuation)))
                continuation = []
            continue
        if BULLET_LINE_RE.match(raw):
            if continuation:
                units.append(clean_unit_text(" ".join(continuation)))
            continuation = [strip_bullet_prefix(raw)]
            continue
        if continuation:
            continuation.append(stripped)
        else:
            continuation = [stripped]
    if continuation:
        units.append(clean_unit_text(" ".join(continuation)))
    return [unit for unit in units if unit]


def extract_raw_notes_blocks(text: str) -> Dict[str, Any]:
    supplements: List[Dict[str, str]] = []
    notes: List[str] = []

    def replace(match: re.Match[str]) -> str:
        body = match.group("body").strip()
        if body:
            supplements.append({"original": "Embedded RAW notes block", "text": body})
            notes.append("Embedded RAW notes block preserved as supplemental material.")
        return ""

    cleaned_text = RAW_NOTES_BLOCK_RE.sub(replace, text)
    return {"cleanedText": cleaned_text, "supplements": supplements, "notes": notes}


def has_session_headings(text: str) -> bool:
    return bool(re.search(r"^###\s+Session\b", text, re.IGNORECASE | re.MULTILINE))


def strip_frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return text
    lines = text.splitlines()
    if not lines:
        return text
    try:
        end_index = lines[1:].index("---") + 1
    except ValueError:
        return text
    return "\n".join(lines[end_index + 1 :])


def render_units(units: Sequence[Dict[str, str]]) -> str:
    return "\n".join(f"[{unit['uid']} | {unit['kind']}] {unit['text']}" for unit in units)


def render_report(payload: Dict[str, Any]) -> str:
    lines = [
        "# Source Normalization Report",
        "",
        f"- Source Type: {payload.get('sourceType') or 'unknown'}",
        f"- Scope: {payload.get('scope') or 'unknown'}",
        f"- Detected Shape: {payload['detectedShape']}",
        f"- Primary Unit Count: {len(payload['primaryUnits'])}",
        f"- Supplemental Source Count: {len(payload['supplementalSources'])}",
        "",
    ]
    if payload["notes"]:
        lines.append("## Notes")
        lines.append("")
        for note in payload["notes"]:
            lines.append(f"- {note}")
        lines.append("")
    if payload["supplementalSources"]:
        lines.append("## Supplemental Sources")
        lines.append("")
        for source in payload["supplementalSources"]:
            lines.append(f"- {source['label']}: {source['original']} ({source['unitCount']} units)")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def make_unit(index: int, kind: str, text: str) -> Dict[str, str]:
    return {
        "uid": f"u{index:04d}",
        "kind": kind,
        "text": clean_unit_text(text),
    }


def strip_bullet_prefix(text: str) -> str:
    return BULLET_LINE_RE.sub("", text.strip(), count=1)


def clean_unit_text(text: str) -> str:
    cleaned = text.replace("\u00a0", " ")
    cleaned = re.sub(r"\[\[\s+", "[[", cleaned)
    cleaned = re.sub(r"\s+\]\]", "]]", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


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
