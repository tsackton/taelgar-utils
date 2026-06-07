#!/usr/bin/env python3

"""Extract, link, and validate recap-scoped polished transcript files."""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


SOURCE_LINE_RE = re.compile(r"^(?P<header>\[(?P<uid>u\d{4,})(?:\s*\|[^\]]+)?\])\s*(?P<text>.*)$")
RECAP_HEADING_RE = re.compile(r"^### (?P<block_id>recap-\d+)\s+\|\s+(?P<title>.+)$")
RECAP_METADATA_RE = re.compile(r"^-\s+(?P<key>[^:]+):\s*(?P<value>.*)$")
SOURCE_RANGE_VALUE_RE = re.compile(r"^(?P<start>u\d{4,})\s*->\s*(?P<end>u\d{4,})$")
SOURCE_MARKER_RE = re.compile(r"^%%\s*(?P<start>u\d{4,})(?:-(?P<end>u\d{4,}))?\s*%%$")
SPEAKER_TURN_RE = re.compile(r"^[^:\n]{1,80}:\s+\S")
HIGHLIGHT_ID_RE = re.compile(r"^\s*-\s+ID:\s*(?P<id>[A-Za-z0-9_.:-]+)\s*$")
TRANSCRIPT_HEADING = "## Transcript"
PATH_KEY = "Polished Transcript"
HIGHLIGHTS_HEADING = "## Pull Quotes"
MONOLOGUES_HEADING = "## Audio Monologue Candidates"
RECAP_PULL_QUOTES_HEADING = "## Pull Quotes"
RECAP_AUDIO_HEADING = "## Audio Highlights"
MAX_DRAFT_GROUP_LINES = 12


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manage recap-scoped polished transcript files.")
    parser.add_argument("--transcript", type=Path, required=True, help="Cleaned source transcript path.")
    parser.add_argument(
        "--context-json",
        type=Path,
        default=None,
        help="Deprecated and ignored. session-recap.md is authoritative.",
    )
    parser.add_argument("--session-recap-md", type=Path, required=True, help="session-recap.md path to patch or validate.")
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory for polished transcript files.")
    parser.add_argument(
        "--file-prefix",
        type=str,
        required=True,
        help="Unique lowercase prefix for generated artifacts, e.g. 'addermarch-campaign-007'.",
    )
    parser.add_argument("--recap-block-id", type=str, default=None, help="Optional recap block id to process.")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate existing transcript files and recap links without creating or patching files.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing transcript files with freshly extracted source text.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    transcript_path = args.transcript.expanduser().resolve()
    recap_path = args.session_recap_md.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    file_prefix = args.file_prefix.strip()
    if not file_prefix:
        raise SystemExit("--file-prefix must be non-empty.")

    for label, path in (
        ("--transcript", transcript_path),
        ("--session-recap-md", recap_path),
        ("--output-dir", output_dir),
    ):
        assert_not_in_sources_dir(path, label)

    transcript_lines = read_source_lines(transcript_path)
    uid_to_index = build_uid_index(transcript_lines)
    blocks = select_recap_blocks(read_recap_blocks(recap_path), args.recap_block_id)
    summary_path = output_dir / f"{file_prefix}-transcript-highlights.md"
    plan = build_plan(
        blocks=blocks,
        transcript_lines=transcript_lines,
        uid_to_index=uid_to_index,
        transcript_path=transcript_path,
        recap_path=recap_path,
        output_dir=output_dir,
        file_prefix=file_prefix,
    )

    if not args.validate_only:
        output_dir.mkdir(parents=True, exist_ok=True)
        write_missing_or_overwritten_transcripts(plan, overwrite=args.overwrite)
        sync_file_headings(plan)
        write_missing_summary_file(summary_path, plan, transcript_path=transcript_path, recap_path=recap_path)
        patch_session_recap(recap_path, plan)
        sync_recap_review_media(recap_path, summary_path)

    errors, warnings = validate_outputs(recap_path, plan, summary_path=summary_path)
    for warning in warnings:
        print(f"WARNING: {warning}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    action = "Validated" if args.validate_only else "Managed"
    print(f"{action} {len(plan)} polished transcript file(s).")
    for item in plan:
        print(f"- {item['blockId']}: {item['relativePath']}")
    print(f"- highlights: {relative_markdown_path(summary_path, recap_path.parent)}")
    return 0


def assert_not_in_sources_dir(path: Path, arg_name: str) -> None:
    if "sources" in path.parts:
        raise SystemExit(f"{arg_name} must not point inside a bundle 'sources' directory: {path}")


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
                "raw": raw,
                "speaker": extract_speaker(match.group("header")),
                "text": match.group("text").strip(),
            }
        )
    return lines


