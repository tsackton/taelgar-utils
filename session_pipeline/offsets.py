"""Helpers for resolving audio offsets relative to a full session."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional


def determine_offset(
    *,
    manual_offset: Optional[float],
    offsets_json: Optional[Path],
    audio_path: Optional[Path],
) -> float:
    """
    Determine the absolute offset for an audio chunk.

    Preference order:
      1. Use ``offsets_json`` (from ``get_audio_offsets.py``) when both it and
         ``audio_path`` are provided.
      2. Fall back to ``manual_offset`` when specified.
      3. Default to zero.
    """

    if offsets_json:
        if not audio_path:
            raise SystemExit("--audio-path is required when using --offsets-json")
        offsets_map = load_offsets_map(offsets_json)
        resolved = resolve_path(audio_path)
        basename = Path(resolved).name
        if resolved in offsets_map:
            return offsets_map[resolved]
        if basename in offsets_map:
            return offsets_map[basename]
        raise SystemExit(
            f"Audio path {resolved} (or basename {basename}) not found in offsets JSON {offsets_json}"
        )

    if manual_offset is not None:
        return float(manual_offset)

    return 0.0


def load_offsets_map(path: Path) -> Dict[str, float]:
    """
    Load offsets from ``path`` and return a map of absolute/basename paths to offsets.
    """

    data = json.loads(path.read_text(encoding="utf-8"))
    offsets: Dict[str, float] = {}
    for entry in data.get("files", []):
        file_path = entry.get("path")
        offset = entry.get("offset_seconds")
        if file_path is None or offset is None:
            continue
        resolved = resolve_path(file_path)
        offsets[resolved] = float(offset)
        offsets[Path(resolved).name] = float(offset)
    return offsets


def resolve_path(path: Path | str) -> str:
    """Expand and absolute-ize ``path`` consistently for offset lookups."""

    resolved = Path(path).expanduser()
    if not resolved.is_absolute():
        resolved = (Path.cwd() / resolved).resolve()
    else:
        resolved = resolved.resolve()
    return str(resolved)


__all__ = [
    "determine_offset",
    "load_offsets_map",
    "resolve_path",
]
