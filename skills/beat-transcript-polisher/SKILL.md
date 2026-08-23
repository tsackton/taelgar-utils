---
name: beat-transcript-polisher
description: Polish recap-scoped RPG session transcript excerpts for zoomable session notes. Use after `session-summary` when the user wants beat or recap-level polished transcript files under `cleaned/beat-transcripts`, with matching `Polished Transcript` paths inserted into `session-recap.md`.
---

# Beat Transcript Polisher

Use this optional skill after the normal session note pipeline has produced:

- `cleaned/<bundle-stem>-source-cleaned.md`
- `cleaned/<bundle-stem>-session-recap.md`

This skill is not part of default `session-note-prep`.
It adds readable transcript excerpts for zoomable session note views.

## Goal

For each recap block:

1. Extract the block's `sourceRange` from the cleaned source transcript.
2. Polish that transcript excerpt into readable speaker turns without turning it into recap prose.
3. Write the polished transcript to `cleaned/beat-transcripts/`.
4. Add a `Polished Transcript` entry immediately after `Source Range` in the recap block metadata.
5. Fill a transcript highlights summary for pull quotes and audio monologue candidates.
6. Sync editable session-level pull quote and audio highlight candidate sections into `session-recap.md`.

The recap block is the normal unit of work.
If the user asks for one specific beat, map it to the recap block that contains that beat.

`session-recap.md` is the sole source of truth for recap block IDs, titles, beat IDs, and source ranges.
Do not read, trust, or reconcile `session-summary-context.json` for this skill; it may be stale after human recap editing.
The helper owns `Polished Transcript` metadata as derived output and will insert or update it from the recap block identity.

## Allowed Inputs

Primary evidence:

- the current cleaned source transcript
- `session-recap.md`
- optional glossary or dictionary explicitly provided for this polishing run

Secondary evidence is allowed, but subordinate to the primary evidence above.
This can include:

- prior cleaned transcripts
- earlier session outputs
- relevant notes elsewhere in the vault

Strictly ignore files in the bundle's `sources/` directory.
Those files are archival inputs and may contain transcription errors.
They are not valid evidence for polishing or speaker reassignment.

## Output Shape

Write polished transcript files under:

```text
cleaned/beat-transcripts/
```

Use the helper script's stable default filenames:

```text
<bundle-stem>-<recap-block-id>-transcript.md
```

Each file should keep this shape:

```markdown
# recap-001 | Deciphering the Scroll

- Recap Block: recap-001
- Beat IDs: beat-001
- Source Range: u0001 -> u0100
- Source Transcript: ../<bundle-stem>-source-cleaned.md

## Transcript

%% u0001-u0007 %%
DM: The next morning you awake in various states of hungoverness, and meet outside this tower.

%% u0008 %%
Player: I ask whether the tower looks occupied.
```

The file heading must use the title from the final `session-recap.md` recap heading, not the older title in `session-summary-context.json`.
The visible transcript is under `## Transcript`, with one speaker-prefixed line per readable turn.
Put a compact source UID comment immediately before each visible turn.
Use only UID ranges in source comments, for example `%% u0506-u0512 %%`.
Do not include timestamps in the polished transcript.

The helper also creates this review file if it does not already exist:

```text
cleaned/beat-transcripts/<bundle-stem>-transcript-highlights.md
```

Use it to collect session-note callouts after the transcript files are polished:

```markdown
# Transcript Highlights

## Pull Quotes

### beat-001 | Beat Title

- Recap Block: recap-001
- Transcript: <bundle-stem>-recap-001-transcript.md
- Source Range: u0001 -> u0100
- Pull Quotes:
  - ID: quote-beat-001-001
    - Quote: "A short, punchy quote."
    - Speaker: Wazir
    - Source Lines: u0123-u0126

## Audio Monologue Candidates

- ID: audio-001
  - Source Lines: u0230-u0268
  - Speaker: DM
  - Summary: Short description of the monologue content.
  - Why Called Out: Why this may be useful as an audio highlight.
```

