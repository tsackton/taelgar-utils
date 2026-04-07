# Session Pipeline Overview

This document is the current MOC for the session-processing pipeline in this repo.

It summarizes:

- the major stages in the pipeline
- what is implemented and usable now
- what exists as a draft skill or helper
- what is still pending

Related planning docs:

- [Planning Notes](planning/notes.md)
- [Planning Tasks](planning/tasks.md)

## Current Pipeline Shape

The intended flow is now beat-first:

1. raw session source
2. raw transcript generation
3. prepared session bundle
4. cleaned transcript
5. beat segmentation
6. beat facts annotation
7. session recap synthesis
8. session note generation

In practice, the repo is currently strongest at:

- transcript preparation / archiving
- transcript cleanup workflow scaffolding
- beat segmentation workflow scaffolding
- beat-facts validation and preview
- session recap context building and structured markdown recap generation

The final deterministic note-generation stage is still pending.

## Status Summary

| Stage | Purpose | Status |
| --- | --- | --- |
| Raw data -> raw transcript | Normalize Zoom / diarized inputs into a transcript | Partial |
| Session bundle prep | Archive inputs and generate a prepared bundle | Implemented |
| Transcript cleanup | Clean ASR / glossary / punctuation issues | Draft but usable |
| Beat segmentation | Split cleaned transcript into ordered beats | Draft but usable |
| Beat facts annotation | Add summaries, location/NPC/item/org facts, and combat facts to beats without changing boundaries | Implemented and evolving |
| Session recap synthesis | Build `session-summary-context.json` plus structured `session-recap.md` for human review | Implemented and evolving |
| Session note generation | Deterministic note output from artifacts | Pending |

## Implemented Now

### 1. Session Bundle Prep

Current entrypoint:

- [`cli/session.py`](../cli/session.py)
- [`src/taelgar_utils/session/prepare_source.py`](../src/taelgar_utils/session/prepare_source.py)

What it does:

- reads a config plus reusable participant roster
- prepares a canonical source transcript / source text
- archives raw inputs into a self-contained session bundle
- writes cleaned bundle outputs into `cleaned/`
- writes a session manifest and, when available, speaker stats

Current output shape:

- bundle root: `<outputDir>/<campaign-slug>-<session-number>/`
- `sources/` contains archived inputs
- `cleaned/` contains generated outputs
- `session.yaml` is the canonical bundle manifest
- optional speaker stats JSON is written for transcript-based sessions

Current status:

- usable now
- strongest part of the current pipeline

### 2. Transcript Cleaner Skill

Current files:

- [`skills/transcript-cleaner/SKILL.md`](../skills/transcript-cleaner/SKILL.md)
- [`skills/transcript-cleaner/scripts/report_cleanup_diff.py`](../skills/transcript-cleaner/scripts/report_cleanup_diff.py)

What it does:

- guides an agent to clean a prepared transcript while preserving transcript structure
- validates cleaned output against the prepared transcript
- generates deterministic cleanup artifacts

Current deterministic outputs:

- `<prefix>-cleanup-report.json`
- `<prefix>-session-corrections.yaml`
- `<prefix>-human-transcript.md`
- `<prefix>-cleanup-summary.md`

Current status:

- usable as a workflow
- still prompt/skill-driven rather than a full end-to-end CLI
- likely to keep evolving as real transcript edge cases appear

### 3. Transcript Splitter Skill

Current files:

- [`skills/transcript-splitter/SKILL.md`](../skills/transcript-splitter/SKILL.md)
- [`skills/transcript-splitter/scripts/manage_beats.py`](../skills/transcript-splitter/scripts/manage_beats.py)

What it does:

- guides an agent to split a cleaned transcript into ordered beats
- validates beat coverage, ordering, dates, and size constraints
- renders a markdown preview for review

Current deterministic outputs:

- `<prefix>-beats.json`
- `<prefix>-beats-preview.md`

Current status:

- usable as a workflow
- still skill-first, not a fully automated segmenter
- likely to be refined through real-session testing

### 4. Beat Annotator Skill

Current files:

- [`skills/beat-annotator/SKILL.md`](../skills/beat-annotator/SKILL.md)
- [`skills/beat-annotator/scripts/extract_beat_context.py`](../skills/beat-annotator/scripts/extract_beat_context.py)
- [`skills/beat-annotator/scripts/manage_beat_facts.py`](../skills/beat-annotator/scripts/manage_beat_facts.py)

What it does:

- treats `beats.json` as fixed and produces a separate `beat-facts.json` artifact
- extracts deterministic beat-scoped context from the cleaned transcript
- supports annotating all beats or a single `beatId`
- carries through beat dates and time-of-day from `beats.json`

Current beat-facts direction:

- `shortSummary` and `longSummary` per beat
- fixed-location or journey location modeling
- beat-level NPCs, items, and organizations
- beat-level combat facts including phase and main enemies
- guidance for unnamed-first / named-later NPCs and locations

Current deterministic helper outputs:

- `<prefix>-beat-contexts.json`
- `<prefix>-beat-context-index.md`
- `contexts/<beatId>.md`

Current deterministic final outputs:

- `<prefix>-beat-facts.json`
- `<prefix>-beat-facts-preview.md`

Current status:

- implemented and evolving
- the artifact shape is now fairly well defined
- still likely to change as real-session testing surfaces edge cases

### 5. Session Summary Skill

