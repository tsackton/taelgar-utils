from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .asset_policy import TileBounds, tile_paths
from .assets import copy_asset, copy_tree_contents, generate_map_tiles
from .config import WebsiteConfig
from .link_index import LinkIndex
from .manifest import Manifest
from .nav import MkDocsNavigationGenerator
from .notes import MarkdownNote, parse_markdown_note
from .scanner import SourceEntry, note_tag_parts, scan_source
from .session_zoom import (
    SessionArtifactIndex,
    is_zoomable_session_note,
    render_zoomable_session_note,
)
from .transform import LinkIssue, NoteTransformer, TileRequest


CONTENT_WARNING_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("placeholder species token", re.compile(r"\(XXX\)", re.IGNORECASE)),
    ("placeholder short description", re.compile(r"SHORT DESCRIPTION", re.IGNORECASE)),
    ("placeholder character section", re.compile(r"Creating Your\s+\(XXX\)", re.IGNORECASE)),
    ("Excalidraw source marker", re.compile(r"Switch to EXCALIDRAW|Excalidraw Data", re.IGNORECASE)),
    ("TODO marker", re.compile(r"\bTODO\b")),
    ("FIXME marker", re.compile(r"\bFIXME\b")),
)


class CustomDumper(yaml.SafeDumper):
    def represent_none(self, _: Any) -> yaml.nodes.Node:
        return self.represent_scalar("tag:yaml.org,2002:null", "")


CustomDumper.add_representer(type(None), CustomDumper.represent_none)


@dataclass
class ContentWarning:
    source: str
    line: int
    kind: str
    excerpt: str


@dataclass
class ExportStats:
    scanned_files: int = 0
    skipped_source_files: int = 0
    exported_notes: int = 0
    skipped_notes: int = 0
    copied_assets: int = 0
    resized_assets: int = 0
    optimized_assets: int = 0
    tiled_maps: int = 0
    map_tiles_written: int = 0
    deleted_stale_outputs: int = 0
    unresolved_links: list[LinkIssue] = field(default_factory=list)
    ambiguous_links: list[LinkIssue] = field(default_factory=list)
    nav_warnings: list[str] = field(default_factory=list)
    content_warnings: list[ContentWarning] = field(default_factory=list)
    asset_warnings: list["AssetWarning"] = field(default_factory=list)
    zoomable_pages: list[Path] = field(default_factory=list)


@dataclass
class AssetWarning:
    path: str
    size_bytes: int
    linked: bool
    status: str


