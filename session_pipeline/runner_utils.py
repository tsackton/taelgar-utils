"""Utilities that support runner/orchestration scripts."""

from __future__ import annotations

import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Sequence


def run_cli(command: Sequence[str | Path], *, dry_run: bool = False) -> None:
    """
    Print and optionally execute ``command`` using ``subprocess.run``.
    """

    printable = shlex.join(str(part) for part in command)
    print(f"[cmd] {printable}")
    if dry_run:
        return
    resolved = [str(part) for part in command]
    subprocess.run(resolved, check=True)


def move_file(source: Path, destination: Path, *, dry_run: bool = False) -> None:
    """
    Move ``source`` to ``destination`` (creating parents). Safe in dry-run mode.
    """

    if dry_run:
        print(f"[info] (dry-run) Would move {source} -> {destination}")
        return

    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.move(str(source), str(destination))
        print(f"[info] Moved {source} -> {destination}")
    except FileNotFoundError:
        print(f"[warn] Source file missing before move: {source}")


def prompt_for_roster_edit(blank_roster: Path, *, dry_run: bool = False) -> bool:
    """
    Ask the user whether to pause for roster edits; return False to skip cleanup.
    """

    if dry_run:
        if blank_roster.exists():
            print(f"[info] (dry-run) Would pause for roster edits at {blank_roster}")
        else:
            print("[info] (dry-run) Would continue without roster edits (file missing).")
        return True

    if blank_roster.exists():
        prompt = (
            f"\nEdit {blank_roster} now. "
            "Press Enter to continue or type 'skip' to bypass speaker cleanup: "
        )
        choice = input(prompt).strip().lower()
        if choice == "skip":
            print("[info] Skipping clean_speakers per user request.")
            return False
        return True

    print("[warn] Blank roster not found; continuing without manual edits.")
    return True


__all__ = ["move_file", "prompt_for_roster_edit", "run_cli"]