Current files:

- [`skills/session-summary/SKILL.md`](../skills/session-summary/SKILL.md)
- [`skills/session-summary/scripts/build_session_summary_context.py`](../skills/session-summary/scripts/build_session_summary_context.py)
- [`skills/session-summary/scripts/build_session_recap.py`](../skills/session-summary/scripts/build_session_recap.py)
- [`skills/session-summary/scripts/manage_session_recap.py`](../skills/session-summary/scripts/manage_session_recap.py)

What it does:

- builds deterministic recap structure from `session.yaml`, `beats.json`, and `beat-facts.json`
- collapses beat-local facts into timeline blocks, recap blocks, and compact world facts
- generates a structured machine-parseable `session-recap.md` for human review
- validates the reviewed markdown recap against the deterministic context artifact

Current deterministic outputs:

- `<prefix>-session-summary-context.json`
- `<prefix>-session-recap.md`

Current status:

- implemented and evolving
- now the main synthesis boundary for the session pipeline
- intentionally markdown-first rather than summary-JSON-first
- still expected to evolve through real-session review and recap-quality iteration

### 6. JSON Schemas For Current Artifacts

Current files:

- [`_templates/json/README.md`](../_templates/json/README.md)
- [`_templates/json/session-manifest.schema.json`](../_templates/json/session-manifest.schema.json)
- [`_templates/json/speaker-stats.schema.json`](../_templates/json/speaker-stats.schema.json)
- [`_templates/json/normalized-transcript.schema.json`](../_templates/json/normalized-transcript.schema.json)
- [`_templates/json/cleanup-report.schema.json`](../_templates/json/cleanup-report.schema.json)
- [`_templates/json/session-corrections.schema.json`](../_templates/json/session-corrections.schema.json)
- [`_templates/json/beats.schema.json`](../_templates/json/beats.schema.json)
- [`_templates/json/beat-contexts.schema.json`](../_templates/json/beat-contexts.schema.json)
- [`_templates/json/beat-facts.schema.json`](../_templates/json/beat-facts.schema.json)
- [`_templates/json/session-summary-context.schema.json`](../_templates/json/session-summary-context.schema.json)

What they do:

- define the current structured payloads for the session pipeline
- make the beat-first artifact design more explicit
- provide a baseline for future validation and regression checks

Current status:

- implemented for the current structured artifacts
- useful as design references now
- not yet fully wired into automated validation

## Draft / In Progress

### Transcript Cleanup Strategy

The cleanup workflow is converging on:

- prepared bundle as the source of truth
- transcript-cleaner as the main interactive/agentic cleaning stage
- deterministic diff/report generation after cleanup

Still in flux:

- how much glossary context to preload automatically
- best prompts for difficult ASR edge cases
- when and how to surface manual review

### Beat Segmentation Strategy

The current direction is:

- medium-granularity story beats
- day-aware splitting
- combat-specific size handling
- deterministic validation + preview after the agent drafts beats

Still in flux:

- exact boundary heuristics in messy transcripts
- how aggressive the splitter should be with short-beat merging
- how much date inference should rely on secondary context

### Beat Facts Strategy

The current direction is:

- keep `beats.json` as segmentation only
- store summaries and entity/combat/location facts in a separate `beat-facts.json`
- use beat-local facts as the input to the recap synthesis stage
- treat the transcript as the detailed “zoomed-in” view, and beat summaries as higher zoom levels

Still in flux:

- how much per-field evidence/provenance should be preserved in V1
- whether single-beat annotation should load an existing `beat-facts.json` for inherited location context
- how much canon backfilling to do when NPCs or locations are unnamed at first and named later

### Session Recap Strategy

The current direction is:

- build a deterministic `session-summary-context.json` first
- use that context to draft a structured `session-recap.md`
- treat `session-recap.md` as the human review boundary
- preserve enough structure in markdown that downstream note generation can parse it deterministically

Still in flux:

- how aggressively timeline segments should compact on real session data
- how tight the world facts should be while still supporting useful cast / locations summaries
- what final note-generation targets should be derived from the reviewed recap markdown

## Pending

### Session Note Generation

Not yet implemented as a deterministic rebuild-from-reviewed-recap stage.

The intended direction is:

- parse reviewed `session-recap.md` into downstream session-note artifacts
- support multiple note styles / templates
- rebuild without rerunning LLM stages
- keep recap synthesis and final note rendering as separate steps

## Practical Current Workflow

If using the repo today, the most realistic path is:

1. prepare a session bundle with `prepare-source`
2. clean the transcript with the `transcript-cleaner` skill
3. split the cleaned transcript into beats with the `transcript-splitter` skill
4. extract beat context with the beat-annotator helper
5. draft `beat-facts.json`
6. validate and preview `beat-facts.json` with `manage_beat_facts.py`
7. build `session-summary-context.json`
8. draft `session-recap.md`
9. validate the reviewed `session-recap.md`

The main thing still missing from that flow is deterministic downstream note generation from the reviewed recap markdown.

## Pending Priorities

The next highest-value gaps are probably:

1. real-session testing of the beat annotator and session-summary skills on one or two session bundles
2. deterministic parsing from reviewed `session-recap.md` into downstream note artifacts
3. final note assembly from parsed recap artifacts
4. iterative recap prompt/style tightening based on real-session review
5. cleanup / docs polish for the raw-transcript generation side
