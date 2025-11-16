#!/usr/bin/env python3

"""Train a speaker classification model from generated clip manifests."""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import joblib
import librosa
import numpy as np
import torch
from dotenv import load_dotenv
try:  # optional dependency for speechbrain
    import torchaudio  # type: ignore
except Exception:  # pragma: no cover - optional import
    torchaudio = None
else:  # pragma: no cover - ensure API compatibility
    if not hasattr(torchaudio, "list_audio_backends"):
        def _list_audio_backends_stub() -> list[str]:
            return []

        torchaudio.list_audio_backends = _list_audio_backends_stub  # type: ignore[attr-defined]
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import LabelEncoder, Normalizer, StandardScaler
from sklearn.svm import LinearSVC, SVC
from tqdm import tqdm
from transformers import AutoFeatureExtractor, AutoModel

load_dotenv()


DEFAULT_TEST_FRACTION = 0.15
DEFAULT_VAL_FRACTION = 0.15
DEFAULT_MIN_CLIPS_PER_SPEAKER = 5
DEFAULT_SAMPLE_RATE = 16_000
DEFAULT_N_MFCC = 40
FEATURE_TYPES = ("mfcc", "wav2vec2", "ecapa", "pyannote")
CLASSIFIERS = ("linear-svm", "rbf-svm", "logreg")
DEFAULT_W2V_MODEL = "facebook/wav2vec2-base"
DEFAULT_ECAPA_MODEL = "speechbrain/spkrec-ecapa-voxceleb"
DEFAULT_PYANNOTE_MODEL = "pyannote/embedding"


@dataclass
class ManifestEntry:
    clip_path: Path
    speaker: str
    session_id: str
    duration: float


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train a speaker classifier from clip manifests.")
    parser.add_argument("--manifest", type=Path, required=True, help="Path to manifest JSONL file.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory where the trained model and metrics will be saved.",
    )
    parser.add_argument(
        "--test-size",
        type=float,
        default=DEFAULT_TEST_FRACTION,
        help="Fraction of data reserved for test split (default: 0.15).",
    )
    parser.add_argument(
        "--val-size",
        type=float,
        default=DEFAULT_VAL_FRACTION,
        help="Fraction of data reserved for validation split (default: 0.15).",
    )
    parser.add_argument(
        "--random-seed",
        type=int,
        default=42,
        help="Random seed used for splits and sampling.",
    )
    parser.add_argument(
        "--min-clips-per-speaker",
        type=int,
        default=DEFAULT_MIN_CLIPS_PER_SPEAKER,
        help="Skip speakers with fewer clips than this threshold (default: 5).",
    )
    parser.add_argument(
        "--max-clips-per-speaker",
        type=int,
        help="Optional cap on clips per speaker (after shuffling).",
    )
    parser.add_argument(
        "--sample-rate",
        type=int,
        default=DEFAULT_SAMPLE_RATE,
        help="Audio sample rate for feature extraction (default: 16000).",
    )
    parser.add_argument(
        "--n-mfcc",
        type=int,
        default=DEFAULT_N_MFCC,
        help="Number of MFCC coefficients to compute per frame (default: 40).",
    )
    parser.add_argument(
        "--progress",
        action="store_true",
        help="Show progress bars during feature extraction.",
    )
    parser.add_argument(
        "--feature-type",
        choices=FEATURE_TYPES,
        default="mfcc",
        help="Feature extraction backend to use.",
    )
    parser.add_argument(
        "--wav2vec2-model",
        default=DEFAULT_W2V_MODEL,
        help="Model name/path for wav2vec2 embeddings (when --feature-type=wav2vec2).",
    )
    parser.add_argument(
        "--ecapa-model",
        default=DEFAULT_ECAPA_MODEL,
        help="Model hub path for ECAPA speaker encoder (feature-type=ecapa).",
    )
    parser.add_argument(
        "--pyannote-model",
        default=DEFAULT_PYANNOTE_MODEL,
        help="Model hub path for pyannote speaker embedding backend.",
    )
    parser.add_argument(
        "--device",
        default="cpu",
        help="Torch device for wav2vec2 feature extraction (default: cpu).",
    )
    parser.add_argument(
        "--classifier",
        choices=CLASSIFIERS,
        default="linear-svm",
        help="Classifier head (default: linear-svm).",
    )
    parser.add_argument(
        "--clip-level-split",
        action="store_true",
        help="Fallback to clip-level stratified splits instead of session-based splits.",
    )
    parser.add_argument(
        "--hf-token",
        help="Optional Hugging Face token for accessing gated models (e.g., pyannote/embedding).",
    )
    return parser.parse_args(argv)


