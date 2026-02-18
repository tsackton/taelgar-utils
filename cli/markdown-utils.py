#!/usr/bin/env python3
"""CLI entrypoint for markdown utility tasks."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

COMMAND_TO_MODULE = {
    "merge": "taelgar_utils.markdown.merge",
    "extract": "taelgar_utils.markdown.extract_yaml_fields",
    "make-index": "taelgar_utils.markdown.index_page",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Markdown utilities CLI")
    parser.add_argument("command", choices=sorted(COMMAND_TO_MODULE))
    parser.add_argument("args", nargs=argparse.REMAINDER, help="Arguments passed to the selected command")
    parsed = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[1]
    src_root = repo_root / "src"

    env = os.environ.copy()
    env["PYTHONPATH"] = (
        str(src_root)
        if not env.get("PYTHONPATH")
        else f"{src_root}:{env['PYTHONPATH']}"
    )

    module = COMMAND_TO_MODULE[parsed.command]
    cmd = [sys.executable, "-m", module, *parsed.args]
    completed = subprocess.run(cmd, env=env, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
