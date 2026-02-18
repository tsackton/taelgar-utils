#!/usr/bin/env python3
"""
prepare_segments.py
====================

This script normalizes diarization outputs for a collection of chunked audio
recordings into simple speech‐activity segments. It reads a CSV manifest
describing each chunk, computes per‐chunk offsets based on the actual duration
of each audio file, merges adjacent diarization intervals with small gaps, and
writes unified JSON segment files for each chunk and for each entire session
(chunk group). Optionally, a raw audio mapping CSV can be supplied so the script
can verify that the cumulative chunk duration matches the original source audio
within a small tolerance.

The manifest CSV must contain the following columns:

    chunk_group,chunk_order,audio_path,diarization_path

* **chunk_group**: Identifier for the logical recording (e.g. session name).
* **chunk_order**: Integer order of the chunk within the group (0‑based or 1‑based).
* **audio_path**: Path to the chunked audio file on disk.
* **diarization_path**: Path to a diarization JSON or WebVTT file for that chunk.

The script performs these steps for each chunk group:

1. Compute a per‑chunk offset manifest. The offset for the first chunk is 0.
   Subsequent offsets are the cumulative sum of the previous chunk lengths.
   Each chunk’s duration is measured directly by loading the audio file (so
   offsets stay consistent regardless of diarization output). If the script
   cannot determine the length of an audio file, it falls back to using the
   maximum end time found in the diarization. Offsets are cached to disk to
   avoid recomputation.

2. Load diarization files. Diarization JSON files may contain either a list of
   dictionaries with "start"/"end" (and an optional "speaker" field), a
   dictionary with a "segments" list, or Zoom diarization objects shaped like
   ``{"speaker": "...", "segment": {"start": 1.23, "end": 4.56}}``. WebVTT
   files are parsed to extract cue start and end times along with a speaker
   name (if present). For our purposes, the speaker label is used only to merge
   adjacent intervals; it is not retained in the final output.

3. Normalize the diarization: merge adjacent intervals with the same
   speaker id when the gap between them is less than a configurable
   threshold (default: 0.25 seconds). The merged intervals are output in
   a simple JSON array of objects with "start" and "end" keys (float
   seconds).

4. (Optional) When ``--raw-audio-mapping`` is provided, check that the summed
   chunk durations align with the raw source audio length (within a few
   seconds). The resulting offsets JSON records the source metadata plus the
   duration delta in milliseconds for easy auditing.

5. Write two kinds of JSON files per chunk group:
   - Per‑chunk normalized segments (with chunk‑relative times).
   - Merged segments for the entire session, where each segment's
     timestamps are adjusted by the offset of its chunk.

Usage:

    python prepare_segments.py \
        --manifest manifest.csv \
        --output-dir out_dir \
        [--gap-threshold 0.25] [--force] [--raw-audio-mapping raw_mapping.csv]

This script requires the Python standard library plus ``pydub`` (for computing
chunk durations).
"""

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydub import AudioSegment

SOURCE_DURATION_TOLERANCE_SECONDS = 3.0


def parse_time(time_str: str) -> float:
    """Convert a HH:MM:SS.mmm or MM:SS.mmm timestamp to seconds."""
    try:
        parts = time_str.strip().split(":")
        parts = [float(p) for p in parts]
        # If hours are supplied, three parts; if only minutes and seconds, two parts.
        if len(parts) == 3:
            hours, minutes, seconds = parts
        elif len(parts) == 2:
            hours = 0.0
            minutes, seconds = parts
        else:
            raise ValueError(f"Unrecognized timestamp format: {time_str}")
        return hours * 3600 + minutes * 60 + seconds
    except Exception as exc:
        raise ValueError(f"Failed to parse timestamp '{time_str}': {exc}") from exc


