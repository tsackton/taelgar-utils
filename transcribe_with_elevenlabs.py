#!/usr/bin/env python3

"""
Quick helper to run ElevenLabs speech-to-text on one or many local audio files.

Examples:
    python3 transcribe_with_elevenlabs.py sample.mp3 --num-speakers 3
    python3 transcribe_with_elevenlabs.py file_list.txt --diarization-threshold 0.6
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv
from elevenlabs import ElevenLabs
from pydub import AudioSegment
from session_pipeline.audio import chunk_audio_file


AUDIO_EXTENSIONS = {
    ".mp3",
    ".wav",
    ".m4a",
    ".aac",
    ".flac",
    ".ogg",
    ".opus",
    ".webm",
    ".wma",
}

CHUNK_MAX_SECONDS = 60 * 60  # 1 hour


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Transcribe a local audio file with ElevenLabs speech-to-text."
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Either a single audio/video file or a text file containing a list of paths (one per line).",
    )
    parser.add_argument(
        "--model-id",
        default="scribe_v1",
        help="ElevenLabs STT model to use (default: scribe_v1).",
    )
    diarization_options = parser.add_mutually_exclusive_group()
    diarization_options.add_argument(
        "--num-speakers",
        type=int,
        help="Optional speaker count hint.",
    )
    diarization_options.add_argument(
        "--diarization-threshold",
        type=float,
        help="Optional diarization confidence threshold.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path when transcribing a single file. Ignored when --input is a file-of-files.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    input_path = args.input.expanduser().resolve()
    if not input_path.exists():
        parser.error(f"Input not found: {input_path}")
        return 1

    load_dotenv()
    api_key = os.getenv("ELEVEN_LABS_API") or os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        parser.error("ELEVEN_LABS_API or ELEVENLABS_API_KEY environment variable not set.")
        return 1

    client = ElevenLabs(api_key=api_key, base_url="https://api.elevenlabs.io")

    audio_files = resolve_input_files(input_path)
    if not audio_files:
        parser.error("No audio files found to transcribe.")
        return 1

    failures: List[Path] = []
    files_to_transcribe: List[Path] = []
    warned_output_ignored = False
    for audio_file in audio_files:
        try:
            duration_seconds = get_audio_duration_seconds(audio_file)
            if duration_seconds > CHUNK_MAX_SECONDS:
                print(
                    f"Chunking {audio_file} ({duration_seconds/3600:.2f} hours) before transcription..."
                )
                if args.output and len(audio_files) == 1 and not warned_output_ignored:
                    print(
                        f"Warning: --output ignored for chunked file {audio_file}; "
                        "chunks will be transcribed individually.",
                        file=sys.stderr,
                    )
                    warned_output_ignored = True

                chunks = chunk_audio_file(
                    audio_file,
                    audio_file.parent,
                    max_chunk_seconds=CHUNK_MAX_SECONDS,
                    target_format="wav",
                    target_frame_rate=16_000,
                    target_channels=1,
                    target_sample_width=2,
                    target_bitrate=None,
                    chunk_basename=audio_file.stem,
                    normalise=False,
                )
                chunk_paths = [Path(chunk["path"]) for chunk in chunks]
                files_to_transcribe.extend(chunk_paths)
            else:
                files_to_transcribe.append(audio_file)
        except Exception as exc:
            failures.append(audio_file)
            print(f"Failed to prepare {audio_file}: {exc}", file=sys.stderr)

    if args.output and len(files_to_transcribe) > 1:
        print("Warning: --output ignored when processing multiple files.", file=sys.stderr)

    for audio_file in files_to_transcribe:
        try:
            output_path = (
                args.output
                if args.output and len(files_to_transcribe) == 1
                else audio_file.with_suffix(audio_file.suffix + ".elevenlabs.json")
            )
            if output_path.exists():
                print(f"Skipping {audio_file}: output exists")
                continue
            output_path.parent.mkdir(parents=True, exist_ok=True)

            payload = transcribe_file(
                client=client,
                audio_path=audio_file,
                num_speakers=args.num_speakers,
                diarization_threshold=args.diarization_threshold,
                model_id=args.model_id,
            )

            output_text = json.dumps(payload, indent=2, ensure_ascii=False)
            output_path.write_text(output_text, encoding="utf-8")
            print(f"{audio_file} -> {output_path}")
        except Exception as exc:
            failures.append(audio_file)
            print(f"Failed to transcribe {audio_file}: {exc}", file=sys.stderr)

    if failures:
        print(f"{len(failures)} file(s) failed.", file=sys.stderr)
        return 1

    return 0


def resolve_input_files(input_path: Path) -> List[Path]:
    if input_path.is_dir():
        files = sorted(
            p
            for p in input_path.iterdir()
            if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS
        )
        return files

    if input_path.suffix.lower() in AUDIO_EXTENSIONS:
        return [input_path]

    try:
        lines = input_path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return [input_path] if input_path.suffix else []

    audio_files: List[Path] = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        candidate = Path(line)
        if not candidate.is_absolute():
            candidate = (input_path.parent / candidate).resolve()
        if candidate.exists() and candidate.suffix.lower() in AUDIO_EXTENSIONS:
            audio_files.append(candidate)
        else:
            print(f"Skipping {line}: not found or unsupported format.", file=sys.stderr)
    return audio_files


def transcribe_file(
    client: ElevenLabs,
    audio_path: Path,
    *,
    num_speakers: int | None,
    diarization_threshold: float | None,
    model_id: str,
) -> Dict[str, Any]:
    file_obj = BytesIO(audio_path.read_bytes())
    file_obj.name = audio_path.name  # type: ignore[attr-defined]
    convert_kwargs = {
        "file": file_obj,
        "model_id": model_id,
        "diarize": True,
        "file_format": "pcm_s16le_16",
    }
    if num_speakers is not None:
        if num_speakers <= 0:
            raise ValueError("--num-speakers must be a positive integer.")
        convert_kwargs["num_speakers"] = num_speakers
    if diarization_threshold is not None:
        convert_kwargs["diarization_threshold"] = diarization_threshold

    transcription = client.speech_to_text.convert(**convert_kwargs)

    if hasattr(transcription, "model_dump"):
        return transcription.model_dump()
    if hasattr(transcription, "dict"):
        return transcription.dict()  # type: ignore[attr-defined]
    return json.loads(json.dumps(transcription, default=str))


def get_audio_duration_seconds(path: Path) -> float:
    try:
        audio = AudioSegment.from_file(path)
        return len(audio) / 1000.0
    except Exception as exc:  # pragma: no cover - defensive
        print(f"Warning: failed to inspect duration for {path}: {exc}", file=sys.stderr)
        return float("inf")


if __name__ == "__main__":
    raise SystemExit(main())
