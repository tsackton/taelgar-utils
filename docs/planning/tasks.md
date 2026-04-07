# Taelgar Session Pipeline – Tasks

High-level milestones:

- **M1 – Solidify raw data → raw transcript** (Zoom, diarized audio, raw audio)
- **M2 – Robust cleaning pipeline** (preprocess → LLM/manual)
- **M3 – Clean transcript → scenes → bullets → narrative**
- **M4 – Session note generation + rebuild-from-artifacts**
- **M5 – Docs, examples, and polish**

---

## Current Direction

The current implementation direction has converged on **beats** as the core unit rather than generic scenes.

That means the active path is now:

1. prepared bundle
2. cleaned transcript
3. `beats.json`
4. `beat-facts.json`
5. `session-summary-context.json`
6. `session-recap.md`
7. note generation from reviewed recap

Some of the older “scene” tasks below are still useful conceptually, but they should now be interpreted through a beat-first pipeline unless there is a strong reason to revive a separate scene layer.

## Recent Progress

- [x] Add `docs/session-pipeline-overview.md` as the current MOC for the session pipeline.
- [x] Solidify the transcript-cleaner skill around deterministic cleanup artifacts.
- [x] Solidify the transcript-splitter skill around canonical `beats.json` plus preview rendering.
- [x] Create the beat-annotator skill scaffold as a separate stage that does **not** edit `beats.json`.
- [x] Define the current `beat-facts.json` target shape for:
  - [x] beat summaries (`shortSummary`, `longSummary`)
  - [x] beat location facts
  - [x] beat NPC/item/organization facts
  - [x] beat combat facts
- [x] Add deterministic beat-context extraction for either all beats or a single `beatId`.
- [x] Implement deterministic validation + preview rendering for `beat-facts.json`.
- [x] Build the `session-summary` skill around deterministic context plus structured `session-recap.md`.
- [x] Add JSON Schemas under `_templates/json` for the current structured session-pipeline artifacts.

## Immediate Next Steps

- [ ] Test the current splitter + beat-annotator + session-summary flow on a real session bundle and revise schemas/prompts based on actual edge cases.
- [ ] Decide whether single-beat annotation should optionally load an existing `beat-facts.json` for prior-location inheritance.
- [ ] Implement deterministic parsing from reviewed `session-recap.md` into downstream note artifacts.
- [ ] Design the first deterministic session-note renderer that consumes parsed recap artifacts.

---

## M1 – Raw Data → Raw Transcript

### A1. Normalize → Sync → Clean refactor

- [ ] Sketch desired CLI for a single `process_transcript_pipeline.py` that runs normalize → synchronize → clean_speakers in one go.
- [ ] List current CLI options for `normalize_transcript.py`, `synchronize_transcripts.py`, and `clean_speakers.py` and decide which flags belong on the unified runner.
- [ ] Add a small wrapper script (e.g. `run_transcript_pipeline.py`) that shells out to the three existing scripts with passed-through arguments.
- [ ] Replace the wrapper with a proper Python module that imports and calls the underlying functions directly (no subprocess).
- [ ] Update `process_zoom_sessions.py` to call the new unified pipeline instead of invoking the three scripts separately.
- [ ] Update `transcribe_with_whisper.py` docs/comments to refer to the unified transcript pipeline.
- [ ] Add one end-to-end test or dry run script that takes a sample Zoom VTT and confirms the unified pipeline produces the same final transcript as the old three-step flow.



### A4. Option 2 + Option 3 alignment (diarized paths)

- [ ] Identify the exact input schema currently expected by `normalize_transcript.py` for diarized JSON (fields, speaker IDs, timestamps).
- [ ] Write a converter for ElevenLabs diarization JSON → normalize schema (for Option 3).
- [ ] Write a converter for any alternative diarization source you care about (e.g. Zoom or pyannote) → normalize schema (for Option 2/3).
- [ ] Update `transcribe_with_whisper.py` to write chunk manifests in a format that Option 3 will also use (shared manifest structure).
- [ ] Sketch the CLI for `transcribe_with_elevenlabs.py` (Option 3 runner) that: audio prep → chunk → diarize+transcribe → normalized JSON.
- [ ] Implement `transcribe_with_elevenlabs.py` to:
  - [ ] Accept a WAV path or a file-of-paths list.
  - [ ] Call shared audio chunking.
  - [ ] Save per-chunk ElevenLabs JSON beside the audio.
