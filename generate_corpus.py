#!/usr/bin/env python3
"""
Stage 0: Corpus generation for Taelgar transcripts.

Usage:
    python generate_corpus.py --config path/to/config.yaml

Config YAML format:

vault_root: "/path/to/ObsidianVault"
transcript_root: "/path/to/raw_transcripts"
corpus_state_root: "/path/to/taelgar-data/corpus_state"

canonical_tags:
  - person
  - place
  - organization
  - item
  - deity
  - species
  - event
  - holiday
  - culture

transcript_globs:
  - "**/*.txt"
  - "**/*.vtt"
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import datetime as dt
import hashlib
import json
import pickle
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml
from wordfreq import zipf_frequency


# ---------------------------------------------------------------------------
# Config & data models
# ---------------------------------------------------------------------------

@dataclass
class CorpusConfig:
    vault_root: Path
    transcript_root: Path
    corpus_state_root: Path
    canonical_tags: List[str]
    transcript_globs: List[str]
    token_min_doc_count: int = 1
    token_long_length: int = 10
    token_short_max_zipf: float = 2.5
    token_long_max_zipf: float = 3.3
    bigram_max_doc_count: int = 20
    bigram_min_component_zipf: float = 2.0

    @classmethod
    def from_yaml(cls, path: Path) -> "CorpusConfig":
        data = yaml.safe_load(path.read_text()) or {}
        base_dir = path.parent.resolve()

        def resolve_path(raw: str) -> Path:
            p = Path(str(raw)).expanduser()
            if not p.is_absolute():
                p = base_dir / p
            return p

        return cls(
            vault_root=resolve_path(data["vault_root"]),
            transcript_root=resolve_path(data["transcript_root"]),
            corpus_state_root=resolve_path(data["corpus_state_root"]),
            canonical_tags=[str(tag).lower() for tag in data["canonical_tags"]],
            transcript_globs=[str(g) for g in data.get("transcript_globs", ["**/*.txt"])],
            token_min_doc_count=int(data.get("token_min_doc_count", 1)),
            token_long_length=int(data.get("token_long_length", 10)),
            token_short_max_zipf=float(data.get("token_short_max_zipf", 2.5)),
            token_long_max_zipf=float(data.get("token_long_max_zipf", 3.3)),
            bigram_max_doc_count=int(data.get("bigram_max_doc_count", 20)),
            bigram_min_component_zipf=float(data.get("bigram_min_component_zipf", 2.0)),
        )


@dataclass
class VaultNote:
    note_id: str
    path: str         # relative to vault root
    canonical_name: str
    note_type: str
    full_name: str | None = None
    short_name: str | None = None


@dataclass
class Count:
    total: int = 0
    docs: int = 0


@dataclass
class TranscriptTask:
    transcript_id: str
    path: Path
    rel_path: str
    file_hash: str
    added_at: str


@dataclass
class SegmentTokens:
    text: str
    tokens: List[str]
    lower_tokens: List[str]


@dataclass
class TranscriptCounts:
    tokens: Dict[str, Count]
    bigrams: Dict[Tuple[str, str], Count]


@dataclass
class TranscriptPlan:
    tasks: List[TranscriptTask]
    updated_index: List[Dict[str, Any]] | None
    removed_ids: List[str]
    mode: str  # "normal", "force_all", "force_one"


SLUG_RE = re.compile(r"[^a-z0-9]+")
TIMESTAMP_LINE_RE = re.compile(r"^\s*\[[^]]+\]\s*[^:]+:\s*(?P<text>.*)$")
WORD_RE = re.compile(r"[A-Za-z0-9'-]+")
COMMON_WORD_ZIPF = 3.5
CONTEXT_SIDE_TARGET = 15
CONTEXT_MAX_WORDS = 50


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def slugify(term: str) -> str:
    s = term.lower()
    s = SLUG_RE.sub("_", s)
    return s.strip("_")


def slugify_path(rel_path: Path) -> str:
    as_posix = rel_path.as_posix()
    slug = slugify(as_posix)
    digest = hashlib.sha1(as_posix.encode("utf-8")).hexdigest()[:8]
    return f"{slug}_{digest}" if slug else digest


def extract_transcript_segments(raw_text: str) -> List[str]:
    """
    Extract the text portion of `[timestamp] Speaker: text` transcripts.
    If no structured lines are found, return the full text as a single segment.
    """
    segments: List[str] = []
    for line in raw_text.splitlines():
        match = TIMESTAMP_LINE_RE.match(line)
        if match:
            text = match.group("text").strip()
            if text:
                segments.append(text)
    if segments:
        return segments
    cleaned = raw_text.strip()
    return [cleaned] if cleaned else []


def extract_h1_title(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None
    lines = text.splitlines()
    idx = 0
    if lines and FRONTMATTER_RE.match(lines[0]):
        idx = 1
        while idx < len(lines) and not FRONTMATTER_RE.match(lines[idx]):
            idx += 1
        idx += 1
    for line in lines[idx:]:
        if line.startswith("# "):
            return line[2:].strip()
    return None


def normalize_name(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    name = value.strip()
    if not name:
        return None
    if name.lower().startswith("the "):
        name = name[4:].strip()
    return name or None


def choose_note_names(file_name: str | None,
                      yaml_name: str | None,
                      header_name: str | None) -> Tuple[str, str | None, str | None]:
    candidates: List[str] = []
    sources = []
    for label, value in (("file", file_name), ("yaml", yaml_name), ("header", header_name)):
        if value:
            candidates.append(value)
            sources.append((label, value))

    if not candidates:
        raise ValueError("At least one name must be provided")

    unique_lower = {name.lower() for name in candidates}
    if len(unique_lower) == 1:
        canonical = candidates[0]
        return canonical, None, None

    canonical = yaml_name or file_name or candidates[0]
    canonical_lower = canonical.lower()

    others = [name for name in candidates if name.lower() != canonical_lower]

    full_name = None
    if others:
        longest = max(others, key=len)
        if len(longest) > len(canonical):
            full_name = longest

    short_name = None
    if others:
        shortest = min(others, key=len)
        if len(shortest) < len(canonical):
            short_name = shortest

    if not short_name and len(canonical.split()) > 1:
        short_name = canonical.split()[0]

    return canonical, full_name, short_name


def is_common_word(token: str) -> bool:
    """
    Return True if the token is common English (high zipf frequency) and should
    be ignored for lexicon purposes.
    """
    return zipf_frequency(token, "en") >= COMMON_WORD_ZIPF


def prepare_segments(raw_text: str) -> List[SegmentTokens]:
    segments: List[SegmentTokens] = []
    for text in extract_transcript_segments(raw_text):
        tokens = [m.group(0) for m in WORD_RE.finditer(text)]
        lower_tokens = [tok.lower() for tok in tokens]
        segments.append(SegmentTokens(text=text, tokens=tokens, lower_tokens=lower_tokens))
    return segments


def collect_neighbor_tokens(segments: List[SegmentTokens], idx: int, limit: int, before: bool) -> List[str]:
    collected: List[str] = []
    cursor = idx - 1 if before else idx + 1
    while 0 <= cursor < len(segments) and len(collected) < limit:
        seg_tokens = segments[cursor].tokens
        if before:
            take = seg_tokens[-(limit - len(collected)):]
            collected = take + collected
        else:
            collected.extend(seg_tokens[:limit - len(collected)])
        cursor = cursor - 1 if before else cursor + 1
    return collected


def build_segment_context(segments: List[SegmentTokens], seg_idx: int, token_idx: int, span_len: int) -> str:
    if not (0 <= seg_idx < len(segments)):
        return ""
    segment = segments[seg_idx]
    words = segment.tokens
    n_words = len(words)
    if n_words == 0:
        return segment.text.strip()

    center_tokens = words[token_idx:token_idx + span_len] or [words[token_idx]]

    before_tokens = words[max(0, token_idx - CONTEXT_SIDE_TARGET):token_idx]
    before_tokens = before_tokens[-CONTEXT_SIDE_TARGET:]
    if len(before_tokens) < CONTEXT_SIDE_TARGET:
        needed = CONTEXT_SIDE_TARGET - len(before_tokens)
        extra = collect_neighbor_tokens(segments, seg_idx, needed, before=True)
        before_tokens = extra + before_tokens
        before_tokens = before_tokens[-CONTEXT_SIDE_TARGET:]

    after_tokens = words[token_idx + span_len:min(n_words, token_idx + span_len + CONTEXT_SIDE_TARGET)]
    after_tokens = after_tokens[:CONTEXT_SIDE_TARGET]
    if len(after_tokens) < CONTEXT_SIDE_TARGET:
        needed = CONTEXT_SIDE_TARGET - len(after_tokens)
        extra = collect_neighbor_tokens(segments, seg_idx, needed, before=False)
        after_tokens = after_tokens + extra
        after_tokens = after_tokens[:CONTEXT_SIDE_TARGET]

    before_len = len(before_tokens)
    after_len = len(after_tokens)
    total_len = before_len + len(center_tokens) + after_len
    if total_len > CONTEXT_MAX_WORDS:
        overflow = total_len - CONTEXT_MAX_WORDS
        while overflow > 0 and (before_len > 0 or after_len > 0):
            if before_len >= after_len and before_len > 0:
                before_len -= 1
            elif after_len > 0:
                after_len -= 1
            overflow -= 1
        snippet = before_tokens[-before_len:] + center_tokens + after_tokens[:after_len]
    else:
        snippet = before_tokens + center_tokens + after_tokens

    if not snippet:
        return segment.text.strip()
    return " ".join(snippet).strip()


# ---------------------------------------------------------------------------
# Helpers: IO & hashing
# ---------------------------------------------------------------------------

def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False))


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def note_to_dict(note: VaultNote) -> Dict[str, Any]:
    data = dataclasses.asdict(note)
    return {k: v for k, v in data.items() if v is not None}


def load_transcripts_index(cfg: CorpusConfig) -> List[Dict[str, Any]]:
    path = cfg.corpus_state_root / "transcripts_index.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raise ValueError(f"Invalid JSON in {path}")


def merge_counts(dest: Dict[Any, Count], source: Dict[Any, Count], multiplier: int) -> None:
    for key, count in source.items():
        existing = dest.get(key)
        if existing is None:
            if multiplier > 0:
                dest[key] = Count(total=count.total * multiplier, docs=count.docs * multiplier)
            continue
        existing.total += multiplier * count.total
        existing.docs += multiplier * count.docs
        if existing.total <= 0 or existing.docs <= 0:
            dest.pop(key, None)


def tally_transcript(task: TranscriptTask) -> Tuple[TranscriptCounts, Dict[str, str], Dict[Tuple[str, str], str]]:
    raw_text = task.path.read_text(encoding="utf-8", errors="ignore")
    segments = prepare_segments(raw_text)

    token_counts: Dict[str, Count] = {}
    bigram_counts: Dict[Tuple[str, str], Count] = {}
    token_examples: Dict[str, str] = {}
    bigram_examples: Dict[Tuple[str, str], str] = {}

    seen_tokens: set[str] = set()
    seen_bigrams: set[Tuple[str, str]] = set()

    for seg_idx, segment in enumerate(segments):
        lowers = segment.lower_tokens
        if not lowers:
            continue
        for i, tok in enumerate(lowers):
            if tok not in token_counts:
                token_counts[tok] = Count()
            token_counts[tok].total += 1
            if tok not in seen_tokens:
                token_counts[tok].docs += 1
                seen_tokens.add(tok)
            if tok not in token_examples:
                token_examples[tok] = build_segment_context(segments, seg_idx, i, 1)

            if i > 0:
                bigram = (lowers[i - 1], tok)
                if bigram not in bigram_counts:
                    bigram_counts[bigram] = Count()
                bigram_counts[bigram].total += 1
                if bigram not in seen_bigrams:
                    bigram_counts[bigram].docs += 1
                    seen_bigrams.add(bigram)
                if bigram not in bigram_examples:
                    bigram_examples[bigram] = build_segment_context(segments, seg_idx, i - 1, 2)

    return TranscriptCounts(tokens=token_counts, bigrams=bigram_counts), token_examples, bigram_examples


def scan_transcripts(tasks: List[TranscriptTask]) -> Tuple[Dict[str, Count], Dict[Tuple[str, str], Count], Dict[str, TranscriptCounts], Dict[str, str], Dict[Tuple[str, str], str]]:
    aggregate_tokens: Dict[str, Count] = {}
    aggregate_bigrams: Dict[Tuple[str, str], Count] = {}
    per_transcript: Dict[str, TranscriptCounts] = {}
    token_examples: Dict[str, str] = {}
    bigram_examples: Dict[Tuple[str, str], str] = {}

    for task in tasks:
        counts, token_ctx, bigram_ctx = tally_transcript(task)
        per_transcript[task.transcript_id] = counts
        merge_counts(aggregate_tokens, counts.tokens, 1)
        merge_counts(aggregate_bigrams, counts.bigrams, 1)
        for token, ctx in token_ctx.items():
            token_examples.setdefault(token, ctx)
        for bigram, ctx in bigram_ctx.items():
            bigram_examples.setdefault(bigram, ctx)

    return aggregate_tokens, aggregate_bigrams, per_transcript, token_examples, bigram_examples


# ---------------------------------------------------------------------------
# Vault scan → vault_index.json
# ---------------------------------------------------------------------------

FRONTMATTER_RE = re.compile(r"^---\s*$")


def parse_frontmatter(path: Path) -> Dict[str, Any]:
    """
    Return a dict with at least 'tags', 'title', 'name' keys (may be None).
    If no YAML frontmatter, returns {}.
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or not FRONTMATTER_RE.match(lines[0]):
        return {}

    fm_lines: List[str] = []
    for line in lines[1:]:
        if FRONTMATTER_RE.match(line):
            break
        fm_lines.append(line)

    if not fm_lines:
        return {}

    try:
        fm = yaml.safe_load("\n".join(fm_lines)) or {}
    except Exception:
        fm = {}

    tags = fm.get("tags")
    if not tags:
        tags = []
    elif isinstance(tags, str):
        tags = [tags]

    title = fm.get("title")
    name = fm.get("name")

    return {"tags": tags, "title": title, "name": name}


