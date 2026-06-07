from __future__ import annotations

import hashlib
import html
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from .asset_policy import (
    TileBounds,
    image_tile_bounds,
    is_tile_map_asset,
    parse_tile_bounds,
    tile_base_path,
    tile_extension,
    tile_native_max_zoom,
)
from .link_index import LinkIndex
from .notes import ASSET_SUFFIXES, AUDIO_SUFFIXES, IMAGE_SUFFIXES, WIKILINK_RE, MarkdownNote, title_case
from .scanner import SourceEntry


@dataclass
class LinkIssue:
    source: str
    target: str
    message: str


@dataclass
class TransformResult:
    text: str
    linked_assets: set[str] = field(default_factory=set)
    tile_assets: dict[str, "TileRequest"] = field(default_factory=dict)
    unresolved_links: list[LinkIssue] = field(default_factory=list)
    ambiguous_links: list[LinkIssue] = field(default_factory=list)

    def extend(self, other: "TransformResult") -> None:
        self.linked_assets.update(other.linked_assets)
        self.tile_assets.update(other.tile_assets)
        self.unresolved_links.extend(other.unresolved_links)
        self.ambiguous_links.extend(other.ambiguous_links)


@dataclass(frozen=True)
class TileRequest:
    bounds: object


CALLOUT_BLOCK_RE = re.compile(r'^ ?(?P<markers>>+) *\[!(?P<type>[^\]]*)\](?P<fold>[-+]?)(?P<title>.*)?$')
CALLOUT_CONTENT_RE = re.compile(r"^ ?(?P<markers>>+) ?")
CALLOUT_ALIASES = {
    "summary": "abstract",
    "tldr": "abstract",
    "hint": "tip",
    "important": "tip",
    "check": "success",
    "done": "success",
    "help": "question",
    "faq": "question",
    "caution": "warning",
    "attention": "warning",
    "fail": "failure",
    "missing": "failure",
    "error": "danger",
    "cite": "quote",
}
AUDIO_SUFFIX_PATTERN = "|".join(re.escape(suffix.lstrip(".")) for suffix in sorted(AUDIO_SUFFIXES))