def extract_speaker(header: str) -> str:
    inner = header.strip()[1:-1]
    parts = [part.strip() for part in inner.split("|")]
    if len(parts) >= 3 and parts[-1]:
        return parts[-1]
    return "Source"


def build_uid_index(transcript_lines: Sequence[Dict[str, str]]) -> Dict[str, int]:
    return {line["uid"]: index for index, line in enumerate(transcript_lines)}


def read_recap_blocks(recap_path: Path) -> List[Dict[str, Any]]:
    blocks: List[Dict[str, Any]] = []
    in_recap = False
    current: Optional[Dict[str, Any]] = None
    seen_ids: set[str] = set()

    for line_number, raw in enumerate(recap_path.read_text(encoding="utf-8").splitlines(), start=1):
        if raw.startswith("## "):
            if in_recap and current is not None:
                blocks.append(finalize_recap_block(current, recap_path))
                current = None
            in_recap = raw == "## Recap"
            continue
        if not in_recap:
            continue

        heading_match = RECAP_HEADING_RE.match(raw)
        if heading_match:
            if current is not None:
                blocks.append(finalize_recap_block(current, recap_path))
            block_id = heading_match.group("block_id")
            if block_id in seen_ids:
                raise SystemExit(f"Duplicate recap block id in {recap_path}: {block_id}")
            seen_ids.add(block_id)
            current = {
                "blockId": block_id,
                "title": heading_match.group("title").strip(),
                "metadata": {},
                "metadataOpen": True,
                "lineNumber": line_number,
            }
            continue

        if current is None:
            continue
        if raw.startswith("#### "):
            current["metadataOpen"] = False
            continue
        metadata_match = RECAP_METADATA_RE.match(raw) if current["metadataOpen"] else None
        if metadata_match:
            current["metadata"][metadata_match.group("key").strip()] = metadata_match.group("value").strip()

    if in_recap and current is not None:
        blocks.append(finalize_recap_block(current, recap_path))

    if not blocks:
        raise SystemExit(f"Could not find recap blocks in {recap_path}.")
    return blocks


def finalize_recap_block(raw: Dict[str, Any], recap_path: Path) -> Dict[str, Any]:
    block_id = raw["blockId"]
    metadata = raw["metadata"]
    source_range = metadata.get("Source Range", "")
    range_match = SOURCE_RANGE_VALUE_RE.match(source_range)
    if not range_match:
        raise SystemExit(f"{block_id} in {recap_path} is missing a valid Source Range.")
    beat_ids = parse_recap_list(metadata.get("Beat IDs", ""))
    return {
        "blockId": block_id,
        "title": raw["title"],
        "beatIds": beat_ids,
        "startUid": range_match.group("start"),
        "endUid": range_match.group("end"),
        "sourceEntries": recap_source_entries(
            block_id=block_id,
            title=raw["title"],
            beat_ids=beat_ids,
            start_uid=range_match.group("start"),
            end_uid=range_match.group("end"),
        ),
    }


def parse_recap_list(value: str) -> List[str]:
    text = value.strip()
    if not text or text.lower() == "none":
        return []
    return [item.strip() for item in text.split(",") if item.strip()]


def recap_source_entries(
    *,
    block_id: str,
    title: str,
    beat_ids: Sequence[str],
    start_uid: str,
    end_uid: str,
) -> List[Dict[str, str]]:
    if not beat_ids:
        return []
    return [
        {
            "beatId": beat_id,
            "title": title if len(beat_ids) == 1 else beat_id,
            "startUid": start_uid,
            "endUid": end_uid,
            "shortSummary": "",
            "recapBlockId": block_id,
        }
        for beat_id in beat_ids
    ]