def build_vault_index(cfg: CorpusConfig) -> List[VaultNote]:
    vault_root = cfg.vault_root
    canonical_tags = set(cfg.canonical_tags)
    notes: List[VaultNote] = []

    for path in vault_root.rglob("*.md"):
        rel_path = path.relative_to(vault_root)
        fm = parse_frontmatter(path)
        tags = [str(t).lower() for t in fm.get("tags", [])]
        if not tags:
            continue

        # keep only notes with at least one canonical tag
        note_type = next((t for t in tags if t in canonical_tags), None)
        if not note_type:
            continue

        raw_file_name = path.stem
        file_name = normalize_name(raw_file_name) or raw_file_name.strip()
        if not file_name:
            continue
        yaml_name = normalize_name(fm.get("name"))
        header_name = normalize_name(extract_h1_title(path))
        canonical_name, full_name, short_name = choose_note_names(
            file_name, yaml_name, header_name
        )

        notes.append(
            VaultNote(
                note_id=slugify_path(rel_path),
                path=str(rel_path),
                canonical_name=canonical_name,
                note_type=note_type,
                full_name=full_name,
                short_name=short_name,
            )
        )

    return notes


# ---------------------------------------------------------------------------
# Lexicon building → lexicon.json
# ---------------------------------------------------------------------------