class NoteTransformer:
    def __init__(self, config: Any, index: LinkIndex) -> None:
        self.config = config
        self.index = index
        self.template_cache: dict[Path, str] = {}

    def transform_entry(self, entry: SourceEntry) -> TransformResult:
        if entry.note is None:
            raise ValueError(f"{entry.relative_path} is not a markdown note")
        return self.transform_note(entry.note, entry.target_path, entry.relative_path.as_posix())

    def transform_note(self, note: MarkdownNote, page_path: Path, source_label: str) -> TransformResult:
        result = TransformResult(text=note.clean_text)
        if self.config.clean_code_blocks and self.config.codeblock_template_dir:
            result.text = self._clean_code_blocks(result.text, page_path, source_label, result)
        result.text = self._replace_audio_tags(result.text, source_label, result)
        result.text = re.sub(WIKILINK_RE, lambda match: self._replace_wikilink(match, page_path, source_label, result), result.text)
        result.text = self._replace_markdown_audio_links(result.text, source_label, result)
        result.text = self._rewrite_and_collect_direct_asset_links(result.text, source_label, result)
        result.text = convert_obsidian_callouts(result.text)
        result.text = normalize_loose_lists(result.text)
        return result

    def _clean_code_blocks(self, text: str, page_path: Path, source_label: str, result: TransformResult) -> str:
        def replace(match: re.Match[str]) -> str:
            codeblock = match.group(2) or match.group(3)
            if not codeblock:
                return match.group(0)
            codeblock_type, _, codeblock_content = codeblock.partition("\n")
            codeblock_type = codeblock_type.strip()
            if codeblock_type == "mermaid":
                return match.group(0)
            template_path = self.config.codeblock_template_dir / f"{codeblock_type}.html"
            if not template_path.is_file():
                return ""
            template_text = self.template_cache.get(template_path)
            if template_text is None:
                template_text = template_path.read_text(encoding="utf-8")
                self.template_cache[template_path] = template_text
            template_content = yaml.safe_load(codeblock_content) or {}
            if codeblock_type == "leaflet":
                template_content["height"] = template_content.get("height", "600px")
                template_content["mapConfigJson"] = self._missing_leaflet_config(template_content)
            if codeblock_type == "leaflet" and "image" in template_content:
                image_name = str(template_content["image"][0]).replace("[", "").replace("]", "").replace("'", "")
                image_resolution = self.index.resolve(image_name)
                if image_resolution.status == "found" and image_resolution.entry:
                    image_entry = image_resolution.entry
                    bounds = parse_tile_bounds(template_content.get("bounds"))
                    if bounds:
                        if is_tile_map_asset(image_entry.relative_path, self.config):
                            result.tile_assets[image_entry.id] = TileRequest(bounds=bounds)
                        else:
                            result.linked_assets.add(image_entry.id)
                        template_content["mapConfigJson"] = self._leaflet_config_json(
                            template_content,
                            image_entry,
                            bounds,
                            tiled=is_tile_map_asset(image_entry.relative_path, self.config),
                        )
                elif image_resolution.status == "ambiguous":
                    result.ambiguous_links.append(LinkIssue(source_label, image_name, "Ambiguous leaflet image"))
                else:
                    result.unresolved_links.append(LinkIssue(source_label, image_name, "Missing leaflet image"))
            return template_text.format(**template_content)

        return re.sub(r"(```([^`]+)```|~~~([^~]+)~~~|`([^`]*)`)", replace, text, flags=re.DOTALL)

    def _replace_audio_tags(self, text: str, source_label: str, result: TransformResult) -> str:
        def replace(match: re.Match[str]) -> str:
            file_name = match.group("target")
            resolution = self.index.resolve(file_name)
            if resolution.status == "found" and resolution.entry:
                result.linked_assets.add(resolution.entry.id)
                return self._audio_html(resolution.entry.target_path)
            if resolution.status == "ambiguous":
                result.ambiguous_links.append(LinkIssue(source_label, file_name, "Ambiguous audio link"))
            else:
                result.unresolved_links.append(LinkIssue(source_label, file_name, "Missing audio link"))
            return match.group(0)

        return re.sub(
            rf"!\[\[(?P<target>[^\]]+\.(?:{AUDIO_SUFFIX_PATTERN}))\]\]",
            replace,
            text,
            flags=re.IGNORECASE,
        )

    def _replace_markdown_audio_links(self, text: str, source_label: str, result: TransformResult) -> str:
        pattern = re.compile(
            rf"!\[[^\]]*\]\(\s*<?(?P<target>[^<>)\s]+\.(?:{AUDIO_SUFFIX_PATTERN}))>?\s*\)",
            re.IGNORECASE,
        )

        def replace(match: re.Match[str]) -> str:
            raw_target = match.group("target")
            resolution = self.index.resolve(self._clean_direct_target(raw_target))
            if resolution.status == "found" and resolution.entry:
                result.linked_assets.add(resolution.entry.id)
                return self._audio_html(resolution.entry.target_path)
            if resolution.status == "ambiguous":
                result.ambiguous_links.append(LinkIssue(source_label, raw_target, "Ambiguous audio link"))
            else:
                result.unresolved_links.append(LinkIssue(source_label, raw_target, "Missing audio link"))
            return match.group(0)

        return pattern.sub(replace, text)

    def _audio_html(self, target_path: Path) -> str:
        return (
            "<audio controls>\n"
            f'    <source src="{self.absolute_url(target_path)}" type="{audio_mime_type(target_path)}">\n'
            "</audio>"
        )

    def _replace_wikilink(
        self,
        match: re.Match[str],
        page_path: Path,
        source_label: str,
        result: TransformResult,
    ) -> str:
        whole_link = match.group(0)
        filename = match.group(1).strip() if match.group(1) else ""
        title = match.group(2).strip() if match.group(2) else ""
        alias = match.group(3) if match.group(3) else ""
        width = match.group(4) if match.group(4) else ""
        height = match.group(5) if match.group(5) else ""
        if not filename:
            rel_link_url = "#" + gfm_anchor(title)
            return markdown_link(alias or title, rel_link_url)
        if filename.startswith(("http://", "https://", "mailto:")):
            return markdown_link(alias or filename, filename)

        resolution = self.index.resolve(filename)
        if resolution.status == "ambiguous":
            candidates = ", ".join(entry.relative_path.as_posix() for entry in resolution.candidates)
            result.ambiguous_links.append(LinkIssue(source_label, filename, f"Ambiguous link candidates: {candidates}"))
            return alias or filename
        if resolution.status != "found" or resolution.entry is None:
            result.unresolved_links.append(LinkIssue(source_label, filename, "Missing wikilink target"))
            return alias or filename

        target = resolution.entry
        rel_link_url = self.absolute_url(target.target_path) if target.is_asset else relative_url(page_path, target.target_path)
        if title:
            rel_link_url += "#" + gfm_anchor(title)

        image_link = target.target_path.suffix.lower() in IMAGE_SUFFIXES or alias in {"right", "left"} or bool(width or height)
        if image_link:
            if is_tile_map_asset(target.relative_path, self.config):
                bounds = image_tile_bounds(target.source_path)
                if bounds:
                    result.tile_assets[target.id] = TileRequest(bounds=bounds)
                    return self._render_inline_tile_map(target, bounds)
            image_alias = title_case(Path(filename).stem.replace("-", " ").replace("_", " "))
            params = []
            if alias in {"right", "left"}:
                params.append(f'align="{alias}"')
            if width:
                params.append(f'width="{width}"')
            if height:
                params.append(f'height="{height}"')
            attrs = "{" + "; ".join(params) + "}" if params else ""
            if target.is_asset:
                result.linked_assets.add(target.id)
            return f"[{image_alias}]({rel_link_url}){attrs}"
        if target.is_asset:
            result.linked_assets.add(target.id)
        return markdown_link(alias or filename + title, rel_link_url)

    def _rewrite_and_collect_direct_asset_links(self, text: str, source_label: str, result: TransformResult) -> str:
        suffix_pattern = "|".join(re.escape(suffix.lstrip(".")) for suffix in sorted(ASSET_SUFFIXES))
        pattern = re.compile(rf"(?P<prefix>[\(\"=])(?P<target>[^\"()\s]+\.(?:{suffix_pattern}))(?P<suffix>[\)\"])", re.IGNORECASE)

        def replace(match: re.Match[str]) -> str:
            raw_target = match.group("target")
            if ":" in raw_target and not raw_target.startswith(("http://", "https://")):
                return match.group(0)
            if raw_target.startswith(("http://", "https://", "data:")):
                return match.group(0)
            clean_target = raw_target
            if clean_target.startswith(self.config.base_path):
                clean_target = clean_target[len(self.config.base_path) :]
            clean_target = clean_target.lstrip("/")
            resolution = self.index.resolve(clean_target)
            if resolution.status == "found" and resolution.entry:
                result.linked_assets.add(resolution.entry.id)
                return f"{match.group('prefix')}{self.absolute_url(resolution.entry.target_path)}{match.group('suffix')}"
            elif resolution.status == "ambiguous":
                result.ambiguous_links.append(LinkIssue(source_label, raw_target, "Ambiguous direct asset link"))
            else:
                result.unresolved_links.append(LinkIssue(source_label, raw_target, "Missing direct asset link"))
            return match.group(0)

        return pattern.sub(replace, text)

    def absolute_url(self, target_path: Path) -> str:
        return self.config.base_path + target_path.as_posix()

    def _clean_direct_target(self, raw_target: str) -> str:
        clean_target = raw_target
        if clean_target.startswith(self.config.base_path):
            clean_target = clean_target[len(self.config.base_path) :]
        return clean_target.lstrip("/")

    def _missing_leaflet_config(self, template_content: dict[str, Any]) -> str:
        config = {
            "id": str(template_content.get("id", "leaflet-map")),
            "bounds": template_content.get("bounds") or [[0, 0], [1, 1]],
        }
        return html.escape(json.dumps(config, separators=(",", ":")), quote=True)

    def _leaflet_config_json(
        self,
        template_content: dict[str, Any],
        target: SourceEntry,
        bounds: TileBounds,
        *,
        tiled: bool,
    ) -> str:
        config = self._leaflet_config(
            str(template_content.get("id", "leaflet-map")),
            target,
            bounds,
            tiled=tiled,
            min_zoom=number_value(template_content.get("minZoom"), -3),
            max_zoom=number_value(template_content.get("maxZoom"), 2),
            default_zoom=number_value(template_content.get("defaultZoom"), 0),
            lat=number_value(template_content.get("lat"), None),
            long=number_value(template_content.get("long"), None),
            fit_bounds=False,
        )
        return html.escape(json.dumps(config, separators=(",", ":")), quote=True)

    def _leaflet_config(
        self,
        map_id: str,
        target: SourceEntry,
        bounds: TileBounds,
        *,
        tiled: bool,
        min_zoom: float | None,
        max_zoom: float | None,
        default_zoom: float | None,
        lat: float | None,
        long: float | None,
        fit_bounds: bool,
    ) -> dict[str, Any]:
        config: dict[str, Any] = {
            "id": map_id,
            "bounds": [[bounds.y0, bounds.x0], [bounds.y1, bounds.x1]],
            "minZoom": min_zoom if min_zoom is not None else -3,
            "maxZoom": max_zoom if max_zoom is not None else 2,
            "defaultZoom": default_zoom if default_zoom is not None else 0,
            "fitBounds": fit_bounds,
        }
        if lat is not None and long is not None:
            config["center"] = [lat, long]
        if tiled:
            config["tile"] = {
                "baseUrl": self.absolute_url(tile_base_path(target.target_path)),
                "cacheKey": self._tile_cache_key(),
                "extension": tile_extension(self.config),
                "tileSize": self.config.map_tile_size,
                "width": bounds.width,
                "height": bounds.height,
                "minNativeZoom": 0,
                "maxNativeZoom": tile_native_max_zoom(target.source_path, bounds),
            }
        else:
            config["image"] = {"url": self.absolute_url(target.target_path)}
        return config

    def _tile_cache_key(self) -> str:
        payload = json.dumps(self.config.digest_payload(), sort_keys=True, default=str)
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:10]

    def _render_inline_tile_map(self, target: SourceEntry, bounds: TileBounds) -> str:
        map_id = "tile-map-" + re.sub(r"[^a-z0-9_-]+", "-", target.target_path.stem.lower()).strip("-")
        config = self._leaflet_config(
            map_id,
            target,
            bounds,
            tiled=True,
            min_zoom=-3,
            max_zoom=2,
            default_zoom=0,
            lat=None,
            long=None,
            fit_bounds=True,
        )
        config_json = html.escape(json.dumps(config, separators=(",", ":")), quote=True)
        return "\n".join(
            [
                f'<div id="{map_id}" class="ext-map-container taelgar-leaflet-map" '
                f'style="height: 600px;" data-taelgar-leaflet="{config_json}"></div>',
            ]
        )