- [ ] Add an orchestration script `process_raw_audio_sessions.py` that runs:
  - [ ] Audio prep.
  - [ ] ElevenLabs / GPT diarization + transcription.
  - [ ] `normalize_transcript.py`.
  - [ ] `synchronize_transcripts.py`.
  - [ ] `clean_speakers.py`.
- [ ] Add a README section with a concrete Option 3 example (“raw audio only” workflow).

### A5. Speaker mapping via voiceprints (Option 3)

- [ ] List known speakers and gather 1–2 short reference clips per person for training voiceprints.
- [ ] Choose a Python method/library for speaker embedding / voiceprint comparison.
- [ ] Write a small script that takes a reference clip and a diarized segment and outputs a similarity score.
- [ ] Create a helper that:
  - [ ] Computes embeddings for diarized segments.
  - [ ] Matches each segment to the closest reference voice if above a confidence threshold.
- [ ] Integrate this helper into the Option 3 pipeline so diarized `speaker_num` values are mapped to canonical speaker names before `normalize_transcript.py`.
- [ ] Log ambiguous or low-confidence mappings to a review file (e.g. `speaker_conflicts.json`).

---

## M2 – Raw Transcript → Clean Transcript

Notes - so after a day of fiddling, it seems like the corpus generation is just too tricky, and fundamentally this is a task for AI, and really actually the better thinking models. ChatGPT does it incredibly well, albeit in pieces and requiring copying-pasting. It isn't going to be perfect - but it is so much better than anything else. 

So I think the best strategy is actually going to be doing the deterministic cleaning AFTER chatGPT. 

So we need a three-part approach:
(1) split into segments for chatGPT, and just copy-paste into new segments
(2) interactive session to replace tagged words and various other things, and also generate list of possible errors and replacements for consistency; likely benefits from a corpus. 
(3) final cleaning to do last replacements

Need to figure out how to optimize...

- [ ] Reorganize raw -> clean based on insights so far. 



### B1. Preprocess / quality assessment (`preprocess_raw_transcript.py`)

- [x] Decide the input format for `preprocess_raw_transcript.py` (normalized JSON vs `[start - end] Speaker: text`).
- [X] Define the output JSON schema (proper_noun_candidates, unknown_speaker_count, basic stats, optional quality_score).
- [X] Reuse or wrap `find_proper_nouns.py` logic to populate `proper_noun_candidates` in the preprocess output.
- [X] Add a counter for unknown speaker lines and store `unknown_speaker_count` plus a handful of example lines.
- [ ] Implement an optional LLM call that classifies overall text quality (e.g. “rough”, “okay”, “already cleaned”).
- [X] Add a `--no-llm` flag to skip quality classification.
- [X] Save preprocess reports as `<session>.preprocess.json` alongside the transcript.
- [ ] Document how to run `preprocess_raw_transcript.py` and interpret its output in the README.

### B2. LLM-based cleaner (`clean_transcript_llm.py`)

- [ ] Refactor existing `clean_transcript.py` into:
  - [ ] A reusable library function for chunking + LLM cleanup.
  - [ ] A thin CLI script `clean_transcript_llm.py`.
- [ ] Ensure `clean_transcript_llm.py` can optionally read the preprocess report and respect a quality decision (e.g. skip if already “clean”).
- [ ] Tighten the prompt to emphasize: “return input exactly except for spelling, punctuation, and speaker cleanup.”
- [ ] Add an option to feed in a glossary / mistakes JSON file from `find_proper_nouns.py`.
- [ ] Ensure raw LLM responses are logged per chunk in a consistent directory (similar to existing `clean_transcript.py` logging).
- [ ] Add a `--first-chunk-only` or `--sample` flag for quick prompt iteration.
- [ ] Add a wrapper or Makefile target that runs: preprocess → `clean_transcript_llm.py` → `compare_transcript.py` for a given session.