def build_lexicon(notes: List[VaultNote]) -> Tuple[Dict[str, str | None], set[str], set[str]]:
    """
    Builds a flat token/phrase → source map based on canonical/full/short names.
    Multi-word canonical names contribute both the full phrase and the filtered
    component tokens (common English words removed). When a term maps to
    multiple notes, the source is None.

    Returns:
        lexicon_map: Dict[term -> source_id or None]
        lexicon_tokens: set of single-token terms
        lexicon_phrases: set of multi-word phrases
    """
    term_sources: Dict[str, set[str]] = defaultdict(set)

    for note in notes:
        names_to_capture = []
        if note.canonical_name:
            names_to_capture.append(note.canonical_name)
        if note.full_name and note.full_name.lower() != note.canonical_name.lower():
            names_to_capture.append(note.full_name)
        if note.short_name and note.short_name.lower() not in {n.lower() for n in names_to_capture}:
            names_to_capture.append(note.short_name)

        for name in names_to_capture:
            phrase_key = name.lower()
            term_sources[phrase_key].add(note.note_id)

        for tok in WORD_RE.findall(note.canonical_name):
            tok_l = tok.lower()
            if not tok_l or is_common_word(tok_l):
                continue
            term_sources[tok_l].add(note.note_id)

    lexicon_map: Dict[str, str | None] = {}
    lexicon_tokens: set[str] = set()
    lexicon_phrases: set[str] = set()

    for term, sources in term_sources.items():
        source_id: str | None
        if len(sources) == 1:
            source_id = next(iter(sources))
        else:
            source_id = None
        lexicon_map[term] = source_id

        if " " in term:
            lexicon_phrases.add(term)
        else:
            lexicon_tokens.add(term)

    return lexicon_map, lexicon_tokens, lexicon_phrases


