"""
Split a session recording into silence-aware chunks and transcribe each with Whisper.

Example:
    python3 transcribe_session_audio.py session_audio.mp3 --prefix outputs/session-135
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from openai import OpenAI

from session_pipeline import chunk_audio_file, transcribe_audio_chunks


def _optional_positive_int(value: Optional[int]) -> Optional[int]:
    if value is None:
        return None
    return value if value > 0 else None


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Chunk a session recording on silence and transcribe each piece with OpenAI Whisper.",
    )
    parser.add_argument("input_path", type=Path, help="Path to the source audio file.")
    parser.add_argument(
        "--prefix",
        required=True,
        type=Path,
        help="Directory where outputs will be written (chunks, transcripts, logs).",
    )
    parser.add_argument(
        "--min-silence-len",
        "-m",
        type=int,
        default=1000,
        help="Minimum silence length in ms to consider for a split (default: 1000).",
    )
    parser.add_argument(
        "--silence-thresh",
        "-s",
        type=int,
        default=-40,
        help="Silence threshold in dBFS (default: -40).",
    )
    parser.add_argument(
        "--keep-silence",
        "-k",
        type=int,
        default=500,
        help="Silence in ms to retain around each split (default: 500).",
    )
    parser.add_argument(
        "--max-length",
        "-x",
        type=float,
        default=15.0,
        help="Maximum chunk length in minutes (default: 15.0).",
    )
    parser.add_argument(
        "--model",
        default="whisper-1",
        help="Speech-to-text model to invoke (default: whisper-1).",
    )
    parser.add_argument(
        "--chunk-format",
        "-f",
        default="mp3",
        choices=["mp3", "wav", "ogg"],
        help="Output audio format (default: mp3).",
    )
    parser.add_argument(
        "--bitrate",
        "-b",
        default="192k",
        help="Bitrate for MP3 export (default: 192k).",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=2,
        help="Maximum concurrent transcription requests (default: 2).",
    )
    parser.add_argument(
        "--sample-rate",
        type=int,
        default=0,
        help="Target sample rate for exported chunks. Set to 0 to keep original.",
    )
    parser.add_argument(
        "--channels",
        type=int,
        default=0,
        help="Target channel count for exported chunks. Set to 0 to keep original.",
    )
    parser.add_argument(
        "--high-precision",
        action="store_true",
        help="Emit verbose_json transcripts with word-level timestamps instead of VTT.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level (DEBUG, INFO, WARNING, ...).",
    )
    parser.add_argument(
        "--api-key",
        help="Optional OpenAI API key override. Otherwise loads OPEN_API_TAELGAR from .env or falls back to default OpenAI env vars.",
    )
    return parser


def perform_transcription(args: argparse.Namespace) -> Dict[str, Any]:
    prefix_dir = Path(args.prefix).expanduser().resolve()
    prefix_dir.mkdir(parents=True, exist_ok=True)
    chunks_dir = prefix_dir / "chunks"
    transcripts_dir = prefix_dir / "transcripts"
    for directory in (chunks_dir, transcripts_dir):
        directory.mkdir(parents=True, exist_ok=True)

    log_file = prefix_dir / "transcribe.log"

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(levelname)s %(name)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, mode="w", encoding="utf-8"),
        ],
        force=True,
    )
    logger = logging.getLogger("transcribe_session_audio")

    max_chunk_seconds = args.max_length * 60 if args.max_length else None
    target_sample_rate = _optional_positive_int(args.sample_rate)
    target_channels = _optional_positive_int(args.channels)

    load_dotenv()

    client_kwargs: Dict[str, Any] = {}
    api_key = (
        args.api_key
        or os.getenv("OPEN_API_TAELGAR")
        or os.getenv("OPENAI_API_KEY")
    )
    if api_key:
        client_kwargs["api_key"] = api_key

    client = OpenAI(**client_kwargs)

    chunk_manifest_path = prefix_dir / "chunk_manifest.json"

    def _load_existing_chunks() -> List[Dict[str, Any]]:
        try:
            data = json.loads(chunk_manifest_path.read_text())
        except (json.JSONDecodeError, FileNotFoundError):
            return []

        chunk_entries: List[Dict[str, Any]] = []
        missing_files = False
        for entry in data:
            try:
                chunk_path = Path(entry["path"])
                chunk_entries.append(
                    {
                        "index": int(entry["index"]),
                        "start_ms": int(entry["start_ms"]),
                        "end_ms": int(entry["end_ms"]),
                        "path": chunk_path,
                        "format": entry.get("format"),
                        "bitrate": entry.get("bitrate"),
                    }
                )
                if not chunk_path.exists():
                    missing_files = True
            except (KeyError, TypeError, ValueError):
                missing_files = True
        if missing_files:
            logger.warning("Chunk manifest references missing or invalid files; regenerating chunks.")
            return []
        chunk_entries.sort(key=lambda item: item["index"])
        return chunk_entries

    def _create_chunks() -> List[Dict[str, Any]]:
        logger.info("Chunking audio into %s", chunks_dir)
        fresh_chunks = chunk_audio_file(
            args.input_path,
            chunks_dir,
            max_chunk_seconds=max_chunk_seconds,
            target_format=args.chunk_format,
            target_frame_rate=target_sample_rate,
            target_channels=target_channels,
            target_bitrate=args.bitrate,
            chunk_basename=prefix_dir.name,
            min_silence_len=args.min_silence_len,
            silence_thresh=args.silence_thresh,
            keep_silence=args.keep_silence,
        )

        chunk_entries: List[Dict[str, Any]] = []
        for entry in fresh_chunks:
            chunk_entries.append(
                {
                    "index": entry["index"],
                    "start_ms": entry["start_ms"],
                    "end_ms": entry["end_ms"],
                    "path": entry["path"],
                    "format": entry.get("format"),
                    "bitrate": entry.get("bitrate"),
                }
            )
        chunk_entries.sort(key=lambda item: item["index"])

        manifest_payload = [
            {
                "index": entry["index"],
                "start_ms": entry["start_ms"],
                "end_ms": entry["end_ms"],
                "path": str(entry["path"]),
                "format": entry.get("format"),
                "bitrate": entry.get("bitrate"),
            }
            for entry in chunk_entries
        ]
        chunk_manifest_path.write_text(json.dumps(manifest_payload, indent=2), encoding="utf-8")
        logger.info("Created %d chunk(s)", len(chunk_entries))
        return chunk_entries

    chunks = _load_existing_chunks()
    if chunks:
        logger.info("Using %d existing chunk(s)", len(chunks))
    else:
        chunks = _create_chunks()

    response_format = "verbose_json" if args.high_precision else "vtt"
    timestamp_granularities = ["word"] if args.high_precision else None
    transcript_extension = ".json" if response_format == "verbose_json" else ".vtt"

    manifest_path = prefix_dir / "transcription_manifest.json"
    chunk_metadata_map: Dict[int, Dict[str, Any]] = {}
    if manifest_path.exists():
        try:
            existing_manifest = json.loads(manifest_path.read_text())
            for entry in existing_manifest.get("chunks", []):
                try:
                    idx = int(entry["index"])
                except (KeyError, TypeError, ValueError):
                    continue
                chunk_metadata_map[idx] = entry
        except json.JSONDecodeError:
            logger.warning("Existing manifest is invalid; it will be rebuilt.")

    valid_indexes = {entry["index"] for entry in chunks}
    chunk_metadata_map = {idx: meta for idx, meta in chunk_metadata_map.items() if idx in valid_indexes}

    manifest_base = {
        "source_audio": str(args.input_path.resolve()),
        "output_prefix": str(prefix_dir),
        "model": args.model,
        "response_format": response_format,
        "timestamp_granularities": timestamp_granularities,
        "chunk_format": args.chunk_format,
        "chunk_bitrate": args.bitrate,
        "max_chunk_minutes": args.max_length,
        "min_silence_len": args.min_silence_len,
        "silence_thresh": args.silence_thresh,
        "keep_silence": args.keep_silence,
        "chunk_count": len(chunks),
        "chunks_dir": str(chunks_dir),
        "transcripts_dir": str(transcripts_dir),
        "log_path": str(log_file),
    }

    manifest_lock = threading.Lock()

    def write_manifest_locked() -> Dict[str, Any]:
        manifest_data = dict(manifest_base)
        ordered = [chunk_metadata_map[idx] for idx in sorted(chunk_metadata_map)]
        cleaned: List[Dict[str, Any]] = []
        for item in ordered:
            entry = dict(item)
            entry["index"] = int(entry.get("index", 0))
            entry["audio_path"] = str(entry.get("audio_path", ""))
            entry["transcript_path"] = str(entry.get("transcript_path", ""))
            entry["metadata_path"] = str(entry.get("metadata_path", ""))
            cleaned.append(entry)
        manifest_data["chunks"] = cleaned
        manifest_path.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")
        return manifest_data

    def record_metadata(index: int, metadata: Dict[str, Any]) -> Dict[str, Any]:
        with manifest_lock:
            chunk_metadata_map[index] = metadata
            return write_manifest_locked()

    pending_chunks: List[Dict[str, Any]] = []
    for chunk in chunks:
        chunk_index = chunk["index"]
        base_name = f"{prefix_dir.name}_chunk_{chunk_index:03d}"
        transcript_path = transcripts_dir / f"{base_name}{transcript_extension}"
        metadata_path = transcripts_dir / f"{base_name}.metadata.json"

        if transcript_path.exists():
            logger.info("Skipping chunk %s; transcript already exists.", chunk_index)
            try:
                metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
            except json.JSONDecodeError:
                metadata = {}
            metadata.update(
                {
                    "index": chunk_index,
                    "audio_path": str(chunk["path"]),
                    "start_ms": chunk["start_ms"],
                    "end_ms": chunk["end_ms"],
                    "duration_ms": chunk["end_ms"] - chunk["start_ms"],
                    "format": chunk.get("format"),
                    "bitrate": chunk.get("bitrate"),
                    "transcript_path": str(transcript_path),
                    "metadata_path": str(metadata_path),
                    "response_format": response_format,
                    "status": metadata.get("status", "existing"),
                }
            )
            if timestamp_granularities:
                metadata["timestamp_granularities"] = timestamp_granularities
            metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            record_metadata(chunk_index, metadata)
            continue

        pending_chunks.append(
            {
                "index": chunk_index,
                "start_ms": chunk["start_ms"],
                "end_ms": chunk["end_ms"],
                "path": chunk["path"],
                "format": chunk.get("format"),
                "bitrate": chunk.get("bitrate"),
                "base_name": base_name,
                "transcript_path": transcript_path,
                "metadata_path": metadata_path,
            }
        )

    def process_chunk(entry: Dict[str, Any]) -> None:
        chunk_payload = {
            "index": entry["index"],
            "start_ms": entry["start_ms"],
            "end_ms": entry["end_ms"],
            "path": entry["path"],
            "format": entry.get("format"),
            "bitrate": entry.get("bitrate"),
        }

        logger.info("Transcribing chunk %s (%s)", entry["index"], Path(entry["path"]).name)
        result = transcribe_audio_chunks(
            client,
            [chunk_payload],
            model=args.model,
            response_format=response_format,
            timestamp_granularities=timestamp_granularities,
        )[0]

        transcript = result["transcript"]
        transcript_path: Path = entry["transcript_path"]
        metadata_path: Path = entry["metadata_path"]

        if response_format == "vtt":
            transcript_path.write_text(transcript, encoding="utf-8")
        else:
            transcript_path.write_text(json.dumps(transcript, indent=2), encoding="utf-8")

        metadata = {
            "index": entry["index"],
            "audio_path": str(entry["path"]),
            "start_ms": entry["start_ms"],
            "end_ms": entry["end_ms"],
            "duration_ms": entry["end_ms"] - entry["start_ms"],
            "format": entry.get("format"),
            "bitrate": entry.get("bitrate"),
            "transcript_path": str(transcript_path),
            "metadata_path": str(metadata_path),
            "response_format": response_format,
            "status": "transcribed",
        }
        if timestamp_granularities:
            metadata["timestamp_granularities"] = timestamp_granularities

        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        record_metadata(entry["index"], metadata)

    if pending_chunks:
        max_workers = max(1, min(args.max_workers, len(pending_chunks)))
        logger.info(
            "Transcribing %d pending chunk(s) with up to %d worker(s)",
            len(pending_chunks),
            max_workers,
        )
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(process_chunk, entry): entry for entry in pending_chunks}
            for future in as_completed(futures):
                entry = futures[future]
                try:
                    future.result()
                    logger.info("Chunk %s transcribed", entry["index"])
                except Exception as exc:
                    logger.error("Chunk %s failed: %s", entry["index"], exc)
                    raise
    else:
        logger.info("No pending chunks to transcribe.")

    with manifest_lock:
        final_manifest = write_manifest_locked()

    logger.info("Manifest written to %s", manifest_path)
    logger.info(
        "Processed %d/%d chunk transcripts",
        len(chunk_metadata_map),
        len(chunks),
    )

    return final_manifest


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    try:
        manifest = perform_transcription(args)
    except Exception as exc:  # pragma: no cover - defensive logging
        logging.getLogger("transcribe_session_audio").exception("transcription failed")
        parser.error(str(exc))
        return 1

    logger = logging.getLogger("transcribe_session_audio")
    logger.info("Completed transcription for %s", manifest.get("source_audio"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
