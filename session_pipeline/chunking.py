"""Helpers for preparing and caching audio chunks for transcription pipelines."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from session_pipeline.audio import chunk_audio_file


ChunkEntry = Dict[str, Any]


def prepare_audio_chunks(
    audio_path: Path,
    chunks_dir: Path,
    *,
    manifest_path: Path,
    reuse_existing: bool = True,
    max_chunk_seconds: Optional[float] = 900.0,
    chunk_basename: Optional[str] = None,
    min_silence_len: int = 500,
    silence_thresh: int = -40,
) -> List[ChunkEntry]:
    """
    Ensure ``audio_path`` is split into chunks and tracked via ``manifest_path``.

    If ``reuse_existing`` is True and the manifest lists valid chunk files,
    those entries are reused; otherwise the audio is re-chunked with the
    provided parameters.
    """

    chunks_dir = chunks_dir.expanduser().resolve()
    chunks_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_path.expanduser().resolve()

    if reuse_existing:
        existing = _load_chunk_manifest(manifest_path)
        if existing:
            return existing

    fresh_chunks = chunk_audio_file(
        audio_path,
        chunks_dir,
        max_chunk_seconds=max_chunk_seconds,
        chunk_basename=chunk_basename,
        min_silence_len=min_silence_len,
        silence_thresh=silence_thresh,
    )

    normalized_entries: List[ChunkEntry] = []
    for entry in fresh_chunks:
        chunk_path = Path(entry["path"]).expanduser().resolve()
        normalized_entries.append(
            {
                "index": int(entry["index"]),
                "start_ms": int(entry["start_ms"]),
                "end_ms": int(entry["end_ms"]),
                "path": str(chunk_path),
                "format": entry.get("format"),
                "bitrate": entry.get("bitrate"),
                "frame_rate": entry.get("frame_rate"),
                "channels": entry.get("channels"),
                "sample_width": entry.get("sample_width"),
            }
        )

    _write_chunk_manifest(manifest_path, normalized_entries)
    return _convert_manifest_entries(normalized_entries)


def _load_chunk_manifest(manifest_path: Path) -> List[ChunkEntry]:
    """Load chunk metadata from ``manifest_path`` if it exists and is valid."""
    if not manifest_path.exists():
        return []
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []

    if not isinstance(raw, list):
        return []

    entries: List[ChunkEntry] = []
    for item in raw:
        if not isinstance(item, dict):
            return []
        try:
            chunk_path = Path(item["path"]).expanduser()
            index = int(item["index"])
            start_ms = int(item["start_ms"])
            end_ms = int(item["end_ms"])
        except (KeyError, ValueError, TypeError):
            return []
        if not chunk_path.exists():
            return []
        entry = {
            "index": index,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "path": chunk_path.resolve(),
            "format": item.get("format"),
            "bitrate": item.get("bitrate"),
            "frame_rate": item.get("frame_rate"),
            "channels": item.get("channels"),
            "sample_width": item.get("sample_width"),
        }
        entries.append(entry)

    entries.sort(key=lambda item: item["index"])
    return entries


def _write_chunk_manifest(manifest_path: Path, entries: List[ChunkEntry]) -> None:
    """Persist ``entries`` to ``manifest_path`` as JSON."""
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    serializable = []
    for entry in entries:
        serializable.append(
            {
                "index": entry["index"],
                "start_ms": entry["start_ms"],
                "end_ms": entry["end_ms"],
                "path": str(entry["path"]),
                "format": entry.get("format"),
                "bitrate": entry.get("bitrate"),
                "frame_rate": entry.get("frame_rate"),
                "channels": entry.get("channels"),
                "sample_width": entry.get("sample_width"),
            }
        )
    manifest_path.write_text(json.dumps(serializable, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _convert_manifest_entries(entries: List[ChunkEntry]) -> List[ChunkEntry]:
    """Normalise manifest entries so each contains resolved ``Path`` objects."""
    converted: List[ChunkEntry] = []
    for entry in entries:
        converted.append(
            {
                "index": int(entry["index"]),
                "start_ms": int(entry["start_ms"]),
                "end_ms": int(entry["end_ms"]),
                "path": Path(entry["path"]).expanduser().resolve(),
                "format": entry.get("format"),
                "bitrate": entry.get("bitrate"),
                "frame_rate": entry.get("frame_rate"),
                "channels": entry.get("channels"),
                "sample_width": entry.get("sample_width"),
            }
        )
    converted.sort(key=lambda item: item["index"])
    return converted


__all__ = ["prepare_audio_chunks"]
