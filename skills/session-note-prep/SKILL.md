---
name: session-note-prep
description: Run the full RPG session-prep pipeline from a prepared session bundle through `session-recap.md`, branching between transcript cleanup and non-transcript source normalization before beat splitting, then continuing through `beat-annotator` and `session-summary` in either `auto` mode (no user pauses) or `interactive` mode (pause for cleanup and confirmation at the main checkpoints).
---

# Session Note Prep

Use this skill to run the existing session pipeline end to end on one prepared bundle.

This is an orchestration skill.
It does not replace the stage-specific rules in the component skills.
At each stage, load the next skill and follow its rules strictly:

- [`../transcript-cleaner/SKILL.md`](../transcript-cleaner/SKILL.md)
- [`../transcript-splitter/SKILL.md`](../transcript-splitter/SKILL.md)
- [`../beat-annotator/SKILL.md`](../beat-annotator/SKILL.md)
- [`../session-summary/SKILL.md`](../session-summary/SKILL.md)

Prefer loading only the stage you are currently executing, not every component in full up front.

## Required Inputs

Work from a prepared session bundle with:

- bundle root containing `cleaned/` and `sources/`
- `cleaned/<bundle-stem>-session.yaml`
- `cleaned/<bundle-stem>-source-prepared.md`
- optional glossary or dictionary explicitly provided for this run

Use `<bundle-stem>` as the canonical `file_prefix`.
Derive it from the session manifest filename by stripping the trailing `-session`.

In this repo, the cleaned transcript equivalent of `source.cleaned.md` should normally be:

- `cleaned/<bundle-stem>-source-cleaned.md`

Prefer these canonical downstream artifact paths in `cleaned/`:

- `<bundle-stem>-beats.json`
- `<bundle-stem>-beats-preview.md`
- `<bundle-stem>-beat-facts.json`
- `<bundle-stem>-beat-facts-preview.md`
- `<bundle-stem>-recap-scenes.json`
- `<bundle-stem>-recap-scenes-preview.md`
- `<bundle-stem>-session-summary-context.json`
- `<bundle-stem>-session-recap.md`

Stage-specific helper artifacts may live in subdirectories under `cleaned/`, for example:

- `cleanup-artifacts/`
- `annotation-context/`

## Modes

If the user does not specify a mode, default to `interactive`.

### `auto`

- Run all stages in order.
- After each stage, run the stage's deterministic validator or helper for a quick validation pass.
- Make one narrow repair pass if the validator output is specific and easy to fix.
- Do not pause for user confirmation between stages.
- Do not ask for manual cleanup at checkpoint boundaries.
- If a stage still has a hard blocker after the quick repair pass, stop the pipeline there and report the blocker clearly instead of pretending the next stage is reliable.

### `interactive`

- Run all stages in order.
- After transcript cleanup, transcript splitting, beat annotation, and recap-scene proposal:
  - run the validator
  - summarize the current artifact state and warnings
  - pause for user cleanup or confirmation before continuing
- If the user edits an artifact during a checkpoint, reread it and rerun the validator before moving on.
- Do not insert an extra checkpoint after `session-summary` unless the user explicitly asks for one.

## Human-Edited Recap Boundary

Validation and repair apply to the skill's own generated recap only, before its initial handoff to the user.

Once the recap has been handed off and a human has edited, accepted, or deliberately removed any generated content or structure, the recap is human-owned:

- do not run `manage_session_recap.py` against it
- do not rebuild, normalize, or repair it because it would fail the generated-artifact schema
- do not restore missing subsections, metadata, wording, or formatting
- do not treat validation failure as evidence that a human edit is wrong

A human-owned recap is allowed to fail the pipeline validator. Later skills may read it as authoritative input, but may change it only within the scope of a new explicit user request. Revalidate or repair it only when the user explicitly asks to revalidate, rebuild, or fix the recap.

## Shared Rules

