# Taelgar Session Pipeline – Tasks

High-level milestones:

- **M1 – Solidify raw data → raw transcript** (Zoom, diarized audio, raw audio)
- **M2 – Robust cleaning pipeline** (preprocess → LLM/manual)
- **M3 – Clean transcript → scenes → bullets → narrative**
- **M4 – Session note generation + rebuild-from-artifacts**
- **M5 – Docs, examples, and polish**

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

### A2. Audio processing (ffmpeg / `preprocess_audio.py`)

- [x] Document the exact ffmpeg graphs used by each audio profile (passthrough, normalize-only, zoom-audio, voice-memo).
- [x] Expand `session_pipeline/audio_processing.py` to cover any additional filters we need (e.g., noise gates, gating, multiband compression).
- [x] Polish the `preprocess_audio.py` CLI (directory traversal UX, progress reporting, dry-run).
- [x] Replace any lingering references to the legacy shell script in README/docs with the Python CLI instructions.
- [x] Ensure all audio entry points (`transcribe_with_whisper.py`, `transcribe_with_elevenlabs.py`, future Option 3) can call a single “prepare audio” helper with consistent sample rate / mono / PCM assumptions.
- [x] Add a check or small script that confirms only transcript/text artifacts are written under the `sessions/` output path (raw audio lives in a clearly separate path).

### A3. Chunking + session output hygiene

- [x] Review `session_pipeline/audio.py` chunking logic and note current edge cases (tiny trailing chunks, silence-only chunks, etc.).
- [x] Adjust chunking so that very small trailing chunks are merged into the previous chunk where possible.
- [x] Add a simple test script that feeds a synthetic WAV of known length and checks that chunk durations cover the full audio with no overlaps or gaps.
- [x] Create a helper or script that walks the session output directories and flags any non-text files (enforcing “session outputs are text only”).
- [x] Run this validation over existing sessions and clean or move any stray audio files out of `sessions/`.

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

### B1. Preprocess / quality assessment (`preprocess_raw_transcript.py`)

- [ ] Decide the input format for `preprocess_raw_transcript.py` (normalized JSON vs `[start - end] Speaker: text`).
- [ ] Define the output JSON schema (proper_noun_candidates, unknown_speaker_count, basic stats, optional quality_score).
- [ ] Reuse or wrap `find_proper_nouns.py` logic to populate `proper_noun_candidates` in the preprocess output.
- [ ] Add a counter for unknown speaker lines and store `unknown_speaker_count` plus a handful of example lines.
- [ ] Implement an optional LLM call that classifies overall text quality (e.g. “rough”, “okay”, “already cleaned”).
- [ ] Add a `--no-llm` flag to skip quality classification.
- [ ] Save preprocess reports as `<session>.preprocess.json` alongside the transcript.
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

- [ ] Decide which Obsidian notes should feed into a “session glossary” (e.g. NPCs, places, items).
- [ ] Write `export_session_glossary.py` that reads those notes and outputs a `glossary.json` of canonical spellings.
- [ ] Add an optional step in `preprocess_raw_transcript.py` to generate or consume `glossary.json`.
- [ ] Update LLM cleaning prompts to include glossary examples where relevant.

---

## M3 – Clean Transcript → Scenes → Bullets

### C1. Core formats

- [ ] Decide on the canonical “clean transcript” format that the scene splitter will take as input.
- [ ] Define the JSON schema for a “scene” object (id, start/end timestamps, list of speakers, raw text, etc.).
- [ ] Define the JSON schema for a “scene summary” (bullets, tagged NPCs, locations, loot, flags like `is_combat`).
- [ ] Define the YAML/JSON structure for a final session note (synopsis, scenes, NPCs, timeline, tags, etc.).

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

---

## M4 – Bullets → Narrative → Session Note

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
- [ ] Define a `session_config.yaml` format with:
  - [ ] Session ID, title, date.
  - [ ] Campaign/location tags.
  - [ ] Optional manual notes to inject.
- [ ] Implement `generate_session_note.py` that:
  - [ ] Reads `session.scene_summaries.json` and `session.scene_narratives.json`.
  - [ ] Reads `session_config.yaml`.
  - [ ] Outputs a Markdown session note matching your template.
- [ ] Add a “rebuild note” mode that:
  - [ ] Re-renders the note entirely from existing JSON artifacts without calling any LLMs.
  - [ ] Allows template changes to be applied retroactively.
- [ ] Implement simple combat extraction inside note generation:
  - [ ] Use `is_combat` flags or heuristics on scenes.
  - [ ] Collect combat-related bullets into a “Combats” section in the note.

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