# ---------------------------------------------------------------------------
# Transcript scanning → stats.pkl + transcripts_index.json
# ---------------------------------------------------------------------------

def plan_transcript_tasks(cfg: CorpusConfig,
                          existing_index: List[Dict[str, Any]],
                          force: str | None) -> TranscriptPlan:
    tasks: List[TranscriptTask] = []
    now_iso = dt.datetime.now().isoformat()

    if force:
        if not existing_index:
            raise FileNotFoundError("transcripts_index.json not found; cannot use --force.")
        force_lower = force.lower()
        id_lookup = {entry["id"]: entry for entry in existing_index}
        if force_lower == "all":
            updated_entries: List[Dict[str, Any]] = []
            for entry in existing_index:
                rel_path = entry["path"]
                path = cfg.transcript_root / rel_path
                if not path.is_file():
                    raise FileNotFoundError(f"Transcript file missing: {path}")
                file_hash = hash_file(path)
                updated_entry = dict(entry)
                updated_entry["hash"] = file_hash
                updated_entries.append(updated_entry)
                tasks.append(
                    TranscriptTask(
                        transcript_id=entry["id"],
                        path=path,
                        rel_path=rel_path,
                        file_hash=file_hash,
                        added_at=entry.get("added_at", now_iso),
                    )
                )
            return TranscriptPlan(tasks=tasks,
                                  updated_index=updated_entries,
                                  removed_ids=[],
                                  mode="force_all")

        entry = id_lookup.get(force)
        if not entry:
            raise ValueError(f"Transcript id '{force}' not found in transcripts_index.json")
        rel_path = entry["path"]
        path = cfg.transcript_root / rel_path
        if not path.is_file():
            raise FileNotFoundError(f"Transcript file missing: {path}")
        file_hash = hash_file(path)
        tasks.append(
            TranscriptTask(
                transcript_id=entry["id"],
                path=path,
                rel_path=rel_path,
                file_hash=file_hash,
                added_at=entry.get("added_at", now_iso),
            )
        )
        return TranscriptPlan(tasks=tasks,
                              updated_index=None,
                              removed_ids=[],
                              mode="force_one")

    existing_by_path = {entry["path"]: entry for entry in existing_index}
    seen_paths: set[str] = set()
    final_entries: List[Dict[str, Any]] = []

    for abs_path in list_transcripts(cfg):
        rel_path_obj = abs_path.relative_to(cfg.transcript_root)
        rel_path = str(rel_path_obj)
        seen_paths.add(rel_path)
        file_hash = hash_file(abs_path)
        existing = existing_by_path.get(rel_path)
        entry_id = existing["id"] if existing else slugify_path(rel_path_obj)
        added_at = existing.get("added_at") if existing else now_iso
        entry = {
            "id": entry_id,
            "path": rel_path,
            "hash": file_hash,
            "added_at": added_at,
        }
        final_entries.append(entry)
        if not existing or existing.get("hash") != file_hash:
            tasks.append(
                TranscriptTask(
                    transcript_id=entry_id,
                    path=abs_path,
                    rel_path=rel_path,
                    file_hash=file_hash,
                    added_at=added_at,
                )
            )

    final_entries.sort(key=lambda e: e["path"])
    removed_ids = [entry["id"] for entry in existing_index if entry["path"] not in seen_paths]

    return TranscriptPlan(tasks=tasks,
                          updated_index=final_entries,
                          removed_ids=removed_ids,
                          mode="normal")