- Honor the component skills' evidence rules and hard prohibitions, especially the ban on using files in `sources/` as correction or annotation evidence.
- Treat validated downstream artifacts as the handoff between stages.
- Do not silently weaken a stage's validation requirements just because this orchestrator is running the full pipeline.
- Before starting a stage, check whether its expected bundle artifact already exists.
- If an artifact already exists, validate it before trusting it.
- If an existing artifact validates cleanly and its upstream dependencies also exist in the current bundle, reuse it and skip regenerating that stage.
- If an existing artifact fails validation, treat that stage as incomplete: repair or regenerate it, then continue forward.
- The human-edited recap boundary above overrides these existing-artifact rules for `session_recap_md` after handoff.
- Do not rerun completed stages just because this is a full-pipeline skill.
- Keep filenames stable across the run so later stages point at the current validated outputs.

## Workflow

1. Discover the bundle root and `cleaned/` directory.
2. Resolve:
   - `session_yaml = cleaned/<bundle-stem>-session.yaml`
   - `prepared_transcript = cleaned/<bundle-stem>-source-prepared.md`
   - `cleaned_transcript = cleaned/<bundle-stem>-source-cleaned.md`
   - `beats_json = cleaned/<bundle-stem>-beats.json`
   - `beat_facts_json = cleaned/<bundle-stem>-beat-facts.json`
   - `recap_scenes_json = cleaned/<bundle-stem>-recap-scenes.json`
   - `summary_context_json = cleaned/<bundle-stem>-session-summary-context.json`
   - `session_recap_md = cleaned/<bundle-stem>-session-recap.md`
3. Check which stage outputs are already present in `cleaned/`.
4. Validate and resume from the latest trustworthy stage instead of restarting automatically.
   Use this order:
   - if `session_recap_md` and `summary_context_json` exist and the recap is still an untouched agent-generated artifact in the current pre-handoff run, validate it; if `manage_session_recap.py` passes, the pipeline is already complete
   - if an existing recap predates the current run or has been handed off for human review, treat it as human-owned and do not validate or repair it without an explicit request
   - else if `recap_scenes_json` exists and `manage_recap_scenes.py` passes, resume at `session-summary`
   - else if `beat_facts_json` exists and `manage_beat_facts.py` passes, resume at recap-scene proposal
   - else if `beats_json` exists and `manage_beats.py` passes, resume at `beat-annotator`
   - else if `cleaned_transcript` exists and the upstream normalization/cleanup stage has already produced it, resume at `transcript-splitter`
   - else start at transcript cleanup for `sourceType=transcript`, or source normalization for `sourceType=narrative|raw_notes`
5. Create helper directories only if needed, for example:
   - `cleaned/cleanup-artifacts/`
   - `cleaned/annotation-context/`
6. Run the remaining stages in order below.

## Stage 1: Upstream Source Cleanup Or Normalization

For `sourceType=transcript`, load `transcript-cleaner` before doing this stage.

Produce `cleaned/<bundle-stem>-source-cleaned.md`.

If `cleaned/<bundle-stem>-source-cleaned.md` already exists and is trustworthy, skip this stage and move to source splitting.

For transcript bundles:

Then run the diff report:

```bash
python skills/transcript-cleaner/scripts/report_cleanup_diff.py \
  --original /path/to/cleaned/<bundle-stem>-source-prepared.md \
  --cleaned /path/to/cleaned/<bundle-stem>-source-cleaned.md \
  --output-dir /path/to/cleaned/cleanup-artifacts \
  --file-prefix <bundle-stem>
```

For non-transcript bundles:

Run:

```bash
python cli/session.py normalize-source \
  --session /path/to/cleaned/<bundle-stem>-session.yaml \
  --output-dir /path/to/cleaned \
  --file-prefix <bundle-stem>
```

Quick-pass validation focus:

- transcript bundles: header preservation, line-count preservation, unresolved markers, repeated correction drift
- non-transcript bundles: sensible detected shape, useful primary units, preserved supplemental sources, omitted duplicate sections recorded in the normalization report

Mode handling:

- `auto`: do not pause; either fix narrow validation issues immediately or stop with a blocker report.
- `interactive`: pause after the report is generated and validated or blocked.

At the interactive checkpoint, provide:

- path to the cleaned transcript
- changed-line count and unresolved-marker count from the cleanup report
- path to the cleanup summary markdown
- a direct request for user cleanup or confirmation

## Stage 2: Source Splitting

Load `transcript-splitter` before doing this stage.

