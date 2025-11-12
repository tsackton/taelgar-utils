#!/usr/bin/env python3

"""
Chunk a session recording and transcribe each piece with OpenAI Whisper/GPT-STT.

Outputs:
    - Individual chunk transcripts (<method>/chunk_transcripts/*.whisper.json)
    - A merged transcript (<method>/<method>.whisper.json) with absolute timestamps
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from dotenv import load_dotenv
from openai import OpenAI

from session_pipeline.chunking import prepare_audio_chunks
from session_pipeline.io_utils import write_json
from session_pipeline.transcription import transcribe_audio_chunks


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Split an audio file into chunks and transcribe each chunk with OpenAI Whisper."
    )
    parser.add_argument("audio_path", type=Path, help="Path to the source audio file.")
    parser.add_argument("--session-id", required=True, help="Canonical session identifier (e.g., dufr-138).")
    parser.add_argument("--method", required=True, help="Method/prefix for the outputs (e.g., whisper-r1).")
    parser.add_argument(
        "--out-dir",
        required=True,
        type=Path,
        help="Root output directory; transcripts are written under <out-dir>/<session>/<method>/.",
    )
    parser.add_argument(
        "--model",
        default="whisper-1",
        help="OpenAI speech-to-text model (default: whisper-1).",
    )
    parser.add_argument(
        "--max-chunk-seconds",
        type=float,
        default=900.0,
        help="Maximum chunk length in seconds (default: 900s / 15 minutes).",
    )
    parser.add_argument(
        "--chunk-format",
        choices=["wav", "mp3", "ogg"],
        default="wav",
        help="Export format for chunked audio (default: wav).",
    )
    parser.add_argument(
        "--chunk-bitrate",
        help="Optional bitrate (e.g., 192k) when exporting compressed formats.",
    )
    parser.add_argument(
        "--sample-rate",
        type=int,
        default=16_000,
        help="Target sample rate for chunks (default: 16_000 Hz; use 0 to keep original).",
    )
    parser.add_argument(
        "--channels",
        type=int,
        default=1,
        help="Target channel count for chunks (default: mono; use 0 to keep original).",
    )
    parser.add_argument(
        "--min-silence-ms",
        type=int,
        default=1000,
        help="Minimum silence length (ms) to trigger a split (default: 1000).",
    )
    parser.add_argument(
        "--keep-silence-ms",
        type=int,
        default=500,
        help="Silence padding (ms) retained around each split (default: 500).",
    )
    parser.add_argument(
        "--silence-threshold",
        type=int,
        default=-40,
        help="Silence threshold in dBFS (default: -40).",
    )
    parser.add_argument(
        "--chunk-dir",
        type=Path,
        help="Optional explicit directory for chunked audio (defaults to <method>/chunks).",
    )
    parser.add_argument(
        "--force-rechunk",
        action="store_true",
        help="Ignore existing chunk manifests and regenerate chunks.",
    )
    parser.add_argument(
        "--api-key",
        help="Optional OpenAI API key override (defaults to OPEN_API_TAELGAR or OPENAI_API_KEY in the environment).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    audio_path = args.audio_path.expanduser().resolve()
    if not audio_path.exists():
        parser.error(f"Audio file not found: {audio_path}")

    session_dir = args.out_dir.expanduser().resolve() / args.session_id
    method_dir = session_dir / args.method
    chunks_dir = (args.chunk_dir or (method_dir / "chunks")).expanduser().resolve()
    transcripts_dir = method_dir / "chunk_transcripts"
    manifest_path = method_dir / "chunk_manifest.json"
    combined_path = method_dir / f"{args.method}.whisper.json"

    method_dir.mkdir(parents=True, exist_ok=True)
    transcripts_dir.mkdir(parents=True, exist_ok=True)

    chunk_entries = prepare_audio_chunks(
        audio_path,
        chunks_dir,
        manifest_path=manifest_path,
        reuse_existing=not args.force_rechunk,
        max_chunk_seconds=args.max_chunk_seconds,
        target_format=args.chunk_format,
        target_frame_rate=_optional_positive(args.sample_rate),
        target_channels=_optional_positive(args.channels),
        target_sample_width=2,
        target_bitrate=args.chunk_bitrate,
        chunk_basename=f"{args.session_id}-{args.method}",
        min_silence_len=args.min_silence_ms,
        silence_thresh=args.silence_threshold,
        keep_silence=args.keep_silence_ms,
        normalise=True,
    )

    if not chunk_entries:
        parser.error("No chunks were produced; cannot transcribe.")

    client = _build_openai_client(args.api_key)

    print(f"[info] Transcribing {len(chunk_entries)} chunk(s) with model {args.model}...")
    results = transcribe_audio_chunks(
        client=client,
        chunks=chunk_entries,
        model=args.model,
        response_format="verbose_json",
        timestamp_granularities=["word"],
    )

    if not results:
        parser.error("Transcription produced no results.")

    chunk_transcript_paths: List[Path] = []
    for item in results:
        chunk = item["chunk"]
        transcript = item["transcript"]
        chunk_path = Path(chunk["path"])
        transcript_path = transcripts_dir / f"{chunk_path.stem}.whisper.json"
        write_json(transcript_path, transcript)
        chunk_transcript_paths.append(transcript_path)

    merged_payload = combine_chunk_transcripts(
        results,
        session_id=args.session_id,
        method=args.method,
        manifest_path=manifest_path,
    )
    write_json(combined_path, merged_payload)

    print(f"[info] Wrote {len(chunk_transcript_paths)} chunk transcript(s) to {transcripts_dir}")
    print(f"[info] Wrote merged transcript to {combined_path}")
    return 0


def combine_chunk_transcripts(
    results: List[Dict[str, Any]],
    *,
    session_id: str,
    method: str,
    manifest_path: Path,
) -> Dict[str, Any]:
    """
    Combine per-chunk verbose_json payloads into a single session-level transcript.
    """

    combined_segments: List[Dict[str, Any]] = []
    combined_words: List[Dict[str, Any]] = []
    combined_texts: List[str] = []
    metadata_chunks: List[Dict[str, Any]] = []
    language = None
    model_name = None
    max_end = 0.0

    for item in results:
        chunk = item["chunk"]
        transcript = item["transcript"]
        chunk_path = Path(chunk["path"])
        start_ms = int(chunk.get("start_ms", 0))
        end_ms = int(chunk.get("end_ms", start_ms))
        offset = start_ms / 1000.0
        chunk_duration = max(0.0, (end_ms - start_ms) / 1000.0)

        metadata_chunks.append(
            {
                "index": chunk.get("index"),
                "path": str(chunk_path),
                "offset_seconds": round(offset, 6),
                "duration_seconds": round(chunk_duration, 6),
            }
        )

        text = (transcript.get("text") or "").strip()
        if text:
            combined_texts.append(text)
        language = language or transcript.get("language")
        model_name = model_name or transcript.get("model")

        segments = transcript.get("segments") or []
        words_from_segments = False
        if segments:
            for segment in segments:
                seg_copy = dict(segment)
                seg_start = float(segment.get("start", 0.0))
                seg_end = float(segment.get("end", seg_start))
                seg_copy["start"] = round(offset + seg_start, 6)
                seg_copy["end"] = round(offset + seg_end, 6)
                adjusted_words: List[Dict[str, Any]] = []
                for word in segment.get("words") or []:
                    word_copy = dict(word)
                    word_start = float(word.get("start", seg_start))
                    word_end = float(word.get("end", word_start))
                    word_copy["start"] = round(offset + word_start, 6)
                    word_copy["end"] = round(offset + word_end, 6)
                    adjusted_words.append(word_copy)
                    combined_words.append(word_copy)
                if adjusted_words:
                    words_from_segments = True
                seg_copy["words"] = adjusted_words
                combined_segments.append(seg_copy)
                max_end = max(max_end, seg_copy["end"])

        if not words_from_segments:
            words = transcript.get("words") or []
            for word in words:
                word_copy = dict(word)
                word_start = float(word.get("start", 0.0))
                word_end = float(word.get("end", word_start))
                word_copy["start"] = round(offset + word_start, 6)
                word_copy["end"] = round(offset + word_end, 6)
                combined_words.append(word_copy)
                max_end = max(max_end, word_copy["end"])

        max_end = max(max_end, offset + chunk_duration)

    combined_segments.sort(key=lambda seg: seg.get("start", 0.0))
    combined_words.sort(key=lambda word: (word.get("start", 0.0), word.get("end", 0.0)))

    combined_payload: Dict[str, Any] = {
        "text": "\n\n".join(combined_texts).strip(),
        "language": language,
        "model": model_name,
        "duration": round(max_end, 6),
        "segments": combined_segments,
        "words": combined_words,
        "metadata": {
            "session_id": session_id,
            "method": method,
            "chunk_manifest": str(manifest_path),
            "chunks": metadata_chunks,
        },
    }
    return combined_payload


def _build_openai_client(api_key_override: str | None) -> OpenAI:
    """Instantiate an OpenAI client using dotenv-backed API key discovery."""

    load_dotenv()
    api_key = api_key_override or os.getenv("OPEN_API_TAELGAR") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("OpenAI API key not found. Set OPEN_API_TAELGAR or pass --api-key.")
    return OpenAI(api_key=api_key)


def _optional_positive(value: int) -> Optional[int]:
    """Return ``value`` if positive; otherwise return None."""

    if value and value > 0:
        return value
    return None


if __name__ == "__main__":
    raise SystemExit(main())
