from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from taelgar_lib.TaelgarDate import TaelgarDate


WIKILINK_RE = r"""\[\[([^\|\]\#\\]+)(\#.*?)?(?:\\?\|([^\|\]]*))?(?:\\?\|([^\|\]]*))?(?:\\?\|([^\|\]]*))?\]\]"""
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic"}
ASSET_SUFFIXES = IMAGE_SUFFIXES | {".mp3", ".pdf"}


@dataclass
class MarkdownNote:
    source_path: Path
    metadata: dict[str, Any]
    raw_text: str
    clean_text: str
    page_title: str
    outlinks: list[str] = field(default_factory=list)
    is_stub: bool = False
    is_unnamed: bool = False
    is_future_dated: bool = False


def parse_markdown_note(path: Path, config: Any) -> MarkdownNote:
    metadata, raw_text = parse_frontmatter(path)
    clean_text = clean_note_text(raw_text, metadata, config)
    page_title = page_title_for(path, metadata)
    outlinks = [match[0] for match in re.findall(WIKILINK_RE, raw_text) if match[0]]
    is_stub = count_relevant_lines(clean_text) < 1
    is_unnamed = page_title.startswith("~") or path.stem.startswith("~")
    is_future = is_future_dated(metadata, config)
    return MarkdownNote(
        source_path=path,
        metadata=metadata,
        raw_text=raw_text,
        clean_text=clean_text,
        page_title=page_title,
        outlinks=outlinks,
        is_stub=is_stub,
        is_unnamed=is_unnamed,
        is_future_dated=is_future,
    )


def parse_frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, "".join(lines)
    try:
        end_index = next(i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration:
        return {}, "".join(lines)
    metadata = yaml.safe_load("".join(lines[1:end_index])) or {}
    if not isinstance(metadata, dict):
        metadata = {}
    return metadata, "".join(lines[end_index + 1 :])


def clean_note_text(raw_text: str, metadata: dict[str, Any], config: Any) -> str:
    text = raw_text
    if config.strip_date_blocks and config.export_date:
        text = strip_date_content(text, config.export_date)
    if config.strip_campaign_blocks and config.campaigns:
        text = strip_campaign_content(text, config.campaigns)
    if config.strip_comments:
        text = strip_comments(text)
    if config.clean_inline_tags:
        text = clean_inline_tags(text)
    return text


def strip_comments(text: str) -> str:
    return re.sub(r"%%.*?%%|%%.*", "", text, flags=re.DOTALL)


def strip_campaign_content(text: str, campaigns: tuple[str, ...]) -> str:
    campaign_names = {campaign.lower() for campaign in campaigns}

    def keep_or_remove(match: re.Match[str]) -> str:
        campaign_text = match.group(1).strip().lower()
        content = match.group(2)
        return content if campaign_text in campaign_names else ""

    return re.sub(r"%%\^Campaign:(.*?)%%(.*?)%%\^End%%", keep_or_remove, text, flags=re.DOTALL | re.IGNORECASE)


def strip_date_content(text: str, export_date: str) -> str:
    target_date = TaelgarDate.parse_date_string(export_date)

    def keep_or_remove(match: re.Match[str]) -> str:
        comment_date_str = match.group(1).strip()
        parse_code = "b"
        comment_date_str = comment_date_str.rstrip("^").strip()
        if comment_date_str and comment_date_str[-1].isalpha():
            parse_code = comment_date_str[-1].lower()
            comment_date_str = comment_date_str[:-1].rstrip("^").strip()
        comment_date = TaelgarDate.parse_date_string(comment_date_str)
        if parse_code == "a":
            return "" if target_date <= comment_date else match.group(2)
        if parse_code == "b":
            return "" if target_date >= comment_date else match.group(2)
        raise ValueError(f"Invalid date block parse code: {parse_code}")

    return re.sub(r"%%\^Date:(.*?)%%(.*?)%%\^End%%", keep_or_remove, text, flags=re.DOTALL)


def clean_inline_tags(text: str) -> str:
    def replace_tag(match: re.Match[str]) -> str:
        inline_tag = match.group(1)
        tag_value = match.group(2)
        if inline_tag in {"DR", "DR_end"}:
            parts = tag_value.split("-")
            if len(parts) > 1:
                parts[1] = TaelgarDate.DR_MONTHS[int(parts[1])]
            if len(parts) == 3:
                return f"{parts[1]} {parts[2]}, {parts[0]} DR"
            if len(parts) == 2:
                return f"{parts[1]} {parts[0]} DR"
            if len(parts) == 1:
                return f"{parts[0]} DR"
        return f"{inline_tag} {tag_value}"

    return re.sub(r"\((\w+)::\s*([^\s\)]+)\s*\)", replace_tag, text, flags=re.DOTALL)


def count_relevant_lines(text: str) -> int:
    def is_excluded(line: str) -> bool:
        stripped = line.strip()
        return stripped == "" or stripped in {"stub", "(stub)"} or line.lstrip().startswith("#")

    return len([line for line in text.splitlines() if not is_excluded(line)])


def is_future_dated(metadata: dict[str, Any], config: Any) -> bool:
    if not config.skip_future_dated or not metadata.get("activeYear") or not config.export_date:
        return False
    return TaelgarDate.parse_date_string(str(metadata["activeYear"])) > TaelgarDate.parse_date_string(config.export_date)


def title_case(text: str, exclusions: set[str] | None = None, always_upper: set[str] | None = None) -> str:
    if exclusions is None:
        exclusions = {
            "a",
            "an",
            "the",
            "and",
            "but",
            "or",
            "for",
            "nor",
            "as",
            "at",
            "by",
            "from",
            "in",
            "into",
            "near",
            "of",
            "on",
            "onto",
            "to",
            "with",
            "de",
            "about",
        }
    if always_upper is None:
        always_upper = {"dr"}
    words = text.split()
    output: list[str] = []
    for index, word in enumerate(words):
        stripped = re.sub(r"\W+", "", word)
        if stripped.lower() in always_upper:
            output.append(word.upper())
        elif index == 0 or stripped.lower() not in exclusions:
            output.append(re.sub(r"(\b\w)", lambda match: match.group(1).upper(), word, count=1))
        else:
            output.append(word.lower())
    return " ".join(output)


def page_title_for(path: Path, metadata: dict[str, Any]) -> str:
    page_name = title_case(str(metadata.get("name") or path.stem.replace("-", " ")))
    page_title = title_case(str(metadata.get("title"))) if metadata.get("title") else ""
    return " ".join([page_title, page_name]).strip()


def is_markdown(path: Path) -> bool:
    return path.suffix == ".md" and len(path.suffixes) == 1


def is_asset(path: Path) -> bool:
    return path.suffix.lower() in ASSET_SUFFIXES