def entry_to_task(cfg: CorpusConfig, entry: Dict[str, Any]) -> TranscriptTask:
    rel_path = entry["path"]
    path = cfg.transcript_root / rel_path
    if not path.is_file():
        raise FileNotFoundError(f"Transcript file missing: {path}")
    file_hash = entry.get("hash")
    if not file_hash:
        file_hash = hash_file(path)
    added_at = entry.get("added_at", dt.datetime.now().isoformat())
    return TranscriptTask(
        transcript_id=entry["id"],
        path=path,
        rel_path=rel_path,
        file_hash=file_hash,
        added_at=added_at,
    )
def list_transcripts(cfg: CorpusConfig) -> List[Path]:
    paths: List[Path] = []
    for pattern in cfg.transcript_globs:
        paths.extend(cfg.transcript_root.glob(pattern))
    return sorted(set(p for p in paths if p.is_file()))


def load_stats(cfg: CorpusConfig) -> Tuple[Dict[str, Count], Dict[Tuple[str, str], Count], Dict[str, TranscriptCounts], bool]:
    stats_path = cfg.corpus_state_root / "stats" / "stats.pkl"
    if not stats_path.exists():
        return {}, {}, {}, False

    with stats_path.open("rb") as f:
        data = pickle.load(f)

    def parse_counts(raw: Dict[str, Dict[str, int]]) -> Dict[str, Count]:
        return {token: Count(**counts) for token, counts in raw.items()}

    def parse_bigram_counts(raw: Dict[str, Dict[str, int]]) -> Dict[Tuple[str, str], Count]:
        result: Dict[Tuple[str, str], Count] = {}
        for key, counts in raw.items():
            t1, t2 = key.split("\t", 1)
            result[(t1, t2)] = Count(**counts)
        return result

    token_counts = parse_counts(data.get("tokens", {}))
    bigram_counts = parse_bigram_counts(data.get("bigrams", {}))

    per_transcript_raw = data.get("per_transcript", {})
    per_transcript: Dict[str, TranscriptCounts] = {}
    for transcript_id, payload in per_transcript_raw.items():
        per_transcript[transcript_id] = TranscriptCounts(
            tokens=parse_counts(payload.get("tokens", {})),
            bigrams=parse_bigram_counts(payload.get("bigrams", {})),
        )

    return token_counts, bigram_counts, per_transcript, True


