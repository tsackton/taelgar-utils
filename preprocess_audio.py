#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, List

from session_pipeline.audio_processing import (
    AUDIO_PROFILES,
    AudioProcessingError,
    SUPPORTED_OUTPUT_FORMATS,
    preprocess_audio_file,
)

AUDIO_EXTENSIONS = {
    ".wav",
    ".mp3",
    ".m4a",
    ".aac",
    ".flac",
    ".ogg",
    ".opus",
    ".webm",
    ".wma",
    ".mp4",
    ".mov",
    ".m4v",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preprocess audio files into a transcription-friendly format."
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        type=Path,
        help="Audio file(s) or directories containing audio files.",
    )
    parser.add_argument(
        "--audio-profile",
        choices=sorted(AUDIO_PROFILES.keys()),
        default="voice-memo",
        help="Processing profile to apply (default: voice-memo).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Optional directory for processed files (defaults to each file's directory).",
    )
    parser.add_argument(
        "--output-format",
        choices=sorted(SUPPORTED_OUTPUT_FORMATS),
        default="wav",
        help="Output container/codec (default: wav).",
    )
    parser.add_argument(
        "--sample-rate",
        type=int,
        default=16_000,
        help="Target sample rate (Hz). Default: 16000.",
    )
    parser.add_argument(
        "--channels",
        type=int,
        default=1,
        help="Target channel count (1=mono, 2=stereo). Default: 1.",
    )
    parser.add_argument(
        "--bit-depth",
        type=int,
        choices=[16],
        default=16,
        help="Target bit depth. Currently only 16-bit PCM is supported.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite outputs that already exist.",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="When directories are provided, search recursively for audio files.",
    )

    advanced = parser.add_argument_group("advanced filter options")
    advanced.add_argument("--highpass", type=int, help="Override high-pass cutoff (Hz).")
    advanced.add_argument("--lowpass", type=int, help="Override low-pass cutoff (Hz).")
    advanced.add_argument(
        "--disable-denoise",
        action="store_true",
        help="Disable denoise step even if the profile enables it.",
    )
    advanced.add_argument(
        "--disable-dynaudnorm",
        action="store_true",
        help="Disable adaptive loudness normalisation.",
    )
    advanced.add_argument(
        "--disable-compression",
        action="store_true",
        help="Disable the compressor stage.",
    )
    advanced.add_argument(
        "--rnnoise-model",
        type=Path,
        help="Explicit path to an rnnoise model when using voice-memo (defaults to cached std.rnnn).",
    )

    return parser


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    files = list(collect_audio_files(args.inputs, recursive=args.recursive))
    if not files:
        parser.error("No audio files found for the provided inputs.")

    output_dir = args.output_dir.expanduser().resolve() if args.output_dir else None
    bit_depth_bytes = args.bit_depth // 8

    failures = 0
    for path in files:
        try:
            target_dir = output_dir or path.parent
            target_dir.mkdir(parents=True, exist_ok=True)
            output_path = target_dir / f"{path.stem}-clean.{args.output_format}"

            preprocess_audio_file(
                path,
                output_path,
                profile=args.audio_profile,
                sample_rate=args.sample_rate,
                channels=args.channels,
                sample_width=bit_depth_bytes,
                output_format=args.output_format,
                overwrite=args.overwrite,
                highpass=args.highpass,
                lowpass=args.lowpass,
                disable_denoise=args.disable_denoise,
                disable_dynaudnorm=args.disable_dynaudnorm,
                disable_compression=args.disable_compression,
                rnnoise_model_path=args.rnnoise_model,
            )
            print(f"{path} -> {output_path}")
        except AudioProcessingError as exc:
            failures += 1
            print(f"[error] {path}: {exc}", file=sys.stderr)

    if failures:
        print(f"{failures} file(s) failed.", file=sys.stderr)
        return 1

    return 0


def collect_audio_files(inputs: Iterable[Path], *, recursive: bool) -> Iterable[Path]:
    for entry in inputs:
        path = entry.expanduser().resolve()
        if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS:
            yield path
        elif path.is_dir():
            iterator = path.rglob("*") if recursive else path.iterdir()
            for child in iterator:
                if child.is_file() and child.suffix.lower() in AUDIO_EXTENSIONS:
                    yield child


if __name__ == "__main__":
    raise SystemExit(main())
