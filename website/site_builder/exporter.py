from __future__ import annotations

import hashlib
import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .assets import copy_asset, copy_tree_contents
from .config import WebsiteConfig
from .link_index import LinkIndex
from .manifest import Manifest
from .nav import MkDocsNavigationGenerator
from .notes import MarkdownNote, parse_markdown_note
from .scanner import SourceEntry, scan_source
from .transform import LinkIssue, NoteTransformer


class CustomDumper(yaml.SafeDumper):
    def represent_none(self, _: Any) -> yaml.nodes.Node:
        return self.represent_scalar("tag:yaml.org,2002:null", "")


CustomDumper.add_representer(type(None), CustomDumper.represent_none)


@dataclass
class ExportStats:
    scanned_files: int = 0
    skipped_source_files: int = 0
    exported_notes: int = 0
    skipped_notes: int = 0
    copied_assets: int = 0
    resized_assets: int = 0
    deleted_stale_outputs: int = 0
    unresolved_links: list[LinkIssue] = field(default_factory=list)
    ambiguous_links: list[LinkIssue] = field(default_factory=list)
    nav_warnings: list[str] = field(default_factory=list)


def export_site(config: WebsiteConfig) -> ExportStats:
    start = time.perf_counter()
    stats = ExportStats()
    print(f"Config: {config.config_path}")
    print(f"Source: {config.source_dir}")
    print(f"Docs: {config.docs_dir}")

    if config.clean_docs and config.docs_dir.exists():
        print(f"Cleaning docs directory: {config.docs_dir}")
        shutil.rmtree(config.docs_dir)
    config.docs_dir.mkdir(parents=True, exist_ok=True)

    if config.overrides_source and config.overrides_dir:
        copied = copy_tree_contents(config.overrides_source, config.overrides_dir)
        print(f"Overrides: copied {len(copied)} file(s)")

    manifest = Manifest.load(config.manifest_path)
    previous_manifest = {} if config.clean_docs else manifest.files
    scan = scan_source(config)
    stats.scanned_files = scan.scanned_files
    stats.skipped_source_files = scan.skipped_files
    print(f"Scan: {stats.scanned_files} file(s), {stats.skipped_source_files} skipped")

    index = LinkIndex(scan.entries)
    index_digest = index.digest()
    config_digest = digest(config.digest_payload())
    transformer = NoteTransformer(config, index)
    new_manifest: dict[str, dict[str, Any]] = {}
    generated: set[str] = set()
    linked_asset_ids: set[str] = set()

    for entry in [item for item in scan.entries if item.is_markdown]:
        previous = previous_manifest.get(entry.id)
        target_path = config.docs_dir / entry.target_path
        if can_skip_entry(previous, entry, target_path, config_digest, index_digest):
            stats.skipped_notes += 1
            generated.add(entry.target_path.as_posix())
            linked_asset_ids.update(previous.get("linked_assets", []))
            new_manifest[entry.id] = previous
            continue

        result = transformer.transform_entry(entry)
        stats.unresolved_links.extend(result.unresolved_links)
        stats.ambiguous_links.extend(result.ambiguous_links)
        linked_asset_ids.update(result.linked_assets)
        output = render_note(entry.note, result.text, config)
        if write_text_if_changed(target_path, output):
            stats.exported_notes += 1
        else:
            stats.skipped_notes += 1
        generated.add(entry.target_path.as_posix())
        new_manifest[entry.id] = manifest_record(entry, config_digest, index_digest, result.linked_assets)

    if config.home_source:
        home_note = parse_markdown_note(config.home_source, config)
        home_result = transformer.transform_note(home_note, config.home_dest, config.home_source.as_posix())
        stats.unresolved_links.extend(home_result.unresolved_links)
        stats.ambiguous_links.extend(home_result.ambiguous_links)
        linked_asset_ids.update(home_result.linked_assets)
        home_output = render_note(home_note, home_result.text, config)
        if write_text_if_changed(config.docs_dir / config.home_dest, home_output):
            stats.exported_notes += 1
        else:
            stats.skipped_notes += 1
        generated.add(config.home_dest.as_posix())

    if config.nav_source:
        nav_result = MkDocsNavigationGenerator(config.nav_source, scan.entries, config).process_template()
        stats.nav_warnings.extend(nav_result.warnings)
        write_text_if_changed(config.docs_dir / config.nav_dest, "\n".join(nav_result.lines) + "\n")
        generated.add(config.nav_dest.as_posix())

    linked_asset_ids.update(resolve_always_include_assets(config, index))
    asset_entries = {entry.id: entry for entry in scan.entries if entry.is_asset}
    for asset_id in sorted(linked_asset_ids):
        entry = asset_entries.get(asset_id)
        if entry is None:
            continue
        target_path = config.docs_dir / entry.target_path
        previous = previous_manifest.get(entry.id)
        if can_skip_asset(previous, entry, target_path, config_digest):
            generated.add(entry.target_path.as_posix())
            new_manifest[entry.id] = previous
            continue
        result = copy_asset(entry, target_path, config)
        stats.copied_assets += 1
        stats.resized_assets += 1 if result.resized else 0
        generated.add(entry.target_path.as_posix())
        new_manifest[entry.id] = asset_record(entry, config_digest)

    stats.deleted_stale_outputs = delete_stale_outputs(config.docs_dir, manifest.generated, generated)
    manifest.save(new_manifest, generated)
    print_summary(stats, time.perf_counter() - start)
    return stats