### B3. Manual/dictionary cleaner (`clean_transcript_manual.py`)

- [ ] Define CLI for `clean_transcript_manual.py` (input transcript path, mistakes dictionary path, output path).
- [ ] Wire `clean_transcript_manual.py` to use existing deterministic find/replace logic (`mistakes.json`).
- [ ] Implement a step that scans for unknown/placeholder speakers and writes those lines to `unknown_speakers_for_review.txt`.
- [ ] Add a simple TUI/CLI loop that:
  - [ ] Shows each unknown-speaker line plus a few lines of context.
  - [ ] Prompts for a known speaker from a roster, “delete”, or “leave unknown”.
- [ ] Save manual decisions to `unknown_speaker_resolutions.json` so they can be reused.
- [ ] Integrate `clean_transcript_manual.py` into the overall flow: if preprocess says “high quality but unknown speakers exist,” recommend this path.
- [ ] Document LLM vs manual cleaner usage in the README.

### B4. Obsidian glossary integration

- [X] Decide which Obsidian notes should feed into a “session glossary” (e.g. NPCs, places, items).
- [X] Write `export_session_glossary.py` that reads those notes and outputs a `glossary.json` of canonical spellings.
- [X] Add an optional step in `preprocess_raw_transcript.py` to generate or consume `glossary.json`.
- [ ] Update LLM cleaning prompts to include glossary examples where relevant.

---

## M3 – Clean Transcript → Scenes → Bullets

### C1. Core formats

- [ ] Decide on the canonical “clean transcript” format that the scene splitter will take as input.
- [ ] Define the JSON schema for a “scene” object (id, start/end timestamps, list of speakers, raw text, etc.).
- [ ] Define the JSON schema for a “scene summary” (bullets, tagged NPCs, locations, loot, flags like `is_combat`).
- [ ] Define the YAML/JSON structure for a final session note (synopsis, scenes, NPCs, timeline, tags, etc.).

### C1a. Beat-first artifacts

- [x] Define the canonical `beats.json` structure.
- [x] Define the initial `beat-facts.json` structure.
- [x] Define JSON Schemas for the current structured beat/bundle artifacts under `_templates/json`.
- [x] Implement deterministic validation for `beat-facts.json`.
- [x] Add a rendered preview artifact for `beat-facts.json`, similar to the beat preview.
- [ ] Decide whether `beat-facts.json` should preserve per-field provenance/evidence references, or keep V1 fully summary-level.
- [ ] Test beat-facts on at least one real session and revise enum values / field names where the current design is awkward.

### C2. Scene detection (`split_transcript_into_scenes.py`)

- [ ] Draft a simple heuristic for scene boundaries (timestamp gaps over a threshold, obvious setting changes, etc.).
- [ ] Implement `split_transcript_into_scenes.py` that:
  - [ ] Reads the clean transcript.
  - [ ] Applies heuristics.
  - [ ] Writes `session.scenes.json`.
- [ ] Add support for a small override file (e.g. YAML listing scene start timestamps) to adjust auto boundaries.
- [ ] Write a script that prints a human-readable summary of scenes (scene id, duration, first line).
- [ ] Test the scene splitter on 1–2 real transcripts and manually review whether boundaries feel right.

### C3. Scene summaries (`summarize_scenes.py`)

- [ ] Design an LLM prompt to summarize a single scene into:
  - [ ] Bullet list of key events.
  - [ ] Lists of NPCs, locations, loot, and plot hooks.
- [ ] Implement `summarize_scenes.py` that:
  - [ ] Reads `session.scenes.json`.
  - [ ] Calls the LLM per scene.
  - [ ] Writes `session.scene_summaries.json`.
- [ ] Add structured output parsing and raw-response logging per scene (similar to transcript cleaner).
- [ ] Add options to:
  - [ ] Only process selected scene IDs.
  - [ ] Re-run specific scenes with updated glossary/mistake dictionaries.
- [ ] Add a `--previously-on` input option so the LLM can incorporate prior-session context.

### C3a. Beat facts and zoom levels

