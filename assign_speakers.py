#!/usr/bin/env python3

"""Assign speaker names to diarized segments using a trained classifier."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import joblib
import librosa
import numpy as np
from dotenv import load_dotenv

from session_pipeline.audio_processing import prepare_clean_audio

# Reuse the FeatureExtractor implementation from training.
from train_speaker_classifier import FeatureExtractor, resolve_hf_token  # type: ignore


load_dotenv()


DEFAULT_MIN_SEGMENT_SECONDS = 1.5
DEFAULT_MIN_CONFIDENCE = 0.55
DEFAULT_WINDOW_THRESHOLD = 0.0  # disabled by default
DEFAULT_WINDOW_SIZE = 5.0
DEFAULT_WINDOW_STEP = 2.0
DEFAULT_WINDOW_MIN_CONFIDENCE = 0.65
DEFAULT_AGGREGATION_SECONDS = 20.0


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assign canonical speaker names to diarized segments.")
    parser.add_argument("--diarization", type=Path, required=True, help="Path to diarization JSON.")
    parser.add_argument("--audio", type=Path, required=True, help="Path to the source session audio.")
    parser.add_argument("--model", type=Path, required=True, help="Path to trained speaker model (joblib bundle).")
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Where to write the assignment JSON.",
    )
    parser.add_argument(
        "--min-segment-seconds",
        type=float,
        default=DEFAULT_MIN_SEGMENT_SECONDS,
        help="Skip diarization segments shorter than this many seconds (default: 1.5).",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=DEFAULT_MIN_CONFIDENCE,
        help="Minimum confidence for a direct assignment (default: 0.55).",
    )
    parser.add_argument(
        "--window-threshold",
        type=float,
        default=DEFAULT_WINDOW_THRESHOLD,
        help="Segments longer than this (seconds) may use sliding-window refinement (default: 10).",
    )
    parser.add_argument(
        "--window-size",
        type=float,
        default=DEFAULT_WINDOW_SIZE,
        help="Sliding window size in seconds (default: 5).",
    )
    parser.add_argument(
        "--window-step",
        type=float,
        default=DEFAULT_WINDOW_STEP,
        help="Sliding window hop in seconds (default: 2).",
    )
    parser.add_argument(
        "--window-min-confidence",
        type=float,
        default=DEFAULT_WINDOW_MIN_CONFIDENCE,
        help="Minimum average confidence for a window-based reassignment (default: 0.65).",
    )
    parser.add_argument(
        "--aggregation-seconds",
        type=float,
        default=DEFAULT_AGGREGATION_SECONDS,
        help="Aggregate contiguous segments from the same diarized speaker into "
        "chunks roughly this long before classifying (default: 20 seconds).",
    )
    parser.add_argument(
        "--audio-profile",
        default="zoom-audio",
        help="Audio preprocessing profile (defaults to zoom-audio).",
    )
    parser.add_argument(
        "--hf-token",
        help="Optional Hugging Face token for gated models (overrides environment).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print verbose debugging information.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    args.hf_token = resolve_hf_token(args.hf_token)
    diarization_path = args.diarization.expanduser().resolve()
    audio_path = args.audio.expanduser().resolve()
    model_path = args.model.expanduser().resolve()
    output_path = args.output.expanduser().resolve()

    diarization = load_diarization(diarization_path)
    if not diarization:
        raise SystemExit("No segments found in diarization.")

    bundle = joblib.load(model_path)
    model = bundle["model"]
    label_encoder = bundle["label_encoder"]
    feature_params = bundle.get("feature_params", {})
    sample_rate = int(feature_params.get("sample_rate", 16_000))
    n_mfcc = int(feature_params.get("n_mfcc", 40))
    feature_type = feature_params.get("feature_type", "mfcc")
    wav2vec2_model = feature_params.get("wav2vec2_model")
    ecapa_model = feature_params.get("ecapa_model")
    pyannote_model = feature_params.get("pyannote_model")

    extractor = FeatureExtractor(
        feature_type=feature_type,
        sample_rate=sample_rate,
        n_mfcc=n_mfcc,
        wav2vec2_model=wav2vec2_model,
        ecapa_model=ecapa_model,
        pyannote_model=pyannote_model,
        hf_token=args.hf_token,
        device="cpu",
    )

    clean_path, temp_path = prepare_clean_audio(
        audio_path,
        profile=args.audio_profile,
        discard=True,
        sample_rate=sample_rate,
        channels=1,
        output_format="wav",
    )
    try:
        audio_wave, sr = librosa.load(clean_path, sr=sample_rate, mono=True)
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink(missing_ok=True)

    assignments, stats = assign_segments(
        diarization,
        audio_wave,
        sr,
        model,
        label_encoder,
        extractor,
        min_segment_seconds=args.min_segment_seconds,
        min_confidence=args.min_confidence,
        aggregation_seconds=args.aggregation_seconds,
        verbose=args.verbose,
    )

    output = {
        "summary": stats,
        "model": {
            "path": str(model_path),
            "feature_type": feature_type,
            "sample_rate": sample_rate,
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(output, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    diarization_output = diarization_path.with_suffix(".assigned.json")
    annotated = annotate_diarization(diarization, assignments)
    diarization_output.write_text(json.dumps(annotated, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote summary to {output_path}")
    print(f"Wrote annotated diarization to {diarization_output}")
    return 0


def load_diarization(path: Path) -> List[Dict[str, float]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        segments = data
    elif isinstance(data, dict) and "segments" in data:
        segments = data["segments"]
    else:
        raise SystemExit(f"Unsupported diarization format in {path}")
    normalized: List[Dict[str, float]] = []
    for idx, seg in enumerate(segments):
        try:
            start = float(seg.get("start", 0.0))
            end = float(seg.get("end", start))
        except (TypeError, ValueError):
            continue
        normalized.append(
            {
                "id": seg.get("id", f"seg_{idx:05d}"),
                "start": start,
                "end": max(end, start),
                "speaker": seg.get("speaker") or seg.get("speaker_id") or "",
                "raw": seg,
            }
        )
    return normalized


def assign_segments(
    segments: Sequence[Dict[str, float]],
    audio: np.ndarray,
    sample_rate: int,
    model,
    label_encoder,
    extractor: FeatureExtractor,
    *,
    min_segment_seconds: float,
    min_confidence: float,
    aggregation_seconds: float,
    verbose: bool,
) -> Tuple[List[Dict[str, object]], Dict[str, Dict[str, object]]]:
    assignments: List[Dict[str, object]] = []
    stats: Dict[str, Dict[str, object]] = {}
    blocks = aggregate_segments(
        segments,
        aggregation_seconds=max(min_segment_seconds, aggregation_seconds),
        min_segment_seconds=min_segment_seconds,
    )
    print(f"Aggregated {len(blocks)} block(s) from {len(segments)} diarized segments.")
    for block in blocks:
        clip_audio = extract_clip(audio, sample_rate, block["start"], block["end"])
        if clip_audio.size == 0:
            continue
        features = extractor.compute_from_waveform(clip_audio, sample_rate)
        prediction, confidence = predict_label(model, label_encoder, features)
        method = "direct"

        for segment in block["segments"]:
            assignment = {
                "segment_id": segment["id"],
                "source_speaker": segment["speaker"],
                "start": segment["start"],
                "end": segment["end"],
                "duration": segment["end"] - segment["start"],
                "prediction": prediction,
                "confidence": confidence,
                "method": method,
                "block_id": block["block_id"],
            }
            assignments.append(assignment)
        update_stats(stats, block, prediction, confidence)

    return assignments, summarize_stats(stats)


def extract_clip(audio: np.ndarray, sample_rate: int, start: float, end: float) -> np.ndarray:
    start_idx = max(0, int(round(start * sample_rate)))
    end_idx = min(len(audio), int(round(end * sample_rate)))
    if end_idx <= start_idx:
        return np.array([], dtype=np.float32)
    return audio[start_idx:end_idx]


def predict_label(model, label_encoder, feature_vector: np.ndarray) -> Tuple[str, float]:
    vector = feature_vector.reshape(1, -1)
    classifier = model.named_steps.get("classifier", model)
    if hasattr(model, "predict_proba"):
        proba = model.predict_proba(vector)[0]
        idx = int(np.argmax(proba))
        return label_encoder.inverse_transform([idx])[0], float(proba[idx])
    if hasattr(model, "decision_function"):
        scores = model.decision_function(vector)
        if scores.ndim == 1:
            scores = scores.reshape(1, -1)
        probs = softmax(scores[0])
        idx = int(np.argmax(probs))
        return label_encoder.inverse_transform([idx])[0], float(probs[idx])
    prediction = model.predict(vector)[0]
    return label_encoder.inverse_transform([prediction])[0], 0.0


def softmax(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64)
    shifted = values - np.max(values)
    exp = np.exp(shifted)
    total = np.sum(exp)
    if total <= 0:
        return np.full_like(exp, 1.0 / len(exp))
    return exp / total


def sliding_window_refinement(
    clip_audio: np.ndarray,
    sample_rate: int,
    extractor: FeatureExtractor,
    model,
    label_encoder,
    window_size: float,
    window_step: float,
) -> Tuple[Optional[str], float, List[Dict[str, object]]]:
    window_len = int(round(window_size * sample_rate))
    step_len = int(round(window_step * sample_rate))
    if window_len <= 0 or step_len <= 0:
        return None, 0.0, []
    windows = []
    totals: Dict[str, float] = defaultdict(float)
    for start_idx in range(0, max(1, len(clip_audio) - window_len + 1), step_len):
        end_idx = start_idx + window_len
        if end_idx > len(clip_audio):
            end_idx = len(clip_audio)
        window = clip_audio[start_idx:end_idx]
        if len(window) < window_len // 2:
            break
        features = extractor.compute_from_waveform(window, sample_rate)
        label, confidence = predict_label(model, label_encoder, features)
        windows.append(
            {
                "offset_start": start_idx / sample_rate,
                "offset_end": end_idx / sample_rate,
                "prediction": label,
                "confidence": confidence,
            }
        )
        totals[label] += confidence * (end_idx - start_idx)
    if not totals:
        return None, 0.0, windows
    best_label = max(totals.items(), key=lambda item: item[1])[0]
    total_duration = sum(totals.values())
    best_confidence = totals[best_label] / (total_duration or 1.0)
    return best_label, best_confidence, windows


def aggregate_segments(
    segments: Sequence[Dict[str, float]],
    *,
    aggregation_seconds: float,
    min_segment_seconds: float,
) -> List[Dict[str, object]]:
    blocks: List[Dict[str, object]] = []
    current_segments: List[Dict[str, float]] = []
    current_speaker: Optional[str] = None
    block_start: Optional[float] = None
    accumulated = 0.0
    aggregation_seconds = max(aggregation_seconds, min_segment_seconds)
    print(f"Aggregating contiguous segments into ~{aggregation_seconds:.1f}s blocks...")

    def flush() -> None:
        nonlocal current_segments, current_speaker, block_start, accumulated
        if not current_segments:
            return
        block_end = current_segments[-1]["end"]
        block_duration = block_end - (block_start or block_end)
        if block_duration < min_segment_seconds:
            current_segments = []
            current_speaker = None
            block_start = None
            accumulated = 0.0
            return
        block_id = f"block_{len(blocks):05d}"
        blocks.append(
            {
                "block_id": block_id,
                "speaker": current_speaker,
                "start": block_start,
                "end": block_end,
                "duration": block_duration,
                "segments": list(current_segments),
            }
        )
        current_segments = []
        current_speaker = None
        block_start = None
        accumulated = 0.0

    for segment in segments:
        duration = segment["end"] - segment["start"]
        if duration < min_segment_seconds:
            continue
        speaker = segment["speaker"]
        if speaker != current_speaker or (current_segments and accumulated >= aggregation_seconds):
            flush()
        if not current_segments:
            current_speaker = speaker
            block_start = segment["start"]
            accumulated = 0.0
        current_segments.append(segment)
        accumulated += duration
        if accumulated >= aggregation_seconds:
            flush()

    flush()
    return blocks


def annotate_diarization(
    segments: Sequence[Dict[str, float]],
    assignments: Sequence[Dict[str, object]],
) -> Dict[str, object]:
    assignment_map = {entry["segment_id"]: entry for entry in assignments}
    annotated_segments = []
    for segment in segments:
        assignment = assignment_map.get(segment["id"])
        annotated = dict(segment["raw"])
        if assignment:
            annotated["predicted_speaker"] = assignment["prediction"]
            annotated["confidence"] = assignment["confidence"]
        else:
            annotated["predicted_speaker"] = "unknown"
            annotated["confidence"] = 0.0
        annotated_segments.append(annotated)
    return {"segments": annotated_segments}


def update_stats(
    stats: Dict[str, Dict[str, object]],
    block: Dict[str, object],
    prediction: str,
    confidence: float,
) -> None:
    speaker_id = block.get("speaker") or "unknown"
    speaker_stats = stats.setdefault(
        speaker_id,
        {
            "blocks": [],
            "block_count": 0,
            "total_duration": 0.0,
        },
    )
    per_speaker_index = sum(1 for block_summary in speaker_stats["blocks"] if block_summary["speaker"] == speaker_id)
    speaker_stats["blocks"].append(
        {
            "block_id": block["block_id"],
            "block_index": per_speaker_index,
            "speaker": speaker_id,
            "prediction": prediction,
            "confidence": confidence,
            "duration": block["duration"],
        }
    )
    speaker_stats["block_count"] += 1
    speaker_stats["total_duration"] += block["duration"]


def summarize_stats(stats: Dict[str, Dict[str, object]]) -> Dict[str, Dict[str, object]]:
    summary: Dict[str, Dict[str, object]] = {}
    for speaker_id, info in stats.items():
        blocks = info["blocks"]
        block_counter: Dict[int, int] = defaultdict(int)
        for block in blocks:
            counter = block_counter[block["speaker"]]
            block["block_number"] = counter
            block_counter[block["speaker"]] += 1
        summary[speaker_id] = {
            "total_blocks": info["block_count"],
            "total_duration": info["total_duration"],
            "blocks": blocks,
        }
    return summary


if __name__ == "__main__":
    raise SystemExit(main())