@dataclass
class AssetReportItem:
    source: str
    target: str
    source_size: int
    output_size: int
    linked: bool
    status: str


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
    session_artifacts = SessionArtifactIndex(config.session_artifact_roots)
    new_manifest: dict[str, dict[str, Any]] = {}
    generated: set[str] = set()
    linked_asset_ids: set[str] = set()
    tile_requests: dict[str, TileRequest] = {}

    for entry in [item for item in scan.entries if item.is_markdown]:
        previous = previous_manifest.get(entry.id)
        target_path = config.docs_dir / entry.target_path
        zoomable_session = is_zoomable_session_note(entry.note)
        if entry.note:
            stats.content_warnings.extend(scan_content_warnings(entry.note.clean_text, entry.relative_path.as_posix()))
        if not zoomable_session and can_skip_entry(previous, entry, target_path, config_digest, index_digest):
            stats.skipped_notes += 1
            generated.add(entry.target_path.as_posix())
            linked_asset_ids.update(previous.get("linked_assets", []))
            for asset_id, raw_request in previous.get("tile_assets", {}).items():
                bounds = raw_request.get("bounds") if isinstance(raw_request, dict) else None
                if isinstance(bounds, list):
                    tile_requests[asset_id] = TileRequest(bounds=tile_bounds_from_manifest(bounds))
            new_manifest[entry.id] = previous
            continue

        result = transformer.transform_entry(entry)
        stats.unresolved_links.extend(result.unresolved_links)
        stats.ambiguous_links.extend(result.ambiguous_links)
        linked_asset_ids.update(result.linked_assets)
        tile_requests.update(result.tile_assets)
        if zoomable_session and entry.note is not None:
            zoom_result = render_zoomable_session_note(
                note=entry.note,
                transformed_text=result.text,
                page_path=entry.target_path,
                config=config,
                index=index,
                artifact_index=session_artifacts,
            )
            if zoom_result.warning:
                stats.content_warnings.append(
                    ContentWarning(
                        source=entry.relative_path.as_posix(),
                        line=1,
                        kind="zoomable session view",
                        excerpt=zoom_result.warning,
                    )
                )
            else:
                result.text = zoom_result.text
                stats.zoomable_pages.append(entry.target_path)
                if zoom_result.transcript_asset_path is not None and zoom_result.transcript_json is not None:
                    write_text_if_changed(config.docs_dir / zoom_result.transcript_asset_path, zoom_result.transcript_json)
                    generated.add(zoom_result.transcript_asset_path.as_posix())
        output = render_note(entry.note, result.text, config)
        if write_text_if_changed(target_path, output):
            stats.exported_notes += 1
        else:
            stats.skipped_notes += 1
        generated.add(entry.target_path.as_posix())
        new_manifest[entry.id] = manifest_record(entry, config_digest, index_digest, result.linked_assets, result.tile_assets)

    if config.home_source:
        home_note = parse_markdown_note(config.home_source, config)
        stats.content_warnings.extend(scan_content_warnings(home_note.clean_text, config.home_source.as_posix()))
        home_result = transformer.transform_note(home_note, config.home_dest, config.home_source.as_posix())
        stats.unresolved_links.extend(home_result.unresolved_links)
        stats.ambiguous_links.extend(home_result.ambiguous_links)
        linked_asset_ids.update(home_result.linked_assets)
        tile_requests.update(home_result.tile_assets)
        home_output = render_note(home_note, home_result.text, config)
        if write_text_if_changed(config.docs_dir / config.home_dest, home_output):
            stats.exported_notes += 1
        else:
            stats.skipped_notes += 1
        generated.add(config.home_dest.as_posix())

    if config.nav_source:
        nav_result = MkDocsNavigationGenerator(config.nav_source, scan.entries, config).process_template()
        stats.nav_warnings.extend(nav_result.warnings)
        write_text_if_changed(config.docs_dir / config.nav_dest, render_nav_file(nav_result.lines))
        generated.add(config.nav_dest.as_posix())

    linked_asset_ids.update(resolve_always_include_assets(config, index))
    asset_entries = {entry.id: entry for entry in scan.entries if entry.is_asset}
    for asset_id, request in sorted(tile_requests.items()):
        entry = asset_entries.get(asset_id)
        if entry is None:
            continue
        bounds = request.bounds
        if not isinstance(bounds, TileBounds):
            continue
        tile_rel_paths = tile_paths(entry.target_path, bounds, config, entry.source_path)
        generated.update(path.as_posix() for path in tile_rel_paths)
        manifest_id = tile_manifest_id(entry.id)
        previous = previous_manifest.get(manifest_id)
        if can_skip_tiles(previous, entry, config_digest, bounds, tile_rel_paths, config.docs_dir):
            new_manifest[manifest_id] = previous
            continue
        tile_result = generate_map_tiles(entry, config.docs_dir, bounds, config)
        stats.tiled_maps += 1
        stats.map_tiles_written += tile_result.tiles_written
        new_manifest[manifest_id] = tile_record(entry, config_digest, bounds, tile_rel_paths)

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
        stats.optimized_assets += 1 if result.optimized else 0
        generated.add(entry.target_path.as_posix())
        new_manifest[entry.id] = asset_record(entry, config_digest)

    stats.deleted_stale_outputs = delete_stale_outputs(config.docs_dir, manifest.generated, generated)
    manifest.save(new_manifest, generated)
    write_warning_report(config.warning_report_path, stats.content_warnings)
    stats.asset_warnings = write_asset_report(config.asset_report_path, scan.entries, linked_asset_ids, tile_requests, config)
    print_summary(stats, time.perf_counter() - start)
    return stats