def render_note(note: MarkdownNote | None, body: str, config: WebsiteConfig) -> str:
    if note is None:
        raise ValueError("Cannot render missing note")
    metadata = dict(note.metadata)
    metadata["title"] = note.page_title
    tags = metadata.get("tags", [])
    if isinstance(tags, str):
        tags = [tags]
    tag_parts = {part for tag in tags for part in str(tag).split("/")}
    hide_nav = bool(tag_parts.intersection(config.hide_nav_tags))
    hide_toc = bool(tag_parts.intersection(config.hide_toc_tags))
    hide_backlinks = bool(tag_parts.intersection(config.hide_backlinks_tags))
    if hide_toc:
        metadata["hide_toc"] = True
    if hide_backlinks:
        metadata["hide_backlinks"] = True
    if hide_nav and (hide_toc or hide_backlinks):
        metadata["hide"] = ["toc", "navigation"] if hide_toc else ["navigation"]
    elif hide_nav:
        metadata["hide"] = ["navigation"]
    elif hide_toc and metadata.get("hide_backlinks"):
        metadata["hide"] = ["toc"]
    frontmatter = yaml.dump(
        metadata,
        sort_keys=False,
        default_flow_style=None,
        allow_unicode=True,
        Dumper=CustomDumper,
        width=2000,
    )
    return "---\n" + frontmatter + "---\n" + body


def can_skip_entry(
    previous: dict[str, Any] | None,
    entry: SourceEntry,
    target_path: Path,
    config_digest: str,
    index_digest: str,
) -> bool:
    return bool(
        previous
        and target_path.exists()
        and previous.get("source_signature") == entry.source_signature
        and previous.get("config_digest") == config_digest
        and previous.get("index_digest") == index_digest
    )


def can_skip_asset(previous: dict[str, Any] | None, entry: SourceEntry, target_path: Path, config_digest: str) -> bool:
    return bool(
        previous
        and target_path.exists()
        and previous.get("source_signature") == entry.source_signature
        and previous.get("config_digest") == config_digest
    )


def manifest_record(entry: SourceEntry, config_digest: str, index_digest: str, linked_assets: set[str]) -> dict[str, Any]:
    return {
        "kind": "note",
        "source_signature": entry.source_signature,
        "target": entry.target_path.as_posix(),
        "config_digest": config_digest,
        "index_digest": index_digest,
        "linked_assets": sorted(linked_assets),
    }


def asset_record(entry: SourceEntry, config_digest: str) -> dict[str, Any]:
    return {
        "kind": "asset",
        "source_signature": entry.source_signature,
        "target": entry.target_path.as_posix(),
        "config_digest": config_digest,
    }


def resolve_always_include_assets(config: WebsiteConfig, index: LinkIndex) -> set[str]:
    asset_ids: set[str] = set()
    for pattern in config.always_include_assets:
        for entry in index.entries:
            if entry.is_asset and entry.relative_path.match(pattern):
                asset_ids.add(entry.id)
    return asset_ids


def delete_stale_outputs(docs_dir: Path, previous: set[str], current: set[str]) -> int:
    deleted = 0
    for rel_path in sorted(previous - current, reverse=True):
        target = docs_dir / rel_path
        if target.exists() and target.is_file():
            target.unlink()
            deleted += 1
            remove_empty_parents(target.parent, docs_dir)
    return deleted


def remove_empty_parents(path: Path, stop: Path) -> None:
    while path != stop and path.exists():
        try:
            path.rmdir()
        except OSError:
            break
        path = path.parent


def write_text_if_changed(path: Path, text: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.write_text(text, encoding="utf-8")
    return True


def digest(payload: Any) -> str:
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def print_summary(stats: ExportStats, elapsed: float) -> None:
    print(
        "Export: "
        f"{stats.exported_notes} note(s) written, "
        f"{stats.skipped_notes} note(s) unchanged, "
        f"{stats.copied_assets} asset(s) copied, "
        f"{stats.resized_assets} resized, "
        f"{stats.deleted_stale_outputs} stale output(s) removed"
    )
    print(
        "Checks: "
        f"{len(stats.unresolved_links)} unresolved link(s), "
        f"{len(stats.ambiguous_links)} ambiguous link(s), "
        f"{len(stats.nav_warnings)} nav warning(s)"
    )
    print(f"Done in {elapsed:.2f}s")

