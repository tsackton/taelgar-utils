"""
Command-line entry point for transcribing and diarizing session audio.

Example:
    python3 transcribe_session_audio.py input_audio.mp3 --output transcript.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Dict, Optional

from openai import OpenAI

from session_pipeline import (
    combine_chunk_transcripts,
    chunk_audio_file,
    transcribe_audio_chunks,
)


def _optional_positive_int(value: Optional[int]) -> Optional[int]:
    if value is None:
        return None
    if value <= 0:
        return None
    return value


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Transcribe and diarize a session recording with GPT-4o.",
    )
    parser.add_argument(
        "input_path",
        type=Path,
        help="Path to the source audio file.",
    )
    parser.add_argument(
        "-o",
        "--output",
        dest="output_path",
        type=Path,
        help="Optional path to write transcription JSON. Defaults to stdout.",
    )
    parser.add_argument(
        "--max-chunk-seconds",
        type=int,
        default=900,
        help="Split audio into chunks of this length. Set to 0 to disable chunking.",
    )
    parser.add_argument(
        "--model",
        default="gpt-4o-transcribe-diarize",
        help="Speech-to-text model to invoke.",
    )
    parser.add_argument(
        "--response-format",
        default="verbose_json",
        help="Response format requested from the API.",
    )
    parser.add_argument(
        "--sample-rate",
        type=int,
        default=16000,
        help="Target sample rate for exported chunks. Set to 0 to keep original.",
    )
    parser.add_argument(
        "--channels",
        type=int,
        default=1,
        help="Target channel count for exported chunks. Set to 0 to keep original.",
    )
    parser.add_argument(
        "--chunk-format",
        default="wav",
        help="Audio format to use for chunk files.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level (DEBUG, INFO, WARNING, ...).",
    )
    parser.add_argument(
        "--api-key",
        help="Optional OpenAI API key override. Falls back to OPENAI_API_KEY env variable.",
    )
    parser.add_argument(
        "--pretty",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Pretty-print JSON output (default: enabled).",
    )
    return parser


def configure_logging(level_name: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level_name.upper(), logging.INFO),
        format="%(levelname)s %(name)s - %(message)s",
    )


def perform_transcription(args: argparse.Namespace) -> Dict[str, Any]:
    configure_logging(args.log_level)
    logger = logging.getLogger("transcribe_session_audio")

    max_chunk_seconds = _optional_positive_int(args.max_chunk_seconds)
    target_sample_rate = _optional_positive_int(args.sample_rate)
    target_channels = _optional_positive_int(args.channels)

    client_kwargs: Dict[str, Any] = {}
    if args.api_key:
        client_kwargs["api_key"] = args.api_key

    client = OpenAI(**client_kwargs)

    with TemporaryDirectory(prefix="session-chunks-") as chunk_dir:
        logger.info("Chunking audio...")
        chunks = chunk_audio_file(
            args.input_path,
            Path(chunk_dir),
            max_chunk_seconds=max_chunk_seconds,
            target_format=args.chunk_format,
            target_frame_rate=target_sample_rate,
            target_channels=target_channels,
        )

        logger.info("Submitting %d chunk(s) to %s", len(chunks), args.model)
        request_options = {"response_format": args.response_format}
        chunk_results = transcribe_audio_chunks(
            client,
            chunks,
            model=args.model,
            request_options=request_options,
        )

    combined = combine_chunk_transcripts(chunk_results)
    combined.setdefault("meta", {})
    combined["meta"].update(
        {
            "source": str(args.input_path.resolve()),
            "model": args.model,
            "max_chunk_seconds": max_chunk_seconds,
            "chunk_format": args.chunk_format,
            "response_format": args.response_format,
        }
    )

    return combined


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    try:
        result = perform_transcription(args)
    except Exception as exc:  # pragma: no cover - defensive logging
        logging.getLogger("transcribe_session_audio").exception("transcription failed")
        parser.error(str(exc))
        return 1

    json_kwargs = {"indent": 2} if args.pretty else {}
    output_text = json.dumps(result, **json_kwargs)

    if args.output_path:
        args.output_path.parent.mkdir(parents=True, exist_ok=True)
        args.output_path.write_text(output_text)
    else:
        sys.stdout.write(output_text)
        if args.pretty:
            sys.stdout.write("\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
