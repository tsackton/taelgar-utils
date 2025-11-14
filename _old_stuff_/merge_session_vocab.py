#!/usr/bin/env python3
"""Merge curated session mistakes/glossaries back into the master dictionaries."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


def load_mistakes(path: Path) -> Dict[str, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except Exception as exc:
        raise ValueError(f"Failed to parse {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"Unexpected mistakes format in {path}; expected JSON object.")
    return {str(k): str(v) for k, v in data.items()}


def read_glossary(path: Path) -> List[str]:
    if not path.exists():
        return []
    terms: List[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        terms.append(stripped)
    return terms


def write_glossary(path: Path, terms: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(terms)
    if payload:
        payload += "\n"
    path.write_text(payload, encoding="utf-8")


def write_mistakes(path: Path, text_map: Dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(sorted(text_map.items()))
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def merge_maps(
    base: Dict[str, str],
    additions: Dict[str, str],
    *,
    source: Path,
) -> Tuple[int, int]:
    merged = 0
    skipped = 0
    for key, value in additions.items():
        if not value:
            skipped += 1
            continue
        if key in base and base[key] != value:
            print(
                f"[warn] Conflict for '{key}': keeping existing '{base[key]}' over '{value}' from {source}",
                file=sys.stderr,
            )
            skipped += 1
            continue
        if key not in base:
            merged += 1
        base[key] = value
    return merged, skipped


def merge_glossaries(base_terms: List[str], additions: Iterable[str]) -> Tuple[List[str], int]:
    seen = {term.casefold(): term for term in base_terms}
    merged = 0
    for term in additions:
        normalized = term.casefold()
        if normalized in seen:
            continue
        seen[normalized] = term
        base_terms.append(term)
        merged += 1
    base_terms_sorted = sorted(base_terms, key=str.casefold)
    return base_terms_sorted, merged


@dataclass
class MergeResult:
    merged_mistakes: int
    merged_glossary_terms: int


def merge_session_vocab(
    dest_mistakes: Path,
    dest_glossary: Path,
    session_mistakes_paths: List[Path],
    session_glossary_paths: List[Path],
) -> MergeResult:
    text_map: Dict[str, str] = {}
    if dest_mistakes.exists():
        text_map = load_mistakes(dest_mistakes)

    merged_entries = 0
    for session_path in session_mistakes_paths:
        if not session_path.exists():
            print(f"[warn] Session mistakes {session_path} not found; skipping.", file=sys.stderr)
            continue
        text_add = load_mistakes(session_path)
        added, skipped = merge_maps(text_map, text_add, source=session_path)
        merged_entries += added
        if skipped and not added:
            print(f"[info] No finalized entries merged from {session_path} (all blank or conflicts).", file=sys.stderr)

    glossary_terms = read_glossary(dest_glossary)
    merged_glossary = 0
    for session_glossary in session_glossary_paths:
        if not session_glossary.exists():
            print(f"[warn] Session glossary {session_glossary} not found; skipping.", file=sys.stderr)
            continue
        entries = [
            line.strip()
            for line in session_glossary.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        glossary_terms, added = merge_glossaries(glossary_terms, entries)
        merged_glossary += added

    write_mistakes(dest_mistakes, text_map)
    write_glossary(dest_glossary, glossary_terms)

    return MergeResult(merged_mistakes=merged_entries, merged_glossary_terms=merged_glossary)


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge session-level vocabulary into master dictionaries.")
    parser.add_argument("--dest-mistakes", type=Path, required=True, help="Destination mistakes JSON (updated in place)")
    parser.add_argument("--dest-glossary", type=Path, required=True, help="Destination glossary TXT (updated in place)")
    parser.add_argument("--session-mistakes", nargs="*", type=Path, default=[], help="Session mistakes JSON files to merge")
    parser.add_argument("--session-glossaries", nargs="*", type=Path, default=[], help="Session glossary TXT files to merge")
    args = parser.parse_args()

    result = merge_session_vocab(
        dest_mistakes=args.dest_mistakes,
        dest_glossary=args.dest_glossary,
        session_mistakes_paths=list(args.session_mistakes),
        session_glossary_paths=list(args.session_glossaries),
    )

    print(
        f"Merged {result.merged_mistakes} mistake entries and {result.merged_glossary_terms} glossary terms "
        f"into {args.dest_mistakes} / {args.dest_glossary}",
    )


if __name__ == "__main__":
    main()
