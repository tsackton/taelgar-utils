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

The intended flow is:

1. raw session source
2. raw transcript generation
3. prepared session bundle
4. cleaned transcript
5. beat segmentation
6. beat annotation
7. session synthesis
8. session note generation

In practice, the repo is currently strongest at:

- transcript preparation / archiving
- transcript cleanup workflow scaffolding
- beat segmentation workflow scaffolding

The annotation and final note-generation stages are still largely pending.

## Status Summary

| Stage | Purpose | Status |
| --- | --- | --- |
| Raw data -> raw transcript | Normalize Zoom / diarized inputs into a transcript | Partial |
| Session bundle prep | Archive inputs and generate a prepared bundle | Implemented |
| Transcript cleanup | Clean ASR / glossary / punctuation issues | Draft but usable |
| Beat segmentation | Split cleaned transcript into ordered beats | Draft but usable |
| Beat annotation | NPCs, places, items, combats, summaries, timeline facts | Pending |
| Session synthesis | Roll beats into recap, world payload, timeline | Pending |
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

Current output shape:

- bundle root: `<outputDir>/<campaign-slug>-<session-number>/`
- `sources/` contains archived inputs
- `cleaned/` contains generated outputs

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

## Pending

### Beat Annotation

Not yet implemented as a real pipeline stage.

Intended outputs will likely include:

- beat titles and summaries
- NPCs
- locations
- combats
- items / treasure
- important events / outcomes
- timeline facts

### Session Synthesis

Not yet implemented.

This is expected to roll beat annotations into:

- player recap
- world payload
- compressed campaign timeline

### Session Note Generation

Not yet implemented as a deterministic rebuild-from-artifacts stage.

The intended direction is:

- generate note content from artifacts, not directly from raw transcript
- support multiple note styles / templates
- rebuild without rerunning LLM stages

## Practical Current Workflow

If using the repo today, the most realistic path is:

1. prepare a session bundle with `prepare-source`
2. clean the transcript with the `transcript-cleaner` skill
3. split the cleaned transcript into beats with the `transcript-splitter` skill
4. manually inspect the generated markdown preview artifacts

Everything after that is still mostly planning and scaffolding rather than a finished pipeline.

## Pending Priorities

The next highest-value gaps are probably:

1. beat annotation artifact design and implementation
2. deterministic session synthesis outputs
3. final note assembly from artifacts
4. cleanup / docs polish for the raw-transcript generation side
