from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from typing import Any

from .config import WebsiteConfig
from .link_index import LinkIndex
from .nav import MkDocsNavigationGenerator
from .scanner import scan_source
from .transform import LinkIssue, NoteTransformer


@dataclass
class CheckResult:
    missing_dependencies: list[str] = field(default_factory=list)
    ambiguous_aliases: dict[str, tuple[str, ...]] = field(default_factory=dict)
    unresolved_links: list[LinkIssue] = field(default_factory=list)
    ambiguous_links: list[LinkIssue] = field(default_factory=list)
    nav_warnings: list[str] = field(default_factory=list)
    scanned_files: int = 0
    skipped_files: int = 0

    @property
    def has_errors(self) -> bool:
        return bool(self.missing_dependencies or self.unresolved_links or self.ambiguous_links)


def check_site(config: WebsiteConfig) -> CheckResult:
    result = CheckResult()
    result.missing_dependencies.extend(missing_dependencies(config))
    scan = scan_source(config)
    result.scanned_files = scan.scanned_files
    result.skipped_files = scan.skipped_files
    index = LinkIndex(scan.entries)
    result.ambiguous_aliases = {
        alias: tuple(entry.relative_path.as_posix() for entry in entries)
        for alias, entries in index.ambiguous_aliases().items()
    }
    transformer = NoteTransformer(config, index)
    for entry in [item for item in scan.entries if item.is_markdown]:
        transformed = transformer.transform_entry(entry)
        result.unresolved_links.extend(transformed.unresolved_links)
        result.ambiguous_links.extend(transformed.ambiguous_links)
    if config.home_source:
        from .notes import parse_markdown_note

        home_note = parse_markdown_note(config.home_source, config)
        transformed = transformer.transform_note(home_note, config.home_dest, config.home_source.as_posix())
        result.unresolved_links.extend(transformed.unresolved_links)
        result.ambiguous_links.extend(transformed.ambiguous_links)
    if config.nav_source:
        nav_result = MkDocsNavigationGenerator(config.nav_source, scan.entries, config).process_template()
        result.nav_warnings.extend(nav_result.warnings)
    print_check_result(result)
    return result


def missing_dependencies(config: WebsiteConfig) -> list[str]:
    missing: list[str] = []
    for module_name in ["yaml"]:
        if importlib.util.find_spec(module_name) is None:
            missing.append(module_name)
    if config.resize_images and importlib.util.find_spec("PIL") is None:
        missing.append("Pillow")
    if importlib.util.find_spec("mkdocs") is None:
        missing.append("mkdocs")
    return missing


def print_check_result(result: CheckResult) -> None:
    print(f"Scan: {result.scanned_files} file(s), {result.skipped_files} skipped")
    if result.missing_dependencies:
        print("Missing dependencies:")
        for dependency in result.missing_dependencies:
            print(f"  - {dependency}")
    if result.ambiguous_aliases:
        print(f"Ambiguous aliases: {len(result.ambiguous_aliases)}")
        for alias, entries in list(result.ambiguous_aliases.items())[:20]:
            print(f"  - {alias}: {', '.join(entries)}")
    if result.unresolved_links:
        print(f"Unresolved links: {len(result.unresolved_links)}")
        for issue in result.unresolved_links[:40]:
            print(f"  - {issue.source}: {issue.target} ({issue.message})")
    if result.ambiguous_links:
        print(f"Ambiguous links: {len(result.ambiguous_links)}")
        for issue in result.ambiguous_links[:40]:
            print(f"  - {issue.source}: {issue.target} ({issue.message})")
    if result.nav_warnings:
        print(f"Nav warnings: {len(result.nav_warnings)}")
        for warning in result.nav_warnings[:40]:
            print(f"  - {warning}")
    if not result.has_errors:
        print("Check passed")

