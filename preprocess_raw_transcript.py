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
from typing import Dict, List, Sequence, Tuple, Optional, Iterable
from functools import lru_cache

try:  # pragma: no cover - required dependency
    from wordfreq import zipf_frequency
except ImportError:
    print("[error] wordfreq is required. Install via 'pip install wordfreq'.", file=sys.stderr)
    raise SystemExit(1)

try:  # pragma: no cover - required dependency
    import spacy
    from spacy.language import Language
except ImportError:
    print("[error] spaCy is required. Install via 'pip install spacy'.", file=sys.stderr)
    raise SystemExit(1)

LINE_RE = re.compile(r"^\[(?P<start>[0-9:\.]+)\s*-\s*(?P<end>[0-9:\.]+)\]\s*(?P<speaker>[^:]+):\s*(?P<text>.*)$")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\-]+")
SENTENCE_SPLIT_RE = re.compile(r"[.!?]+")
UNKNOWN_SPEAKER_RE = re.compile(r"^unknown(?:\b|[_\s-])", re.IGNORECASE)
FILLERS = {"uh", "um", "erm", "hmm", "like", "kinda", "sorta", "youknow", "yknow", "y'know"}
QUALITY_MIN_ENTRY_WORDS = 4
QUALITY_MIN_SENTENCE_WORDS = 6
PUNCTUATION_CHARS = set(".?!,;:-")
DEFAULT_EXAMPLE_LIMIT = 3
EXAMPLE_WINDOW_WORDS = 50
MAX_PUNCT_GAP_THRESHOLD = 80


_NLP: Language | None = None


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


def collect_unknown_speakers(entries: Sequence[Utterance]) -> Tuple[int, List[str]]:
    unknown_lines: List[str] = []
    count = 0
    for entry in entries:
        if UNKNOWN_SPEAKER_RE.match(entry.speaker):
            count += 1
            if len(unknown_lines) < 5:
                unknown_lines.append(f"[{entry.start} - {entry.end}] {entry.speaker}: {entry.text}")
    return count, unknown_lines


def compute_token_noise(
    utterances: Sequence[Utterance],
    known_tokens_lower: set[str],
    noise_zipf_threshold: float = 2.5,
) -> Dict[str, object]:
    total_tokens = 0
    noisy_tokens = 0
    for entry in utterances:
        tokens_in_entry = tokenize(entry.text)
        if len(tokens_in_entry) < QUALITY_MIN_ENTRY_WORDS:
            continue
        for token in tokens_in_entry:
            total_tokens += 1
            lower = token.lower()
            if lower in known_tokens_lower:
                continue
            freq = word_zipf(lower)
            if freq <= noise_zipf_threshold:
                noisy_tokens += 1
    ratio = noisy_tokens / total_tokens if total_tokens else 0.0
    return {
        "total_tokens": total_tokens,
        "noisy_tokens": noisy_tokens,
        "noise_ratio": ratio,
    }


def max_tokens_without_punctuation(utterances: Sequence[Utterance]) -> int:
    longest = 0
    current = 0
    for entry in utterances:
        tokens = entry.text.split()
        if len(tokens) < QUALITY_MIN_ENTRY_WORDS:
            continue
        for token in tokens:
            if any(ch in PUNCTUATION_CHARS for ch in token):
                longest = max(longest, current)
                current = 0
            else:
                current += 1
    longest = max(longest, current)
    return longest


def split_sentences(utterances: Sequence[Utterance]) -> List[Tuple[str, int]]:
    sentences: List[Tuple[str, int]] = []
    for entry in utterances:
        raw = entry.text.strip()
        if not raw:
            continue
        parts = [segment.strip() for segment in SENTENCE_SPLIT_RE.split(raw) if segment.strip()]
        if not parts:
            words = tokenize(raw)
            if words:
                sentences.append((raw, len(words)))
            continue
        for part in parts:
            words = tokenize(part)
            if not words:
                continue
            sentences.append((part, len(words)))
    return sentences


