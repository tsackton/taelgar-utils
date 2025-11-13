#!/usr/bin/env python3

"""Helper to normalize + synchronize + clean batches of Zoom transcripts."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydub import AudioSegment
from webvtt import Caption, WebVTT

from session_pipeline.runner_utils import move_file, prompt_for_roster_edit, run_cli
from session_pipeline.time_utils import format_timestamp, parse_vtt_timestamp


REPO_ROOT = Path(__file__).resolve().parent
NORMALIZE_SCRIPT = REPO_ROOT / "normalize_transcript.py"
SYNC_SCRIPT = REPO_ROOT / "synchronize_transcripts.py"
CLEAN_SCRIPT = REPO_ROOT / "clean_speakers.py"
ZOOM_VTT_PATTERN = "GMT*.transcript.vtt"
DEFAULT_SESSION_PREFIX = "dufr-"
METHOD_PREFIX = "zoom-session-"
AUDIO_EXTENSIONS = [".mp4", ".m4a", ".m4v", ".mov", ".wav", ".mp3"]


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
    parser.add_argument(
        "--session-prefix",
        default=DEFAULT_SESSION_PREFIX,
        help=f"Prefix used when building session IDs (default: {DEFAULT_SESSION_PREFIX!r}).",
    )
    parser.add_argument(
        "--skip-merge",
        action="store_true",
        help="If multiple Zoom transcripts exist, skip automatic merging (session will be skipped).",
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
            session_prefix=args.session_prefix,
            skip_merge=args.skip_merge,
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
    session_prefix: str,
    skip_merge: bool,
    dry_run: bool,
) -> None:
    session_number = extract_session_number(zoom_dir.name)
    if not session_number:
        print(f"[skip] Could not determine session number from '{zoom_dir}'.")
        return

    vtt_path = prepare_zoom_vtt(zoom_dir, skip_merge=skip_merge)
    if not vtt_path:
        print(f"[skip] {zoom_dir}: missing usable Zoom transcript.")
        return

    session_id = f"{session_prefix}{session_number}"
    method_name = f"{METHOD_PREFIX}{session_number}"
    session_dir = sessions_root / session_id
    method_dir = session_dir / method_name
    if method_dir.exists():
        print(f"[skip] {method_dir} already exists; skipping.")
        return
    normalized_path = sessions_root / f"{session_id}.normalized.json"

    print(f"[info] Processing {zoom_dir} -> session {session_id}")

    run_cli(
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
    run_cli(sync_cmd, dry_run=dry_run)

    blank_roster = method_dir / f"{method_name}.speakers.blank.json"
    target_normalized = session_dir / normalized_path.name
    move_file(normalized_path, target_normalized, dry_run=dry_run)

    if not prompt_for_roster_edit(blank_roster, dry_run=dry_run):
        return

    run_cli(
        [
            str(python),
            str(CLEAN_SCRIPT),
            str(method_dir),
        ],
        dry_run=dry_run,
    )


def extract_session_number(name: str) -> Optional[str]:
    match = re.search(r"(\d+)", name)
    return match.group(1).zfill(3) if match else None


def prepare_zoom_vtt(zoom_dir: Path, *, skip_merge: bool) -> Optional[Path]:
    vtt_files = sorted(path for path in zoom_dir.glob(ZOOM_VTT_PATTERN) if path.is_file())
    if not vtt_files:
        return None
    if len(vtt_files) == 1:
        return vtt_files[0]

    if skip_merge:
        print(
            f"[warn] Found {len(vtt_files)} Zoom transcripts in {zoom_dir}; "
            "skipping automatic merge per --skip-merge."
        )
        return None

    entries = build_chunk_entries(vtt_files)
    if not entries:
        return None

    merged_path = zoom_dir / "merged.transcript.vtt"
    merge_vtt_entries(entries, merged_path)

    order_summary = ", ".join(
        f"{entry['path'].name} ({entry['duration']:.1f}s)" for entry in entries
    )
    print(f"[info] Merged Zoom transcripts into {merged_path.name}: {order_summary}")
    return merged_path


def build_chunk_entries(vtt_files: List[Path]) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for vtt in vtt_files:
        audio_match = find_matching_audio(vtt)
        duration = None
        if audio_match:
            duration = get_audio_duration_seconds(audio_match)
        if duration is None:
            duration = estimate_vtt_duration_seconds(vtt)
        entries.append(
            {
                "path": vtt,
                "duration": duration,
            }
        )

    if not entries:
        return []

    entries.sort(key=lambda item: (-item["duration"], item["path"].name))
    offset = 0.0
    for entry in entries:
        entry["offset"] = offset
        offset += entry["duration"]
    return entries


def find_matching_audio(vtt_path: Path) -> Optional[Path]:
    name = vtt_path.name
    if name.endswith(".transcript.vtt"):
        base = name[: -len(".transcript.vtt")]
    else:
        base = vtt_path.stem
    for ext in AUDIO_EXTENSIONS:
        candidate = vtt_path.with_name(base + ext)
        if candidate.exists():
            return candidate
    return None


def get_audio_duration_seconds(audio_path: Path) -> Optional[float]:
    try:
        audio = AudioSegment.from_file(audio_path)
        return len(audio) / 1000.0
    except Exception as exc:  # pragma: no cover - best-effort logging
        print(f"[warn] Failed to inspect {audio_path}: {exc}")
        return None


def estimate_vtt_duration_seconds(vtt_path: Path) -> float:
    vtt = WebVTT().read(str(vtt_path))
    max_end = 0.0
    for caption in vtt:
        max_end = max(max_end, parse_vtt_timestamp(caption.end))
    return max_end


def merge_vtt_entries(entries: List[Dict[str, Any]], output_path: Path) -> None:
    merged = WebVTT()
    for entry in entries:
        offset = entry["offset"]
        src_vtt = WebVTT().read(str(entry["path"]))
        for caption in src_vtt:
            start_seconds = parse_vtt_timestamp(caption.start) + offset
            end_seconds = parse_vtt_timestamp(caption.end) + offset
            merged.captions.append(
                Caption(
                    start=format_timestamp(start_seconds),
                    end=format_timestamp(end_seconds),
                    text=caption.text,
                )
            )
    merged.save(str(output_path))


if __name__ == "__main__":
    raise SystemExit(main())
