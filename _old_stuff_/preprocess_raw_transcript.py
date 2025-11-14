#!/usr/bin/env python3
"""Preprocess `[start - end] Speaker: text` transcripts for QC + session artifacts."""

from __future__ import annotations

import argparse
import json
import statistics
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple, Optional
from functools import lru_cache

try:  # pragma: no cover - required dependency
    from wordfreq import zipf_frequency
except ImportError:
    print("[error] wordfreq is required. Install via 'pip install wordfreq'.", file=sys.stderr)
    raise SystemExit(1)

try:  # pragma: no cover - required dependency
    import spacy
    from spacy.language import Language
    from spacy.tokens import Doc, Span, Token
except ImportError:
    print("[error] spaCy is required. Install via 'pip install spacy'.", file=sys.stderr)
    raise SystemExit(1)

try:  # pragma: no cover - required dependency
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
except ImportError:
    print("[error] torch and transformers are required. Install via 'pip install torch transformers'.", file=sys.stderr)
    raise SystemExit(1)

LINE_RE = re.compile(r"^\[(?P<start>[0-9:\.]+)\s*-\s*(?P<end>[0-9:\.]+)\]\s*(?P<speaker>[^:]+):\s*(?P<text>.*)$")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\-]+")
SENTENCE_SPLIT_RE = re.compile(r"[.!?]+")
UNKNOWN_SPEAKER_RE = re.compile(r"^unknown(?:\b|[_\s-])", re.IGNORECASE)
QUALITY_MIN_ENTRY_WORDS = 4
QUALITY_MIN_SENTENCE_WORDS = 6
PUNCTUATION_CHARS = set(".?!,;:-")
DEFAULT_EXAMPLE_LIMIT = 3
EXAMPLE_WINDOW_WORDS = 50
MAX_PUNCT_GAP_THRESHOLD = 80
QUALITY_SAMPLE_MIN_WORDS = 10
QUALITY_SAMPLE_WORD_LIMIT: Optional[int] = None
UNKNOWN_EXAMPLE_LIMIT = 10
LM_MODEL_NAME = "gpt2"
LM_HIGH_LOSS_THRESHOLD = 4.0
LM_LOSS_SCALE = 5.0
TRANSCRIPTION_ERROR_Z = 1.5
TRANSCRIPTION_ERROR_MAX = 15
TRANSCRIPTION_ERROR_PAD = 1
RARE_TOKEN_ZIPF = 3.0
SINGLE_CHAR_ALLOWED = {"a", "i"}


_NLP: Language | None = None
_LM_TOKENIZER: AutoTokenizer | None = None
_LM_MODEL: AutoModelForCausalLM | None = None
_LM_DEVICE: str | None = None


def get_nlp() -> Language:
    global _NLP
    if _NLP is None:
        try:
            _NLP = spacy.load("en_core_web_sm")
        except OSError as exc:
            print(
                "[error] spaCy model 'en_core_web_sm' not found. Install via 'python -m spacy download en_core_web_sm'.",
                file=sys.stderr,
            )
            raise SystemExit(1) from exc
    return _NLP


def get_lm() -> Tuple[AutoTokenizer, AutoModelForCausalLM, str]:
    global _LM_TOKENIZER, _LM_MODEL, _LM_DEVICE
    if _LM_MODEL is None or _LM_TOKENIZER is None or _LM_DEVICE is None:
        device = "mps" if torch.backends.mps.is_available() else "cpu"
        dtype = torch.float16 if device == "mps" else torch.float32
        tokenizer = AutoTokenizer.from_pretrained(LM_MODEL_NAME)
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token
        model = AutoModelForCausalLM.from_pretrained(LM_MODEL_NAME, dtype=dtype)
        model = model.to(device)
        model.eval()
        if hasattr(model.config, "loss_type"):
            model.config.loss_type = "ForCausalLMLoss"
        _LM_TOKENIZER = tokenizer
        _LM_MODEL = model
        _LM_DEVICE = device
    return _LM_TOKENIZER, _LM_MODEL, _LM_DEVICE


def normalize_token(token: str) -> str:
    return re.sub(r"[^\w]", "", token).lower()


def snippet_around_word(entry: Utterance, word: str, window: int = EXAMPLE_WINDOW_WORDS) -> str:
    tokens = entry.text.split()
    if not tokens:
        return entry.text.strip()
    target = normalize_token(word)
    positions = [idx for idx, token in enumerate(tokens) if normalize_token(token) == target]
    if not positions:
        start = 0
        end = min(len(tokens), window)
    else:
        idx = positions[0]
        half = window // 2
        start = max(0, idx - half)
        end = min(len(tokens), idx + half + 1)
    snippet = " ".join(tokens[start:end])
    return snippet.strip()