Pull quotes are required for each beat.
Each pull quote must have a globally unique `ID`, preferably `quote-<beatId>-NNN`.
Choose 2-3 pull quotes per beat when the transcript has enough material.
Prefer variety across speakers, moods, and story functions rather than picking several quotes that all do the same job.
Choose lines that are punchy, interesting, emotionally revealing, funny, ominous, or otherwise useful as session-note highlights.
Audio monologue candidates are expected across the session; include at least 2 when the transcript contains two worthwhile longer speeches, narrations, exchanges, or table moments, and include up to 5 when there are enough strong candidates.
Each audio monologue candidate must have a globally unique `ID`, preferably `audio-NNN`.
Only write `None identified.` under `## Audio Monologue Candidates` when no viable audio highlight exists, and report that constraint to the user.

After the highlights summary is filled, the helper also syncs selected-material candidates into `session-recap.md`:

```markdown
## Pull Quotes

- ID: quote-beat-001-001
  - Quote: "A short, punchy quote."
  - Speaker: Wazir
  - Source Lines: u0123-u0126

## Audio Highlights

- ID: audio-001
  - Title: Short description of the monologue content.
  - Speaker: DM
  - Source Lines: u0230-u0268
  - Output: audio-001.m4a
```

The full highlights summary remains the complete record. The recap sections are the human-reviewed selected set for the session note: delete candidates that should not appear and reorder the remaining entries as desired. Do not manually copy candidate text from the highlights file into the recap.

## Polishing Rules

- Preserve every `uNNNN` UID in exactly one source comment and keep UID order unchanged.
- Hide source UIDs in `%% ... %%` comments; do not leave `[uNNNN | ...]` source headers visible.
- Speaker labels may be corrected only when the local context makes the original assignment obviously wrong.
- Merge adjacent source lines into natural speaker turns.
  A turn is a complete readable speech unit, not a fixed number of source lines.
  Keep source comments tight by rhetorical unit, sentence, action, or topic; do not split a visible turn in the middle of a phrase just because a source UID boundary falls there.
- Split long same-speaker stretches at natural rhetorical, breath, sentence, action, or topic boundaries, with a separate source comment for each turn.
- Do not omit, summarize, reorder, or add substantive content.
- Treat the output as an edited transcript, not a prose adaptation.
  Preserve the speaker's wording, tense, syntax, repetitions, rhetorical fragments, run-on cadence, and vocal texture unless they are clearly ASR errors or make the text hard to parse.
- Polish more aggressively than `transcript-cleaner`:
  - fix grammar and punctuation
  - repair broken source-line boundaries and capitalization
  - remove obvious ASR filler and duplicated false starts when doing so preserves the speaker's meaning
  - correct additional ASR errors missed by the upstream cleaner
  - normalize known names and campaign terms using the same evidence standards as transcript cleanup
- Do not substitute smoother, more literary, or more concise wording merely because it reads better.
  Examples of over-polish: changing `got denser` to `grew denser`, `long, long since` to `long since`, `anyways` to `anyway`, or `He tells you` to `He told you` without a clear transcript reason.
- Keep character voice and table phrasing where it carries meaning.
  Do not make every speaker sound formal.
- Preserve performance texture where it carries meaning: rhetorical questions, hedges, repeated adjectives, self-corrections, trailing constructions, and deliberate run-on sentences.
- Do not add narrative descriptions, scene summaries, or stage directions that are not in the transcript.
- If a phrase remains suspicious but cannot be corrected with high confidence, mark only that phrase with `[[...]]`.
- If any `[[...]]` markers remain, report them to the user with UID locations before treating the polished transcript as final.

### Calibration Examples

Prefer transcript-faithful cleanup over smoothed recap prose:

- Bad: `Lord Holda: proud, bitter, resentful, over the hill...`
- Good: `Lord Holda, who was, what? Proud? Bitter? Resentful? Over the hill?`
- Bad: `in a place long since swallowed by woods`
- Good: `in a place that was long, long since swallowed by woods`
- Bad: `this self-described elven archivist`
- Good: `this elf, who called himself an archivist`

## Quality Review

After polishing transcript files, run a separate prose-quality review pass before filling highlights or treating the transcript set as final.
When a fast/low-effort review agent is available, use it for this pass.
The reviewer must not edit files directly; it should return `pass` or `rework` with compact findings that cite transcript file, visible line, UID range, and issue type.

The review pass should look specifically for text that still reads like joined ASR output:

