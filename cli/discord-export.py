#!/usr/bin/env python3
"""CLI entrypoint for Discord export utilities."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    repo_root = Path(__file__).resolve().parents[1]
    src_root = repo_root / "src"

    env = os.environ.copy()
    env["PYTHONPATH"] = (
        str(src_root)
        if not env.get("PYTHONPATH")
        else f"{src_root}:{env['PYTHONPATH']}"
    )

    cmd = [sys.executable, "-m", "taelgar_utils.utilities.discord_export", *args]
    completed = subprocess.run(cmd, env=env, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