def render_note(note: MarkdownNote | None, body: str, config: WebsiteConfig) -> str:
    if note is None:
        raise ValueError("Cannot render missing note")
    metadata = dict(note.metadata)
    metadata["title"] = note.page_title
    tag_parts = note_tag_parts(note)
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
    if tag_parts.intersection(config.search_exclude_tags):
        search_metadata = metadata.get("search")
        search_dict = dict(search_metadata) if isinstance(search_metadata, dict) else {}
        search_dict["exclude"] = True
        metadata["search"] = search_dict
    frontmatter = yaml.dump(
        metadata,
        sort_keys=False,
        default_flow_style=None,
        allow_unicode=True,
        Dumper=CustomDumper,
        width=2000,
    )
    return "---\n" + frontmatter + "---\n" + body


def render_nav_file(lines: list[str]) -> str:
    frontmatter = yaml.dump(
        {"title": "Toc", "search": {"exclude": True}},
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        Dumper=CustomDumper,
        width=2000,
    )
    return "---\n" + frontmatter + "---\n" + "\n".join(lines) + "\n"


def scan_content_warnings(text: str, source: str) -> list[ContentWarning]:
    warnings: list[ContentWarning] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for kind, pattern in CONTENT_WARNING_PATTERNS:
            if pattern.search(line):
                warnings.append(
                    ContentWarning(
                        source=source,
                        line=line_number,
                        kind=kind,
                        excerpt=line.strip()[:160],
                    )
                )
    return warnings


