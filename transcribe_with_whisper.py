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
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from dotenv import load_dotenv
from openai import OpenAI

from session_pipeline.audio_processing import AUDIO_PROFILES, AudioProcessingError, prepare_clean_audio
from session_pipeline.chunking import prepare_audio_chunks
from session_pipeline.io_utils import write_json


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
        "--min-silence-ms",
        type=int,
        default=500,
        help="Minimum silence length (ms) to trigger a split (default: 500).",
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
        "--audio-profile",
        choices=sorted(AUDIO_PROFILES.keys()),
        default="zoom-audio",
        help="Audio preprocessing profile applied before chunking (default: zoom-audio).",
    )
    parser.add_argument(
        "--discard-audio",
        action="store_true",
        help="Write preprocessed audio to a temporary file that is deleted after chunking.",
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
    parser.add_argument(
        "--max-workers",
        type=int,
        default=8,
        help="Maximum concurrent transcription requests (default: 2).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level (e.g., DEBUG, INFO).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(levelname)s %(name)s - %(message)s",
    )
    logger = logging.getLogger("transcribe_with_whisper")

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

    try:
        clean_audio_path, cleanup_path = prepare_clean_audio(
            audio_path,
            profile=args.audio_profile,
            discard=args.discard_audio,
            sample_rate=16_000,
            channels=1,
            output_format="wav",
            log_fn=lambda message: logger.info(message),
        )
    except AudioProcessingError as exc:
        parser.error(f"Failed to preprocess audio: {exc}")

    logger.info("Preparing audio chunks from %s", clean_audio_path)

    chunk_entries = prepare_audio_chunks(
        clean_audio_path,
        chunks_dir,
        manifest_path=manifest_path,
        reuse_existing=not args.force_rechunk,
        max_chunk_seconds=args.max_chunk_seconds,
        chunk_basename=f"{args.session_id}-{args.method}",
        min_silence_len=args.min_silence_ms,
        silence_thresh=args.silence_threshold,
    )

    if not chunk_entries:
        parser.error("No chunks were produced; cannot transcribe.")

    client = _build_openai_client(args.api_key)

    logger.info(
        "Transcribing %d chunk(s) with model %s using %d worker(s)...",
        len(chunk_entries),
        args.model,
        max(1, args.max_workers),
    )

    transcription_results: List[Dict[str, Any]] = []
    errors: List[Tuple[int, BaseException]] = []

    with ThreadPoolExecutor(max_workers=max(1, args.max_workers)) as executor:
        future_map = {
            executor.submit(transcribe_chunk, client, chunk, args.model): chunk
            for chunk in chunk_entries
        }
        for future in as_completed(future_map):
            chunk = future_map[future]
            chunk_path = Path(chunk["path"])
            try:
                transcript = future.result()
                out_path = transcripts_dir / f"{chunk_path.stem}.whisper.json"
                write_json(out_path, transcript)
                transcription_results.append({"chunk": chunk, "transcript": transcript})
                logger.info("Wrote chunk transcript %s", out_path)
            except Exception as exc:  # pragma: no cover - defensive logging
                errors.append((chunk.get("index"), exc))
                logger.error("Chunk %s failed: %s", chunk.get("index"), exc)

    if errors:
        raise SystemExit(f"{len(errors)} chunk(s) failed; see logs for details.")

    transcription_results.sort(key=lambda item: (item["chunk"]["start_ms"], item["chunk"]["index"]))

    merged_payload = combine_chunk_transcripts(
        transcription_results,
        session_id=args.session_id,
        method=args.method,
        manifest_path=manifest_path,
    )
    write_json(combined_path, merged_payload)

    logger.info(
        "Wrote %d chunk transcript(s) to %s", len(transcription_results), transcripts_dir
    )
    logger.info("Wrote merged transcript to %s", combined_path)

    if cleanup_path and cleanup_path.exists():
        cleanup_path.unlink(missing_ok=True)
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


def transcribe_chunk(client: OpenAI, chunk: Dict[str, Any], model: str) -> Dict[str, Any]:
    """
    Transcribe a single chunk using the OpenAI client and return the verbose JSON payload.
    """

    chunk_path = Path(chunk["path"])
    with chunk_path.open("rb") as audio_file:
        response = client.audio.transcriptions.create(
            model=model,
            file=audio_file,
            response_format="verbose_json",
            timestamp_granularities=["word"],
        )

    return _normalise_response(response)


def _normalise_response(response: Any) -> Dict[str, Any]:
    """Ensure the OpenAI response is a standard dictionary."""

    if isinstance(response, dict):
        return response
    if hasattr(response, "to_dict"):
        return response.to_dict()  # type: ignore[attr-defined]
    if hasattr(response, "model_dump"):
        return response.model_dump()  # type: ignore[attr-defined]
    if isinstance(response, (bytes, bytearray)):
        response = response.decode("utf-8")
    if isinstance(response, str):
        return json.loads(response)
    return json.loads(json.dumps(response, default=str))


def _build_openai_client(api_key_override: str | None) -> OpenAI:
    """Instantiate an OpenAI client using dotenv-backed API key discovery."""

    load_dotenv()
    api_key = api_key_override or os.getenv("OPEN_API_TAELGAR") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("OpenAI API key not found. Set OPEN_API_TAELGAR or pass --api-key.")
    return OpenAI(api_key=api_key)


if __name__ == "__main__":
    raise SystemExit(main())