def load_vtt_segments(path: str) -> List[Tuple[str, float, float]]:
    """
    Load segments from a WebVTT file.

    Returns a list of tuples (speaker_id, start, end). The speaker_id
    is extracted from the cue text if possible (by splitting on ':'),
    otherwise 'Unknown' is used. Only cues with valid timestamps are
    returned.
    """
    segments = []
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if "-->" in line:
            # timestamp line
            try:
                start_str, end_str = [s.strip() for s in line.split("-->")]
                start = parse_time(start_str)
                end = parse_time(end_str.split(" ")[0])  # ignore any settings after time
                # Next non‑blank line is the cue text
                j = i + 1
                text = ""
                while j < len(lines) and lines[j].strip() == "":
                    j += 1
                if j < len(lines):
                    text = lines[j].strip()
                # Extract speaker if text contains ':'
                speaker = "Unknown"
                if ":" in text:
                    spk, _ = text.split(":", 1)
                    speaker = spk.strip()
                segments.append((speaker, start, end))
            except Exception:
                # Skip malformed cues
                pass
        i += 1
    return segments


def _segments_from_items(items: List[Dict[str, Any]]) -> List[Tuple[str, float, float]]:
    segments: List[Tuple[str, float, float]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        segment = item.get("segment")
        start_val: Optional[float] = None
        end_val: Optional[float] = None
        if isinstance(segment, dict):
            start_val = segment.get("start")
            end_val = segment.get("end")
        else:
            start_val = item.get("start")
            end_val = item.get("end")
        if start_val is None or end_val is None:
            continue
        try:
            start = float(start_val)
            end = float(end_val)
        except Exception:
            continue
        if end < start:
            continue
        speaker = item.get("speaker") or item.get("speaker_id") or "Unknown"
        segments.append((str(speaker), start, end))
    return segments


def _segments_from_words(words: List[Dict[str, Any]]) -> List[Tuple[str, float, float]]:
    """
    Convert ElevenLabs-style word arrays into contiguous speaker segments.
    """
    segments: List[Tuple[str, float, float]] = []
    current_speaker: Optional[str] = None
    current_start: Optional[float] = None
    current_end: Optional[float] = None

    def flush_current() -> None:
        nonlocal current_speaker, current_start, current_end
        if current_speaker is None or current_start is None or current_end is None:
            return
        segments.append((current_speaker, current_start, current_end))
        current_speaker = None
        current_start = None
        current_end = None

    for word in words:
        if not isinstance(word, dict):
            continue
        word_type = (word.get("type") or "").lower()
        if word_type == "spacing":
            continue
        speaker = (
            word.get("speaker_id")
            or word.get("speaker")
            or word.get("speaker_label")
        )
        start_val = word.get("start")
        end_val = word.get("end")
        if speaker is None or start_val is None or end_val is None:
            continue
        try:
            start = float(start_val)
            end = float(end_val)
        except Exception:
            continue
        if end < start:
            continue
        speaker = str(speaker)
        if current_speaker is None:
            current_speaker = speaker
            current_start = start
            current_end = end
            continue
        if speaker == current_speaker and current_end is not None:
            # Extend the active span for contiguous words.
            current_end = max(current_end, end)
            continue
        flush_current()
        current_speaker = speaker
        current_start = start
        current_end = end

    flush_current()
    return segments


def load_json_segments(path: str) -> List[Tuple[str, float, float]]:
    """
    Load segments from a diarization JSON file.

    Returns a list of tuples (speaker_id, start, end). Recognizes multiple
    common formats:

    1. A top‑level list where each element is a dict containing
       'start', 'end' and either 'speaker' or 'speaker_id'.
    2. A top‑level dict with a 'segments' list containing objects with
       the same fields.
    3. ElevenLabs transcription JSON where speech is stored under a
       'words' array with per-word 'speaker_id', 'start', and 'end'.

    Extra keys in the objects are ignored. If a speaker label is
    missing, 'Unknown' is used. Times are converted to floats.
    """
    with open(path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except Exception as exc:
            raise ValueError(f"Failed to parse JSON from {path}: {exc}")
    segments: List[Tuple[str, float, float]] = []
    items: Optional[List[Dict[str, Any]]] = None
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        if "segments" in data:
            seg_items = data.get("segments")
            if isinstance(seg_items, list):
                items = seg_items  # type: ignore[assignment]
        elif "words" in data:
            words = data.get("words")
            if isinstance(words, list):
                return _segments_from_words(words)  # type: ignore[arg-type]
    if items is None:
        raise ValueError(f"Unrecognized diarization JSON format in {path}")
    else:
        return _segments_from_items(items)


def load_diar_segments(path: str) -> List[Tuple[str, float, float]]:
    if path.lower().endswith(".vtt"):
        return load_vtt_segments(path)
    return load_json_segments(path)


def merge_segments_by_speaker(
    segments: List[Tuple[str, float, float]], gap_thresh: float
) -> List[Tuple[float, float]]:
    """
    Merge adjacent segments when they belong to the same speaker and the
    gap between them is less than or equal to `gap_thresh` seconds.

    The input list must contain tuples of (speaker_id, start, end). The
    returned list contains tuples of (start, end) for the merged
    segments, discarding the speaker identifiers.
    """
    # Sort by start time
    segments_sorted = sorted(segments, key=lambda x: x[1])
    merged: List[Tuple[float, float]] = []
    current_speaker: Optional[str] = None
    current_start: Optional[float] = None
    current_end: Optional[float] = None
    for speaker, start, end in segments_sorted:
        # If this is the first segment, initialise current
        if current_speaker is None:
            current_speaker = speaker
            current_start = start
            current_end = end
            continue
        assert current_start is not None and current_end is not None
        # If same speaker and gap small, extend the current segment
        if speaker == current_speaker and start - current_end <= gap_thresh:
            # Extend the end time
            current_end = max(current_end, end)
        else:
            # Finalize current segment
            merged.append((current_start, current_end))
            # Start new segment
            current_speaker = speaker
            current_start = start
            current_end = end
    # Append the last one
    if current_speaker is not None:
        assert current_start is not None and current_end is not None
        merged.append((current_start, current_end))
    return merged


def compute_audio_duration(
    audio_path: str, diar_segments: Optional[List[Tuple[str, float, float]]] = None
) -> float:
    """
    Determine the duration of ``audio_path`` in seconds by decoding the file.

    Falls back to the maximum diarization end time when the audio cannot be
    loaded (and diarization segments are available).
    """
    try:
        audio = AudioSegment.from_file(audio_path)
        return len(audio) / 1000.0
    except Exception as exc:
        print(f"Warning: failed to load audio {audio_path} for duration: {exc}", file=sys.stderr)
    if diar_segments:
        return max((end for _, _, end in diar_segments), default=0.0)
    return 0.0


def register_offset_keys(offsets: Dict[str, float], audio_path: str, offset: float) -> None:
    """
    Track ``offset`` under multiple path representations for reliable lookups.
    """
    resolved = Path(audio_path).expanduser()
    if not resolved.is_absolute():
        resolved = (Path.cwd() / resolved).resolve()
    else:
        resolved = resolved.resolve()
    candidates = {
        audio_path,
        str(resolved),
        resolved.name,
        os.path.basename(audio_path),
    }
    for candidate in candidates:
        if candidate:
            offsets[candidate] = offset


def offsets_from_payload(data: Any) -> Dict[str, float]:
    """
    Convert an offsets JSON payload into a lookup map keyed by various path forms.
    """
    offsets: Dict[str, float] = {}
    if isinstance(data, dict) and "files" in data:
        for entry in data.get("files", []):
            path_val = entry.get("path") or entry.get("audio_path") or entry.get("source_path")
            offset = entry.get("offset_seconds")
            if path_val is None or offset is None:
                continue
            register_offset_keys(offsets, path_val, float(offset))
            source_path = entry.get("source_path")
            if source_path:
                register_offset_keys(offsets, source_path, float(offset))
    elif isinstance(data, dict):
        for path_val, offset in data.items():
            try:
                register_offset_keys(offsets, path_val, float(offset))
            except Exception:
                continue
    else:
        raise ValueError("Unrecognized offsets JSON structure.")
    return offsets


def ensure_dir(path: str) -> None:
    """Create directory if it does not exist."""
    os.makedirs(path, exist_ok=True)


def load_source_audio_map(path: Path) -> Dict[str, str]:
    """
    Load a chunk_group -> source audio path mapping from a two-column CSV.
    """
    mapping: Dict[str, str] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"chunk_group", "source_file"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(f"{path} must contain columns: chunk_group, source_file")
        for row in reader:
            chunk_group = row.get("chunk_group")
            audio_path = row.get("source_file")
            if not chunk_group or not audio_path:
                continue
            mapping[chunk_group] = audio_path
    return mapping


def process_manifest(
    manifest_path: str,
    output_dir: str,
    gap_thresh: float,
    force: bool,
    raw_audio_mapping: Optional[str],
) -> None:
    """
    Main processing function.

    Reads the manifest CSV, computes offsets, loads and normalizes
    diarization files, and writes JSON outputs.
    """
    # Read manifest
    rows = []
    with open(manifest_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required_cols = {"chunk_group", "chunk_order", "audio_path", "diarization_path"}
        for col in required_cols:
            if col not in reader.fieldnames:
                raise ValueError(f"Manifest is missing required column '{col}'")
        for row in reader:
            # Normalise integer order
            try:
                order = int(row["chunk_order"])
            except Exception:
                order = int(float(row["chunk_order"]))
            rows.append(
                {
                    "chunk_group": row["chunk_group"],
                    "order": order,
                    "audio_path": row["audio_path"],
                    "diar_path": row["diarization_path"],
                }
            )

    # Group rows by chunk_group
    groups: Dict[str, List[Dict]] = {}
    for row in rows:
        groups.setdefault(row["chunk_group"], []).append(row)

    # Ensure output subdirectories exist
    per_chunk_dir = os.path.join(output_dir, "per_chunk")
    per_session_dir = os.path.join(output_dir, "per_session")
    offsets_dir = os.path.join(output_dir, "offsets")
    ensure_dir(per_chunk_dir)
    ensure_dir(per_session_dir)
    ensure_dir(offsets_dir)

    source_map: Dict[str, str] = {}
    if raw_audio_mapping:
        source_map = load_source_audio_map(Path(raw_audio_mapping).expanduser().resolve())

    # Process each group
    for chunk_group, group_rows in groups.items():
        print(f"Processing chunk group: {chunk_group}", file=sys.stderr)
        # Sort by order
        group_rows = sorted(group_rows, key=lambda r: r["order"])
        # Determine offset manifest path
        offset_path = os.path.join(offsets_dir, f"{chunk_group}_offsets.json")
        if force and os.path.exists(offset_path):
            try:
                os.remove(offset_path)
            except OSError as exc:
                print(f"Warning: failed to remove cached offsets {offset_path}: {exc}", file=sys.stderr)
        offsets: Dict[str, float] = {}
        diar_cache: Dict[str, List[Tuple[str, float, float]]] = {}

        def get_diar_segments(path: str) -> List[Tuple[str, float, float]]:
            if path not in diar_cache:
                try:
                    diar_cache[path] = load_diar_segments(path)
                except Exception as exc:
                    print(f"Warning: failed to load diarization {path}: {exc}", file=sys.stderr)
                    diar_cache[path] = []
            return diar_cache[path]
        # Attempt to load existing offsets
        if not force and os.path.exists(offset_path):
            try:
                with open(offset_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                offsets = offsets_from_payload(data)
                # Validate that all audio paths are present
                missing = [
                    r["audio_path"]
                    for r in group_rows
                    if r["audio_path"] not in offsets and os.path.basename(r["audio_path"]) not in offsets
                ]
                if missing:
                    print(
                        f"Offset file {offset_path} missing entries for {len(missing)} chunks; recomputing.",
                        file=sys.stderr,
                    )
                    offsets = {}
            except Exception:
                offsets = {}
        if not offsets:
            offsets = {}
            offset_entries: List[Dict[str, Any]] = []
            cumulative_offset = 0.0
            source_info: Optional[Dict[str, Any]] = None
            source_path = source_map.get(chunk_group)
            source_duration = None
            if source_path:
                try:
                    source_duration = compute_audio_duration(source_path)
                    source_info = {
                        "source_file": str(Path(source_path).expanduser().resolve()),
                        "source_duration_seconds": round(source_duration, 6),
                    }
                except Exception as exc:
                    print(f"Warning: failed to compute source duration for {chunk_group}: {exc}", file=sys.stderr)

            for r in group_rows:
                diar_segments = get_diar_segments(r["diar_path"])
                duration = compute_audio_duration(r["audio_path"], diar_segments)
                register_offset_keys(offsets, r["audio_path"], cumulative_offset)
                offset_entries.append(
                    {
                        "path": str(Path(r["audio_path"]).expanduser().resolve()),
                        "chunk_order": r["order"],
                        "offset_seconds": round(cumulative_offset, 6),
                        "duration_seconds": round(duration, 6),
                    }
                )
                cumulative_offset += duration
            diff_ms = None
            if source_info and source_duration is not None:
                diff_seconds = cumulative_offset - source_duration
                diff_ms = round(diff_seconds * 1000.0, 3)
                source_info["chunk_sum_duration_seconds"] = round(cumulative_offset, 6)
                source_info["duration_diff_milliseconds"] = diff_ms
                if abs(diff_seconds) > SOURCE_DURATION_TOLERANCE_SECONDS:
                    print(
                        f"Warning: chunk sum vs source mismatch for {chunk_group}: {diff_seconds:.2f}s",
                        file=sys.stderr,
                    )
            payload = {
                "chunk_group": chunk_group,
                "files": offset_entries,
                "total_duration_seconds": round(cumulative_offset, 6),
            }
            if source_info:
                payload["source_info"] = source_info
            try:
                with open(offset_path, "w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=2)
            except Exception as exc:
                print(f"Failed to write offsets for {chunk_group}: {exc}", file=sys.stderr)

        # Process chunks
        aggregated_segments: List[Tuple[float, float]] = []
        for r in group_rows:
            audio_path = r["audio_path"]
            diar_path = r["diar_path"]
            diar_segments = get_diar_segments(diar_path)
            # Merge segments by speaker
            merged = merge_segments_by_speaker(diar_segments, gap_thresh)
            # Write per-chunk normalized JSON
            chunk_base = os.path.splitext(os.path.basename(audio_path))[0]
            out_chunk_path = os.path.join(per_chunk_dir, f"{chunk_base}_segments.json")
            try:
                with open(out_chunk_path, "w", encoding="utf-8") as f:
                    json.dump([{"start": s, "end": e} for s, e in merged], f, indent=2)
            except Exception as exc:
                print(f"Warning: failed to write per-chunk segments {out_chunk_path}: {exc}", file=sys.stderr)
            # Add to aggregated list
            offset = offsets.get(audio_path)
            if offset is None:
                offset = offsets.get(os.path.basename(audio_path), 0.0)
            for s, e in merged:
                aggregated_segments.append((s + offset, e + offset))
        # Merge aggregated segments (union) to avoid overlaps and gaps
        aggregated_segments_sorted = sorted(aggregated_segments, key=lambda x: x[0])
        merged_agg: List[Tuple[float, float]] = []
        for seg in aggregated_segments_sorted:
            if not merged_agg:
                merged_agg.append(seg)
                continue
            last_start, last_end = merged_agg[-1]
            cur_start, cur_end = seg
            # If overlapping or small gap <= gap_thresh, merge
            if cur_start <= last_end + gap_thresh:
                merged_agg[-1] = (last_start, max(last_end, cur_end))
            else:
                merged_agg.append(seg)
        # Write per-session merged JSON
        session_out_path = os.path.join(per_session_dir, f"{chunk_group}_merged_segments.json")
        if force and os.path.exists(session_out_path):
            try:
                os.remove(session_out_path)
            except OSError as exc:
                print(f"Warning: failed to remove prior session segments {session_out_path}: {exc}", file=sys.stderr)
        try:
            with open(session_out_path, "w", encoding="utf-8") as f:
                json.dump([{"start": s, "end": e} for s, e in merged_agg], f, indent=2)
        except Exception as exc:
            print(f"Failed to write session segments {session_out_path}: {exc}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Normalize diarization into simple segments.")
    parser.add_argument("--manifest", type=str, required=True, help="CSV manifest with chunk info")
    parser.add_argument(
        "--output-dir",
        type=str,
        required=True,
        help="Directory where per-chunk, per-session and offsets JSONs will be written",
    )
    parser.add_argument(
        "--gap-threshold",
        type=float,
        default=0.25,
        help="Maximum gap in seconds for merging adjacent segments belonging to the same speaker",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite cached offsets and per-session outputs for the manifest chunk groups.",
    )
    parser.add_argument(
        "--raw-audio-mapping",
        type=str,
        help="Optional CSV with chunk_group/source_file to verify total duration vs. chunk sum.",
    )
    args = parser.parse_args()
    process_manifest(args.manifest, args.output_dir, args.gap_threshold, args.force, args.raw_audio_mapping)


if __name__ == "__main__":
    main()
