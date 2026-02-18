import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from pydub import AudioSegment


def chunk_audio_file(
    source_path: Path,
    destination_dir: Path,
    *,
    max_chunk_seconds: Optional[float] = 900,
    chunk_basename: Optional[str] = None,
    min_silence_len: int = 500,
    silence_thresh: int = -40,
) -> List[Dict[str, object]]:
    """
    Split ``source_path`` into audio chunks using silence midpoints and size limits.

    The steps are:
        1. Use FFmpeg ``silencedetect`` to find silence intervals (in seconds).
        2. Convert each silence to an exact midpoint (ms) and treat those as boundaries.
        3. Merge adjacent pieces until ``max_chunk_seconds`` would be exceeded.
        4. Export each chunk as 16 kHz mono PCM WAV.

    Because the boundaries are midpoints, the exported chunks cover the source audio
    exactly—no samples are trimmed or duplicated.
    """

    source_path = Path(source_path).expanduser().resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"Audio file not found: {source_path}")

    destination_dir = Path(destination_dir).expanduser().resolve()
    destination_dir.mkdir(parents=True, exist_ok=True)

    with source_path.open("rb") as source_handle:
        audio = AudioSegment.from_file(source_handle)

    silence_ranges = _detect_silences_ffmpeg(
        source_path,
        silence_thresh=silence_thresh,
        min_silence_len=min_silence_len,
    )

    initial_segments = _split_audio_on_silence(audio, silence_ranges)

    if max_chunk_seconds is None or max_chunk_seconds <= 0:
        max_chunk_ms = len(audio)
    else:
        max_chunk_ms = int(max_chunk_seconds * 1000)

    combined_segments = _combine_segments(initial_segments, max_chunk_ms)

    chunks: List[Dict[str, object]] = []
    base_name = chunk_basename or source_path.stem
    for index, segment in enumerate(combined_segments):
        start_ms, end_ms, chunk_audio = segment
        chunk_filename = destination_dir / f"{base_name}_chunk_{index:03d}.wav"
        chunk_audio = (
            chunk_audio.set_frame_rate(16_000).set_channels(1).set_sample_width(2)
        )
        export_handle = chunk_audio.export(chunk_filename, format="wav")
        export_handle.close()

        chunks.append(
            {
                "index": index,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "path": chunk_filename,
                "format": "wav",
                "bitrate": None,
                "frame_rate": chunk_audio.frame_rate,
                "channels": chunk_audio.channels,
                "sample_width": chunk_audio.sample_width,
            }
        )

    if not chunks:
        raise RuntimeError("No audio chunks were produced; check the source file.")

    return chunks
def _detect_silences_ffmpeg(
    source_path: Path,
    *,
    silence_thresh: int,
    min_silence_len: int,
) -> List[Dict[str, float]]:
    """
    Run ffmpeg ``silencedetect`` over ``source_path`` and return silence ranges.
    """

    cmd = [
        "ffmpeg",
        "-i",
        str(source_path),
        "-af",
        f"silencedetect=noise={silence_thresh}dB:d={min_silence_len/1000.0}",
        "-f",
        "null",
        "-",
    ]

    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    _, stderr = process.communicate()

    silence_starts: List[float] = []
    silence_ends: List[float] = []

    for line in stderr.splitlines():
        if "silence_start" in line:
            try:
                silence_start = float(line.split("silence_start: ")[1])
                silence_starts.append(silence_start)
            except (IndexError, ValueError):
                continue
        elif "silence_end" in line:
            parts = line.split("silence_end: ")
            if len(parts) < 2:
                continue
            try:
                silence_part = parts[1].split(" |")[0]
                silence_end = float(silence_part)
                silence_ends.append(silence_end)
            except ValueError:
                continue

    ranges: List[Dict[str, float]] = []
    for start, end in zip(silence_starts, silence_ends):
        ranges.append({"start": start, "end": end})

    return ranges


def _split_audio_on_silence(
    audio: AudioSegment,
    silence_ranges: List[Dict[str, float]],
) -> List[List[object]]:
    """Split audio at silence midpoints without trimming any content."""

    length_ms = len(audio)
    boundaries = _build_split_boundaries(length_ms, silence_ranges)
    segments: List[List[object]] = []

    for start_ms, end_ms in zip(boundaries, boundaries[1:]):
        if end_ms <= start_ms:
            continue
        chunk = audio[start_ms:end_ms]
        if len(chunk) > 0:
            segments.append([start_ms, end_ms, chunk])

    return segments


def _build_split_boundaries(
    length_ms: int,
    silence_ranges: List[Dict[str, float]],
) -> List[int]:
    boundaries = [0, length_ms]
    for silence in silence_ranges:
        start_ms = max(0, int(round(silence["start"] * 1000)))
        end_ms = min(length_ms, int(round(silence["end"] * 1000)))
        if end_ms <= start_ms:
            continue
        midpoint = int(round((start_ms + end_ms) / 2))
        if 0 < midpoint < length_ms:
            boundaries.append(midpoint)

    boundaries = sorted(set(boundaries))
    return boundaries


def _split_overlong_segments(segments: List[List[object]], max_length_ms: int) -> List[List[object]]:
    """
    Ensure no single candidate segment exceeds ``max_length_ms`` by slicing it directly.
    """

    if max_length_ms <= 0:
        return segments

    normalized: List[List[object]] = []
    for start_ms, end_ms, audio in segments:
        segment_len = len(audio)
        if segment_len <= max_length_ms:
            normalized.append([start_ms, end_ms, audio])
            continue

        offset = 0
        while offset < segment_len:
            slice_audio = audio[offset : offset + max_length_ms]
            slice_start = start_ms + offset
            slice_end = slice_start + len(slice_audio)
            if len(slice_audio) == 0:
                break
            normalized.append([slice_start, slice_end, slice_audio])
            offset += len(slice_audio)

    return normalized


def _combine_segments(segments: List[List[object]], max_length_ms: int) -> List[List[object]]:
    """
    Combine adjacent segments until they reach ``max_length_ms`` in duration.
    """

    if not segments:
        return []

    normalized_segments = _split_overlong_segments(segments, max_length_ms)
    combined: List[List[object]] = []
    current_start, current_end, current_audio = normalized_segments[0]

    for start_ms, end_ms, segment_audio in normalized_segments[1:]:
        if len(current_audio) + len(segment_audio) <= max_length_ms:
            current_audio += segment_audio
            current_end = end_ms
        else:
            combined.append([current_start, current_end, current_audio])
            current_start = start_ms
            current_end = end_ms
            current_audio = segment_audio

    combined.append([current_start, current_end, current_audio])

    if len(combined) >= 2:
        _rebalance_tail_segments(combined)

    return combined


def _rebalance_tail_segments(segments: List[List[object]], min_ratio: float = 0.75) -> None:
    """Ensure the final two chunks are roughly even to avoid tiny trailing segments."""

    if len(segments) < 2:
        return

    tail_len = len(segments[-1][2])
    max_length = len(segments[-2][2])
    if tail_len == 0 or max_length == 0:
        return

    if tail_len / max_length >= min_ratio:
        return

    prev_start, _, prev_audio = segments[-2]
    _, last_end, last_audio = segments[-1]

    merged_audio = prev_audio + last_audio
    midpoint = len(merged_audio) // 2
    first_audio = merged_audio[:midpoint]
    second_audio = merged_audio[midpoint:]

    first_end = prev_start + len(first_audio)
    second_end = first_end + len(second_audio)

    segments[-2] = [prev_start, first_end, first_audio]
    segments[-1] = [first_end, second_end, second_audio]
