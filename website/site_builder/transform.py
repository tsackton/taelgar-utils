from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from .link_index import LinkIndex
from .notes import ASSET_SUFFIXES, IMAGE_SUFFIXES, WIKILINK_RE, MarkdownNote, title_case
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
    unresolved_links: list[LinkIssue] = field(default_factory=list)
    ambiguous_links: list[LinkIssue] = field(default_factory=list)

    def extend(self, other: "TransformResult") -> None:
        self.linked_assets.update(other.linked_assets)
        self.unresolved_links.extend(other.unresolved_links)
        self.ambiguous_links.extend(other.ambiguous_links)


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
        result.text = self._rewrite_and_collect_direct_asset_links(result.text, source_label, result)
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
            if codeblock_type == "leaflet" and "image" in template_content:
                image_name = str(template_content["image"][0]).replace("[", "").replace("]", "").replace("'", "")
                image_resolution = self.index.resolve(image_name)
                if image_resolution.status == "found" and image_resolution.entry:
                    result.linked_assets.add(image_resolution.entry.id)
                    template_content["image"] = self.absolute_url(image_resolution.entry.target_path)
                elif image_resolution.status == "ambiguous":
                    result.ambiguous_links.append(LinkIssue(source_label, image_name, "Ambiguous leaflet image"))
                else:
                    result.unresolved_links.append(LinkIssue(source_label, image_name, "Missing leaflet image"))
            return template_text.format(**template_content)

        return re.sub(r"(```([^`]+)```|~~~([^~]+)~~~|`([^`]*)`)", replace, text, flags=re.DOTALL)

    def _replace_audio_tags(self, text: str, source_label: str, result: TransformResult) -> str:
        def replace(match: re.Match[str]) -> str:
            file_name = match.group(1)
            resolution = self.index.resolve(file_name)
            if resolution.status == "found" and resolution.entry:
                result.linked_assets.add(resolution.entry.id)
                return f'<audio controls>\n    <source src="{self.absolute_url(resolution.entry.target_path)}">\n</audio>'
            if resolution.status == "ambiguous":
                result.ambiguous_links.append(LinkIssue(source_label, file_name, "Ambiguous audio link"))
            else:
                result.unresolved_links.append(LinkIssue(source_label, file_name, "Missing audio link"))
            return match.group(0)

        return re.sub(r"!\[\[(.*?\.mp3)\]\]", replace, text)

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
        if target.is_asset:
            result.linked_assets.add(target.id)
        rel_link_url = relative_url(page_path, target.target_path)
        if title:
            rel_link_url += "#" + gfm_anchor(title)

        image_link = target.target_path.suffix.lower() in IMAGE_SUFFIXES or alias in {"right", "left"} or bool(width or height)
        if image_link:
            image_alias = title_case(Path(filename).stem.replace("-", " ").replace("_", " "))
            params = []
            if alias in {"right", "left"}:
                params.append(f'align="{alias}"')
            if width:
                params.append(f'width="{width}"')
            if height:
                params.append(f'height="{height}"')
            attrs = "{" + "; ".join(params) + "}" if params else ""
            return f"[{image_alias}]({rel_link_url}){attrs}"
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
                if raw_target.startswith("/"):
                    return f"{match.group('prefix')}{self.absolute_url(resolution.entry.target_path)}{match.group('suffix')}"
            elif resolution.status == "ambiguous":
                result.ambiguous_links.append(LinkIssue(source_label, raw_target, "Ambiguous direct asset link"))
            else:
                result.unresolved_links.append(LinkIssue(source_label, raw_target, "Missing direct asset link"))
            return match.group(0)

        return pattern.sub(replace, text)

    def absolute_url(self, target_path: Path) -> str:
        return self.config.base_path + target_path.as_posix()


def gfm_anchor(title: str) -> str:
    if not title:
        return ""
    title = title.lstrip("#").strip().lower()
    title = re.sub(r"[^\w\u4e00-\u9fff\- ]", "", title)
    return re.sub(r" +", "-", title)


def relative_url(from_path: Path, to_path: Path) -> str:
    from_dir = PurePosixPath(from_path.as_posix()).parent.as_posix()
    start = from_dir if from_dir != "." else "."
    return os.path.relpath(to_path.as_posix(), start=start).replace("\\", "/")


def markdown_link(label: str, url: str) -> str:
    return f"[{label}](<{url}>)"