def build_candidate_examples(
    word: str,
    example_indices: Sequence[int],
    utterances: Sequence[Utterance],
    *,
    verbose: bool,
    limit: int = DEFAULT_EXAMPLE_LIMIT,
) -> List[str]:
    examples: List[str] = []
    seen: set[str] = set()
    max_examples = float("inf") if verbose else limit
    for idx in example_indices:
        if idx < 0 or idx >= len(utterances):
            continue
        entry = utterances[idx]
        snippet = snippet_around_word(entry, word)
        formatted = f"[{entry.start} - {entry.end}] {entry.speaker}: {snippet}"
        if formatted in seen:
            continue
        seen.add(formatted)
        examples.append(formatted)
        if len(examples) >= max_examples:
            break
    return examples


def attach_candidate_examples(
    candidates: Dict[str, Dict[str, object]],
    example_map: Dict[str, List[int]],
    utterances: Sequence[Utterance],
    *,
    verbose: bool,
) -> None:
    for word, data in candidates.items():
        indices = example_map.get(word, [])
        if not indices:
            continue
        example_lines = build_candidate_examples(word, indices, utterances, verbose=verbose)
        if example_lines:
            data["examples"] = example_lines


@dataclass
class Utterance:
    idx: int
    start: str
    end: str
    speaker: str
    text: str


@dataclass
class SessionArtifacts:
    session_mistakes: Dict[str, str]
    session_glossary_terms: List[str]
    report: Dict[str, object]
    report_markdown: str


def parse_transcript(path: Path) -> List[Utterance]:
    entries: List[Utterance] = []
    for idx, raw in enumerate(path.read_text(encoding="utf-8").splitlines()):
        match = LINE_RE.match(raw.strip())
        if not match:
            continue
        entries.append(
            Utterance(
                idx=len(entries),
                start=match.group("start"),
                end=match.group("end"),
                speaker=match.group("speaker").strip(),
                text=match.group("text").strip(),
            )
        )
    return entries