def resolve_hf_token(cli_token: Optional[str]) -> Optional[str]:
    if cli_token:
        return cli_token
    for var in ("PYANNO", "PYANNOTE_TOKEN", "HF_TOKEN", "HUGGINGFACE_TOKEN", "HUGGINGFACEHUB_API_TOKEN"):
        value = os.getenv(var)
        if value:
            return value
    return None


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    args.hf_token = resolve_hf_token(args.hf_token)
    manifest_path = args.manifest.expanduser().resolve()
    if not manifest_path.is_file():
        raise SystemExit(f"Manifest not found: {manifest_path}")

    entries = load_manifest(manifest_path)
    if not entries:
        raise SystemExit("Manifest did not include any usable entries.")

    entries = filter_entries(
        entries,
        min_clips=args.min_clips_per_speaker,
        max_clips=args.max_clips_per_speaker,
        seed=args.random_seed,
    )
    if not entries:
        raise SystemExit("All speakers were filtered out (check min/max clip thresholds).")

    feature_extractor = FeatureExtractor.from_args(args)

    session_map: Optional[Dict[str, List[str]]] = None
    if args.clip_level_split:
        clips = extract_features_for_entries(
            entries,
            feature_extractor,
            show_progress=args.progress,
        )
        splits, label_encoder = stratified_clip_splits(
            clips,
            test_size=args.test_size,
            val_size=args.val_size,
            seed=args.random_seed,
        )
    else:
        splits, label_encoder, session_map = session_based_splits(
            entries,
            feature_extractor,
            test_size=args.test_size,
            val_size=args.val_size,
            seed=args.random_seed,
            show_progress=args.progress,
        )

    model = build_model(args.classifier)
    model.fit(splits["train"].x, splits["train"].y)

    metrics = evaluate_model(model, splits, label_encoder)
    if session_map:
        metrics["session_assignments"] = session_map
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    save_artifacts(
        output_dir,
        model,
        label_encoder,
        metrics,
        args,
    )
    print(f"Model saved to {output_dir}")
    return 0