def save_stats(cfg: CorpusConfig,
               token_stats: Dict[str, Count],
               bigram_stats: Dict[Tuple[str, str], Count],
               per_transcript: Dict[str, TranscriptCounts]) -> None:
    stats_path = cfg.corpus_state_root / "stats" / "stats.pkl"
    stats_path.parent.mkdir(parents=True, exist_ok=True)

    def serialize_counts(counts: Dict[str, Count]) -> Dict[str, Dict[str, int]]:
        return {token: dataclasses.asdict(c) for token, c in counts.items()}

    def serialize_bigrams(counts: Dict[Tuple[str, str], Count]) -> Dict[str, Dict[str, int]]:
        return {f"{t1}\t{t2}": dataclasses.asdict(c) for (t1, t2), c in counts.items()}

    per_transcript_payload: Dict[str, Dict[str, Dict[str, Dict[str, int]]]] = {}
    for transcript_id, counts in per_transcript.items():
        per_transcript_payload[transcript_id] = {
            "tokens": serialize_counts(counts.tokens),
            "bigrams": serialize_bigrams(counts.bigrams),
        }

    payload = {
        "tokens": serialize_counts(token_stats),
        "bigrams": serialize_bigrams(bigram_stats),
        "per_transcript": per_transcript_payload,
    }

    with stats_path.open("wb") as f:
        pickle.dump(payload, f)


def save_transcripts_index(cfg: CorpusConfig, entries: List[Dict[str, Any]]) -> None:
    path = cfg.corpus_state_root / "transcripts_index.json"
    write_json(path, entries)


# ---------------------------------------------------------------------------
# Candidate generation → candidates/stage0_global.tsv
# ---------------------------------------------------------------------------

