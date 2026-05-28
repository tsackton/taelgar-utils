from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from .checker import check_site
from .config import ConfigError, load_config
from .exporter import export_site


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Taelgar MkDocs website from taelgar-static.")
    parser.add_argument("--config", default="website.json", help="Path to website.json")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("check", help="Validate config, links, assets, and nav without writing files")
    subparsers.add_parser("export", help="Export taelgar-static into docs")
    subparsers.add_parser("build", help="Export, then run mkdocs build")
    subparsers.add_parser("serve", help="Export, run mkdocs build, then run mkdocs serve")
    publish_parser = subparsers.add_parser("publish", help="Run mkdocs build, commit generated site files, and push")
    publish_parser.add_argument("--message", default="autobuild", help="Commit message for publish")
    deploy_parser = subparsers.add_parser("deploy", help="Export, build, stage generated files, commit, and push")
    deploy_parser.add_argument("--message", default="autobuild", help="Commit message for deploy")

    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
    except (ConfigError, OSError, ValueError) as error:
        print(f"Config error: {error}", file=sys.stderr)
        return 2

    if args.command == "check":
        result = check_site(config)
        return 1 if result.has_errors else 0
    if args.command == "export":
        export_site(config)
        return 0
    if args.command == "build":
        export_site(config)
        return run_command(["mkdocs", "build"], config.root_dir)
    if args.command == "serve":
        export_site(config)
        rc = run_command(["mkdocs", "build"], config.root_dir)
        if rc != 0:
            return rc
        return run_command(["mkdocs", "serve"], config.root_dir)
    if args.command == "publish":
        rc = run_command(["mkdocs", "build"], config.root_dir)
        if rc != 0:
            return rc
        return publish_site(config, args.message)
    if args.command == "deploy":
        export_site(config)
        rc = run_command(["mkdocs", "build"], config.root_dir)
        if rc != 0:
            return rc
        return publish_site(config, args.message)
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


if __name__ == "__main__":
    raise SystemExit(main())