def analyze_sentence_structure(sentences_with_len: Sequence[Tuple[str, int]]) -> Dict[str, object]:
    if not sentences_with_len:
        return {
            "sentence_count": 0,
            "avg_sentence_length": 0.0,
            "fragment_ratio": 0.0,
            "verbless_ratio": 0.0,
            "comma_density": 0.0,
            "non_terminal_ratio": 0.0,
        }
    sentences = [sentence for sentence, _ in sentences_with_len]
    lengths = [length for _, length in sentences_with_len]
    fragment_count = sum(1 for length in lengths if length < QUALITY_MIN_SENTENCE_WORDS)
    long_sentences = [
        sentence for sentence, length in sentences_with_len if length >= QUALITY_MIN_SENTENCE_WORDS
    ]
    if long_sentences:
        verbless = sum(1 for sentence in long_sentences if not sentence_has_verb(sentence))
        verbless_ratio = verbless / len(long_sentences)
    else:
        verbless_ratio = 0.0
    comma_count = sum(sentence.count(",") for sentence in sentences)
    non_terminal = sum(1 for sentence in sentences if not sentence.endswith((".", "!", "?")))
    return {
        "sentence_count": len(sentences),
        "avg_sentence_length": statistics.mean(lengths),
        "fragment_ratio": fragment_count / len(sentences),
        "verbless_ratio": verbless_ratio,
        "comma_density": comma_count / len(sentences),
        "non_terminal_ratio": non_terminal / len(sentences),
    }
    if not sentences:
        return {
            "sentence_count": 0,
            "avg_sentence_length": 0.0,
            "fragment_ratio": 0.0,
            "verbless_ratio": 0.0,
            "comma_density": 0.0,
            "non_terminal_ratio": 0.0,
        }
    lengths = [len(tokenize(sentence)) for sentence in sentences]
    fragment_count = sum(1 for length in lengths if length < 4)
    long_sentences = [
        sentence for sentence, length in zip(sentences, lengths) if length >= 5
    ]
    if long_sentences:
        verbless = sum(1 for sentence in long_sentences if not sentence_has_verb(sentence))
        verbless_ratio = verbless / len(long_sentences)
    else:
        verbless_ratio = 0.0
    comma_count = sum(sentence.count(",") for sentence in sentences)
    non_terminal = sum(1 for sentence in sentences if not sentence.endswith((".", "!", "?")))
    return {
        "sentence_count": len(sentences),
        "avg_sentence_length": statistics.mean(lengths),
        "fragment_ratio": fragment_count / len(sentences),
        "verbless_ratio": verbless_ratio,
        "comma_density": comma_count / len(sentences),
        "non_terminal_ratio": non_terminal / len(sentences),
    }


def sentence_has_verb(sentence: str) -> bool:
    doc = get_nlp()(sentence)
    return any(token.pos_ == "VERB" for token in doc)


def _build_word_spans(utterances: Sequence[Utterance]) -> List[Dict[str, object]]:
    spans: List[Dict[str, object]] = []
    total = 0
    for entry in utterances:
        words = WORD_RE.findall(entry.text)
        if not words:
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


def transcript_clean_score(text: str) -> float:
    """Return a cleanliness score in [0, 1] using spaCy-derived heuristics."""

    doc = get_nlp()(text)
    tokens = [token for token in doc if not token.is_space]
    if not tokens:
        return 0.0
    alpha_tokens = [token for token in tokens if token.is_alpha]
    n_alpha = len(alpha_tokens) or 1
    n_tokens = len(tokens)
    sents = list(doc.sents)
    n_sents = len(sents) or 1
    avg_sent_len = n_alpha / n_sents
    oov_ratio = sum(token.is_oov for token in alpha_tokens) / n_alpha
    punct_ratio = sum(token.is_punct for token in tokens) / n_tokens
    run = 0
    longest_run = 0
    for token in tokens:
        if token.is_punct:
            longest_run = max(longest_run, run)
            run = 0
        else:
            run += 1
    longest_run = max(longest_run, run)
    fillers = sum(
        1
        for token in alpha_tokens
        if token.lower_.replace(" ", "").replace("'", "") in FILLERS
    )
    filler_ratio = fillers / n_alpha
    score = 1.0
    score -= oov_ratio * 0.7
    score -= filler_ratio * 0.5
    if avg_sent_len > 40:
        score -= 0.2
    if longest_run > 60:
        score -= 0.2
    if punct_ratio < 0.01:
        score -= 0.2
    return max(0.0, min(1.0, score))