class FeatureExtractor:
    def __init__(
        self,
        *,
        feature_type: str,
        sample_rate: int,
        n_mfcc: int,
        wav2vec2_model: Optional[str],
        ecapa_model: Optional[str],
        pyannote_model: Optional[str],
        hf_token: Optional[str],
        device: str,
    ):
        self.feature_type = feature_type
        self.sample_rate = sample_rate
        self.n_mfcc = n_mfcc
        self.device = torch.device(device)
        self.hf_token = hf_token
        self.wav2vec2_model_name = wav2vec2_model or DEFAULT_W2V_MODEL
        self.wav2vec2_extractor = None
        self.wav2vec2_model = None
        self.ecapa_model_name = ecapa_model or DEFAULT_ECAPA_MODEL
        self.ecapa_classifier = None
        self.pyannote_model_name = pyannote_model or DEFAULT_PYANNOTE_MODEL
        self.pyannote_inference = None
        if feature_type == "wav2vec2":
            self._init_wav2vec2()
        elif feature_type == "ecapa":
            self._init_ecapa()
        elif feature_type == "pyannote":
            self._init_pyannote()

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> "FeatureExtractor":
        feature_type = args.feature_type
        if args.clip_level_split and feature_type == "wav2vec2":
            print("[info] Using wav2vec2 embeddings for clip-level split (may be slower).")
        return cls(
            feature_type=feature_type,
            sample_rate=args.sample_rate,
            n_mfcc=args.n_mfcc,
            wav2vec2_model=args.wav2vec2_model,
            ecapa_model=args.ecapa_model,
            pyannote_model=args.pyannote_model,
            hf_token=args.hf_token,
            device=args.device,
        )

    def compute(self, audio_path: Path) -> np.ndarray:
        waveform, sr = librosa.load(audio_path, sr=self.sample_rate, mono=True)
        return self.compute_from_waveform(waveform, sr)

    def compute_from_waveform(self, waveform: np.ndarray, sample_rate: int) -> np.ndarray:
        if sample_rate != self.sample_rate:
            waveform = librosa.resample(waveform, orig_sr=sample_rate, target_sr=self.sample_rate)
        waveform = np.asarray(waveform, dtype=np.float32)
        if self.feature_type == "wav2vec2":
            return self._compute_wav2vec2_from_waveform(waveform)
        if self.feature_type == "ecapa":
            return self._compute_ecapa_from_waveform(waveform)
        if self.feature_type == "pyannote":
            return self._compute_pyannote_from_waveform(waveform)
        return self._compute_mfcc_from_waveform(waveform)

    def _init_wav2vec2(self) -> None:
        extra = {"token": self.hf_token} if self.hf_token else {}
        self.wav2vec2_extractor = AutoFeatureExtractor.from_pretrained(self.wav2vec2_model_name, **extra)
        self.wav2vec2_model = AutoModel.from_pretrained(self.wav2vec2_model_name, **extra)
        self.wav2vec2_model.to(self.device)
        self.wav2vec2_model.eval()

    def _compute_mfcc_from_waveform(self, audio: np.ndarray) -> np.ndarray:
        if audio.size == 0:
            raise ValueError("empty audio")
        mfcc = librosa.feature.mfcc(y=audio, sr=self.sample_rate, n_mfcc=self.n_mfcc)
        delta = librosa.feature.delta(mfcc)
        delta2 = librosa.feature.delta(mfcc, order=2)
        stats = []
        for feature in (mfcc, delta, delta2):
            stats.append(feature.mean(axis=1))
            stats.append(feature.std(axis=1))
        return np.concatenate(stats).astype(np.float32)

    def _compute_wav2vec2_from_waveform(self, audio: np.ndarray) -> np.ndarray:
        if self.wav2vec2_model is None or self.wav2vec2_extractor is None:
            self._init_wav2vec2()
        if audio.size == 0:
            raise ValueError("empty audio")
        inputs = self.wav2vec2_extractor(
            audio,
            sampling_rate=self.sample_rate,
            return_tensors="pt",
        )
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        with torch.no_grad():
            outputs = self.wav2vec2_model(**inputs)
            embedding = outputs.last_hidden_state.mean(dim=1).squeeze(0).cpu().numpy()
        return embedding.astype(np.float32)

    def _init_ecapa(self) -> None:
        from speechbrain.pretrained import EncoderClassifier

        self.ecapa_classifier = EncoderClassifier.from_hparams(
            source=self.ecapa_model_name,
            run_opts={"device": self.device.type},
        )

    def _compute_ecapa_from_waveform(self, audio: np.ndarray) -> np.ndarray:
        if self.ecapa_classifier is None:
            self._init_ecapa()
        if audio.size == 0:
            raise ValueError("empty audio")
        signal = torch.from_numpy(audio).float().unsqueeze(0)
        embedding = self.ecapa_classifier.encode_batch(signal.to(self.device)).squeeze(0).squeeze(0)
        return embedding.cpu().numpy().astype(np.float32)

    def _init_pyannote(self) -> None:
        from pyannote.audio import Inference, Model

        kwargs = {"token": self.hf_token} if self.hf_token else {}
        model = Model.from_pretrained(self.pyannote_model_name, **kwargs)
        self.pyannote_inference = Inference(model, window="whole", device=self.device)

    def _compute_pyannote_from_waveform(self, audio: np.ndarray) -> np.ndarray:
        if self.pyannote_inference is None:
            self._init_pyannote()
        if audio.size == 0:
            raise ValueError("empty audio")
        waveform = torch.from_numpy(audio).unsqueeze(0)
        embedding = self.pyannote_inference({"waveform": waveform, "sample_rate": self.sample_rate})
        if isinstance(embedding, torch.Tensor):
            embedding = embedding.cpu().numpy()
        return np.asarray(embedding, dtype=np.float32)


