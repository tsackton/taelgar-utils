---
name: transcript-splitter
description: Split a cleaned RPG session transcript into ordered story beats while preserving full transcript coverage. Use when producing `beats.json` from a cleaned transcript, especially when beat titles, date inference, time windows, combat sub-splits, and markdown preview artifacts are needed.
---

# Transcript Splitter

Use this skill when working from a cleaned session bundle:

- `session.yaml`
- cleaned transcript (`source.cleaned.md` or equivalent)
- optional campaign glossary or dictionary

The goal is to produce an ordered beat segmentation artifact that later annotation steps can trust.

## Allowed Inputs

Primary evidence:

- `session.yaml`
- the current cleaned transcript
- an optional glossary or dictionary explicitly provided for this segmentation run

Strictly ignore files in the bundle's `sources/` directory when making segmentation decisions.
Those files are archival inputs and may themselves contain transcription errors or stale failed attempts.
They are not valid evidence for beat boundaries or date inference.
Treat this as a hard prohibition, not a preference.
Do not read from `sources/`, do not quote from it, and do not use it to confirm or reject a boundary.

Secondary evidence is allowed, but subordinate to the primary evidence above.
This can include:

- prior cleaned transcripts
- earlier session outputs
- relevant notes elsewhere in the vault

Use secondary evidence only to support or confirm a boundary or date inference, never to override what the current cleaned transcript, `session.yaml`, and glossary/dictionary indicate.
The `sources/` directory is never secondary evidence. It is always out of bounds.

## Rules

- Work from the cleaned transcript, not the raw transcript.
- The canonical artifact is `beats.json`.
- Do not repeat transcript body text in `beats.json`.
  Reference transcript ranges only with `startUid` and `endUid`.
- Every transcript line must belong to exactly one beat.
- Beat order must match transcript order.
- Segment in two passes:
  1. split on obvious scene transitions
  2. split overly long scenes at natural sub-points
- Prefer day-aware boundaries where evidence supports them.
  If the transcript clearly moves into a new day, prefer a beat split there unless it would create a trivial fragment.
- Aim for beats between 150 and 500 transcript lines.
- Beats under 150 lines should usually be merged with an adjacent beat, especially at the beginning or end of the transcript, unless there is a strong scene break or day transition.
- Beats over 500 lines should usually be split at natural sub-points.
- Treat combat as one beat unless that beat would exceed 500 transcript lines.
  If so, split the combat into contiguous sub-beats at natural tactical or narrative phase changes.
- Exceptions to the 150-500 target range are allowed only when strongly justified by a real scene break or date transition.
- Every beat must have `dateStart`.
- `dateEnd` is optional and should be used only when a single beat spans multiple consecutive days.
- `timeWindow` is optional and must be one of:
  `dawn`, `morning`, `midday`, `afternoon`, `evening`, `night`
- Beat `n+1` must either:
  - stay on the same day as beat `n`, or
  - advance by exactly one day from beat `n`'s effective end date
- Do not skip days between adjacent beats.
  If the transcript covers multiple days in one continuous beat, use a date range within that beat instead.
- Every beat should have:
  - a short title
  - a boundary reason
  - date evidence
- Beat titles should aim to be 6 words or fewer.
  Only exceed that when extra words are strictly needed for clarity.

## Date Inference

Infer beat dates and time windows from the transcript and `session.yaml`.

Strong date/time evidence includes:

- long rests
- sleep / waking
- watches
- "next morning"
- "at dawn"
- "by evening"
- travel-day transitions
- explicit calendar references

When date evidence is weak:

- default to the prior beat's date
- only advance the date when the transcript gives real support
- omit `timeWindow` rather than guessing

## Workflow

1. Read `session.yaml` and the current cleaned transcript.
2. If a glossary or dictionary is provided, load it once before reasoning about beats.
3. Do a line-by-line boundary scan through the transcript.
   For each local region, check for:
   - location shifts
   - objective shifts
   - social scene to combat changes
   - combat phase changes
   - day or time-of-day transitions
   - travel montage boundaries
4. Draft an initial ordered beat list by first splitting on obvious scene transitions.
5. Review the resulting scene-sized beats for size.
   - merge very short beats unless a day transition or very strong scene break justifies them
   - split long beats, especially long combats, at natural sub-points
6. For each beat, assign:
   - `beatId`
   - `title`
   - `startUid`
   - `endUid`
   - `dateStart`
   - optional `dateEnd`
   - optional `timeWindow`
   - `containsCombat`
   - `boundaryReason`
   - `dateEvidence`
7. Run `scripts/manage_beats.py` to validate the beats and render the preview deterministically.
8. If validation fails or the preview shows weak boundaries, revise the beats in chat or edit the JSON directly, then rerun the script.

## Review Artifacts

The deterministic script should own these files:

- `<prefix>-beats.json`
- `<prefix>-beats-preview.md`

The preview is for human review in Obsidian.
If you want to adjust titles, dates, time windows, or beat boundaries, revise the JSON directly or ask the agent to do it interactively in chat.

## Deterministic Script

Generate artifacts with:

```bash
python skills/transcript-splitter/scripts/manage_beats.py \
  --transcript /path/to/source.cleaned.md \
  --session /path/to/session.yaml \
  --beats-json /path/to/beats.json \
  --output-dir /path/to/beat-artifacts \
  --file-prefix addermarch-campaign-007
```

The script is the source of truth for:

- transcript coverage validation
- date sequencing validation
- beat-size warnings
- combat-size validation
- preview rendering

Treat the script output as the canonical beat artifact rather than editing the preview.
