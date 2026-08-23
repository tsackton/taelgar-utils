from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from .checker import check_site
from .comment_blocks import CommentBlockError
from .config import ConfigError, load_config
from .exporter import export_site


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Taelgar MkDocs website from taelgar-static.")
    parser.add_argument("--config", default="website.json", help="Path to website.json")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("check", help="Validate config, links, assets, and nav without writing files")
    subparsers.add_parser("export", help="Export taelgar-static into docs")
    subparsers.add_parser("build", help="Export, then run mkdocs build")
    subparsers.add_parser("serve", help="Export, then run mkdocs serve")
    publish_parser = subparsers.add_parser("publish", help="Commit generated site files and push")
    publish_parser.add_argument("--message", default="autobuild", help="Commit message for publish")
    deploy_parser = subparsers.add_parser("deploy", help="Export, stage generated files, commit, and push")
    deploy_parser.add_argument("--message", default="autobuild", help="Commit message for deploy")

    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
    except (ConfigError, OSError, ValueError) as error:
        print(f"Config error: {error}", file=sys.stderr)
        return 2

    try:
        if args.command == "check":
            result = check_site(config)
            return 1 if result.has_errors else 0
        if args.command == "export":
            export_site(config)
            return 0
        if args.command == "build":
            stats = export_site(config)
            rc = run_command(["mkdocs", "build"], config.root_dir)
            if rc == 0:
                print_zoomable_html_paths(config, stats.zoomable_pages)
            return rc
        if args.command == "serve":
            export_site(config)
            return run_command(["mkdocs", "serve"], config.root_dir)
        if args.command == "publish":
            return publish_site(config, args.message)
        if args.command == "deploy":
            export_site(config)
            return publish_site(config, args.message)
    except CommentBlockError as error:
        print(f"Content filtering error: {error}", file=sys.stderr)
        return 2
    return 2


def publish_site(config, message: str) -> int:
    stage_targets = [config.docs_dir, config.overrides_dir, config.config_path, config.root_dir / "mkdocs.yml"]
    rc = run_command(["git", "add", *[str(path) for path in stage_targets if path is not None and Path(path).exists()]], config.root_dir)
    if rc != 0:
        return rc
    rc = run_command(["git", "commit", "-m", message], config.root_dir)
    if rc != 0:
        return rc
    return run_command(["git", "push"], config.root_dir)


def run_command(command: list[str], cwd: Path) -> int:
    print("+ " + " ".join(command))
    return subprocess.run(command, cwd=cwd).returncode


def print_zoomable_html_paths(config: Any, pages: list[Path]) -> None:
    if not pages:
        return
    site_dir, use_directory_urls = mkdocs_output_config(config.root_dir)
    print("Zoomable session HTML:")
    for page in pages:
        print(f"  - {site_dir / html_path_for_markdown(page, use_directory_urls)}")


def mkdocs_output_config(root_dir: Path) -> tuple[Path, bool]:
    mkdocs_path = root_dir / "mkdocs.yml"
    site_dir = root_dir / "site"
    use_directory_urls = True
    if not mkdocs_path.exists():
        return site_dir, use_directory_urls
    payload = yaml.safe_load(mkdocs_path.read_text(encoding="utf-8")) or {}
    if isinstance(payload, dict):
        raw_site_dir = payload.get("site_dir")
        if isinstance(raw_site_dir, str) and raw_site_dir.strip():
            candidate = Path(raw_site_dir.strip())
            site_dir = candidate if candidate.is_absolute() else root_dir / candidate
        if isinstance(payload.get("use_directory_urls"), bool):
            use_directory_urls = bool(payload["use_directory_urls"])
    return site_dir, use_directory_urls


def html_path_for_markdown(path: Path, use_directory_urls: bool) -> Path:
    if path.name == "index.md":
        return path.with_suffix(".html")
    if use_directory_urls:
        return path.with_suffix("") / "index.html"
    return path.with_suffix(".html")


if __name__ == "__main__":
    raise SystemExit(main())
