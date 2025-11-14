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

    @classmethod
    def from_yaml(cls, path: Path) -> "CorpusConfig":
        data = yaml.safe_load(path.read_text())
        return cls(
            vault_root=Path(data["vault_root"]),
            transcript_root=Path(data["transcript_root"]),
            corpus_state_root=Path(data["corpus_state_root"]),
            canonical_tags=list(data["canonical_tags"]),
            transcript_globs=list(data.get("transcript_globs", ["**/*.txt"])),
        )


@dataclass
class VaultNote:
    note_id: str
    path: str         # relative to vault root
    title: str
    tags: List[str]
    aliases: List[str]
    last_modified: str


@dataclass
class LexiconEntry:
    id: str
    term: str
    kind: str
    tokens: List[str]
    aliases: List[str]
    source_notes: List[str]

    def lower_phrase(self) -> str:
        return self.term.lower()

    def lower_tokens(self) -> List[str]:
        return [t.lower() for t in self.tokens]


@dataclass
class Count:
    total: int = 0
    docs: int = 0


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


# ---------------------------------------------------------------------------
# Vault scan → vault_index.json
# ---------------------------------------------------------------------------

FRONTMATTER_RE = re.compile(r"^---\s*$")


def parse_frontmatter(path: Path) -> Dict[str, Any]:
    """
    Return a dict with at least 'tags', 'aliases', 'title' (may be None).
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

    tags = fm.get("tags", [])
    if isinstance(tags, str):
        tags = [tags]
    aliases = fm.get("aliases", [])
    if isinstance(aliases, str):
        aliases = [aliases]

    title = fm.get("title")

    return {"tags": tags, "aliases": aliases, "title": title}


def get_title_from_body(text: str) -> str | None:
    # First H1 style heading "# Title"
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return None


def build_vault_index(cfg: CorpusConfig) -> List[VaultNote]:
    vault_root = cfg.vault_root
    canonical_tags = set(t.lower() for t in cfg.canonical_tags)
    notes: List[VaultNote] = []

    for path in vault_root.rglob("*.md"):
        rel_path = path.relative_to(vault_root)
        fm = parse_frontmatter(path)
        tags = [t.lower() for t in fm.get("tags", [])]
        if not tags:
            continue

        # keep only notes with at least one canonical tag
        if not any(t in canonical_tags for t in tags):
            continue

        text = path.read_text(encoding="utf-8")
        title = fm.get("title") or get_title_from_body(text) or path.stem

        aliases = fm.get("aliases", [])
        aliases = [str(a) for a in aliases]

        mtime = dt.datetime.fromtimestamp(path.stat().st_mtime).isoformat()

        notes.append(
            VaultNote(
                note_id=path.stem,
                path=str(rel_path),
                title=title,
                tags=tags,
                aliases=aliases,
                last_modified=mtime,
            )
        )

    return notes


# ---------------------------------------------------------------------------
# Lexicon building → lexicon.json
# ---------------------------------------------------------------------------

SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(term: str) -> str:
    s = term.lower()
    s = SLUG_RE.sub("_", s)
    return s.strip("_")


def build_lexicon_from_vault(cfg: CorpusConfig, notes: List[VaultNote]) -> List[LexiconEntry]:
    entries: List[LexiconEntry] = []
    canonical_tags = set(cfg.canonical_tags)

    for note in notes:
        term = note.title.strip()
        if not term:
            continue

        # choose the first matching canonical tag as kind
        kind = next((t for t in note.tags if t in canonical_tags), "unknown")

        tokens = term.split()
        entry_id = slugify(term)

        entries.append(
            LexiconEntry(
                id=entry_id,
                term=term,
                kind=kind,
                tokens=tokens,
                aliases=note.aliases,
                source_notes=[note.path],
            )
        )

        # Also create entries for aliases as full phrases
        for alias in note.aliases:
            alias_term = alias.strip()
            if not alias_term:
                continue
            alias_tokens = alias_term.split()
            alias_id = slugify(alias_term)
            entries.append(
                LexiconEntry(
                    id=alias_id,
                    term=alias_term,
                    kind=kind,
                    tokens=alias_tokens,
                    aliases=[],
                    source_notes=[note.path],
                )
            )

    return entries


def build_lexicon_indexes(entries: List[LexiconEntry]) -> Tuple[set[str], set[str]]:
    """
    Returns:
      - lexicon_tokens: set of lowercase tokens that are part of any lexicon entry
      - lexicon_phrases: set of full lowercase phrases (term and aliases)
    """
    lexicon_tokens: set[str] = set()
    lexicon_phrases: set[str] = set()

    for e in entries:
        phrase = e.term.lower()
        lexicon_phrases.add(phrase)
        for tok in e.tokens:
            lexicon_tokens.add(tok.lower())
        for alias in e.aliases:
            lexicon_phrases.add(alias.lower())
            for tok in alias.split():
                lexicon_tokens.add(tok.lower())

    return lexicon_tokens, lexicon_phrases


# ---------------------------------------------------------------------------
# Transcript scanning → stats.pkl + transcripts_index.json
# ---------------------------------------------------------------------------

WORD_RE = re.compile(r"[A-Za-z']+")


def tokenize_text(text: str) -> List[str]:
    return [m.group(0).lower() for m in WORD_RE.finditer(text)]


def list_transcripts(cfg: CorpusConfig) -> List[Path]:
    paths: List[Path] = []
    for pattern in cfg.transcript_globs:
        paths.extend(cfg.transcript_root.glob(pattern))
    return sorted(set(p for p in paths if p.is_file()))


def full_scan_transcripts(
    cfg: CorpusConfig,
    lexicon_tokens: set[str],
) -> Tuple[Dict[str, Count], Dict[Tuple[str, str], Count], List[Dict[str, Any]]]:
    """
    Returns token_stats, bigram_stats, transcripts_index_entries.
    """
    token_stats: Dict[str, Count] = {}
    bigram_stats: Dict[Tuple[str, str], Count] = {}
    transcripts_index: List[Dict[str, Any]] = []

    for path in list_transcripts(cfg):
        text = path.read_text(encoding="utf-8", errors="ignore")
        tokens = tokenize_text(text)

        seen_tokens: set[str] = set()
        seen_bigrams: set[Tuple[str, str]] = set()

        # tokens
        for i, tok in enumerate(tokens):
            if tok not in token_stats:
                token_stats[tok] = Count()
            token_stats[tok].total += 1
            if tok not in seen_tokens:
                token_stats[tok].docs += 1
                seen_tokens.add(tok)

            # bigrams
            if i > 0:
                t1 = tokens[i - 1]
                t2 = tok
                bigram = (t1, t2)
                if bigram not in bigram_stats:
                    bigram_stats[bigram] = Count()
                bigram_stats[bigram].total += 1
                if bigram not in seen_bigrams:
                    bigram_stats[bigram].docs += 1
                    seen_bigrams.add(bigram)

        transcripts_index.append(
            {
                "id": path.stem,
                "path": str(path.relative_to(cfg.transcript_root)),
                "hash": hash_file(path),
                "added_at": dt.datetime.now().isoformat(),
            }
        )

    return token_stats, bigram_stats, transcripts_index


def save_stats(cfg: CorpusConfig,
               token_stats: Dict[str, Count],
               bigram_stats: Dict[Tuple[str, str], Count]) -> None:
    stats_path = cfg.corpus_state_root / "stats" / "stats.pkl"
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    # convert dataclasses to plain dicts for pickling clarity if you like
    token_dict = {t: dataclasses.asdict(c) for t, c in token_stats.items()}
    bigram_dict = {f"{t1}\t{t2}": dataclasses.asdict(c) for (t1, t2), c in bigram_stats.items()}
    with stats_path.open("wb") as f:
        pickle.dump({"tokens": token_dict, "bigrams": bigram_dict}, f)


def save_transcripts_index(cfg: CorpusConfig, entries: List[Dict[str, Any]]) -> None:
    path = cfg.corpus_state_root / "transcripts_index.json"
    write_json(path, entries)


# ---------------------------------------------------------------------------
# Candidate generation → candidates/stage0_global.tsv
# ---------------------------------------------------------------------------

def generate_token_candidates(
    token_stats: Dict[str, Count],
    lexicon_tokens: set[str],
    writer: csv.writer,
    min_doc_count: int = 1,
    max_doc_count: int = 50,
    max_zipf: float = 3.0,
) -> None:
    """
    Heuristic:
      - tokens that appear in at least `min_doc_count` docs but not too many
      - relatively rare in English (zipf < max_zipf)
      - not in lexicon_tokens
    """
    for token, c in sorted(token_stats.items(), key=lambda kv: (kv[1].docs, kv[1].total)):
        if token in lexicon_tokens:
            continue
        if c.docs < min_doc_count or c.docs > max_doc_count:
            continue

        z = zipf_frequency(token, "en")
        # 0 means 'unknown' in wordfreq; we keep these – lexicon should filter the meaningful ones
        if z > max_zipf:
            continue

        writer.writerow([
            "token",        # kind
            token,          # surface_form
            1,              # n_tokens
            c.total,        # total_count
            c.docs,         # doc_count
            0,              # in_lexicon (token-level; we already filtered)
            "",             # example_context (can be filled in later)
            "",             # action
            "",             # replacement
        ])


def generate_bigram_candidates(
    bigram_stats: Dict[Tuple[str, str], Count],
    lexicon_phrases: set[str],
    writer: csv.writer,
    min_doc_count: int = 1,
    max_doc_count: int = 20,
    max_zipf_sum: float = 6.0,
) -> None:
    """
    Heuristic:
      - bigrams that are rare-ish (doc_count between bounds)
      - both words not extremely rare individually
      - combined "English-ness" not too high (z1+z2 <= max_zipf_sum)
      - skip if bigram matches a known lexicon phrase
    """
    for (t1, t2), c in sorted(bigram_stats.items(), key=lambda kv: (kv[1].docs, kv[1].total)):
        if c.docs < min_doc_count or c.docs > max_doc_count:
            continue

        phrase = f"{t1} {t2}"
        if phrase in lexicon_phrases:
            continue

        z1 = zipf_frequency(t1, "en")
        z2 = zipf_frequency(t2, "en")

        # skip bigrams where both words are total aliens; these are often your names and should be covered by lexicon
        if z1 == 0 and z2 == 0:
            continue

        # if both words are super common and the sum is high, this is probably fine English
        if (z1 + z2) > max_zipf_sum:
            continue

        writer.writerow([
            "bigram",
            phrase,
            2,
            c.total,
            c.docs,
            0,      # in_lexicon-ish
            "",
            "",
            "",
        ])


def write_stage0_global_candidates(
    cfg: CorpusConfig,
    token_stats: Dict[str, Count],
    bigram_stats: Dict[Tuple[str, str], Count],
    lexicon_tokens: set[str],
    lexicon_phrases: set[str],
) -> None:
    out_path = cfg.corpus_state_root / "candidates" / "stage0_global.tsv"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow([
            "kind",
            "surface_form",
            "n_tokens",
            "total_count",
            "doc_count",
            "in_lexicon",
            "example_context",
            "action",
            "replacement",
        ])
        generate_token_candidates(token_stats, lexicon_tokens, w)
        generate_bigram_candidates(bigram_stats, lexicon_phrases, w)


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Stage 0: generate corpus state (full scan).")
    ap.add_argument("--config", type=str, required=True, help="Path to config.yaml")
    args = ap.parse_args()

    cfg = CorpusConfig.from_yaml(Path(args.config))

    # 1) Vault → vault_index.json
    notes = build_vault_index(cfg)
    write_json(cfg.corpus_state_root / "vault_index.json", [dataclasses.asdict(n) for n in notes])
    print(f"Indexed {len(notes)} vault notes")

    # 2) vault_index.json → lexicon.json
    lex_entries = build_lexicon_from_vault(cfg, notes)
    write_json(cfg.corpus_state_root / "lexicon.json", [dataclasses.asdict(e) for e in lex_entries])
    print(f"Wrote {len(lex_entries)} lexicon entries")

    lexicon_tokens, lexicon_phrases = build_lexicon_indexes(lex_entries)

    # 3) Transcripts → stats + transcripts_index.json
    token_stats, bigram_stats, transcripts_index = full_scan_transcripts(cfg, lexicon_tokens)
    save_stats(cfg, token_stats, bigram_stats)
    save_transcripts_index(cfg, transcripts_index)
    print(f"Scanned {len(transcripts_index)} transcripts, "
          f"{len(token_stats)} unique tokens, {len(bigram_stats)} unique bigrams")

    # 4) Stats + lexicon → candidate TSV for manual curation
    write_stage0_global_candidates(cfg, token_stats, bigram_stats, lexicon_tokens, lexicon_phrases)
    print(f"Wrote candidate list to {cfg.corpus_state_root / 'candidates' / 'stage0_global.tsv'}")


if __name__ == "__main__":
    main()