If `beats_json` already exists, run the validator first.
If it validates cleanly, skip regeneration and move to beat annotation.

Otherwise, draft `beats_json`, then validate and render it with:

```bash
python skills/transcript-splitter/scripts/manage_beats.py \
  --transcript /path/to/cleaned/<bundle-stem>-source-cleaned.md \
  --session /path/to/cleaned/<bundle-stem>-session.yaml \
  --beats-json /path/to/cleaned/<bundle-stem>-beats.json \
  --output-dir /path/to/cleaned \
  --file-prefix <bundle-stem>
```

Quick-pass validation focus:

- full transcript coverage
- beat order
- date sequencing
- suspiciously tiny or oversized beats
- preview sanity

Mode handling:

- `auto`: revise once if the validator or preview reveals an obvious fix, then continue without asking.
- `interactive`: pause after validation and preview generation.

At the interactive checkpoint, provide:

- path to `beats.json`
- beat count
- any validator warnings worth human review
- path to `beats-preview.md`
- a request for boundary/date/title cleanup or confirmation

## Stage 3: Beat Annotation

Load `beat-annotator` before doing this stage.

If `beat_facts_json` already exists, validate it first.
If it validates cleanly, skip regeneration and move to session summary.

Otherwise, first extract deterministic beat context:

```bash
python skills/beat-annotator/scripts/extract_beat_context.py \
  --transcript /path/to/cleaned/<bundle-stem>-source-cleaned.md \
  --session /path/to/cleaned/<bundle-stem>-session.yaml \
  --beats-json /path/to/cleaned/<bundle-stem>-beats.json \
  --output-dir /path/to/cleaned/annotation-context \
  --file-prefix <bundle-stem>
```

Then draft and validate beat facts:

```bash
python skills/beat-annotator/scripts/manage_beat_facts.py \
  --session /path/to/cleaned/<bundle-stem>-session.yaml \
  --beats-json /path/to/cleaned/<bundle-stem>-beats.json \
  --beat-facts-json /path/to/cleaned/<bundle-stem>-beat-facts.json \
  --output-dir /path/to/cleaned \
  --file-prefix <bundle-stem>
```

Quick-pass validation focus:

- beat/fact ordering alignment
- missing facts
- PCs incorrectly tagged as NPCs
- location continuity problems
- combat mismatches and preview sanity

Mode handling:

- `auto`: revise once if the validator exposes a narrow fix, then continue without asking.
- `interactive`: pause after beat facts validate and preview cleanly enough for review.

At the interactive checkpoint, provide:

- path to `beat-facts.json`
- path to `beat-facts-preview.md`
- path to `annotation-context/<bundle-stem>-beat-context-index.md` if useful
- any warnings or suspicious facts that merit human cleanup
- a request for fact cleanup or confirmation

## Stage 3.5: Recap Scene Proposal

Beats are evidence and navigation units; they are not automatically recap scenes. Before building the summary context, propose a smaller set of contiguous scene groups that reflects the session's actual playable situations.

Human guidance controls this stage:

- If the user gives exact beat groupings, preserve them unless they fail ordered coverage validation.
- If the user gives partial guidance, treat it as a constraint and propose the remaining boundaries around it.
- If the user gives no guidance, infer scenes from continuity of location, situation, immediate goal, and active cast.
- Do not target a fixed scene count or mechanically make one scene per beat.
- Do not merge across a genuine change of situation merely to make the recap shorter.
- Keep scene grouping independent from timeline grouping; one recap scene may cross a calendar-date boundary.

Draft `cleaned/<bundle-stem>-recap-scenes.json` with this shape:

```json
{
  "schemaVersion": "1.0",
  "scenes": [
    {
      "sceneId": "scene-001",
      "title": "A short scene title",
      "beatIds": ["beat-001", "beat-002"],
      "rationale": "Why these adjacent beats form one playable situation."
    }
  ]
}
```

Validate it and render the proposal preview:

```bash
python skills/session-summary/scripts/manage_recap_scenes.py \
  --beats-json /path/to/cleaned/<bundle-stem>-beats.json \
  --beat-facts-json /path/to/cleaned/<bundle-stem>-beat-facts.json \
  --recap-scenes-json /path/to/cleaned/<bundle-stem>-recap-scenes.json \
  --output-dir /path/to/cleaned \
  --file-prefix <bundle-stem>
```