def select_recap_blocks(blocks: Sequence[Dict[str, Any]], block_id: Optional[str]) -> List[Dict[str, Any]]:
    if block_id is None:
        return list(blocks)
    selected = [block for block in blocks if block["blockId"] == block_id]
    if not selected:
        known = ", ".join(block["blockId"] for block in blocks)
        raise SystemExit(f"Unknown recap block id: {block_id}. Known recap blocks: {known}")
    return selected


def build_plan(
    *,
    blocks: Sequence[Dict[str, Any]],
    transcript_lines: Sequence[Dict[str, str]],
    uid_to_index: Dict[str, int],
    transcript_path: Path,
    recap_path: Path,
    output_dir: Path,
    file_prefix: str,
) -> List[Dict[str, Any]]:
    plan: List[Dict[str, Any]] = []
    for block in blocks:
        start_index = uid_to_index.get(block["startUid"])
        end_index = uid_to_index.get(block["endUid"])
        if start_index is None or end_index is None:
            raise SystemExit(f"{block['blockId']} references unknown source uid.")
        if start_index > end_index:
            raise SystemExit(f"{block['blockId']} has an inverted source range.")
        output_path = output_dir / f"{file_prefix}-{safe_slug(block['blockId'])}-transcript.md"
        relative_path = relative_markdown_path(output_path, recap_path.parent)
        source_relative_path = relative_markdown_path(transcript_path, output_path.parent)
        selected_lines = list(transcript_lines[start_index : end_index + 1])
        plan.append(
            {
                **block,
                "outputPath": output_path,
                "relativePath": relative_path,
                "sourceRelativePath": source_relative_path,
                "sourceLines": selected_lines,
                "expectedUids": [line["uid"] for line in selected_lines],
            }
        )
    return plan


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-")
    return slug or "block"


def relative_markdown_path(path: Path, base_dir: Path) -> str:
    return os.path.relpath(path, base_dir).replace(os.sep, "/")


def write_missing_or_overwritten_transcripts(plan: Sequence[Dict[str, Any]], *, overwrite: bool) -> None:
    for item in plan:
        output_path: Path = item["outputPath"]
        if output_path.exists() and not overwrite:
            continue
        output_path.write_text(render_transcript_file(item), encoding="utf-8")


def render_transcript_file(item: Dict[str, Any]) -> str:
    lines = [
        transcript_heading(item),
        "",
        f"- Recap Block: {item['blockId']}",
        f"- Beat IDs: {', '.join(item['beatIds']) if item['beatIds'] else 'none'}",
        f"- Source Range: {item['startUid']} -> {item['endUid']}",
        f"- Source Transcript: {item['sourceRelativePath']}",
        "",
        TRANSCRIPT_HEADING,
        "",
    ]
    lines.extend(render_draft_turns(item["sourceLines"]))
    return "\n".join(lines).rstrip() + "\n"


def transcript_heading(item: Dict[str, Any]) -> str:
    return f"# {item['blockId']} | {item['title']}"


def render_draft_turns(source_lines: Sequence[Dict[str, str]]) -> List[str]:
    output: List[str] = []
    for group in group_source_lines(source_lines):
        output.append(format_source_marker([line["uid"] for line in group]))
        output.append(f"{group[0]['speaker']}: {join_source_text(group)}")
        output.append("")
    while output and output[-1] == "":
        output.pop()
    return output


def group_source_lines(source_lines: Sequence[Dict[str, str]]) -> List[List[Dict[str, str]]]:
    groups: List[List[Dict[str, str]]] = []
    current: List[Dict[str, str]] = []
    for line in source_lines:
        if (
            current
            and (
                line["speaker"] != current[-1]["speaker"]
                or len(current) >= MAX_DRAFT_GROUP_LINES
            )
        ):
            groups.append(current)
            current = []
        current.append(line)
    if current:
        groups.append(current)
    return groups


def format_source_marker(uids: Sequence[str]) -> str:
    if not uids:
        raise ValueError("Cannot format an empty UID marker.")
    if len(uids) == 1:
        return f"%% {uids[0]} %%"
    return f"%% {uids[0]}-{uids[-1]} %%"


