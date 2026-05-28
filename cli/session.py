#!/usr/bin/env python3
"""Unified CLI for session pipeline tasks."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

COMMAND_TO_MODULE = {
    "preprocess-audio": "taelgar_utils.audio.preprocess",
    "transcribe-whisper": "taelgar_utils.session.transcribe.whisper",
    "transcribe-elevenlabs": "taelgar_utils.session.transcribe.elevenlabs",
    "prepare-source": "taelgar_utils.session.prepare_source",
    "normalize-source": "taelgar_utils.session.normalize_source",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Session workflow CLI")
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
