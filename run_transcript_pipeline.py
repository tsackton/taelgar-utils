#!/usr/bin/env python3

"""Run normalize -> synchronise pipeline from a manifest."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


REPO_ROOT = Path(__file__).resolve().parent
NORMALIZE_SCRIPT = REPO_ROOT / "normalize_transcript.py"
SYNC_SCRIPT = REPO_ROOT / "synchronize_transcripts.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run normalize+sync pipeline using a manifest.")
    parser.add_argument("manifest", type=Path, help="Path to the manifest JSON file.")
    parser.add_argument(
        "--skip-sync",
        action="store_true",
        help="Only run normalization steps; skip synchronization phase.",
    )
    parser.add_argument(
        "--python",
        type=Path,
        default=Path(sys.executable),
        help="Python interpreter to use (default: current interpreter).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))

    session_id = manifest.get("session_id")
    methods_out_dir = manifest.get("methods_out_dir") or manifest.get("out_dir")
    normalize_entries: List[Dict[str, Any]] = manifest.get("normalize") or []
    method_entries: List[Dict[str, Any]] = manifest.get("methods") or []

    if not normalize_entries:
        raise SystemExit("Manifest missing 'normalize' entries.")

    normalized_outputs: List[Path] = []
    for entry in normalize_entries:
        output_path = run_normalize_entry(entry, args.python)
        normalized_outputs.append(output_path)

    if args.skip_sync or not method_entries:
        return 0

    run_methods(method_entries, session_id, args.python, methods_out_dir)
    return 0


def run_normalize_entry(entry: Dict[str, Any], python: Path) -> Path:
    required_keys = {"input", "input_format"}
    missing = required_keys - entry.keys()
    if missing:
        raise SystemExit(f"Normalize entry missing required keys: {missing}")

    input_path = Path(entry["input"]).expanduser().resolve()
    input_format = entry["input_format"]
    session_id = entry.get("session_id")
    output = entry.get("output")
    if output:
        output_path = Path(output).expanduser().resolve()
    else:
        if session_id:
            output_path = input_path.parent / f"{session_id}-{input_format}-normalized.json"
        else:
            output_path = input_path.with_suffix(".normalized.json")

    cmd = [str(python), str(NORMALIZE_SCRIPT), str(input_path), "--input-format", input_format]

    optional_flags = {
        "session_id": "--session-id",
        "source_id": "--source-id",
        "offset": "--offset",
        "word_gap_seconds": "--word-gap-seconds",
        "offsets_json": "--offsets-json",
        "audio_path": "--audio-path",
    }
    for key, flag in optional_flags.items():
        if key in entry:
            cmd.extend([flag, str(entry[key])])

    if entry.get("diarization"):
        cmd.extend(["--diarization", str(Path(entry["diarization"]).expanduser().resolve())])

    if output:
        cmd.extend(["--output", str(output_path)])

    run_command(cmd)
    return output_path


def run_methods(
    method_entries: List[Dict[str, Any]],
    session_id: Optional[str],
    python: Path,
    out_dir_override: Optional[str],
) -> None:
    if not session_id:
        raise SystemExit("Manifest must include 'session_id' when defining methods.")

    cmd: List[str] = [str(python), str(SYNC_SCRIPT), "--session-id", session_id]
    out_dir = out_dir_override

    for method in method_entries:
        name = method.get("name")
        inputs = method.get("inputs") or []
        if not name or not inputs:
            raise SystemExit("Each method entry must include 'name' and non-empty 'inputs'.")
        cmd.append("--method")
        cmd.append(name)
        for inp in inputs:
            cmd.append(str(Path(inp).expanduser().resolve()))
        if method.get("out_dir") and out_dir is None:
            out_dir = method["out_dir"]

    if out_dir:
        cmd.extend(["--out-dir", str(out_dir)])

    run_command(cmd)


def run_command(cmd: List[str]) -> None:
    print("Running:", " ".join(shlex.quote(part) for part in cmd))
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    raise SystemExit(main())
