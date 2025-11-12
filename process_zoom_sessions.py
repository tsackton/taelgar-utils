#!/usr/bin/env python3

"""Helper to normalize + synchronize + clean batches of Zoom transcripts."""

from __future__ import annotations

import argparse
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple


REPO_ROOT = Path(__file__).resolve().parent
NORMALIZE_SCRIPT = REPO_ROOT / "normalize_transcript.py"
SYNC_SCRIPT = REPO_ROOT / "synchronize_transcripts.py"
CLEAN_SCRIPT = REPO_ROOT / "clean_speakers.py"
ZOOM_VTT_PATTERN = "GMT*.transcript.vtt"
SESSION_PREFIX = "dufr-"
METHOD_PREFIX = "zoom-session-"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch helper for processing Zoom transcripts.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--zoom-root",
        type=Path,
        help="Directory containing Zoom session subdirectories (each with a single transcript).",
    )
    group.add_argument(
        "--zoom-dir",
        type=Path,
        help="Process a single Zoom session directory.",
    )
    parser.add_argument(
        "--sessions-root",
        type=Path,
        required=True,
        help="Destination root for normalized/synchronized outputs (e.g., Dunmar/sessions).",
    )
    parser.add_argument(
        "--speaker-roster",
        type=Path,
        help="JSON mapping of raw speaker names to canonical suggestions (passed to synchronize step).",
    )
    parser.add_argument(
        "--python",
        type=Path,
        default=Path(sys.executable),
        help="Python interpreter to use for helper scripts (default: current interpreter).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the actions without executing.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    zoom_dirs = collect_zoom_dirs(args.zoom_root, args.zoom_dir)
    if not zoom_dirs:
        print("No Zoom session directories to process.")
        return 0

    sessions_root = args.sessions_root.expanduser().resolve()
    sessions_root.mkdir(parents=True, exist_ok=True)

    for zoom_dir in zoom_dirs:
        process_zoom_session(
            zoom_dir=zoom_dir,
            sessions_root=sessions_root,
            python=args.python,
            speaker_roster=args.speaker_roster,
            dry_run=args.dry_run,
        )

    return 0


def collect_zoom_dirs(root: Optional[Path], single: Optional[Path]) -> List[Path]:
    if single:
        dir_path = single.expanduser().resolve()
        return [dir_path] if dir_path.is_dir() else []
    if not root:
        return []
    root_path = root.expanduser().resolve()
    if not root_path.is_dir():
        return []
    zoom_dirs = [entry for entry in sorted(root_path.iterdir()) if entry.is_dir()]
    return zoom_dirs


def process_zoom_session(
    zoom_dir: Path,
    sessions_root: Path,
    python: Path,
    speaker_roster: Optional[Path],
    *,
    dry_run: bool,
) -> None:
    session_number = extract_session_number(zoom_dir.name)
    if not session_number:
        print(f"[skip] Could not determine session number from '{zoom_dir}'.")
        return

    vtt_path = select_zoom_vtt(zoom_dir)
    if not vtt_path:
        print(f"[skip] {zoom_dir}: missing or multiple Zoom transcripts.")
        return

    session_id = f"{SESSION_PREFIX}{session_number}"
    method_name = f"{METHOD_PREFIX}{session_number}"
    normalized_path = sessions_root / f"{session_id}.normalized.json"

    print(f"[info] Processing {zoom_dir} -> session {session_id}")

    run_command(
        [
            str(python),
            str(NORMALIZE_SCRIPT),
            str(vtt_path),
            "--input-format",
            "vtt_speaker",
            "--session-id",
            session_id,
            "--source-id",
            method_name,
            "--output",
            str(normalized_path),
        ],
        dry_run=dry_run,
    )

    sync_cmd = [
        str(python),
        str(SYNC_SCRIPT),
        "--session-id",
        session_id,
        "--method",
        method_name,
        str(normalized_path),
        "--out-dir",
        str(sessions_root),
    ]
    if speaker_roster:
        sync_cmd.extend(["--speaker-guesses", str(speaker_roster.expanduser().resolve())])
    run_command(sync_cmd, dry_run=dry_run)

    method_dir = sessions_root / session_id / method_name
    session_dir = sessions_root / session_id
    blank_roster = method_dir / f"{method_name}.speakers.blank.json"
    if dry_run:
        print(f"[info] (dry-run) Would move normalized JSON into {session_dir}")
    else:
        session_dir.mkdir(parents=True, exist_ok=True)
        target_normalized = session_dir / normalized_path.name
        try:
            shutil.move(str(normalized_path), str(target_normalized))
            print(f"[info] Moved normalized bundle to {target_normalized}")
        except FileNotFoundError:
            print(f"[warn] Normalized file missing before move: {normalized_path}")

    if not dry_run and blank_roster.exists():
        prompt = f"\nEdit {blank_roster} now. Press Enter to continue or type 'skip' to bypass speaker cleanup: "
        choice = input(prompt).strip().lower()
        if choice == "skip":
            print("[info] Skipping clean_speakers per user request.")
            return
    elif not dry_run:
        print("[warn] Blank roster not found; continuing without manual edits.")
    else:
        print("[info] (dry-run) Would pause for roster edits if present.")

    run_command(
        [
            str(python),
            str(CLEAN_SCRIPT),
            str(method_dir),
        ],
        dry_run=dry_run,
    )


def extract_session_number(name: str) -> Optional[str]:
    match = re.search(r"(\d+)", name)
    return match.group(1) if match else None


def select_zoom_vtt(zoom_dir: Path) -> Optional[Path]:
    candidates = [path for path in zoom_dir.glob(ZOOM_VTT_PATTERN) if path.is_file()]
    if len(candidates) != 1:
        return None
    return candidates[0]


def run_command(cmd: Sequence[str], *, dry_run: bool) -> None:
    printable = shlex.join(cmd)
    print(f"[cmd] {printable}")
    if dry_run:
        return
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    raise SystemExit(main())