def is_clean_transcript(text: str, threshold: float = 0.6) -> bool:
    return transcript_clean_score(text) >= threshold


def analyze_bigrams(
    utterances: Sequence[Utterance],
    known_tokens_lower: set[str],
    zipf_threshold: float = 3.0,
    limit: int = 10,
    skip_tokens: Optional[Iterable[str]] = None,
) -> List[Dict[str, object]]:
    bigram_counts: Counter[Tuple[str, str]] = Counter()
    first_seen: Dict[Tuple[str, str], Tuple[int, str]] = {}
    skip_set = {token.lower() for token in skip_tokens} if skip_tokens else set()
    for entry in utterances:
        tokens = [token.lower() for token in tokenize(entry.text)]
        for idx in range(len(tokens) - 1):
            pair = (tokens[idx], tokens[idx + 1])
            if pair[0] in known_tokens_lower or pair[1] in known_tokens_lower:
                continue
            if pair[0] in skip_set or pair[1] in skip_set:
                continue
            bigram_counts[pair] += 1
            first_seen.setdefault(pair, (entry.idx, entry.text))
    suspicious: List[Tuple[Tuple[str, str], int, float]] = []
    for pair, count in bigram_counts.items():
        min_zipf = min(word_zipf(pair[0]), word_zipf(pair[1]))
        if min_zipf <= zipf_threshold and count <= 2:
            suspicious.append((pair, count, min_zipf))
    suspicious.sort(key=lambda item: (item[2], -item[1]))
    results: List[Dict[str, object]] = []
    for pair, count, min_zipf in suspicious[:limit]:
        idx, text = first_seen[pair]
        results.append(
            {
                "pair": " ".join(pair),
                "count": count,
                "min_zipf": round(min_zipf, 3),
                "first_example_idx": idx,
                "example_text": text,
            }
        )
    return results


def rate_quality(
    token_noise_ratio: float,
    fragment_ratio: float,
    verbless_ratio: float,
    suspicious_bigram_count: int,
    cleanliness_scores: Optional[Sequence[float]] = None,
    max_punct_gap: int = 0,
) -> Tuple[str, str]:
    issues = 0
    notes: List[str] = []
    if token_noise_ratio > 0.25:
        issues += 1
        notes.append("High share of low-frequency tokens")
    if fragment_ratio > 0.4:
        issues += 1
        notes.append("Many short fragments")
    if verbless_ratio > 0.35:
        issues += 1
        notes.append("Sentences often missing common verbs")
    if suspicious_bigram_count >= 5:
        issues += 1
        notes.append("Numerous low-frequency bigrams")
    if cleanliness_scores:
        avg_clean = statistics.mean(cleanliness_scores)
        if avg_clean < 0.45:
            issues += 1
            notes.append(f"Transcript clean score low ({avg_clean:.2f})")
        elif avg_clean < 0.6:
            notes.append(f"Transcript clean score moderate ({avg_clean:.2f})")
    if max_punct_gap > MAX_PUNCT_GAP_THRESHOLD:
        issues += 1
        notes.append(f"Long stretches without punctuation ({max_punct_gap} tokens)")

    if issues >= 3:
        return "rough", "; ".join(notes)
    if issues == 2:
        return "needs_review", "; ".join(notes)
    return "mostly_clean", "; ".join(notes) if notes else "looks solid"


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