- [x] Add `shortSummary` and `longSummary` to beat facts as the “zoomed-out” and “medium-detail” beat views.
- [x] Add location modeling for fixed beats, journey beats, and carried-forward location context.
- [x] Add NPC/item/organization role modeling to beat facts.
- [x] Add beat-level combat facts with `phase` and `mainEnemies`.
- [ ] Decide whether beat summaries should remain inside `beat-facts.json` long-term or move into a sibling beat-summary artifact.
- [ ] Decide how aggressively to canonicalize unnamed-first / named-later NPCs and locations when annotating a single beat in isolation.

---

## M4 – Bullets → Narrative → Session Note

### C3b. Session recap synthesis (`session-recap.md`)

- [x] Define the structured markdown shape for the rolled-up session recap that consumes `beats.json` + `beat-facts.json`.
- [x] Decide which session-level outputs belong in synthesis vs note rendering:
  - [x] cast of characters
  - [x] places visited
  - [x] combat tracker
  - [x] notable items / organizations
  - [x] session recap / opening summary
- [x] Implement a separate synthesis skill or script that merges beat-local facts into a machine-parseable markdown recap.
- [x] Implement deterministic markdown validation for reviewed `session-recap.md`.
- [ ] Implement deterministic parsing from reviewed recap markdown into downstream note artifacts.
- [ ] Iterate on recap prose quality and compaction using real session outputs.

### C4. Narrative + timeline (`generate_narrative.py`)

- [ ] Draft an LLM prompt that converts a scene’s bullet list into a short narrative paragraph or two, with optional timeline entries.
- [ ] Decide what the timeline representation looks like (e.g., list of `{time, description}` entries per scene or per session).
- [ ] Implement `generate_narrative.py` that:
  - [ ] Reads `session.scene_summaries.json`.
  - [ ] Writes `session.scene_narratives.json` (narrative + optional timeline).
- [ ] Add an option to generate a combined “session narrative” summarizing all scenes.
- [ ] Add flags to control tone/length (DM-log style vs player recap style).

### C5. Session note assembly (`generate_session_note.py`)

- [ ] Extract your current Obsidian session-note template into a standalone template file (Jinja or simple string formatting).
- [ ] Define the parsed artifact shape that comes out of reviewed `session-recap.md`.
- [ ] Implement `generate_session_note.py` that:
  - [ ] Reads parsed recap artifacts from reviewed `session-recap.md`.
  - [ ] Outputs a Markdown session note matching your template.
- [ ] Add a “rebuild note” mode that:
  - [ ] Re-renders the note entirely from reviewed recap artifacts without calling any LLMs.
  - [ ] Allows template changes to be applied retroactively.
- [ ] Decide whether any additional note-only metadata should be layered in after recap review, or whether the reviewed recap is the complete authoring boundary.

---

## M5 – Docs, Examples, and Polish

### D1. README / docs

- [ ] Update the main README “Session Processing” section to describe the three options (Zoom, diarized audio, raw audio) using the new orchestration scripts.
- [ ] Add a “Transcript Cleaning” section that describes preprocess → LLM/manual cleaner → outputs.
- [ ] Add a “Session Notes” section that outlines: clean transcript → scenes → bullets → narrative → final note.
- [ ] Create a concise “Getting Started” section for a new session:
  1. [ ] Put audio/VTT in a folder.
  2. [ ] Run the appropriate Option (1/2/3) command.
  3. [ ] Run the cleaning step (LLM or manual).
  4. [ ] Run the scene → bullets → narrative → session note pipeline.

### D2. Examples and regression harness

- [ ] Add a minimal example session directory (small transcript + outputs) to the repo.
- [ ] Add a script or Makefile target that runs the full pipeline on the example session as a quick regression test.
- [ ] Add example `session_config.yaml`, `glossary.json`, and `mistakes.json` to illustrate typical usage.

### D3. Roadmap tracking

- [ ] Create a short `ROADMAP.md` or keep this `tasks.md` updated as tasks are completed.
- [ ] Periodically review M1–M5 and mark newly completed tasks.
- [ ] Add any new ideas or “nice to have” tasks under a separate **Backlog** section at the bottom of this file.

---
