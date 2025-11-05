"""
Audio-centric helpers shared across pipeline stages.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from pydub import AudioSegment


@dataclass(frozen=True)
class AudioChunk:
    """
    Metadata about a chunked audio file that has been exported to disk.

    Attributes:
        index: Zero-based index of the chunk.
        start_ms: Start position of the chunk relative to the source audio.
        end_ms: End position of the chunk relative to the source audio.
        path: Filesystem path to the exported audio chunk.
        format: Container/codec format name (e.g. ``"mp3"`` or ``"wav"``).
    """

    index: int
    start_ms: int
    end_ms: int
    path: Path
    format: str


def chunk_audio_file(
    source_path: Path,
    destination_dir: Path,
    *,
    max_chunk_seconds: Optional[int] = 900,
    target_format: str = "wav",
    target_frame_rate: Optional[int] = 16000,
    target_channels: Optional[int] = 1,
    target_sample_width: Optional[int] = 2,
) -> List[AudioChunk]:
    """
    Split ``source_path`` into smaller files written inside ``destination_dir``.

    The helper optionally normalises the audio to a mono, 16 kHz signal so the
    downstream transcription call stays within model limits.
    """

    if max_chunk_seconds is not None and max_chunk_seconds <= 0:
        raise ValueError("max_chunk_seconds must be greater than zero when provided")

    source_path = Path(source_path).expanduser().resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"Audio file not found: {source_path}")

    destination_dir = Path(destination_dir).expanduser().resolve()
    destination_dir.mkdir(parents=True, exist_ok=True)

    audio = AudioSegment.from_file(source_path)

    if target_channels is not None:
        audio = audio.set_channels(target_channels)
    if target_frame_rate is not None:
        audio = audio.set_frame_rate(target_frame_rate)
    if target_sample_width is not None:
        audio = audio.set_sample_width(target_sample_width)

    total_length_ms = len(audio)
    if max_chunk_seconds is None:
        chunk_length_ms = total_length_ms
    else:
        chunk_length_ms = max_chunk_seconds * 1000

    chunks: List[AudioChunk] = []
    base_name = source_path.stem

    for index, start_ms in enumerate(range(0, total_length_ms, chunk_length_ms)):
        end_ms = min(start_ms + chunk_length_ms, total_length_ms)
        segment = audio[start_ms:end_ms]

        chunk_filename = destination_dir / f"{base_name}_chunk_{index:03d}.{target_format}"
        segment.export(chunk_filename, format=target_format)

        chunks.append(
            AudioChunk(
                index=index,
                start_ms=start_ms,
                end_ms=end_ms,
                path=chunk_filename,
                format=target_format,
            )
        )

    if not chunks:
        raise RuntimeError("No audio chunks were produced; check the source file.")

    return chunks