def preprocess_transcript(
    transcript_path: Path,
    known_mistakes_path: Path,
    glossary_path: Path,
    report_path: Path,
    session_mistakes_path: Path,
    session_glossary_path: Path,
    min_proper_count: int,
    proper_zipf_threshold: float,
    verbose_examples: bool = False,
) -> SessionArtifacts:
    utterances = parse_transcript(transcript_path)
    if not utterances:
        raise SystemExit(f"No parseable lines found in {transcript_path}")

    known_text = load_known_mistakes(known_mistakes_path)
    glossary_terms = load_glossary_terms(glossary_path)
    known_tokens_lower = build_known_token_set(glossary_terms, known_text)

    speaker_counts: Counter[str] = Counter(entry.speaker for entry in utterances)
    total_lines = len(utterances)
    total_words = sum(len(tokenize(entry.text)) for entry in utterances)
    unknown_count, unknown_examples = collect_unknown_speakers(utterances)

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
    token_noise = compute_token_noise(utterances, known_tokens_lower)
    max_gap = max_tokens_without_punctuation(utterances)
    sentences = split_sentences(utterances)
    sentence_metrics = analyze_sentence_structure(sentences)
    candidate_lower = {word.lower() for word in proper_candidates}
    skip_tokens = candidate_lower | known_tokens_lower
    bigrams = analyze_bigrams(
        utterances,
        known_tokens_lower,
        skip_tokens=skip_tokens,
    )
    sample_passages = extract_sample_passages(utterances)
    sample_scores: List[Dict[str, object]] = []
    for idx, sample in enumerate(sample_passages):
        score = transcript_clean_score(sample["text"])
        sample_scores.append(
            {
                "sample_index": idx,
                "score": round(score, 3),
                "word_count": sample["word_count"],
                "start_entry_idx": sample["start_entry_idx"],
                "end_entry_idx": sample["end_entry_idx"],
                "position": sample.get("position"),
            }
        )
    avg_clean_score = statistics.mean([s["score"] for s in sample_scores]) if sample_scores else None
    quality_grade, quality_notes = rate_quality(
        token_noise_ratio=token_noise["noise_ratio"],
        fragment_ratio=sentence_metrics["fragment_ratio"],
        verbless_ratio=sentence_metrics["verbless_ratio"],
        suspicious_bigram_count=len(bigrams),
        cleanliness_scores=[s["score"] for s in sample_scores],
        max_punct_gap=max_gap,
    )
    session_glossary_terms = detect_session_glossary_terms(glossary_terms, utterances)

    new_candidates = {
        word: data
        for word, data in proper_candidates.items()
        if word.lower() not in known_tokens_lower
    }
    session_mistakes_payload = build_session_mistakes_payload(mistake_hits, new_candidates, known_text)

    report = {
        "metadata": {
            "transcript": str(transcript_path),
            "total_lines": total_lines,
            "total_words": total_words,
        },
        "speaker_summary": {
            "unique_speakers": len(speaker_counts),
            "top_speakers": speaker_counts.most_common(10),
            "unknown_speaker_count": unknown_count,
            "unknown_examples": unknown_examples,
        },
        "token_stats": {**token_noise, "max_tokens_without_punct": max_gap},
        "sentence_metrics": sentence_metrics,
        "quality": {
            "grade": quality_grade,
            "notes": quality_notes,
            "cleanliness_samples": {
                "count": len(sample_scores),
                "average_score": round(avg_clean_score, 3) if avg_clean_score is not None else None,
                "scores": sample_scores,
            },
        },
        "proper_noun_candidates": proper_candidates,
        "suspicious_bigrams": bigrams,
        "artifacts": {
            "report_path": str(report_path),
            "session_known_mistakes": str(session_mistakes_path),
            "session_glossary": str(session_glossary_path),
        },
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

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
        report=report,
    )


def derive_default_paths(transcript: Path) -> Tuple[Path, Path, Path]:
    report = transcript.with_suffix(".preprocess.json")
    session_mistakes = transcript.with_suffix(".session-known-mistakes.json")
    session_glossary = transcript.with_suffix(".session-glossary.txt")
    return report, session_mistakes, session_glossary


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze a raw transcript and export QC + session artifacts.")
    parser.add_argument("transcript", type=Path, help="Path to `[start - end] Speaker: text` transcript")
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

    report_path, session_mistakes_path, session_glossary_path = derive_default_paths(args.transcript)
    if args.report_path:
        report_path = args.report_path
    if args.session_mistakes_path:
        session_mistakes_path = args.session_mistakes_path
    if args.session_glossary_path:
        session_glossary_path = args.session_glossary_path

    result = preprocess_transcript(
        transcript_path=args.transcript,
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
