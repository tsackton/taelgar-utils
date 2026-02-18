#!/usr/bin/env python3
"""CLI entrypoint for vault tasks."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

COMMAND_TO_MODULE = {
    "export": "taelgar_utils.vault.export",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Vault workflow CLI")
    parser.add_argument("command", choices=sorted(COMMAND_TO_MODULE), default="export", nargs="?")
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
