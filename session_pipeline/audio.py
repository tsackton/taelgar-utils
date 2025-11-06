import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from pydub import AudioSegment


def chunk_audio_file(
    source_path: Path,
    destination_dir: Path,
    *,
    max_chunk_seconds: Optional[float] = 900,
    target_format: str = "mp3",
    target_frame_rate: Optional[int] = None,
    target_channels: Optional[int] = None,
    target_sample_width: Optional[int] = None,
    target_bitrate: Optional[str] = "192k",
    chunk_basename: Optional[str] = None,
    min_silence_len: int = 1000,
    silence_thresh: int = -40,
    keep_silence: int = 500,
) -> List[Dict[str, object]]:
    """
    Split ``source_path`` into audio chunks using silence detection and size limits.

    The logic follows ``split_clean_audio.py`` closely:
        1. Normalise the audio to a stable level.
        2. Use FFmpeg ``silencedetect`` to find long silent spans (in seconds).
        3. Split on those silences, retaining a small buffer of context.
        4. Recombine segments until ``max_chunk_seconds`` would be exceeded.
        5. Export each chunk as ``target_format`` with ``target_bitrate`` when applicable.

    Returns metadata dictionaries describing each chunk.
    """

    source_path = Path(source_path).expanduser().resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"Audio file not found: {source_path}")

    destination_dir = Path(destination_dir).expanduser().resolve()
    destination_dir.mkdir(parents=True, exist_ok=True)

    audio = AudioSegment.from_file(source_path)
    audio = _normalise_audio(audio)

    silence_ranges = _detect_silences_ffmpeg(
        source_path,
        silence_thresh=silence_thresh,
        min_silence_len=min_silence_len,
    )

    initial_segments = _split_audio_on_silence(audio, silence_ranges, keep_silence=keep_silence)

    if max_chunk_seconds is None or max_chunk_seconds <= 0:
        max_chunk_ms = len(audio)
    else:
        max_chunk_ms = int(max_chunk_seconds * 1000)

    combined_segments = _combine_segments(initial_segments, max_chunk_ms)

    chunks: List[Dict[str, object]] = []
    base_name = chunk_basename or source_path.stem
    for index, segment in enumerate(combined_segments):
        start_ms, end_ms, chunk_audio = segment
        chunk_filename = destination_dir / f"{base_name}_chunk_{index:03d}.{target_format}"
        export_kwargs = {}
        if target_format in {"mp3", "ogg"} and target_bitrate:
            export_kwargs["bitrate"] = target_bitrate
        if target_frame_rate is not None:
            chunk_audio = chunk_audio.set_frame_rate(target_frame_rate)
        if target_channels is not None:
            chunk_audio = chunk_audio.set_channels(target_channels)
        if target_sample_width is not None:
            chunk_audio = chunk_audio.set_sample_width(target_sample_width)

        chunk_audio.export(chunk_filename, format=target_format, **export_kwargs)

        chunks.append(
            {
                "index": index,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "path": chunk_filename,
                "format": target_format,
                "bitrate": target_bitrate,
            }
        )

    if not chunks:
        raise RuntimeError("No audio chunks were produced; check the source file.")

    return chunks


def _normalise_audio(audio: AudioSegment, target_dbfs: float = -10.0, headroom: float = 1.0) -> AudioSegment:
    change_in_dbfs = target_dbfs - audio.dBFS
    normalised = audio.apply_gain(change_in_dbfs)
    peak_dbfs = normalised.max_dBFS
    if peak_dbfs > (-headroom):
        clipping_gain = (-headroom) - peak_dbfs
        normalised = normalised.apply_gain(clipping_gain)
    return normalised


def _detect_silences_ffmpeg(
    source_path: Path,
    *,
    silence_thresh: int,
    min_silence_len: int,
) -> List[Dict[str, float]]:
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
    *,
    keep_silence: int,
) -> List[List[object]]:
    segments: List[List[object]] = []
    previous_end_ms = 0

    for silence in silence_ranges:
        start_ms = int(silence["start"] * 1000)
        start_ms = max(0, start_ms - keep_silence)
        if start_ms > previous_end_ms:
            chunk = audio[previous_end_ms:start_ms]
            if len(chunk) > 0:
                segments.append([previous_end_ms, start_ms, chunk])
        end_ms = int(silence["end"] * 1000)
        end_ms = min(len(audio), end_ms + keep_silence)
        previous_end_ms = end_ms

    if previous_end_ms < len(audio):
        chunk = audio[previous_end_ms:]
        if len(chunk) > 0:
            segments.append([previous_end_ms, previous_end_ms + len(chunk), chunk])

    return segments


def _combine_segments(segments: List[List[object]], max_length_ms: int) -> List[List[object]]:
    if not segments:
        return []

    combined: List[List[object]] = []
    current_start, current_end, current_audio = segments[0]

    for start_ms, end_ms, segment_audio in segments[1:]:
        if len(current_audio) + len(segment_audio) <= max_length_ms:
            current_audio += segment_audio
            current_end = end_ms
        else:
            combined.append([current_start, current_end, current_audio])
            current_start = start_ms
            current_end = end_ms
            current_audio = segment_audio

    combined.append([current_start, current_end, current_audio])

    return combined
