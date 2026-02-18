# taelgar-utils

Utilities for the Taelgar D&D workflow.

This repo currently has three layers:

1. **Core (maintained):** transcript processing, vault export, Discord export, and markdown helpers.
2. **Experimental (keep, needs work):** speaker-classification and clip-mining pipeline.
3. **Archived:** legacy code and retired corpus artifacts in `_old_stuff_/`.

## Core Workflows

### 1) Session Transcript Pipeline

Primary path from raw recordings/transcripts to cleaned speaker-attributed outputs.

- `preprocess_audio.py`
- `transcribe_with_whisper.py`
- `transcribe_with_elevenlabs.py`
- `normalize_transcript.py`
- `synchronize_transcripts.py`
- `clean_speakers.py`
- `process_zoom_sessions.py`
- `get_audio_offsets.py`
- `session_pipeline/` (shared helpers)

### 2) Obsidian Vault Export + Website

Publishing and Obsidian-related utilities.

- `export_vault.py`
- `taelgar_lib/`
- `website/`
- `website/build_site.py` (strict MkDocs export/build/check CLI)

### 3) Discord Ingestion / Export

- `run_discord_exporter.py`
- Config template: `configs/core/discord_export_config.yaml`

### 4) Markdown Helpers

- `merge_markdown.py`
- `extract_yaml_fields.py`
- `generate_index_page.py`

## Experimental (WIP)

These are kept but considered unfinished and lower stability.

- `generate_speaker_corpus.py`
- `train_speaker_classifier.py`
- `assign_speakers.py`
- `extract_segments.py`
- `generate_session_chunk_clips.py`
- `cleanup_prepare_segments.py`
- `parse_speakers.py`
- `parse_speakers_from_vtt.py`
- `split_transcript_by_scene.py`
- `models/`

## Archived / Legacy

- `_old_stuff_/` contains historical code, drafts, and retired artifacts.
- Retired corpus artifacts are archived under `_old_stuff_/taelgar_corpus/`.

## Configs, Docs, and Examples

- `configs/core/`
  - `default-zoom-roster.json`
  - `discord_export_config.yaml`
- `configs/experimental/`
  - `speaker_corpus.config.template.yaml`
  - `style-guide.json`
  - `voiceprints.json`
- `docs/planning/`
  - `notes.md`
  - `tasks.md`
- `examples/manifests/`
  - `session138_manifest.json`

## Repository Layout (Current)

```text
.
├── configs/                # Core + experimental config files
├── docs/                   # Planning notes and working docs
├── examples/               # Sample manifests and reference inputs
├── session_pipeline/        # Shared transcript/audio pipeline utilities
├── taelgar_lib/             # Obsidian helper library
├── website/                 # MkDocs build templates/assets/scripts
├── tests/                   # Current tests (audio + pipeline-adjacent)
├── models/                  # Experimental speaker model artifacts
├── _old_stuff_/             # Archived code and retired artifacts
└── *.py                     # Task entry-point scripts
```

## Notes

- The repo is in an intentional transition from many standalone scripts toward clearer module boundaries.
- Backward compatibility is not a goal for upcoming refactors.