def gfm_anchor(title: str) -> str:
    if not title:
        return ""
    title = title.lstrip("#").strip().lower()
    title = re.sub(r"[^\w\u4e00-\u9fff\- ]", "", title)
    return re.sub(r" +", "-", title)


def number_value(value: object, default: float | None) -> float | None:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def relative_url(from_path: Path, to_path: Path) -> str:
    from_dir = PurePosixPath(from_path.as_posix()).parent.as_posix()
    start = from_dir if from_dir != "." else "."
    return os.path.relpath(to_path.as_posix(), start=start).replace("\\", "/")


def markdown_link(label: str, url: str) -> str:
    return f"[{label}](<{url}>)"


def convert_obsidian_callouts(text: str) -> str:
    if "> [!" not in text and ">[!" not in text:
        return text

    lines: list[str] = []
    active_callout = False
    for line in text.split("\n"):
        block_match = CALLOUT_BLOCK_RE.search(line)
        if block_match:
            active_callout = True
            lines.append(render_material_callout_opening(block_match))
            continue
        content_match = CALLOUT_CONTENT_RE.search(line)
        if active_callout and content_match:
            indent = "\t" * content_match.group("markers").count(">")
            lines.append(CALLOUT_CONTENT_RE.sub(indent, line, count=1))
            continue
        active_callout = False
        lines.append(line)
    return "\n".join(lines)