def load_manifest(path: Path) -> List[ManifestEntry]:
    entries: List[ManifestEntry] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                print(f"[warn] Manifest line {line_number} is not valid JSON: {exc}")
                continue
            clip_path = Path(data.get("clip_path", "")).expanduser()
            if not clip_path.is_file():
                print(f"[warn] clip not found: {clip_path}")
                continue
            speaker = data.get("speaker")
            session_id = data.get("session_id") or data.get("session")
            duration = float(data.get("duration", 0.0))
            if not speaker or session_id is None:
                print(f"[warn] Missing speaker/session_id in manifest entry #{line_number}")
                continue
            entries.append(
                ManifestEntry(
                    clip_path=clip_path,
                    speaker=str(speaker),
                    session_id=str(session_id),
                    duration=duration,
                )
            )
    return entries


def filter_entries(
    entries: Sequence[ManifestEntry],
    *,
    min_clips: int,
    max_clips: Optional[int],
    seed: int,
) -> List[ManifestEntry]:
    grouped: Dict[str, List[ManifestEntry]] = {}
    for entry in entries:
        grouped.setdefault(entry.speaker, []).append(entry)

    rng = np.random.default_rng(seed)
    filtered: List[ManifestEntry] = []
    for speaker, items in grouped.items():
        if len(items) < min_clips:
            print(f"[info] Skipping speaker '{speaker}' (only {len(items)} clips).")
            continue
        rng.shuffle(items)
        if max_clips is not None:
            items = items[: max(1, max_clips)]
        filtered.extend(items)
    return filtered


def extract_features_for_entries(
    entries: Sequence[ManifestEntry],
    extractor: "FeatureExtractor",
    *,
    show_progress: bool,
) -> List[Tuple[np.ndarray, str]]:
    results: List[Tuple[np.ndarray, str]] = []
    iterator = tqdm(entries, desc="Extracting features") if show_progress else entries
    for entry in iterator:
        try:
            vec = extractor.compute(entry.clip_path)
        except Exception as exc:
            print(f"[warn] Failed to process {entry.clip_path}: {exc}")
            continue
        results.append((vec, entry.speaker))
    return results


def session_based_splits(
    entries: Sequence[ManifestEntry],
    extractor: FeatureExtractor,
    *,
    test_size: float,
    val_size: float,
    seed: int,
    show_progress: bool,
) -> Tuple[Dict[str, Split], LabelEncoder, Dict[str, List[str]]]:
    session_assignments = assign_sessions(entries, test_size=test_size, val_size=val_size, seed=seed)
    splits_entries: Dict[str, List[ManifestEntry]] = {"train": [], "val": [], "test": []}
    for entry in entries:
        split_name = session_assignments.get(entry.session_id, "train")
        splits_entries[split_name].append(entry)

    if not splits_entries["train"]:
        raise SystemExit("No training sessions available after splitting; adjust ratios or data.")

    label_encoder = LabelEncoder()
    train_labels = [entry.speaker for entry in splits_entries["train"]]
    label_encoder.fit(sorted(set(train_labels)))

    splits: Dict[str, Split] = {}
    for split_name, split_entries in splits_entries.items():
        if not split_entries:
            splits[split_name] = Split(np.zeros((0, 1)), np.zeros(0, dtype=int))
            continue
        features = extract_features_for_entries(
            split_entries,
            extractor,
            show_progress=show_progress and split_name == "train",
        )
        if not features:
            splits[split_name] = Split(np.zeros((0, 1)), np.zeros(0, dtype=int))
            continue
        filtered_vectors: List[np.ndarray] = []
        filtered_labels: List[str] = []
        allowed = set(label_encoder.classes_)
        for vec, label in features:
            if label not in allowed:
                print(f"[warn] Speaker '{label}' is not in training set; skipping clip in split '{split_name}'.")
                continue
            filtered_vectors.append(vec)
            filtered_labels.append(label)
        if not filtered_vectors:
            splits[split_name] = Split(np.zeros((0, 1)), np.zeros(0, dtype=int))
            continue
        vectors = np.vstack(filtered_vectors)
        splits[split_name] = Split(vectors, label_encoder.transform(filtered_labels))

    return splits, label_encoder, summarize_session_assignments(session_assignments)