- stray punctuation and capitalization artifacts
- obvious duplicated false starts, such as `how comp... How complex`
- fragments joined across source-line boundaries without sentence repair
- long turns with no readable paragraph, rhetorical, or topic boundaries
- filler and repeated phrases that no longer carry table voice or meaning
- over-polished turns that flatten spoken cadence into recap prose
- unnecessary synonym substitutions, tense harmonization, removed repetitions, or collapsed rhetorical fragments
- source comments that split a visible phrase across turns, such as ending one turn with `a...` and starting the next with `House`

If the review returns `rework`, revise only the cited transcript blocks, then rerun structural validation and prose review.

## Workflow

1. Resolve the bundle paths:
   - `cleaned_transcript = cleaned/<bundle-stem>-source-cleaned.md`
   - `session_recap_md = cleaned/<bundle-stem>-session-recap.md`
   - `transcript_output_dir = cleaned/beat-transcripts`
2. Run the deterministic helper to extract missing transcript files and patch recap metadata:

```bash
python skills/beat-transcript-polisher/scripts/manage_beat_transcripts.py \
  --transcript /path/to/cleaned/<bundle-stem>-source-cleaned.md \
  --session-recap-md /path/to/cleaned/<bundle-stem>-session-recap.md \
  --output-dir /path/to/cleaned/beat-transcripts \
  --file-prefix <bundle-stem>
```

3. Polish each generated transcript file under `## Transcript`.
   For long sessions, work one recap block at a time.
4. Run the prose-quality review pass and fix any `rework` findings.
5. Fill `<bundle-stem>-transcript-highlights.md`:
   - 2-3 pull quotes for each beat when enough material exists
   - at least 2 and up to 5 audio monologue candidates across the whole session when enough material exists
6. Run the helper again in normal mode to sync `## Pull Quotes` and `## Audio Highlights` into `session-recap.md`.
   This does not overwrite existing transcript files unless `--overwrite` is passed.
7. Review `session-recap.md`:
   - delete pull quotes and audio highlights that should not appear in the final session note
   - reorder the remaining entries if desired
   - edit audio titles or output filenames if needed
8. Run the helper again in validation mode:

```bash
python skills/beat-transcript-polisher/scripts/manage_beat_transcripts.py \
  --transcript /path/to/cleaned/<bundle-stem>-source-cleaned.md \
  --session-recap-md /path/to/cleaned/<bundle-stem>-session-recap.md \
  --output-dir /path/to/cleaned/beat-transcripts \
  --file-prefix <bundle-stem> \
  --validate-only
```

9. Fix any validation errors before handing off the polished transcript set.

## Single Block Work

To work on one recap block:

```bash
python skills/beat-transcript-polisher/scripts/manage_beat_transcripts.py \
  --transcript /path/to/cleaned/<bundle-stem>-source-cleaned.md \
  --session-recap-md /path/to/cleaned/<bundle-stem>-session-recap.md \
  --output-dir /path/to/cleaned/beat-transcripts \
  --file-prefix <bundle-stem> \
  --recap-block-id recap-001
```

If the user provides a `beatId` instead of a recap block id, inspect the `## Recap` block metadata in `session-recap.md` and select the recap block whose `Beat IDs` includes that beat.

## Helper Script

`scripts/manage_beat_transcripts.py` owns:

- validating that inputs are outside `sources/`
- reading recap block IDs, titles, beat IDs, and source ranges from `session-recap.md`
- extracting source lines into stable draft transcript files
- syncing transcript file headings to titles from `session-recap.md`
- never overwriting existing transcript files unless `--overwrite` is passed
- creating `<bundle-stem>-transcript-highlights.md` if it is missing
- inserting or updating `- Polished Transcript: ...` immediately after `- Source Range: ...`
- syncing pull quote and audio highlight candidates from the transcript highlights summary into `session-recap.md`
- validating that each polished transcript source comments preserve the exact UID list for its recap source range
- validating that visible transcript lines use `Speaker: text` turn format and do not expose source headers
- validating that the transcript highlights summary exists and has one section for each beat
- validating that pull quote and audio candidate IDs are present and globally unique

The script accepts a deprecated `--context-json` argument for older command lines, but ignores it.
The script does not polish prose or select highlights.
The LLM must edit the generated transcript files and fill the transcript highlights summary.
