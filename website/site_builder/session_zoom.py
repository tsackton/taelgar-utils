from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .link_index import LinkIndex
from .notes import WIKILINK_RE, MarkdownNote
from .slugging import slugify
from .transform import relative_url


TRANSCRIPT_ASSET_DIR = Path("assets/session-zoom")
TRANSCRIPT_COLLAPSE_LIMIT = 900
SOURCE_LINE_RE = re.compile(r"^(?P<header>\[(?P<uid>u\d{4,})(?:\s*\|[^\]]+)?\])\s*(?P<text>.*)$")
LEVELS = ("short", "intermediate", "long", "transcript")


@dataclass(frozen=True)
class SessionArtifactRecord:
    session_key: str
    session_path: Path
    recap_path: Path
    beats_path: Path


@dataclass(frozen=True)
class RecapBlock:
    block_id: str
    title: str
    source_start_uid: str
    source_end_uid: str
    short: str
    intermediate: str
    long: str


@dataclass(frozen=True)
class SourceLine:
    uid: str
    speaker: str
    text: str


@dataclass(frozen=True)
class ZoomRenderResult:
    text: str
    transcript_asset_path: Path | None = None
    transcript_json: str | None = None
    warning: str | None = None


class SessionArtifactIndex:
    def __init__(self, roots: tuple[Path, ...]) -> None:
        self.roots = roots
        self.records: dict[str, SessionArtifactRecord] = {}
        self.duplicates: dict[str, list[SessionArtifactRecord]] = {}
        self._scan()

    def _scan(self) -> None:
        for root in self.roots:
            if not root.exists():
                continue
            for session_path in sorted(root.rglob("*-session.yaml")):
                try:
                    record = build_artifact_record(session_path)
                except (OSError, ValueError, yaml.YAMLError):
                    continue
                if record is None:
                    continue
                existing = self.records.get(record.session_key)
                if existing is None and record.session_key not in self.duplicates:
                    self.records[record.session_key] = record
                    continue
                if record.session_key not in self.duplicates:
                    self.duplicates[record.session_key] = [self.records.pop(record.session_key)]
                self.duplicates[record.session_key].append(record)

    def resolve(self, session_key: str) -> tuple[SessionArtifactRecord | None, str | None]:
        if session_key in self.duplicates:
            paths = ", ".join(str(record.session_path) for record in self.duplicates[session_key])
            return None, f"Multiple session artifacts match sessionKey {session_key!r}: {paths}"
        record = self.records.get(session_key)
        if record is None:
            return None, f"No session artifacts found for sessionKey {session_key!r}."
        return record, None


def build_artifact_record(session_path: Path) -> SessionArtifactRecord | None:
    payload = read_yaml_mapping(session_path)
    campaign = normalize_optional_string(payload.get("campaign"))
    session_number = normalize_optional_string(payload.get("sessionNumber"))
    scope = normalize_optional_string(payload.get("scope")) or "session"
    if campaign is None or session_number is None:
        return None
    session_key = f"{slugify(campaign)}-{slugify(scope)}-{slugify(session_number)}"
    prefix = session_path.name[: -len("-session.yaml")]
    return SessionArtifactRecord(
        session_key=session_key,
        session_path=session_path,
        recap_path=session_path.with_name(f"{prefix}-session-recap.md"),
        beats_path=session_path.with_name(f"{prefix}-beats.json"),
    )


def is_zoomable_session_note(note: MarkdownNote | None) -> bool:
    return bool(note and normalize_optional_string(note.metadata.get("websiteSessionView")) == "zoomable")


def render_zoomable_session_note(
    *,
    note: MarkdownNote,
    transformed_text: str,
    page_path: Path,
    config: Any,
    index: LinkIndex,
    artifact_index: SessionArtifactIndex,
) -> ZoomRenderResult:
    session_key = normalize_optional_string(note.metadata.get("sessionKey"))
    if session_key is None:
        return ZoomRenderResult(
            text=transformed_text,
            warning="Zoomable session note is missing required frontmatter field 'sessionKey'.",
        )
    if not artifact_index.roots:
        return ZoomRenderResult(
            text=transformed_text,
            warning="Zoomable session note requires website.json session_artifact_roots.",
        )

    record, warning = artifact_index.resolve(session_key)
    if warning is not None or record is None:
        return ZoomRenderResult(text=transformed_text, warning=warning)

    try:
        recap_blocks = parse_recap_blocks(record.recap_path)
        transcript_path = transcript_path_from_beats(record.beats_path)
        source_lines = read_source_lines(transcript_path)
        transcript_payload = build_transcript_payload(session_key, recap_blocks, source_lines)
        link_map = build_local_link_map(extract_heading_section(note.clean_text, "Narrative"), page_path, index)
        transcript_asset_path = TRANSCRIPT_ASSET_DIR / f"{session_key}.json"
        zoom_html = render_zoom_html(
            session_key=session_key,
            recap_blocks=recap_blocks,
            transcript_asset_path=transcript_asset_path,
            base_path=config.base_path,
            link_map=link_map,
        )
        updated = replace_narrative_section(transformed_text, zoom_html)
    except (OSError, ValueError, json.JSONDecodeError, yaml.YAMLError) as error:
        return ZoomRenderResult(text=transformed_text, warning=f"Unable to build zoomable session view: {error}")

    if updated is None:
        return ZoomRenderResult(
            text=transformed_text,
            warning="Zoomable session note does not contain a '## Narrative' section to replace.",
        )
    return ZoomRenderResult(
        text=updated,
        transcript_asset_path=transcript_asset_path,
        transcript_json=json.dumps(transcript_payload, indent=2, ensure_ascii=False) + "\n",
    )