def assign_sessions(
    entries: Sequence[ManifestEntry],
    *,
    test_size: float,
    val_size: float,
    seed: int,
) -> Dict[str, str]:
    session_ids = sorted({entry.session_id for entry in entries})
    if not session_ids:
        raise SystemExit("No session_ids available in manifest entries.")
    rng = np.random.default_rng(seed)
    rng.shuffle(session_ids)
    total_sessions = len(session_ids)
    n_test = max(1, min(total_sessions - 1, int(round(total_sessions * test_size))))
    remaining = total_sessions - n_test
    n_val = max(1, min(remaining - 1, int(round(total_sessions * val_size)))) if remaining > 1 else 0

    assignments: Dict[str, str] = {}
    for idx, session_id in enumerate(session_ids):
        if idx < n_test:
            assignments[session_id] = "test"
        elif idx < n_test + n_val:
            assignments[session_id] = "val"
        else:
            assignments[session_id] = "train"

    ensure_training_sessions(entries, assignments)
    ensure_test_coverage(entries, assignments)
    return assignments


def ensure_training_sessions(entries: Sequence[ManifestEntry], assignments: Dict[str, str]) -> None:
    speaker_sessions: Dict[str, List[str]] = defaultdict(list)
    for entry in entries:
        speaker_sessions[entry.speaker].append(entry.session_id)

    for speaker, sessions in speaker_sessions.items():
        if any(assignments.get(session) == "train" for session in sessions):
            continue
        session_to_move = sessions[0]
        assignments[session_to_move] = "train"


def ensure_test_coverage(entries: Sequence[ManifestEntry], assignments: Dict[str, str]) -> None:
    speaker_sessions: Dict[str, List[str]] = defaultdict(list)
    for entry in entries:
        speaker_sessions[entry.speaker].append(entry.session_id)

    for speaker, sessions in speaker_sessions.items():
        unique_sessions = list(dict.fromkeys(sessions))
        if len(unique_sessions) < 2:
            continue
        if any(assignments.get(session) == "test" for session in unique_sessions):
            continue
        for session in unique_sessions:
            if assignments.get(session) == "val":
                assignments[session] = "test"
                break
        else:
            assignments[unique_sessions[-1]] = "test"


def summarize_session_assignments(assignments: Dict[str, str]) -> Dict[str, List[str]]:
    summary: Dict[str, List[str]] = {"train": [], "val": [], "test": []}
    for session_id, split_name in assignments.items():
        summary.setdefault(split_name, []).append(session_id)
    for split_name in summary:
        summary[split_name] = sorted(summary[split_name])
    return summary


@dataclass
class Split:
    x: np.ndarray
    y: np.ndarray


