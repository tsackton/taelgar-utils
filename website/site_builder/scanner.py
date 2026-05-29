from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .asset_policy import asset_target_path_for
from .notes import MarkdownNote, is_asset, is_markdown, parse_markdown_note
from .slugging import slugify


@dataclass
class SourceEntry:
    source_path: Path
    relative_path: Path
    target_path: Path
    is_markdown: bool
    is_asset: bool
    note: MarkdownNote | None = None

    @property
    def id(self) -> str:
        return self.relative_path.as_posix()

    @property
    def source_signature(self) -> str:
        stat = self.source_path.stat()
        return f"{stat.st_mtime_ns}:{stat.st_size}"


@dataclass
class ScanResult:
    entries: list[SourceEntry]
    scanned_files: int
    skipped_files: int


class IgnoreMatcher:
    def __init__(self, ignore_file: Path | None) -> None:
        self.patterns: list[tuple[str, bool]] = []
        self.pathspec = None
        if ignore_file is None or not ignore_file.exists():
            return
        lines = [
            line.strip()
            for line in ignore_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        try:
            import pathspec  # type: ignore

            self.pathspec = pathspec.PathSpec.from_lines("gitwildmatch", lines)
        except ImportError:
            self.patterns = [(line[1:] if line.startswith("!") else line, line.startswith("!")) for line in lines]

    def matches(self, relative_path: Path) -> bool:
        path = relative_path.as_posix()
        if self.pathspec is not None:
            return bool(self.pathspec.match_file(path))
        ignored = False
        for pattern, negated in self.patterns:
            if self._matches_pattern(path, pattern):
                ignored = not negated
        return ignored

    @staticmethod
    def _matches_pattern(path: str, pattern: str) -> bool:
        pattern = pattern.strip()
        if not pattern:
            return False
        if pattern.endswith("/"):
            prefix = pattern.rstrip("/")
            return path == prefix or path.startswith(prefix + "/")
        candidates = {path, os.path.basename(path)}
        if "/" in pattern:
            candidates.add(path + "/")
        return any(fnmatch.fnmatch(candidate, pattern) for candidate in candidates)


def scan_source(config: Any) -> ScanResult:
    matcher = IgnoreMatcher(config.ignore_file)
    entries: list[SourceEntry] = []
    skipped = 0
    scanned = 0
    for source_path in sorted(config.source_dir.rglob("*")):
        if not source_path.is_file():
            continue
        scanned += 1
        relative_path = source_path.relative_to(config.source_dir)
        if any(part.startswith(".") for part in relative_path.parts):
            skipped += 1
            continue
        if matcher.matches(relative_path):
            skipped += 1
            continue
        markdown = is_markdown(source_path)
        note = parse_markdown_note(source_path, config) if markdown else None
        if note and should_skip_note(note, config):
            skipped += 1
            continue
        asset = is_asset(source_path)
        target_path = target_path_for(relative_path, config.slugify)
        if asset:
            target_path = asset_target_path_for(source_path, relative_path, target_path, config)
        entries.append(
            SourceEntry(
                source_path=source_path,
                relative_path=relative_path,
                target_path=target_path,
                is_markdown=markdown,
                is_asset=asset,
                note=note,
            )
        )

    target_paths: dict[str, SourceEntry] = {}
    duplicates: list[str] = []
    for entry in entries:
        target_key = entry.target_path.as_posix()
        if target_key in target_paths:
            duplicates.append(f"{target_key}: {target_paths[target_key].relative_path} and {entry.relative_path}")
        target_paths[target_key] = entry
    if duplicates:
        raise ValueError("Duplicate export target path(s):\n" + "\n".join(duplicates))
    return ScanResult(entries=entries, scanned_files=scanned, skipped_files=skipped)


def should_skip_note(note: MarkdownNote, config: Any) -> bool:
    if note.is_unnamed and config.unnamed_files == "skip":
        return True
    if note.is_stub and config.stub_files == "skip":
        return True
    if note.is_future_dated:
        return True
    if set(config.exclude_tags).intersection(note_tag_parts(note)):
        return True
    campaign_exclusion = note.metadata.get("excludePublish")
    if isinstance(campaign_exclusion, str):
        exclusions = [item.strip().lower() for item in campaign_exclusion.split(",")]
    elif isinstance(campaign_exclusion, list):
        exclusions = [str(item).strip().lower() for item in campaign_exclusion]
    else:
        exclusions = []
    if "all" in exclusions:
        return True
    campaigns = {campaign.lower() for campaign in config.campaigns}
    return bool(campaigns.intersection(exclusions))


def note_is_unlisted(note: MarkdownNote, config: Any) -> bool:
    return (note.is_unnamed and config.unnamed_files == "unlist") or (note.is_stub and config.stub_files == "unlist")


def note_tag_parts(note: MarkdownNote) -> set[str]:
    tags = note.metadata.get("tags", [])
    if isinstance(tags, str):
        tags = [tags]
    if not isinstance(tags, list):
        return set()
    parts: set[str] = set()
    for tag in tags:
        text = str(tag).strip()
        if not text:
            continue
        parts.add(text)
        parts.update(part for part in text.split("/") if part)
    return parts


def target_path_for(relative_path: Path, should_slugify: bool) -> Path:
    if not should_slugify:
        return relative_path
    parts = [slugify(part) for part in relative_path.parts[:-1]]
    filename = relative_path.name
    suffixes = "".join(relative_path.suffixes)
    stem = relative_path.name[: -len(suffixes)] if suffixes else relative_path.name
    target_name = slugify(stem) + suffixes.lower()
    return Path(*parts, target_name)