def parse_recap_blocks(path: Path) -> list[RecapBlock]:
    if not path.exists():
        raise ValueError(f"session recap not found: {path}")
    lines = strip_frontmatter(path.read_text(encoding="utf-8")).splitlines()
    recap_lines = extract_level2_section(lines, "Recap")
    if recap_lines is None:
        raise ValueError(f"session recap is missing ## Recap: {path}")

    blocks: list[RecapBlock] = []
    for heading, block_lines in split_level3_blocks(recap_lines):
        match = re.match(r"^(?P<block_id>recap-\d+)\s+\|\s+(?P<title>.+)$", heading)
        if not match:
            raise ValueError(f"malformed recap block heading in {path}: {heading}")
        metadata = parse_keyed_bullets(block_lines)
        start_uid, end_uid = parse_source_range(metadata.get("Source Range"), match.group("block_id"))
        blocks.append(
            RecapBlock(
                block_id=match.group("block_id"),
                title=match.group("title").strip(),
                source_start_uid=start_uid,
                source_end_uid=end_uid,
                short=parse_required_subsection(block_lines, "#### Short", match.group("block_id")),
                intermediate=parse_required_subsection(block_lines, "#### Intermediate", match.group("block_id")),
                long=parse_required_subsection(block_lines, "#### Long", match.group("block_id")),
            )
        )
    if not blocks:
        raise ValueError(f"session recap has no recap blocks: {path}")
    return blocks