def stratified_clip_splits(
    clips: List[Tuple[np.ndarray, str]],
    *,
    test_size: float,
    val_size: float,
    seed: int,
) -> Tuple[Dict[str, Split], LabelEncoder]:
    if not clips:
        raise SystemExit("No features extracted; cannot split.")
    features = np.vstack([vec for vec, _ in clips])
    label_text = [label for _, label in clips]
    label_encoder = LabelEncoder()
    targets = label_encoder.fit_transform(label_text)

    from sklearn.model_selection import train_test_split

    if not 0 < test_size < 1 or not 0 < val_size < 1:
        raise ValueError("test_size and val_size must be between 0 and 1.")
    remaining = 1.0 - test_size
    if remaining <= 0:
        raise ValueError("test_size too large; no data left for train/val.")
    val_ratio_adjusted = val_size / remaining
    if not 0 < val_ratio_adjusted < 1:
        raise ValueError("val_size too large relative to test_size.")

    X_train, X_temp, y_train, y_temp = train_test_split(
        features,
        targets,
        test_size=test_size,
        random_state=seed,
        stratify=targets,
    )
    X_val, X_test, y_val, y_test = train_test_split(
        X_temp,
        y_temp,
        test_size=val_ratio_adjusted,
        random_state=seed,
        stratify=y_temp,
    )
    splits = {
        "train": Split(X_train, y_train),
        "val": Split(X_val, y_val),
        "test": Split(X_test, y_test),
    }
    return splits, label_encoder

def build_model(classifier_type: str) -> Pipeline:
    if classifier_type == "linear-svm":
        classifier = LinearSVC(
            class_weight="balanced",
            C=0.5             # maybe expose as a param later
        )
        return Pipeline(
            [
                ("normalizer", Normalizer(norm="l2")),  # L2 only
                ("classifier", classifier),
            ]
        )
    if classifier_type == "logreg":
        classifier = LogisticRegression(
            class_weight="balanced",
            max_iter=1000,
            multi_class="multinomial",
            solver="lbfgs",
            C=0.3
        )
        return Pipeline(
            [
                ("normalizer", Normalizer(norm="l2")),  # no StandardScaler
                ("classifier", classifier),
            ]
        )

    raise ValueError(f"Unknown classifier type: {classifier_type}")


def evaluate_model(
    model: Pipeline,
    splits: Dict[str, Split],
    label_encoder: LabelEncoder,
) -> Dict[str, Dict[str, object]]:
    metrics: Dict[str, Dict[str, object]] = {}
    for split_name, split in splits.items():
        if split.x.size == 0 or split.y.size == 0:
            metrics[split_name] = {"accuracy": None, "size": 0}
            continue
        predictions = model.predict(split.x)
        accuracy = float(accuracy_score(split.y, predictions))
        metrics[split_name] = {"accuracy": accuracy, "size": int(split.y.size)}
        if split_name == "test":
            report = classification_report(
                split.y,
                predictions,
                target_names=label_encoder.classes_,
                output_dict=True,
                zero_division=0,
            )
            cm = confusion_matrix(split.y, predictions).tolist()
            metrics[split_name]["classification_report"] = report
            metrics[split_name]["confusion_matrix"] = cm
    return metrics


def save_artifacts(
    output_dir: Path,
    model: Pipeline,
    label_encoder: LabelEncoder,
    metrics: Dict[str, Dict[str, object]],
    args: argparse.Namespace,
) -> None:
    model_path = output_dir / "speaker_classifier.joblib"
    bundle = {
        "model": model,
        "label_encoder": label_encoder,
        "feature_params": {
            "sample_rate": args.sample_rate,
            "n_mfcc": args.n_mfcc,
            "feature_type": args.feature_type,
            "wav2vec2_model": args.wav2vec2_model,
        },
        "training_params": {
            "test_size": args.test_size,
            "val_size": args.val_size,
            "random_seed": args.random_seed,
            "min_clips_per_speaker": args.min_clips_per_speaker,
            "max_clips_per_speaker": args.max_clips_per_speaker,
            "split_mode": "clip" if args.clip_level_split else "session",
            "classifier": args.classifier,
        },
    }
    joblib.dump(bundle, model_path)

    metrics_path = output_dir / "training_metrics.json"
    with metrics_path.open("w", encoding="utf-8") as handle:
        json.dump(metrics, handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    print(f"Saved model to {model_path}")
    print(f"Saved metrics to {metrics_path}")


if __name__ == "__main__":
    raise SystemExit(main())
