# taelgar-utils

A collection of Python scripts to work with Taelgar Obsidian notes

Currently includes two major scripts:

- export_vault.py, which autogenerates clean markdown for Material for Mkdocs
- summarize_session_note.py, which uses OpenAI API to summarize session notes

## Session pipeline CLI (Phase A)

A new CLI, `session_cli.py`, lets you run the session pipeline in targeted chunks without editing YAML by hand. You pass either `--audio` (with diarization) or `--vtt` as inputs and choose the step range to run.

Steps (in order):
- audio — audio/VTT to raw transcript
- clean — raw to cleaned transcript (LLM; can be skipped)
- scenes — create a scene-marked transcript and split into per-scene files
- summarize — per-scene summaries (title, bullets, narrative)
- assemble — merge summaries into the final markdown and add frontmatter

### Quick start

Show help

```bash
python3 session_cli.py --help
python3 session_cli.py run --help
python3 session_cli.py validate --help
```

Run only the audio step from a WebVTT transcript

```bash
python3 session_cli.py run \
	--session-number 106 \
	--campaign Dunmar \
	--vtt /path/to/Recording.transcript.vtt \
	--from audio --to audio
```

Run from transcript to scene summaries (skip cleaning)

```bash
python3 session_cli.py run \
	--session-number 106 \
	--campaign Dunmar \
	--vtt /path/to/Recording.transcript.vtt \
	--from clean --to summarize \
	--skip-clean
```

Finish from summaries to the final session note

```bash
python3 session_cli.py run \
	--session-number 106 \
	--campaign Dunmar \
	--campaign-name "Dunmar" \
	--players "Faldrak, Delwath, Kenzo, Wellby, Riswynn" \
	--dm "Tim Sackton" \
	--dr 968-04-06 --dr-end 968-04-06 \
	--session-date 2024-09-13 \
	--from summarize --to assemble
```

Validate current state for a session

```bash
python3 session_cli.py validate \
	--session-number 106 \
	--campaign Dunmar \
	--vtt /path/to/Recording.transcript.vtt
```

### YAML defaults for CLI

You can provide defaults in a YAML file and override any of them on the command line using `--args-yaml`.

```bash
python3 session_cli.py --args-yaml args.example.yaml validate
python3 session_cli.py --args-yaml args.example.yaml run --to summarize --skip-clean
```

See `args.example.yaml` in the repo root for a template. Notes:
- CLI flags always take precedence over values in the YAML file.
- In YAML, you may use `from:` and `to:` (mapped internally to `from_step`/`to_step`).
- `players` and `examples` can be lists or comma-separated strings.

### Editing prompts (Phase B - prompts extracted)

Prompts used by the pipeline are now externalized in `prompts/` and can be edited without touching code:

- prompts/scene_bullets.md — title + bullets for each scene
- prompts/scene_narrative.md — in-world narrative for each scene
- prompts/session_summary.md — overall session summary/frontmatter fields
- prompts/transcript_cleaner.md — base rules for the transcript cleaning step

Notes:
- If these files are missing, the code falls back to built-in defaults.
- You can override a specific prompt path via environment variable `PROMPT_<NAME>`, where `<NAME>` is the filename stem uppercased. For example:
	- `PROMPT_SCENE_BULLETS=/path/to/custom_bullets.md`
	- `PROMPT_SCENE_NARRATIVE=/path/to/custom_narrative.md`
	- `PROMPT_SESSION_SUMMARY=/path/to/custom_session_summary.md`
	- `PROMPT_TRANSCRIPT_CLEANER=/path/to/custom_cleaner.md`
- The transcript cleaner template supports placeholders that are filled at runtime:
	- `{preserved_speakers}`, `{dm_hint}`, `{glossary_text}`

### Requirements

`session_cli.py` reuses the existing implementation in `generate_session_note_v2.py` and expects these packages to be installed (plus standard libs):

- openai (Responses API)
- python-dotenv (env var loading)
- pydub (audio chunking)
- pydantic (schemas)
- webvtt-py (VTT parsing)
- PyYAML (already present)

If you only need help/usage, the CLI prints without importing heavy dependencies. Running the pipeline steps will require the packages listed above.