def transcript_path_from_beats(path: Path) -> Path:
    if not path.exists():
        raise ValueError(f"beats JSON not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_path = normalize_optional_string(payload.get("sourceTranscriptPath"))
    if raw_path is None:
        raise ValueError(f"beats JSON is missing sourceTranscriptPath: {path}")
    transcript_path = Path(raw_path)
    if not transcript_path.is_absolute():
        transcript_path = path.parent / transcript_path
    if not transcript_path.exists():
        raise ValueError(f"cleaned source transcript not found: {transcript_path}")
    return transcript_path


def read_source_lines(path: Path) -> list[SourceLine]:
    lines: list[SourceLine] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        match = SOURCE_LINE_RE.match(raw)
        if not match:
            raise ValueError(f"invalid cleaned source line in {path}:{line_number}: {raw}")
        lines.append(
            SourceLine(
                uid=match.group("uid"),
                speaker=speaker_from_header(match.group("header")),
                text=match.group("text").strip(),
            )
        )
    return lines


def build_transcript_payload(
    session_key: str,
    recap_blocks: list[RecapBlock],
    source_lines: list[SourceLine],
) -> dict[str, Any]:
    uid_to_index = {line.uid: index for index, line in enumerate(source_lines)}
    payload_blocks = []
    for block in recap_blocks:
        start_index = uid_to_index.get(block.source_start_uid)
        end_index = uid_to_index.get(block.source_end_uid)
        if start_index is None or end_index is None:
            raise ValueError(f"{block.block_id} references missing transcript uid.")
        if start_index > end_index:
            raise ValueError(f"{block.block_id} has an inverted transcript source range.")
        payload_blocks.append(
            {
                "blockId": block.block_id,
                "title": block.title,
                "lines": collapse_transcript_lines(source_lines[start_index : end_index + 1]),
            }
        )
    return {"schemaVersion": "1.0", "sessionKey": session_key, "blocks": payload_blocks}


def collapse_transcript_lines(lines: list[SourceLine]) -> list[dict[str, str]]:
    collapsed: list[dict[str, str]] = []
    for line in lines:
        text = line.text.strip()
        if not text:
            continue
        if collapsed and collapsed[-1]["speaker"] == line.speaker:
            combined = f"{collapsed[-1]['text']} {text}".strip()
            if len(combined) <= TRANSCRIPT_COLLAPSE_LIMIT:
                collapsed[-1]["text"] = combined
                continue
        collapsed.append({"speaker": line.speaker, "text": text})
    return collapsed


def render_zoom_html(
    *,
    session_key: str,
    recap_blocks: list[RecapBlock],
    transcript_asset_path: Path,
    base_path: str,
    link_map: dict[str, str],
) -> str:
    transcript_src = base_path + transcript_asset_path.as_posix()
    lines = [
        (
            f'<div class="taelgar-session-zoom" data-taelgar-session-zoom '
            f'data-session-key="{html.escape(session_key, quote=True)}" '
            f'data-transcript-src="{html.escape(transcript_src, quote=True)}" data-zoom="short">'
        ),
        '  <div class="taelgar-session-zoom__controls" aria-label="Session summary zoom level">',
        '    <div class="taelgar-session-zoom__button-group" role="group" aria-label="Zoom level">',
    ]
    for level in LEVELS:
        label = level.title() if level != "intermediate" else "Intermediate"
        lines.append(
            f'      <button type="button" data-set-session-zoom="{level}" '
            f'aria-pressed="{"true" if level == "short" else "false"}">{label}</button>'
        )
    lines.extend(
        [
            "    </div>",
            '    <button type="button" class="taelgar-session-zoom__cycle">Next: Intermediate</button>',
            "  </div>",
            '  <nav class="taelgar-session-zoom__nav" aria-label="Session beat navigation">',
        ]
    )
    for index, block in enumerate(recap_blocks, start=1):
        beat_id = display_beat_id(index)
        lines.append(
            f'    <a href="#zoom-{html.escape(block.block_id, quote=True)}">'
            f"<span>{beat_id}</span>{html.escape(block.title)}</a>"
        )
    lines.extend(["  </nav>", '  <div class="taelgar-session-zoom__beats">'])
    for index, block in enumerate(recap_blocks, start=1):
        beat_id = display_beat_id(index)
        lines.extend(
            [
                f'    <section class="taelgar-session-zoom__beat" id="zoom-{html.escape(block.block_id, quote=True)}">',
                '      <div class="taelgar-session-zoom__heading">',
                f'        <span class="taelgar-session-zoom__beat-id">{beat_id}</span>',
                f"        <h3>{html.escape(block.title)}</h3>",
                "      </div>",
                render_level("short", block.short, link_map),
                render_level("intermediate", block.intermediate, link_map),
                render_level("long", block.long, link_map),
                (
                    f'      <div class="taelgar-session-zoom__level taelgar-session-zoom__transcript" '
                    f'data-zoom-level="transcript" data-transcript-block="{html.escape(block.block_id, quote=True)}">'
                    '<p class="taelgar-session-zoom__loading">Transcript loads when selected.</p></div>'
                ),
                "    </section>",
            ]
        )
    lines.extend(["  </div>", "</div>"])
    return "\n".join(lines)


def render_level(level: str, text: str, link_map: dict[str, str]) -> str:
    paragraphs = [
        f"<p>{render_linked_text(block.strip(), link_map)}</p>"
        for block in re.split(r"\n\s*\n", text)
        if block.strip()
    ]
    content = "\n".join(paragraphs) if paragraphs else "<p></p>"
    return f'      <div class="taelgar-session-zoom__level" data-zoom-level="{level}">{content}</div>'


def build_local_link_map(narrative_text: str, page_path: Path, index: LinkIndex) -> dict[str, str]:
    links: dict[str, str] = {}
    ambiguous: set[str] = set()
    for match in re.finditer(WIKILINK_RE, narrative_text):
        target = (match.group(1) or "").strip()
        if not target:
            continue
        phrases = [match.group(3).strip()] if match.group(3) else []
        clean_target = target.split("#", 1)[0].strip()
        if clean_target:
            phrases.append(Path(clean_target).stem)
        resolution = index.resolve(target)
        if resolution.status != "found" or resolution.entry is None or not resolution.entry.is_markdown:
            continue
        href = relative_url(page_path, resolution.entry.target_path)
        for phrase in phrases:
            if not phrase:
                continue
            existing = links.get(phrase)
            if existing is not None and existing != href:
                ambiguous.add(phrase)
                links.pop(phrase, None)
                continue
            if phrase not in ambiguous:
                links[phrase] = href
    return links


def render_linked_text(text: str, link_map: dict[str, str]) -> str:
    placeholders: dict[str, str] = {}

    def add_placeholder(value: str) -> str:
        token = f"@@TAELGAR_SESSION_LINK_{len(placeholders)}@@"
        placeholders[token] = value
        return token

    def wikilink_replacement(match: re.Match[str]) -> str:
        target = (match.group(1) or "").strip()
        label = (match.group(3) or Path(target.split("#", 1)[0]).stem).strip()
        href = link_map.get(label) or link_map.get(Path(target.split("#", 1)[0]).stem)
        if href is None:
            return label
        return add_placeholder(anchor_html(href, label))

    working = re.sub(WIKILINK_RE, wikilink_replacement, text)
    for phrase, href in sorted(link_map.items(), key=lambda item: len(item[0]), reverse=True):
        pattern = re.compile(rf"(?<![\w/-]){re.escape(phrase)}(?![\w/-])")

        def phrase_replacement(match: re.Match[str], href: str = href) -> str:
            return add_placeholder(anchor_html(href, match.group(0)))

        working = pattern.sub(phrase_replacement, working)

    escaped = html.escape(working)
    for token, value in placeholders.items():
        escaped = escaped.replace(token, value)
    return escaped


def anchor_html(href: str, label: str) -> str:
    return f'<a href="{html.escape(href, quote=True)}">{html.escape(label)}</a>'


def replace_narrative_section(text: str, replacement: str) -> str | None:
    match = re.search(r"(?m)^##\s+Narrative\s*$", text)
    if match is None:
        return None
    body_start = match.end()
    next_match = re.search(r"(?m)^##\s+", text[body_start:])
    body_end = body_start + next_match.start() if next_match else len(text)
    return text[:body_start] + "\n\n" + replacement.strip() + "\n\n" + text[body_end:].lstrip("\n")


def extract_heading_section(text: str, heading: str) -> str:
    match = re.search(rf"(?m)^##\s+{re.escape(heading)}\s*$", text)
    if match is None:
        return ""
    body_start = match.end()
    next_match = re.search(r"(?m)^##\s+", text[body_start:])
    body_end = body_start + next_match.start() if next_match else len(text)
    return text[body_start:body_end].strip()


def read_yaml_mapping(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Expected YAML mapping in {path}")
    return payload


def strip_frontmatter(text: str) -> str:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return text
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "\n".join(lines[index + 1 :])
    return text


def extract_level2_section(lines: list[str], title: str) -> list[str] | None:
    target = f"## {title}"
    headings: list[tuple[str, int]] = [(line.strip(), index) for index, line in enumerate(lines) if line.startswith("## ")]
    for position, (heading, start) in enumerate(headings):
        if heading != target:
            continue
        end = headings[position + 1][1] if position + 1 < len(headings) else len(lines)
        return lines[start + 1 : end]
    return None


def split_level3_blocks(lines: list[str]) -> list[tuple[str, list[str]]]:
    headings: list[tuple[str, int]] = [(line.strip()[4:], index) for index, line in enumerate(lines) if line.startswith("### ")]
    blocks: list[tuple[str, list[str]]] = []
    for position, (heading, start) in enumerate(headings):
        end = headings[position + 1][1] if position + 1 < len(headings) else len(lines)
        blocks.append((heading, lines[start + 1 : end]))
    return blocks


def parse_keyed_bullets(lines: list[str]) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("- ") or ":" not in stripped:
            continue
        key, value = stripped[2:].split(":", 1)
        data[key.strip()] = value.strip()
    return data


def parse_required_subsection(lines: list[str], heading: str, block_id: str) -> str:
    text = parse_subsection(lines, heading)
    if text is None or not text.strip():
        raise ValueError(f"{block_id} is missing {heading}")
    return text.strip()


def parse_subsection(lines: list[str], heading: str) -> str | None:
    start_index = None
    for index, line in enumerate(lines):
        if line.strip() == heading:
            start_index = index + 1
            break
    if start_index is None:
        return None
    end_index = len(lines)
    for index in range(start_index, len(lines)):
        if lines[index].startswith("#### ") or lines[index].startswith("### "):
            end_index = index
            break
    return "\n".join(lines[start_index:end_index]).strip()


def parse_source_range(value: str | None, block_id: str) -> tuple[str, str]:
    if value is None:
        raise ValueError(f"{block_id} is missing Source Range")
    match = re.search(r"\b(?P<start>u\d{4,})\s*(?:->|to|-)\s*(?P<end>u\d{4,})\b", value)
    if not match:
        raise ValueError(f"{block_id} has invalid Source Range: {value}")
    return match.group("start"), match.group("end")


def speaker_from_header(header: str) -> str:
    inner = header.strip()[1:-1]
    parts = [part.strip() for part in inner.split("|")]
    if len(parts) >= 3 and parts[-1]:
        return parts[-1]
    return "Source"


def display_beat_id(index: int) -> str:
    return f"B{index:02d}"


def normalize_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