def token_zipf_limit(cfg: CorpusConfig, token: str) -> float:
    if len(token) >= cfg.token_long_length:
        return cfg.token_long_max_zipf
    return cfg.token_short_max_zipf


def generate_token_candidates(
    cfg: CorpusConfig,
    token_stats: Dict[str, Count],
    lexicon_tokens: set[str],
    token_examples: Dict[str, str],
) -> Tuple[List[List[str]], set[str]]:
    rows: List[List[str]] = []
    included_tokens: set[str] = set()

    for token, c in sorted(token_stats.items(), key=lambda kv: (kv[1].docs, kv[1].total)):
        if token in lexicon_tokens:
            continue
        if token.isdigit():
            continue
        if c.docs < cfg.token_min_doc_count:
            continue

        z = zipf_frequency(token, "en")
        limit = token_zipf_limit(cfg, token)
        if z > 0 and z > limit:
            continue

        context = token_examples.get(token, "")
        rows.append([
            token,
            "1",
            str(c.total),
            str(c.docs),
            f"{z:.3f}",
            context,
        ])
        included_tokens.add(token)

    return rows, included_tokens


def generate_bigram_candidates(
    cfg: CorpusConfig,
    bigram_stats: Dict[Tuple[str, str], Count],
    lexicon_phrases: set[str],
    token_candidates: set[str],
    bigram_examples: Dict[Tuple[str, str], str],
) -> List[List[str]]:
    rows: List[List[str]] = []

    for (t1, t2), c in sorted(bigram_stats.items(), key=lambda kv: (kv[1].docs, kv[1].total)):
        if c.docs == 0 or c.docs > cfg.bigram_max_doc_count:
            continue

        phrase = f"{t1} {t2}"
        if phrase in lexicon_phrases:
            continue

        if t1 in token_candidates or t2 in token_candidates:
            continue

        z1 = zipf_frequency(t1, "en")
        z2 = zipf_frequency(t2, "en")
        if z1 < cfg.bigram_min_component_zipf or z2 < cfg.bigram_min_component_zipf:
            continue

        context = bigram_examples.get((t1, t2), "")
        rows.append([
            phrase,
            "2",
            str(c.total),
            str(c.docs),
            f"{(z1 + z2):.3f}",
            context,
        ])

    return rows


def write_token_candidates_file(cfg: CorpusConfig, rows: List[List[str]]) -> None:
    out_path = cfg.corpus_state_root / "candidates" / "stage0_tokens.tsv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["surface_form", "n_tokens", "total_count", "doc_count", "zipf", "context"])
        w.writerows(rows)