def join_source_text(lines: Sequence[Dict[str, str]]) -> str:
    return " ".join(line["text"] for line in lines if line["text"]).strip()


def sync_file_headings(plan: Sequence[Dict[str, Any]]) -> None:
    for item in plan:
        output_path: Path = item["outputPath"]
        if not output_path.exists():
            continue
        desired_heading = transcript_heading(item)
        lines = output_path.read_text(encoding="utf-8").splitlines()
        if lines and lines[0].startswith("# "):
            lines[0] = desired_heading
            if len(lines) == 1 or lines[1].strip():
                lines.insert(1, "")
        else:
            lines = [desired_heading, ""] + lines
        output_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_missing_summary_file(
    summary_path: Path,
    plan: Sequence[Dict[str, Any]],
    *,
    transcript_path: Path,
    recap_path: Path,
) -> None:
    if summary_path.exists():
        return
    summary_path.write_text(
        render_summary_file(plan, transcript_path=transcript_path, recap_path=recap_path),
        encoding="utf-8",
    )


def render_summary_file(plan: Sequence[Dict[str, Any]], *, transcript_path: Path, recap_path: Path) -> str:
    lines = [
        "# Transcript Highlights",
        "",
        f"- Session Recap: {relative_markdown_path(recap_path, plan[0]['outputPath'].parent) if plan else recap_path}",
        f"- Source Transcript: {relative_markdown_path(transcript_path, plan[0]['outputPath'].parent) if plan else transcript_path}",
        "",
        HIGHLIGHTS_HEADING,
        "",
    ]
    for item in plan:
        for entry in item["sourceEntries"]:
            lines.append(f"### {entry['beatId']} | {entry['title']}")
            lines.append("")
            lines.append(f"- Recap Block: {item['blockId']}")
            lines.append(f"- Transcript: {item['outputPath'].name}")
            lines.append(f"- Source Range: {entry['startUid']} -> {entry['endUid']}")
            if entry.get("shortSummary"):
                lines.append(f"- Context: {entry['shortSummary']}")
            lines.append("- Pull Quotes:")
            lines.append(f"  - ID: quote-{safe_slug(entry['beatId'])}-001")
            lines.append("    - Quote: \"TODO: Quote text.\"")
            lines.append("    - Speaker: TODO")
            lines.append("    - Source Lines: TODO")
            lines.append("")
    lines.extend(
        [
            MONOLOGUES_HEADING,
            "",
            "- ID: audio-001",
            "  - Optional: If no audio-worthy monologues stand out, replace this block with `None identified.`",
            "  - Source Lines: TODO",
            "  - Speaker: TODO",
            "  - Summary: TODO",
            "  - Why Called Out: TODO",
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def patch_session_recap(recap_path: Path, plan: Sequence[Dict[str, Any]]) -> None:
    path_by_block = {item["blockId"]: item["relativePath"] for item in plan}
    source_seen = {item["blockId"]: False for item in plan}
    lines = recap_path.read_text(encoding="utf-8").splitlines()
    patched: List[str] = []
    in_recap = False
    current_block_id: Optional[str] = None

    for line in lines:
        if line.startswith("## "):
            in_recap = line == "## Recap"
            current_block_id = None
        if in_recap:
            heading_match = RECAP_HEADING_RE.match(line)
            if heading_match:
                current_block_id = heading_match.group("block_id")
            if current_block_id in path_by_block and line.startswith(f"- {PATH_KEY}:"):
                continue
            patched.append(line)
            if current_block_id in path_by_block and line.startswith("- Source Range:"):
                patched.append(f"- {PATH_KEY}: {path_by_block[current_block_id]}")
                source_seen[current_block_id] = True
            continue
        patched.append(line)

    missing_source = [block_id for block_id, seen in source_seen.items() if not seen]
    if missing_source:
        raise SystemExit("Could not find Source Range in recap blocks: " + ", ".join(missing_source))

    updated = "\n".join(patched).rstrip() + "\n"
    if updated != recap_path.read_text(encoding="utf-8"):
        recap_path.write_text(updated, encoding="utf-8")


def sync_recap_review_media(recap_path: Path, summary_path: Path) -> None:
    if not summary_path.exists():
        return
    summary_text = summary_path.read_text(encoding="utf-8")
    pull_quotes = parse_summary_entries(level2_section_after_heading(summary_text, HIGHLIGHTS_HEADING))
    audio_candidates = parse_summary_entries(level2_section_after_heading(summary_text, MONOLOGUES_HEADING))

    recap_text = recap_path.read_text(encoding="utf-8")
    updated = replace_level2_section(
        recap_text,
        RECAP_PULL_QUOTES_HEADING,
        render_recap_pull_quotes_section(pull_quotes),
    )
    updated = replace_level2_section(
        updated,
        RECAP_AUDIO_HEADING,
        render_recap_audio_section(audio_candidates),
    )
    if updated != recap_text:
        recap_path.write_text(updated, encoding="utf-8")


def parse_summary_entries(section_text: str) -> List[Dict[str, str]]:
    entries: List[Dict[str, str]] = []
    current: Optional[Dict[str, str]] = None
    for raw in section_text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped in {"None identified.", "- None identified."}:
            continue
        id_match = HIGHLIGHT_ID_RE.match(raw)
        if id_match:
            current = {"ID": id_match.group("id")}
            entries.append(current)
            continue
        if current is None or not stripped.startswith("- ") or ":" not in stripped:
            continue
        key, value = stripped[2:].split(":", 1)
        current[key.strip()] = value.strip()
    return entries


def level2_section_after_heading(text: str, heading: str) -> str:
    lines = text.splitlines()
    capture = False
    captured: List[str] = []
    for raw in lines:
        if raw.strip() == heading:
            capture = True
            continue
        if capture and raw.startswith("## "):
            break
        if capture:
            captured.append(raw)
    return "\n".join(captured)


def render_recap_pull_quotes_section(entries: Sequence[Dict[str, str]]) -> str:
    rendered_entries = []
    for entry in entries:
        quote = entry.get("Quote", "").strip()
        speaker = entry.get("Speaker", "").strip()
        source_lines = entry.get("Source Lines", "").strip()
        if not entry.get("ID") or not quote or not speaker or not source_lines:
            continue
        rendered_entries.extend(
            [
                f"- ID: {entry['ID']}",
                f"  - Quote: {quote}",
                f"  - Speaker: {speaker}",
                f"  - Source Lines: {source_lines}",
                "",
            ]
        )
    return "\n".join(rendered_entries).rstrip()


def render_recap_audio_section(entries: Sequence[Dict[str, str]]) -> str:
    rendered_entries = []
    for entry in entries:
        entry_id = entry.get("ID", "").strip()
        speaker = entry.get("Speaker", "").strip()
        source_lines = entry.get("Source Lines", "").strip()
        if not entry_id or not speaker or not source_lines:
            continue
        title = entry.get("Title", "").strip() or entry.get("Summary", "").strip() or entry_id
        output = entry.get("Output", "").strip() or f"{entry_id}.m4a"
        rendered_entries.extend(
            [
                f"- ID: {entry_id}",
                f"  - Title: {title}",
                f"  - Speaker: {speaker}",
                f"  - Source Lines: {source_lines}",
                f"  - Output: {output}",
            ]
        )
        for optional_key in ("Summary", "Why Called Out"):
            value = entry.get(optional_key, "").strip()
            if value and value != title:
                rendered_entries.append(f"  - {optional_key}: {value}")
        rendered_entries.append("")
    return "\n".join(rendered_entries).rstrip()


def replace_level2_section(text: str, heading: str, body: str) -> str:
    lines = text.splitlines()
    start: Optional[int] = None
    end = len(lines)
    for index, raw in enumerate(lines):
        if raw.strip() == heading:
            start = index
            continue
        if start is not None and index > start and raw.startswith("## "):
            end = index
            break

    if not body.strip():
        if start is None:
            return text
        new_lines = list(lines[:start])
        while new_lines and not new_lines[-1].strip():
            new_lines.pop()
        tail = list(lines[end:])
        while tail and not tail[0].strip():
            tail.pop(0)
        if tail:
            new_lines.extend(["", *tail])
        return "\n".join(new_lines).rstrip() + "\n"

    section_lines = [heading, "", *body.splitlines()]
    if start is None:
        base = text.rstrip()
        separator = "\n\n" if base else ""
        section_text = "\n".join(section_lines)
        return f"{base}{separator}{section_text}\n"

    new_lines = [*lines[:start], *section_lines]
    tail = list(lines[end:])
    while tail and not tail[0].strip():
        tail.pop(0)
    if tail:
        new_lines.extend(["", *tail])
    return "\n".join(new_lines).rstrip() + "\n"


def validate_outputs(recap_path: Path, plan: Sequence[Dict[str, Any]], *, summary_path: Path) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []
    recap_text = recap_path.read_text(encoding="utf-8")

    for item in plan:
        output_path: Path = item["outputPath"]
        expected_line = f"- {PATH_KEY}: {item['relativePath']}"
        source_line = f"- Source Range: {item['startUid']} -> {item['endUid']}"
        if expected_line not in recap_text:
            errors.append(f"{item['blockId']} is missing recap link: {expected_line}")
        if source_line not in recap_text:
            errors.append(f"{item['blockId']} is missing recap source range: {source_line}")
        if not output_path.exists():
            errors.append(f"{item['blockId']} transcript file does not exist: {output_path}")
            continue
        expected_heading = transcript_heading(item)
        first_line = first_nonempty_line(output_path)
        if first_line != expected_heading:
            errors.append(f"{item['blockId']} transcript heading mismatch: expected {expected_heading!r}, got {first_line!r}")
        try:
            actual_uids, format_errors = read_transcript_marker_uids(output_path, item["expectedUids"])
        except ValueError as exc:
            errors.append(f"{item['blockId']} {exc}")
            continue
        errors.extend(f"{item['blockId']} {error}" for error in format_errors)
        if actual_uids != item["expectedUids"]:
            errors.append(
                f"{item['blockId']} UID coverage mismatch in {output_path}: "
                f"expected {format_uid_span(item['expectedUids'])}, got {format_uid_span(actual_uids)}"
            )
        text = output_path.read_text(encoding="utf-8")
        if "[[" in text or "]]" in text:
            warnings.append(f"{item['blockId']} still contains unresolved [[...]] markers.")
        if "TODO" in text:
            warnings.append(f"{item['blockId']} still contains TODO text.")
    summary_errors, summary_warnings = validate_summary_file(summary_path, plan)
    errors.extend(summary_errors)
    warnings.extend(summary_warnings)
    return errors, warnings


def first_nonempty_line(path: Path) -> str:
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if stripped:
            return stripped
    return ""


def validate_summary_file(summary_path: Path, plan: Sequence[Dict[str, Any]]) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []
    if not summary_path.exists():
        errors.append(f"Transcript highlights summary does not exist: {summary_path}")
        return errors, warnings
    text = summary_path.read_text(encoding="utf-8")
    if HIGHLIGHTS_HEADING not in text:
        errors.append(f"Transcript highlights summary is missing {HIGHLIGHTS_HEADING}.")
    if MONOLOGUES_HEADING not in text:
        errors.append(f"Transcript highlights summary is missing {MONOLOGUES_HEADING}.")
    ids = collect_highlight_ids(text)
    duplicate_ids = sorted({item for item in ids if ids.count(item) > 1})
    for highlight_id in duplicate_ids:
        errors.append(f"Transcript highlights summary has duplicate ID: {highlight_id}")
    for item in plan:
        for entry in item["sourceEntries"]:
            heading = find_beat_heading(text, entry["beatId"])
            if heading is None:
                errors.append(f"Transcript highlights summary is missing beat heading for {entry['beatId']}.")
            elif not beat_section_has_id(text, heading):
                errors.append(f"Transcript highlights summary beat section is missing a pull quote ID: {heading}")
    audio_text = section_after_heading(text, MONOLOGUES_HEADING)
    if "None identified." not in audio_text and audio_text.strip() and not collect_highlight_ids(audio_text):
        errors.append("Transcript highlights summary audio monologue section is missing candidate IDs.")
    if "TODO" in text:
        warnings.append("Transcript highlights summary still contains TODO text.")
    return errors, warnings


def collect_highlight_ids(text: str) -> List[str]:
    ids: List[str] = []
    for raw in text.splitlines():
        match = HIGHLIGHT_ID_RE.match(raw)
        if match:
            ids.append(match.group("id"))
    return ids


def beat_section_has_id(text: str, heading: str) -> bool:
    section = section_after_heading(text, heading)
    return bool(collect_highlight_ids(section))


def find_beat_heading(text: str, beat_id: str) -> Optional[str]:
    pattern = re.compile(rf"^###\s+{re.escape(beat_id)}(?:\s+\|\s+.+)?$")
    for raw in text.splitlines():
        if pattern.match(raw.strip()):
            return raw.strip()
    return None


def section_after_heading(text: str, heading: str) -> str:
    lines = text.splitlines()
    capture = False
    captured: List[str] = []
    for raw in lines:
        if raw.strip() == heading:
            capture = True
            continue
        if capture and raw.startswith("## "):
            break
        if capture and raw.startswith("### "):
            break
        if capture:
            captured.append(raw)
    return "\n".join(captured)


def read_transcript_marker_uids(path: Path, expected_uids: Sequence[str]) -> Tuple[List[str], List[str]]:
    body_lines = transcript_body_lines(path)
    uid_order = {uid: index for index, uid in enumerate(expected_uids)}
    uids: List[str] = []
    errors: List[str] = []
    pending_marker_line: Optional[int] = None
    pending_marker_has_turn = True

    for line_number, raw in body_lines:
        stripped = raw.strip()
        if not stripped:
            continue
        marker_match = SOURCE_MARKER_RE.match(stripped)
        if marker_match:
            if pending_marker_line is not None and not pending_marker_has_turn:
                errors.append(f"source marker at line {pending_marker_line} is not followed by a speaker turn.")
            try:
                uids.extend(expand_uid_marker(marker_match, uid_order, path, line_number))
            except ValueError as exc:
                errors.append(str(exc))
            pending_marker_line = line_number
            pending_marker_has_turn = False
            continue
        if SOURCE_LINE_RE.match(stripped):
            errors.append(f"visible source header remains at line {line_number}: {stripped}")
            pending_marker_has_turn = True
            continue
        if stripped.startswith("%%") and stripped.endswith("%%"):
            errors.append(f"malformed source marker at line {line_number}: {stripped}")
            continue
        if not SPEAKER_TURN_RE.match(stripped):
            errors.append(f"visible transcript line is not `Speaker: text` format at line {line_number}: {stripped}")
            pending_marker_has_turn = True
            continue
        if pending_marker_line is None or pending_marker_has_turn:
            errors.append(f"speaker turn at line {line_number} is missing an immediately preceding source marker.")
        pending_marker_has_turn = True

    if pending_marker_line is not None and not pending_marker_has_turn:
        errors.append(f"source marker at line {pending_marker_line} is not followed by a speaker turn.")
    return uids, errors


def expand_uid_marker(match: re.Match[str], uid_order: Dict[str, int], path: Path, line_number: int) -> List[str]:
    start_uid = match.group("start")
    end_uid = match.group("end") or start_uid
    if start_uid not in uid_order:
        raise ValueError(f"source marker at {path}:{line_number} references unknown UID {start_uid}.")
    if end_uid not in uid_order:
        raise ValueError(f"source marker at {path}:{line_number} references unknown UID {end_uid}.")
    start_index = uid_order[start_uid]
    end_index = uid_order[end_uid]
    if start_index > end_index:
        raise ValueError(f"source marker at {path}:{line_number} has inverted range {start_uid}-{end_uid}.")
    all_uids = list(uid_order)
    return all_uids[start_index : end_index + 1]


def transcript_body_lines(path: Path) -> List[Tuple[int, str]]:
    raw_lines = path.read_text(encoding="utf-8").splitlines()
    start_index = 0
    for index, line in enumerate(raw_lines):
        if line.strip() == TRANSCRIPT_HEADING:
            start_index = index + 1
            break
    return [(index + 1, line) for index, line in enumerate(raw_lines[start_index:], start=start_index)]


def format_uid_span(uids: Sequence[str]) -> str:
    if not uids:
        return "no UIDs"
    if len(uids) == 1:
        return uids[0]
    return f"{uids[0]} -> {uids[-1]} ({len(uids)} lines)"


if __name__ == "__main__":
    raise SystemExit(main())