def load_glossary_terms(path: Path) -> List[str]:
    terms: List[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        terms.append(stripped)
    return terms


def load_known_mistakes(path: Path) -> Dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("known mistakes JSON must be an object mapping misspellings to corrections")
    return {str(k): str(v) for k, v in data.items()}


def tokenize(text: str) -> List[str]:
    return WORD_RE.findall(text)


def build_known_token_set(
    glossary_terms: Sequence[str],
    known_text_replacements: Dict[str, str],
) -> set[str]:
    known_tokens: set[str] = set()
    for term in glossary_terms:
        known_tokens.add(term)
        for piece in WORD_RE.findall(term):
            known_tokens.add(piece)
    for wrong, right in known_text_replacements.items():
        if wrong:
            known_tokens.add(wrong)
            for piece in WORD_RE.findall(wrong):
                known_tokens.add(piece)
        if right:
            known_tokens.add(right)
            for piece in WORD_RE.findall(right):
                known_tokens.add(piece)
    lower_set = {token.lower() for token in known_tokens}
    return lower_set


@lru_cache(maxsize=2048)
def word_zipf(word: str) -> float:
    return zipf_frequency(word, "en")


def analyze_proper_nouns(
    utterances: Sequence[Utterance],
    known_tokens_lower: set[str],
    min_count: int,
    zipf_threshold: float,
) -> Tuple[Dict[str, Dict[str, object]], Dict[str, List[int]]]:
    counts: Counter[str] = Counter()
    examples: Dict[str, List[int]] = {}
    for entry in utterances:
        for word in tokenize(entry.text):
            if (
                not word
                or not word[0].isupper()
                or word.lower() in known_tokens_lower
            ):
                continue
            counts[word] += 1
            examples.setdefault(word, []).append(entry.idx)

    candidates: Dict[str, Dict[str, object]] = {}
    for word, count in counts.items():
        if count < min_count:
            continue
        score = word_zipf(word)
        if score > zipf_threshold:
            continue
        candidates[word] = {
            "count": count,
            "zipf": round(score, 3),
        }
    return candidates, examples


def detect_known_mistake_usage(
    utterances: Sequence[Utterance],
    known_text_replacements: Dict[str, str],
) -> Dict[str, int]:
    hits: Dict[str, int] = {}

    for wrong in known_text_replacements:
        pattern = re.compile(rf"\b{re.escape(wrong)}\b")
        total = 0
        for entry in utterances:
            occurrences = len(pattern.findall(entry.text))
            if occurrences:
                total += occurrences
        if total:
            hits[wrong] = total
    return hits


def collect_unknown_speakers(entries: Sequence[Utterance], limit: int = UNKNOWN_EXAMPLE_LIMIT) -> Tuple[int, List[str]]:
    unknown_lines: List[str] = []
    count = 0
    for entry in entries:
        if UNKNOWN_SPEAKER_RE.match(entry.speaker):
            count += 1
            if len(unknown_lines) < limit:
                unknown_lines.append(f"[{entry.start} - {entry.end}] {entry.speaker}: {entry.text}")
    return count, unknown_lines


def _build_word_spans(utterances: Sequence[Utterance]) -> List[Dict[str, object]]:
    spans: List[Dict[str, object]] = []
    total = 0
    for entry in utterances:
        words = WORD_RE.findall(entry.text)
        if len(words) < QUALITY_MIN_ENTRY_WORDS:
            continue
        start = total
        total += len(words)
        spans.append(
            {
                "idx": entry.idx,
                "text": entry.text.strip(),
                "start": start,
                "end": total,
            }
        )
    return spans


def _collect_text_for_range(
    spans: Sequence[Dict[str, object]],
    start_word: int,
    end_word: int,
) -> Tuple[str, int, Optional[int], Optional[int]]:
    texts: List[str] = []
    start_idx: Optional[int] = None
    end_idx: Optional[int] = None
    collected = 0
    for span in spans:
        if span["end"] <= start_word:
            continue
        if span["start"] >= end_word:
            break
        texts.append(span["text"])
        if start_idx is None:
            start_idx = span["idx"]
        end_idx = span["idx"]
        overlap = min(span["end"], end_word) - max(span["start"], start_word)
        if overlap > 0:
            collected += overlap
    return " ".join(texts).strip(), collected, start_idx, end_idx


def extract_sample_passages(
    utterances: Sequence[Utterance],
    sample_words: int = 1000,
) -> List[Dict[str, object]]:
    spans = _build_word_spans(utterances)
    if not spans:
        return []
    total_words = spans[-1]["end"]
    if total_words == 0:
        return []

    ranges: List[Tuple[str, int, int]] = []
    if total_words <= sample_words:
        ranges.append(("beginning", 0, total_words))
    else:
        start_end = min(sample_words, total_words)
        ranges.append(("beginning", 0, start_end))
        mid_start = max((total_words // 2) - sample_words // 2, ranges[-1][2])
        mid_end = min(mid_start + sample_words, total_words)
        if mid_end - mid_start > 0:
            ranges.append(("middle", mid_start, mid_end))
        end_start = max(total_words - sample_words, ranges[-1][2] if ranges else 0)
        end_end = total_words
        if end_end - end_start > 0 and (not ranges or end_start >= ranges[-1][2]):
            ranges.append(("end", end_start, end_end))

    samples: List[Dict[str, object]] = []
    for label, start, end in ranges[:3]:
        text, word_count, start_idx, end_idx = _collect_text_for_range(spans, start, end)
        if not text:
            continue
        samples.append(
            {
                "position": label,
                "text": text,
                "word_count": word_count,
                "start_entry_idx": start_idx,
                "end_entry_idx": end_idx,
            }
        )
    return samples


def build_quality_sample(
    utterances: Sequence[Utterance],
    min_words: int = QUALITY_SAMPLE_MIN_WORDS,
    word_limit: Optional[int] = QUALITY_SAMPLE_WORD_LIMIT,
) -> Tuple[List[Utterance], Dict[str, object]]:
    """Return long utterances for QC heuristics plus stats about the source pool."""

    eligible: List[Tuple[Utterance, int]] = []
    for entry in utterances:
        word_count = len(tokenize(entry.text))
        if word_count >= min_words:
            eligible.append((entry, word_count))

    pool_word_total = sum(count for _, count in eligible)
    stats: Dict[str, object]
    if not eligible:
        stats = {
            "pool_segments": 0,
            "pool_words": 0,
            "selected_segments": 0,
            "selected_words": 0,
            "word_limit": word_limit,
            "min_words_per_segment": min_words,
            "truncated": False,
        }
        return [], stats

    selected_entries = [entry for entry, _ in eligible]
    selected_words = pool_word_total
    truncated = False

    if word_limit is not None and pool_word_total > word_limit:
        sorted_segments = sorted(eligible, key=lambda item: item[1], reverse=True)
        chosen: List[Tuple[Utterance, int]] = []
        total = 0
        for entry, count in sorted_segments:
            chosen.append((entry, count))
            total += count
            if total >= word_limit and chosen:
                break
        selected_entries = [entry for entry, _ in sorted(chosen, key=lambda item: item[0].idx)]
        selected_words = total
        truncated = True

    stats = {
        "pool_segments": len(eligible),
        "pool_words": pool_word_total,
        "selected_segments": len(selected_entries),
        "selected_words": selected_words,
        "word_limit": word_limit,
        "min_words_per_segment": min_words,
        "truncated": truncated,
    }
    return selected_entries, stats




def detect_session_glossary_terms(glossary_terms: Sequence[str], utterances: Sequence[Utterance]) -> List[str]:
    present: List[str] = []
    text_blocks = [entry.text for entry in utterances]
    if not glossary_terms or not text_blocks:
        return present
    full_text = "\n".join(text_blocks)
    for term in glossary_terms:
        if not term:
            continue
        pattern = re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)
        if pattern.search(full_text):
            present.append(term)
    return sorted(dict.fromkeys(present), key=str.casefold)


def build_session_mistakes_payload(
    hits: Dict[str, int],
    new_candidates: Dict[str, Dict[str, object]],
    known_text_replacements: Dict[str, str],
) -> Dict[str, str]:
    payload: Dict[str, str] = {}
    for token in sorted(hits):
        payload[token] = known_text_replacements.get(token, "")
    for token in sorted(new_candidates):
        if token in payload:
            continue
        payload[token] = ""
    return payload


def _sentence_loss_details(text: str) -> Tuple[List[float], List[Tuple[int, int]]]:
    tokenizer, model, device = get_lm()
    if not text.strip():
        return [], []
    enc = tokenizer(
        text,
        return_tensors="pt",
        return_offsets_mapping=True,
        truncation=True,
        max_length=tokenizer.model_max_length,
    )
    offsets_tensor = enc.pop("offset_mapping")
    offsets = offsets_tensor[0].tolist()
    tensor_inputs = {key: value.to(device) for key, value in enc.items()}
    input_ids = tensor_inputs["input_ids"]
    attention_mask = tensor_inputs.get("attention_mask")
    with torch.no_grad():
        outputs = model(
            **tensor_inputs,
            labels=input_ids,
        )
        logits = outputs.logits
    shift_logits = logits[:, :-1, :].contiguous()
    shift_labels = input_ids[:, 1:].contiguous()
    shift_offsets = offsets[1:]
    loss_fct = torch.nn.CrossEntropyLoss(reduction="none")
    losses = loss_fct(
        shift_logits.view(-1, shift_logits.size(-1)),
        shift_labels.view(-1),
    )
    return losses.detach().cpu().tolist(), shift_offsets


def _map_losses_to_tokens(
    sent: Span,
    losses: Sequence[float],
    offsets: Sequence[Tuple[int, int]],
) -> List[Tuple[Token, float]]:
    if not losses:
        return []
    start_char = sent.start_char
    token_losses: List[Tuple[spacy.tokens.Token, float]] = []
    for token in sent:
        rel_start = token.idx - start_char
        rel_end = rel_start + len(token.text)
        overlapping: List[float] = []
        for loss, (off_start, off_end) in zip(losses, offsets):
            if off_end <= rel_start or off_start >= rel_end:
                continue
            overlapping.append(loss)
        if overlapping:
            avg_loss = sum(overlapping) / len(overlapping)
        else:
            avg_loss = 0.0
        token_losses.append((token, avg_loss))
    return token_losses


def compute_sentence_profiles(doc: Doc) -> List[Dict[str, object]]:
    profiles: List[Dict[str, object]] = []
    for sent in doc.sents:
        text = sent.text.strip()
        if not text:
            continue
        losses, offsets = _sentence_loss_details(text)
        if not losses:
            continue
        avg_loss = sum(losses) / len(losses)
        token_losses = _map_losses_to_tokens(sent, losses, offsets)
        profiles.append(
            {
                "sentence": sent,
                "avg_loss": avg_loss,
                "losses": losses,
                "offsets": offsets,
                "token_losses": token_losses,
            }
        )
    return profiles


def evaluate_quality_from_profiles(
    profiles: Sequence[Dict[str, object]],
) -> Dict[str, object]:
    if not profiles:
        return {
            "grade": "insufficient_sample",
            "score": None,
            "messiness": None,
            "avg_loss": None,
            "high_loss_ratio": None,
            "sentence_count": 0,
            "notes": "No long-form content available for LM quality scoring.",
        }
    avg_losses = [profile["avg_loss"] for profile in profiles]
    avg_loss = statistics.mean(avg_losses)
    high_loss_ratio = sum(loss > LM_HIGH_LOSS_THRESHOLD for loss in avg_losses) / len(avg_losses)
    messiness = max(0.0, min(1.0, 0.5 * (avg_loss / LM_LOSS_SCALE) + 0.5 * high_loss_ratio))
    score = 1.0 - messiness
    if messiness >= 0.65:
        grade = "rough"
    elif messiness >= 0.45:
        grade = "needs_review"
    else:
        grade = "mostly_clean"
    notes: List[str] = []
    if high_loss_ratio > 0.5:
        notes.append("Many sentences are highly surprising to the language model")
    if avg_loss > LM_HIGH_LOSS_THRESHOLD:
        notes.append("Average sentence loss is high")
    payload: Dict[str, object] = {
        "grade": grade,
        "score": round(score, 3),
        "messiness": round(messiness, 3),
        "avg_loss": round(avg_loss, 3),
        "high_loss_ratio": round(high_loss_ratio, 3),
        "sentence_count": len(profiles),
    }
    if notes:
        payload["notes"] = "; ".join(notes)
    return payload


def detect_transcription_error_spans(
    profiles: Sequence[Dict[str, object]],
    known_tokens_lower: set[str],
    z_threshold: float = TRANSCRIPTION_ERROR_Z,
    max_results: int = TRANSCRIPTION_ERROR_MAX,
) -> List[Dict[str, object]]:
    return _detect_transcription_error_spans(
        profiles,
        known_tokens_lower=known_tokens_lower,
        z_threshold=z_threshold,
        max_results=max_results,
        pad_tokens=TRANSCRIPTION_ERROR_PAD,
    )


def _detect_transcription_error_spans(
    profiles: Sequence[Dict[str, object]],
    known_tokens_lower: set[str],
    z_threshold: float,
    max_results: int,
    pad_tokens: int = 0,
) -> List[Dict[str, object]]:
    suspicious: List[Dict[str, object]] = []
    def token_is_weird(token: Token) -> bool:
        text = token.text.strip()
        if not text:
            return False
        lower = text.lower()
        if lower in known_tokens_lower:
            return False
        if not lower.isalpha():
            return True
        if len(lower) == 1 and lower not in SINGLE_CHAR_ALLOWED:
            return True
        freq = word_zipf(lower)
        if freq < RARE_TOKEN_ZIPF:
            return True
        return False

    for idx, profile in enumerate(profiles):
        token_losses = profile["token_losses"]
        if not token_losses:
            continue
        losses = [loss for _, loss in token_losses]
        if not losses:
            continue
        mean = statistics.mean(losses)
        std = statistics.pstdev(losses) or 1.0
        flags = [((loss - mean) / std) >= z_threshold for loss in losses]
        start: Optional[int] = None
        for pos, flagged in enumerate(flags + [False]):
            if flagged and start is None:
                start = pos
            elif not flagged and start is not None:
                end = pos
                span_tokens = [token_losses[i][0] for i in range(start, end)]
                if not span_tokens:
                    start = None
                    continue
                normalized_tokens = [
                    token.text.lower() for token in span_tokens if token.text.strip()
                ]
                if normalized_tokens and all(token in known_tokens_lower for token in normalized_tokens):
                    start = None
                    continue
                if not any(token_is_weird(token) for token in span_tokens):
                    start = None
                    continue
                sentence_span: Span = profile["sentence"]
                doc = sentence_span.doc
                span_start = span_tokens[0].i
                span_end = span_tokens[-1].i + 1
                if pad_tokens:
                    span_start = max(sentence_span.start, span_start - pad_tokens)
                    span_end = min(sentence_span.end, span_end + pad_tokens)
                span = doc[span_start:span_end]
                span_loss = statistics.mean([token_losses[i][1] for i in range(start, end)])
                suspicious.append(
                    {
                        "text": span.text.strip(),
                        "mean_loss": round(span_loss, 3),
                        "sentence_index": idx,
                        "sentence": profile["sentence"].text.strip(),
                    }
                )
                start = None
    suspicious.sort(key=lambda item: item["mean_loss"], reverse=True)
    return suspicious[:max_results]


def build_markdown_report(report_data: Dict[str, object]) -> str:
    """Render the QC payload as human-friendly Markdown."""

    def fmt_percent(value: Optional[float]) -> str:
        if value is None:
            return "n/a"
        return f"{value * 100:.1f}%"

    def fmt_float(value: Optional[float], digits: int = 2) -> str:
        if value is None:
            return "n/a"
        return f"{value:.{digits}f}"

    def escape_pipes(text: str) -> str:
        return text.replace("|", r"\|")

    metadata = report_data.get("metadata", {})
    speaker_summary = report_data.get("speaker_summary", {})
    quality_sample = report_data.get("quality_sample", {})
    quality = report_data.get("quality", {})
    proper_candidates = report_data.get("proper_noun_candidates", {})
    transcription_errors = report_data.get("transcription_errors", [])
    artifacts = report_data.get("artifacts", {})

    lines: List[str] = ["# Transcript QC Report", ""]

    lines.append("## Metadata")
    transcript_path = metadata.get("transcript", "")
    if transcript_path:
        lines.append(f"- Transcript: `{transcript_path}`")
    lines.append(f"- Total lines: {metadata.get('total_lines', 0)}")
    lines.append(f"- Total words: {metadata.get('total_words', 0)}")
    if quality_sample:
        limit = quality_sample.get("word_limit")
        if limit:
            limit_text = f"limit {limit} words"
        else:
            limit_text = "full transcript"
        lines.append(
            f"- Quality sample: {quality_sample.get('selected_segments', 0)} segments / "
            f"{quality_sample.get('selected_words', 0)} words "
            f"(min {quality_sample.get('min_words_per_segment', 0)} words per segment; "
            f"{limit_text})"
        )
        lines.append(
            f"- Eligible pool: {quality_sample.get('pool_segments', 0)} segments / "
            f"{quality_sample.get('pool_words', 0)} words"
        )
        if quality_sample.get("truncated"):
            lines.append("- Sample trimmed to the longest segments to hit the word limit.")
    lines.append("")

    lines.append("## Speaker Summary")
    lines.append(f"- Unique speakers: {speaker_summary.get('unique_speakers', 0)}")
    unknown_count = speaker_summary.get("unknown_speaker_count", 0)
    lines.append(f"- Unknown speaker lines: {unknown_count}")
    top_speakers = speaker_summary.get("top_speakers") or []
    if top_speakers:
        lines.append("")
        lines.append("| Speaker | Words |")
        lines.append("| --- | ---: |")
        for name, count in top_speakers:
            lines.append(f"| {escape_pipes(name)} | {count} |")
        lines.append("")
    unknown_examples = speaker_summary.get("unknown_examples") or []
    if unknown_examples:
        lines.append("**Unknown speaker examples**")
        for example in unknown_examples:
            lines.append(f"- {escape_pipes(example)}")
        lines.append("")

    lines.append("## Quality Overview")
    grade = quality.get("grade", "n/a")
    lines.append(f"- Grade: **{grade}**")
    score = quality.get("score")
    messiness = quality.get("messiness")
    lines.append(f"- Score: {fmt_float(score)}")
    lines.append(f"- Messiness: {fmt_float(messiness)}")
    lines.append(f"- Sample word count: {quality.get('sample_word_count', 0)}")
    lines.append(f"- Sentences analyzed: {quality.get('sentence_count', 0)}")
    if quality.get("notes"):
        lines.append(f"- Notes: {quality['notes']}")
    metric_rows = [
        ("Average LM loss", fmt_float(quality.get("avg_loss"))),
        ("High-loss ratio", fmt_percent(quality.get("high_loss_ratio"))),
    ]
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("| --- | --- |")
    for label, value in metric_rows:
        lines.append(f"| {label} | {value} |")
    lines.append("")

    lines.append("## Candidate Proper Nouns")
    if proper_candidates:
        sorted_candidates = sorted(
            proper_candidates.items(),
            key=lambda item: (-item[1].get("count", 0), item[0]),
        )
        lines.append("| Word | Count | Zipf |")
        lines.append("| --- | ---: | ---: |")
        limit = 15
        for word, details in sorted_candidates[:limit]:
            count = details.get("count", 0)
            zipf_val = details.get("zipf")
            zipf_str = fmt_float(zipf_val, 3) if isinstance(zipf_val, (int, float)) else "n/a"
            lines.append(f"| {escape_pipes(word)} | {count} | {zipf_str} |")
        if len(sorted_candidates) > limit:
            lines.append(f"*…plus {len(sorted_candidates) - limit} additional candidates.*")
        context_candidates = [
            (word, details)
            for word, details in sorted_candidates
            if details.get("count", 0) > 1 and details.get("examples")
        ]
        if context_candidates:
            lines.append("")
            lines.append("**Contexts for repeated candidates**")
            context_limit = 10
            for word, details in context_candidates[:context_limit]:
                snippet = escape_pipes(details.get("examples", [""])[0])
                count = details.get("count", 0)
                lines.append(f"- `{escape_pipes(word)}` (count {count}): {snippet}")
            if len(context_candidates) > context_limit:
                lines.append(f"*…plus {len(context_candidates) - context_limit} additional contexts.*")
            lines.append("")
    else:
        lines.append("_No low-frequency proper noun candidates detected._")
        lines.append("")

    lines.append("## Suspected Transcription Errors")
    if transcription_errors:
        lines.append("| Span | Mean Loss | Sentence |")
        lines.append("| --- | ---: | --- |")
        for error in transcription_errors:
            span = escape_pipes(error.get("text", ""))
            mean_loss = fmt_float(error.get("mean_loss"))
            sentence = escape_pipes(error.get("sentence", ""))
            lines.append(f"| {span} | {mean_loss} | {sentence} |")
        lines.append("")
    else:
        lines.append("_No high-surprisal spans detected in the sample._")
        lines.append("")

    lines.append("## Session Artifacts")
    lines.append(f"- Report path: `{artifacts.get('report_path', '')}`")
    lines.append(f"- Session known mistakes: `{artifacts.get('session_known_mistakes', '')}`")
    lines.append(f"- Session glossary: `{artifacts.get('session_glossary', '')}`")

    return "\n".join(lines).strip() + "\n"


def preprocess_transcript(
    method_bundle_path: Path,
    known_mistakes_path: Path,
    glossary_path: Path,
    report_path: Path,
    session_mistakes_path: Path,
    session_glossary_path: Path,
    min_proper_count: int,
    proper_zipf_threshold: float,
    verbose_examples: bool = False,
) -> SessionArtifacts:
    method_bundle_path = method_bundle_path.expanduser()
    if not method_bundle_path.exists() or not method_bundle_path.is_dir():
        raise SystemExit(f"Method bundle directory not found: {method_bundle_path}")
    transcript_path, _, _, _ = derive_bundle_paths(method_bundle_path)
    if not transcript_path.exists():
        raise SystemExit(f"Transcript not found: {transcript_path}")

    utterances = parse_transcript(transcript_path)
    if not utterances:
        raise SystemExit(f"No parseable lines found in {transcript_path}")

    known_text = load_known_mistakes(known_mistakes_path)
    glossary_terms = load_glossary_terms(glossary_path)
    known_tokens_lower = build_known_token_set(glossary_terms, known_text)

    speaker_counts: Counter[str] = Counter()
    total_words = 0
    for entry in utterances:
        word_count = len(tokenize(entry.text))
        speaker_counts[entry.speaker] += word_count
        total_words += word_count
    total_lines = len(utterances)
    unknown_count, unknown_examples = collect_unknown_speakers(utterances)
    quality_entries, quality_sample_stats = build_quality_sample(utterances)

    proper_candidates, candidate_examples = analyze_proper_nouns(
        utterances,
        known_tokens_lower,
        min_proper_count,
        proper_zipf_threshold,
    )
    attach_candidate_examples(
        proper_candidates,
        candidate_examples,
        utterances,
        verbose=verbose_examples,
    )
    mistake_hits = detect_known_mistake_usage(utterances, known_text)
    sample_text = " ".join(entry.text.strip() for entry in quality_entries if entry.text).strip()
    sample_word_count = sum(len(tokenize(entry.text)) for entry in quality_entries)
    if sample_text:
        doc = get_nlp()(sample_text)
        sentence_profiles = compute_sentence_profiles(doc)
        quality_payload = evaluate_quality_from_profiles(sentence_profiles)
        transcription_errors = detect_transcription_error_spans(sentence_profiles, known_tokens_lower)
    else:
        quality_payload = evaluate_quality_from_profiles([])
        transcription_errors = []
    quality_payload["sample_word_count"] = sample_word_count
    session_glossary_terms = detect_session_glossary_terms(glossary_terms, utterances)

    new_candidates = {
        word: data
        for word, data in proper_candidates.items()
        if word.lower() not in known_tokens_lower
    }
    session_mistakes_payload = build_session_mistakes_payload(mistake_hits, new_candidates, known_text)

    report_data = {
        "metadata": {
            "transcript": str(transcript_path),
            "total_lines": total_lines,
            "total_words": total_words,
        },
        "quality_sample": quality_sample_stats,
        "speaker_summary": {
            "unique_speakers": len(speaker_counts),
            "top_speakers": speaker_counts.most_common(10),
            "unknown_speaker_count": unknown_count,
            "unknown_examples": unknown_examples,
        },
        "quality": quality_payload,
        "proper_noun_candidates": proper_candidates,
        "transcription_errors": transcription_errors,
        "artifacts": {
            "report_path": str(report_path),
            "session_known_mistakes": str(session_mistakes_path),
            "session_glossary": str(session_glossary_path),
        },
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_markdown = build_markdown_report(report_data)
    report_path.write_text(report_markdown, encoding="utf-8")

    session_mistakes_path.parent.mkdir(parents=True, exist_ok=True)
    session_mistakes_path.write_text(
        json.dumps(session_mistakes_payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    session_glossary_path.parent.mkdir(parents=True, exist_ok=True)
    session_glossary_path.write_text("\n".join(session_glossary_terms) + ("\n" if session_glossary_terms else ""), encoding="utf-8")

    return SessionArtifacts(
        session_mistakes=session_mistakes_payload,
        session_glossary_terms=session_glossary_terms,
        report=report_data,
        report_markdown=report_markdown,
    )


def derive_bundle_paths(method_bundle_path: Path) -> Tuple[Path, Path, Path, Path]:
    bundle_path = method_bundle_path.expanduser()
    bundle_name = bundle_path.name
    transcript = bundle_path / f"{bundle_name}.transcript.txt"
    parent_dir = bundle_path.parent
    report = parent_dir / f"{bundle_name}.transcript.preprocess.md"
    session_mistakes = parent_dir / f"{bundle_name}.transcript.session-known-mistakes.json"
    session_glossary = parent_dir / f"{bundle_name}.transcript.session-glossary.txt"
    return transcript, report, session_mistakes, session_glossary


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze a method bundle and export QC + session artifacts.")
    parser.add_argument(
        "bundle",
        type=Path,
        help="Path to method bundle directory (expects `<name>.transcript.txt` inside)",
    )
    parser.add_argument(
        "-k",
        "--known",
        "--known-mistakes",
        dest="known_mistakes",
        type=Path,
        required=True,
        help="JSON of known replacements",
    )
    parser.add_argument(
        "-g",
        "--glossary",
        type=Path,
        required=True,
        help="Plain-text glossary (one canonical term per line)",
    )
    parser.add_argument("-r", "--report", dest="report_path", type=Path, help="Override preprocess report output path")
    parser.add_argument(
        "-m",
        "--session-mistakes",
        dest="session_mistakes_path",
        type=Path,
        help="Override session mistakes output path",
    )
    parser.add_argument(
        "-s",
        "--session-glossary",
        dest="session_glossary_path",
        type=Path,
        help="Override session glossary output path",
    )
    parser.add_argument(
        "-c",
        "--min-count",
        dest="min_proper_count",
        type=int,
        default=2,
        help="Minimum count for proper noun candidates",
    )
    parser.add_argument(
        "-z",
        "--zipf",
        dest="proper_zipf_threshold",
        type=float,
        default=4.0,
        help="ZIPF ceiling for proper noun candidates",
    )
    parser.add_argument(
        "-V",
        "--verbose-report",
        action="store_true",
        dest="verbose_report",
        help="Include full example lists for every proper noun candidate",
    )
    args = parser.parse_args()

    transcript_path, default_report, default_session_mistakes, default_session_glossary = derive_bundle_paths(args.bundle)
    if not transcript_path.exists():
        raise SystemExit(f"Transcript not found: {transcript_path}")
    report_path = args.report_path or default_report
    session_mistakes_path = args.session_mistakes_path or default_session_mistakes
    session_glossary_path = args.session_glossary_path or default_session_glossary

    result = preprocess_transcript(
        method_bundle_path=args.bundle,
        known_mistakes_path=args.known_mistakes,
        glossary_path=args.glossary,
        report_path=report_path,
        session_mistakes_path=session_mistakes_path,
        session_glossary_path=session_glossary_path,
        min_proper_count=args.min_proper_count,
        proper_zipf_threshold=args.proper_zipf_threshold,
        verbose_examples=args.verbose_report,
    )

    print(f"Wrote report → {report_path}")
    print(f"Wrote session mistakes → {session_mistakes_path} ({len(result.session_mistakes)} entries)")
    print(f"Wrote session glossary → {session_glossary_path} ({len(result.session_glossary_terms)} terms)")


if __name__ == "__main__":
    main()