def write_bigram_candidates_file(cfg: CorpusConfig, rows: List[List[str]]) -> None:
    out_path = cfg.corpus_state_root / "candidates" / "stage0_bigrams.tsv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["surface_form", "n_tokens", "total_count", "doc_count", "zipf_sum", "context"])
        w.writerows(rows)


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Stage 0: generate corpus state (full scan).")
    ap.add_argument("--config", type=str, required=True, help="Path to config.yaml")
    ap.add_argument("--rescan-vault", action="store_true",
                    help="Rebuild vault_index.json and lexicon.json before scanning transcripts.")
    ap.add_argument("--force", type=str,
                    help="Process only entries listed in transcripts_index.json. "
                         "Use 'all' or a specific transcript id.")
    args = ap.parse_args()

    cfg = CorpusConfig.from_yaml(Path(args.config))

    vault_index_path = cfg.corpus_state_root / "vault_index.json"
    lexicon_path = cfg.corpus_state_root / "lexicon.json"

    if args.rescan_vault:
        # 1) Vault → vault_index.json
        notes = build_vault_index(cfg)
        write_json(vault_index_path, [note_to_dict(n) for n in notes])
        print(f"Indexed {len(notes)} vault notes")

        # 2) vault_index.json → lexicon.json
        lexicon_map, lexicon_tokens, lexicon_phrases = build_lexicon(notes)
        write_json(lexicon_path, lexicon_map)
        print(f"Wrote {len(lexicon_map)} lexicon terms")
    else:
        if not vault_index_path.exists() or not lexicon_path.exists():
            raise FileNotFoundError("vault_index.json and lexicon.json not found. Run with --rescan-vault first.")
        existing_notes = json.loads(vault_index_path.read_text(encoding="utf-8"))
        lexicon_map = json.loads(lexicon_path.read_text(encoding="utf-8"))
        print(f"Loaded {len(existing_notes)} cached vault notes")
        print(f"Loaded {len(lexicon_map)} cached lexicon terms")
        lexicon_tokens = {term for term in lexicon_map.keys() if " " not in term}
        lexicon_phrases = {term for term in lexicon_map.keys() if " " in term}

    existing_index = load_transcripts_index(cfg)
    plan = plan_transcript_tasks(cfg, existing_index, args.force)
    effective_tasks = plan.tasks
    stats_tokens: Dict[str, Count] = {}
    stats_bigrams: Dict[Tuple[str, str], Count] = {}
    per_transcript_counts: Dict[str, TranscriptCounts] = {}
    stats_exist = False
    seed_required = False

    if plan.mode != "force_one":
        stats_tokens, stats_bigrams, per_transcript_counts, stats_exist = load_stats(cfg)
        seed_required = (
            plan.mode == "normal"
            and stats_exist
            and (stats_tokens or stats_bigrams)
            and not per_transcript_counts
            and plan.updated_index is not None
            and len(plan.updated_index) > 0
        )
        if seed_required:
            effective_tasks = [entry_to_task(cfg, entry) for entry in plan.updated_index]
            print("Stats cache missing per-transcript data; rebuilding aggregates from scratch.")

    if plan.updated_index is not None:
        save_transcripts_index(cfg, plan.updated_index)

    task_token_stats: Dict[str, Count] = {}
    task_bigram_stats: Dict[Tuple[str, str], Count] = {}
    task_counts: Dict[str, TranscriptCounts] = {}
    token_examples: Dict[str, str] = {}
    bigram_examples: Dict[Tuple[str, str], str] = {}
    if effective_tasks:
        task_token_stats, task_bigram_stats, task_counts, token_examples, bigram_examples = scan_transcripts(effective_tasks)

    stats_updated = False
    if plan.mode != "force_one":
        if plan.mode == "force_all" or seed_required:
            stats_tokens.clear()
            stats_bigrams.clear()
            per_transcript_counts.clear()
            stats_updated = True
        elif plan.removed_ids:
            stats_updated = True
            for transcript_id in plan.removed_ids:
                previous = per_transcript_counts.pop(transcript_id, None)
                if previous:
                    merge_counts(stats_tokens, previous.tokens, -1)
                    merge_counts(stats_bigrams, previous.bigrams, -1)

        for task in effective_tasks:
            transcript_id = task.transcript_id
            new_counts = task_counts.get(transcript_id)
            if not new_counts:
                continue
            stats_updated = True
            previous = per_transcript_counts.get(transcript_id)
            if previous:
                merge_counts(stats_tokens, previous.tokens, -1)
                merge_counts(stats_bigrams, previous.bigrams, -1)
            per_transcript_counts[transcript_id] = new_counts
            merge_counts(stats_tokens, new_counts.tokens, 1)
            merge_counts(stats_bigrams, new_counts.bigrams, 1)

        if not stats_exist:
            stats_updated = True

        if stats_updated:
            save_stats(cfg, stats_tokens, stats_bigrams, per_transcript_counts)

    processed = len(effective_tasks)
    if processed == 0:
        print("No transcripts required processing for candidates.")
    else:
        print(f"Prepared {processed} transcripts for candidate generation.")
        token_rows, token_candidate_set = generate_token_candidates(cfg, task_token_stats, lexicon_tokens, token_examples)
        bigram_rows = generate_bigram_candidates(cfg, task_bigram_stats, lexicon_phrases, token_candidate_set, bigram_examples)
        write_token_candidates_file(cfg, token_rows)
        print(f"Wrote token candidates to {cfg.corpus_state_root / 'candidates' / 'stage0_tokens.tsv'}")
        if bigram_rows:
            print("Bigram candidates computed but not written (feature temporarily disabled).")


if __name__ == "__main__":
    main()