def render_material_callout_opening(match: re.Match[str]) -> str:
    indent = "\t" * (match.group("markers").count(">") - 1)
    callout_type = normalize_callout_type(match.group("type"))
    syntax = {"-": "???", "+": "???+"}.get(match.group("fold"), "!!!")
    title = (match.group("title") or "").strip()
    if title:
        return f'{indent}{syntax} {callout_type} "{escape_admonition_title(title)}"'
    return f'{indent}{syntax} {callout_type} " "'


def normalize_callout_type(value: str) -> str:
    callout_type = value.lower()
    callout_type = re.sub(r" *\| *(inline|left) *$", " inline", callout_type)
    callout_type = re.sub(r" *\| *(inline end|right) *$", " inline end", callout_type)
    callout_type = re.sub(r" *\|.*", "", callout_type)
    first, separator, rest = callout_type.partition(" ")
    first = CALLOUT_ALIASES.get(first, first)
    return first + (separator + rest if separator else "")


def escape_admonition_title(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def audio_mime_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".mp3":
        return "audio/mpeg"
    if suffix == ".m4a":
        return "audio/mp4"
    if suffix == ".wav":
        return "audio/wav"
    if suffix == ".flac":
        return "audio/flac"
    if suffix == ".ogg":
        return "audio/ogg"
    return "audio/mpeg"


LIST_MARKER_RE = re.compile(r"^(?P<indent>[ \t]{0,3})(?:[-+*]|\d+[.)])\s+\S")
FENCE_RE = re.compile(r"^[ \t]{0,3}(```|~~~)")


def normalize_loose_lists(text: str) -> str:
    """Add blank lines before paragraph-adjacent lists for Python-Markdown."""
    lines = text.splitlines(keepends=True)
    output: list[str] = []
    in_fence = False

    for line in lines:
        body = line.rstrip("\r\n")
        if FENCE_RE.match(body):
            in_fence = not in_fence
            output.append(line)
            continue

        if not in_fence and LIST_MARKER_RE.match(body) and output and previous_line_needs_list_break(output[-1]):
            output.append("\n")
        output.append(line)

    return "".join(output)


def previous_line_needs_list_break(line: str) -> bool:
    body = line.rstrip("\r\n")
    stripped = body.strip()
    if not stripped:
        return False
    if LIST_MARKER_RE.match(body):
        return False
    if FENCE_RE.match(body):
        return False
    if body.startswith(("    ", "\t")):
        return False
    if stripped.startswith(("#", ">", "|", "<")):
        return False
    if re.match(r"^[*_-]{3,}$", stripped):
        return False
    return True