def write_warning_report(path: Path, warnings: list[ContentWarning]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Export Warnings", ""]
    if not warnings:
        lines.append("No content warnings.")
    else:
        lines.append(f"{len(warnings)} content warning(s) found.")
        lines.append("")
        for warning in warnings:
            lines.append(f"- `{warning.source}:{warning.line}` [{warning.kind}] {warning.excerpt}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_asset_report(
    path: Path,
    entries: list[SourceEntry],
    linked_asset_ids: set[str],
    tile_requests: dict[str, TileRequest],
    config: WebsiteConfig,
) -> list[AssetWarning]:
    path.parent.mkdir(parents=True, exist_ok=True)
    tile_asset_ids = set(tile_requests)
    items: list[AssetReportItem] = []
    warnings: list[AssetWarning] = []
    for entry in entries:
        if not entry.is_asset:
            continue
        source_size = entry.source_path.stat().st_size
        output_path = config.docs_dir / entry.target_path
        output_size = output_path.stat().st_size if output_path.exists() else 0
        linked = entry.id in linked_asset_ids or entry.id in tile_asset_ids
        if entry.id in tile_asset_ids:
            status = "tiled"
        elif entry.target_path.suffix.lower() == ".webp" and entry.source_path.suffix.lower() != ".webp":
            status = "optimized"
        elif linked:
            status = "copied"
        else:
            status = "unlinked"
        item = AssetReportItem(
            source=entry.relative_path.as_posix(),
            target=entry.target_path.as_posix(),
            source_size=source_size,
            output_size=output_size,
            linked=linked,
            status=status,
        )
        items.append(item)
        warning_size = output_size or source_size
        if linked and warning_size >= config.asset_warning_size_bytes and status != "tiled":
            warnings.append(AssetWarning(entry.target_path.as_posix(), warning_size, linked, status))

    top_n = config.asset_report_top_n
    linked_count = sum(1 for item in items if item.linked)
    optimized_count = sum(1 for item in items if item.status == "optimized")
    tiled_count = sum(1 for item in items if item.status == "tiled")
    lines = [
        "# Asset Report",
        "",
        f"- Source assets scanned: {len(items)}",
        f"- Linked assets: {linked_count}",
        f"- Optimized image assets: {optimized_count}",
        f"- Tile-backed map assets: {tiled_count}",
        f"- Warning threshold: {format_bytes(config.asset_warning_size_bytes)}",
        "",
        "## Warnings",
        "",
    ]
    if warnings:
        for warning in sorted(warnings, key=lambda item: item.size_bytes, reverse=True):
            lines.append(f"- `{warning.path}`: {format_bytes(warning.size_bytes)} ({warning.status})")
    else:
        lines.append("No oversized linked assets.")

    lines.extend(["", f"## Top {top_n} Source Assets", ""])
    for item in sorted(items, key=lambda value: value.source_size, reverse=True)[:top_n]:
        lines.append(
            f"- `{item.source}` -> `{item.target}`: source {format_bytes(item.source_size)}, "
            f"output {format_bytes(item.output_size)}, {item.status}"
        )

    lines.extend(["", f"## Top {top_n} Output Assets", ""])
    for item in sorted(items, key=lambda value: value.output_size, reverse=True)[:top_n]:
        lines.append(
            f"- `{item.target}`: output {format_bytes(item.output_size)}, "
            f"source {format_bytes(item.source_size)}, {item.status}"
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return warnings


def format_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


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


def manifest_record(
    entry: SourceEntry,
    config_digest: str,
    index_digest: str,
    linked_assets: set[str],
    tile_assets: dict[str, TileRequest],
) -> dict[str, Any]:
    return {
        "kind": "note",
        "source_signature": entry.source_signature,
        "target": entry.target_path.as_posix(),
        "config_digest": config_digest,
        "index_digest": index_digest,
        "linked_assets": sorted(linked_assets),
        "tile_assets": {
            asset_id: {"bounds": tile_bounds_to_manifest(request.bounds)}
            for asset_id, request in sorted(tile_assets.items())
            if isinstance(request.bounds, TileBounds)
        },
    }


def asset_record(entry: SourceEntry, config_digest: str) -> dict[str, Any]:
    return {
        "kind": "asset",
        "source_signature": entry.source_signature,
        "target": entry.target_path.as_posix(),
        "config_digest": config_digest,
    }


def tile_manifest_id(asset_id: str) -> str:
    return asset_id + "::tiles"


def tile_record(entry: SourceEntry, config_digest: str, bounds: TileBounds, paths: list[Path]) -> dict[str, Any]:
    return {
        "kind": "tiles",
        "source_signature": entry.source_signature,
        "target": entry.target_path.as_posix(),
        "config_digest": config_digest,
        "bounds": tile_bounds_to_manifest(bounds),
        "tiles": [path.as_posix() for path in paths],
    }


def can_skip_tiles(
    previous: dict[str, Any] | None,
    entry: SourceEntry,
    config_digest: str,
    bounds: TileBounds,
    paths: list[Path],
    docs_dir: Path,
) -> bool:
    return bool(
        previous
        and previous.get("source_signature") == entry.source_signature
        and previous.get("config_digest") == config_digest
        and previous.get("bounds") == tile_bounds_to_manifest(bounds)
        and previous.get("tiles") == [path.as_posix() for path in paths]
        and all((docs_dir / path).exists() for path in paths)
    )


def tile_bounds_to_manifest(bounds: object) -> list[list[float]]:
    if not isinstance(bounds, TileBounds):
        return []
    return [[bounds.y0, bounds.x0], [bounds.y1, bounds.x1]]


def tile_bounds_from_manifest(value: object) -> TileBounds:
    if (
        isinstance(value, list)
        and len(value) == 2
        and all(isinstance(item, list) and len(item) == 2 for item in value)
    ):
        return TileBounds(float(value[0][0]), float(value[0][1]), float(value[1][0]), float(value[1][1]))
    return TileBounds(0, 0, 1, 1)


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
        f"{stats.optimized_assets} optimized, "
        f"{stats.map_tiles_written} map tile(s) written, "
        f"{stats.deleted_stale_outputs} stale output(s) removed"
    )
    print(
        "Checks: "
        f"{len(stats.unresolved_links)} unresolved link(s), "
        f"{len(stats.ambiguous_links)} ambiguous link(s), "
        f"{len(stats.nav_warnings)} nav warning(s), "
        f"{len(stats.content_warnings)} content warning(s), "
        f"{len(stats.asset_warnings)} asset warning(s)"
    )
    if stats.content_warnings:
        print("Content warnings:")
        for warning in stats.content_warnings[:40]:
            print(f"  - {warning.source}:{warning.line}: {warning.kind}: {warning.excerpt}")
        if len(stats.content_warnings) > 40:
            print(f"  - ... {len(stats.content_warnings) - 40} more")
    if stats.asset_warnings:
        print("Asset warnings:")
        for warning in sorted(stats.asset_warnings, key=lambda item: item.size_bytes, reverse=True)[:20]:
            print(f"  - {warning.path}: {format_bytes(warning.size_bytes)} ({warning.status})")
        if len(stats.asset_warnings) > 20:
            print(f"  - ... {len(stats.asset_warnings) - 20} more")
    print(f"Done in {elapsed:.2f}s")