The validator requires every beat exactly once, in original order, divided into contiguous groups with stable sequential scene IDs.

Mode handling:

- `auto`: validate the proposal, make one narrow repair if needed, then continue without pausing.
- `interactive`: show the compact scene-to-beat map and rationales, then stop for feedback before summary context generation. The scene map remains a proposal until the user approves it. If the user already supplied and confirmed an exact complete grouping, a redundant second approval pause is unnecessary; show a compact readback and continue.

At the interactive checkpoint, provide:

- the proposed scene count
- each scene title and its beat IDs
- a one-line rationale for any boundary that may be debatable
- the path to `<bundle-stem>-recap-scenes-preview.md`
- a direct request to approve or revise the scene grouping

## Stage 4: Session Summary

Load `session-summary` before doing this stage.

Before drafting, search for one clearly matching human-written session note using the canonical campaign identity and session number. If it exists, read it fully and use it as a secondary guide for summary style, emphasis, established naming, and notable details. Do not let it override the cleaned source, finalized beats, or beat facts; ignore stale dates or unsupported claims, and do not edit the written note during this pipeline stage.

The timeline output has only the compact `Short` view. Exact multi-day beats must be expanded into separate calendar-day entries before drafting. Strongly prefer daily entries: an overnight rest followed by next-day travel or arrival must never remain one date-range entry.

The recap scaffold includes optional human-owned `Arc` and `Table Notes` header fields. Leave both as `none` unless the user explicitly supplies their values. Do not infer them from the transcript, beat facts, or a written session note; surface them at handoff as fields the user may fill in.

If both `summary_context_json` and `session_recap_md` already exist, first apply the human-edited recap boundary above. Run `manage_session_recap.py` only when the recap is still an untouched agent-generated artifact in the current pre-handoff run. If it validates cleanly, skip this stage and treat the bundle as already complete. Otherwise, leave a human-owned recap unchanged unless the user explicitly requested rebuilding or validation.

Otherwise, build the deterministic context:

```bash
python skills/session-summary/scripts/build_session_summary_context.py \
  --session /path/to/cleaned/<bundle-stem>-session.yaml \
  --beats-json /path/to/cleaned/<bundle-stem>-beats.json \
  --beat-facts-json /path/to/cleaned/<bundle-stem>-beat-facts.json \
  --recap-scenes-json /path/to/cleaned/<bundle-stem>-recap-scenes.json \
  --output-dir /path/to/cleaned \
  --file-prefix <bundle-stem>
```

Build the recap scaffold:

```bash
python skills/session-summary/scripts/build_session_recap.py \
  --context-json /path/to/cleaned/<bundle-stem>-session-summary-context.json \
  --output-dir /path/to/cleaned \
  --file-prefix <bundle-stem>
```

Then fill in the prose fields and validate:

```bash
python skills/session-summary/scripts/manage_session_recap.py \
  --context-json /path/to/cleaned/<bundle-stem>-session-summary-context.json \
  --session-recap-md /path/to/cleaned/<bundle-stem>-session-recap.md
```

Quick-pass validation focus:

- all required sections present
- no remaining `TODO` placeholders
- Session Header title, tagline, summary, DM, and PCs are filled correctly
- recap/timeline/combat block ordering preserved
- no timeline `Long` subsections or exact multi-day timeline blocks remain

This stage completes the skill.
Do not add an automatic pause after it in `interactive` mode unless the user asked for one.

## Completion Criteria

The run is complete when these files exist and pass their stage validations:

- `cleaned/<bundle-stem>-source-cleaned.md`
- `cleaned/<bundle-stem>-beats.json`
- `cleaned/<bundle-stem>-beat-facts.json`
- `cleaned/<bundle-stem>-recap-scenes.json`
- `cleaned/<bundle-stem>-session-summary-context.json`
- `cleaned/<bundle-stem>-session-recap.md`

If the run stops early, report:

- the last completed stage
- the blocking artifact path
- the validator error or unresolved review issue
- the next concrete action needed to continue
