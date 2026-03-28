---
name: transcript-cleaner
description: Clean prepared RPG session transcripts while preserving every transcript line id, speaker label, timestamp, and ordering exactly. Use when fixing ASR errors, fantasy names, glossary terms, punctuation, capitalization, and spelling in `source.prepared.md`, especially when an optional campaign glossary is available and unresolved phrases should be surfaced for manual review.
---

# Transcript Cleaner

Use this skill when working from a prepared session bundle:

- `session.yaml`
- `source.prepared.md`
- optional campaign glossary

The goal is to produce a corrected transcript that is still a transcript, not a recap.

## Rules

- Preserve every transcript header exactly.
  The full bracketed id line prefix must remain byte-for-byte identical, including `uNNNN`, timestamps, speaker/game role, separators, and ordering.
- Keep one input transcript line for one output transcript line.
- Only fix errors.
  Do not prettify, summarize, tighten phrasing, or rewrite for style.
- Safe fixes:
  punctuation, capitalization, spelling, obvious grammar noise from ASR, and clearly wrong fantasy terms when the correction is well-supported.
- If a phrase looks wrong but there is no reliable replacement, keep the original words and wrap only the uncertain phrase in `[[...]]`.
- If unresolved `[[...]]` markers remain after a chunk, stop and ask the user for manual replacements before finalizing the whole transcript.

## Workflow

1. Read `session.yaml` and `source.prepared.md`.
2. If a campaign glossary is provided and compact enough to fit comfortably in context, load it once.
3. Clean the transcript in contiguous chunks.
   Keep a rolling session correction ledger so the same error is corrected consistently later in the session.
4. After editing, run `scripts/report_cleanup_diff.py` to validate the cleaned transcript and generate:
   - `cleanup_report.json`
   - `session_corrections.yaml`
5. If the report finds header mismatches, line-count drift, or unresolved `[[...]]` markers, fix those before treating the transcript as complete.

## Chunking

- Prefer chunk sizes that preserve local conversational context.
- For long transcripts, use contiguous blocks with small local overlap in your reasoning, but the written output must still preserve the original one-line-per-unit structure.
- Do not reread the full transcript just to make a report. Use the diff script.

## Glossary

- The glossary is optional.
- If provided, use it to normalize known PCs, NPCs, locations, organizations, items, and fantasy terms.
- Do not force unknown proper nouns to match the glossary.
- Novel entities are allowed. Preserve them if they are internally plausible.

## Manual Review

Ask for manual feedback when:

- a suspicious name or phrase has no obvious replacement
- multiple lore-consistent replacements seem possible
- a repeated term stays unresolved across chunks

When asking, provide a compact list of unique unresolved phrases and the `uNNNN` lines where they appear.

## Diff Report

Generate the report with:

```bash
python skills/transcript-cleaner/scripts/report_cleanup_diff.py \
  --original /path/to/source.prepared.md \
  --cleaned /path/to/source.cleaned.md \
  --report-json /path/to/cleanup_report.json \
  --corrections-yaml /path/to/session_corrections.yaml
```

The script validates:

- exact header preservation
- line-count preservation
- changed lines
- unresolved `[[...]]` markers
- repeated replacement pairs derived from diffs

Treat the script output as the canonical cleanup report rather than asking the model to narrate every change.
