# Running Taelgar Utils

This repo is a collection of command-line utilities and Codex skills for the
Taelgar RPG workflow. The main maintained areas are:

- session source preparation, audio transcription helpers, and recap artifact
  generation
- website export/build tooling for the Taelgarverse MkDocs site
- small markdown and Discord export helpers
- experimental speaker-classifier tooling

Commands below assume you are running from the repo root:

```sh
cd /Users/tim/RPGs/taelgar-utils
```

## Setup

Use Python 3.11 or 3.12 if you plan to install the full ML/audio stack. The
lightweight tests and website exporter may also run on newer Python versions,
but packages such as `torch`, `pyannote.audio`, and `speechbrain` are the most
likely to lag behind new Python releases.

Create an environment and install the direct dependencies:

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Audio commands require `ffmpeg` on `PATH`. On macOS:

```sh
brew install ffmpeg
```

The CLI wrappers in `cli/` set `PYTHONPATH=src` for you. When you run modules
directly with `python -m`, set `PYTHONPATH` yourself:

```sh
PYTHONPATH=src python -m taelgar_utils.audio.offsets /path/to/part1.m4a /path/to/part2.m4a
```

Environment variables used by optional integrations:

- `OPEN_API_TAELGAR` or `OPENAI_API_KEY`: OpenAI transcription.
- `ELEVEN_LABS_API` or `ELEVENLABS_API_KEY`: ElevenLabs transcription.
- `DISCORD_USER`: DiscordChatExporter token used by `cli/discord-export.py`.
- `PYANNO`, `PYANNOTE_TOKEN`, `HF_TOKEN`, `HUGGINGFACE_TOKEN`, or
  `HUGGINGFACEHUB_API_TOKEN`: Hugging Face token for some experimental
  embedding backends.

## Tests

Run the full current test suite:

```sh
pytest
```

Useful focused checks:

```sh
pytest tests/test_website_build.py
pytest tests/test_normalize_source.py
pytest tests/test_manage_beat_facts.py tests/test_session_recap.py
```

## CLI Overview

Session pipeline commands:

```sh
python cli/session.py --help
python cli/session.py prepare-source --help
python cli/session.py normalize-source --help
python cli/session.py preprocess-audio --help
python cli/session.py transcribe-whisper --help
python cli/session.py transcribe-elevenlabs --help
```

Vault and website export command:

```sh
python cli/vault.py export --help
python website/build_site.py --help
```

Markdown utility commands:

```sh
python cli/markdown-utils.py merge --help
python cli/markdown-utils.py extract --help
python cli/markdown-utils.py make-index --help
```

Discord export:

```sh
python cli/discord-export.py --help
```

## Session Bundle Preparation

`prepare-source` is the first maintained step for a session bundle. It reads a
source file and a participant roster, archives the inputs, and writes canonical
prepared artifacts under a bundle-specific `cleaned/` directory.

Start from the templates:

```sh
cp examples/source_prep_config.template.yaml /tmp/source_prep.yaml
cp examples/participants.template.yaml /tmp/participants.yaml
```

Edit `/tmp/source_prep.yaml` so these fields point to real files and folders:

- `sourcePath`: transcript, narrative note, or raw-notes file to prepare.
- `sourceType`: usually `transcript`, `narrative`, or `raw_notes`.
- `outputDir`: directory where the session bundle should be written.
- `participantsPath`: the participant roster YAML.
- session metadata such as `campaign`, `sessionNumber`, `realWorldDate`,
  `drStart`, and `drEnd`.

Edit `/tmp/participants.yaml` with the real people and their canonical game
roles. For transcript sessions, provide speaker mappings in JSON:

```json
{
  "DM": "Tim",
  "Drou": "Alice",
  "Fazoth de Brune": "Bob"
}
```

Then prepare the bundle:

```sh
python cli/session.py prepare-source \
  --config /tmp/source_prep.yaml \
  --speaker-mappings /tmp/speaker-mappings.json \
  --force
```

For an interactive transcript speaker-mapping pass, use:

```sh
python cli/session.py prepare-source \
  --config /tmp/source_prep.yaml \
  --interactive-speakers
```

Typical output shape:

```text
<outputDir>/<bundle-stem>/
  sources/
  cleaned/
    <bundle-stem>-session.yaml
    <bundle-stem>-source-prepared.md
    <bundle-stem>-speaker-stats.json
```

For non-transcript sources, normalize the prepared source into the cleaned
source artifact:

```sh
python cli/session.py normalize-source \
  --session /path/to/cleaned/<bundle-stem>-session.yaml \
  --output-dir /path/to/cleaned \
  --file-prefix <bundle-stem>
```

That writes `cleaned/<bundle-stem>-source-cleaned.md` plus normalization
artifacts.

For transcript sessions, the current note pipeline expects `prepare-source` to
ingest the transcript directly. The supported transcript formats are WebVTT and
speaker-line text; set `transcriptFormat` to `auto`, `vtt`, or `speaker_lines`
in the source-prep config.

If multiple audio files make up one session, `prepare-source` does not combine
them. Use the offsets helper only when you need a quick duration/offset record
for manual source preparation:

```sh
PYTHONPATH=src python -m taelgar_utils.audio.offsets \
  /path/to/part1.m4a /path/to/part2.m4a \
  --output /tmp/audio-offsets.json
```

## Audio Preprocessing And Transcription

Available audio profiles:

- `passthrough`: transcode/resample without speech cleanup.
- `normalize-only`: in-memory loudness normalization.
- `zoom-audio`: ffmpeg high-pass, low-pass, denoise, dynamic normalization, and
  compression tuned for Zoom-like recordings.
- `voice-memo`: similar cleanup tuned for voice memos; the first run downloads
  an RNNoise model into `~/.cache/taelgar/rnnoise`.

Preprocess one or more files:

```sh
python cli/session.py preprocess-audio /path/to/audio.m4a \
  --audio-profile voice-memo \
  --output-dir /tmp/clean-audio \
  --output-format wav \
  --overwrite
```

Preprocess every audio file in a directory:

```sh
python cli/session.py preprocess-audio /path/to/recordings \
  --recursive \
  --audio-profile zoom-audio \
  --output-dir /tmp/clean-audio
```

Transcribe through OpenAI:

```sh
python cli/session.py transcribe-whisper /path/to/session.m4a \
  --session-id dufr-138 \
  --method whisper-r1 \
  --out-dir /path/to/sessions \
  --model whisper-1 \
  --audio-profile zoom-audio \
  --max-chunk-seconds 900 \
  --max-workers 2
```

Outputs are written to:

```text
<out-dir>/<session-id>/<method>/
  chunks/
  chunk_manifest.json
  chunk_transcripts/
  <method>.whisper.json
```

These transcription helpers produce service-output JSON. They are retained as
standalone upstream helpers; the current session-note pipeline starts once you
have a transcript that `prepare-source` can ingest.

Transcribe through ElevenLabs:

```sh
python cli/session.py transcribe-elevenlabs /path/to/session.m4a \
  --num-speakers 4 \
  --audio-profile voice-memo \
  --output /tmp/session.elevenlabs.json
```

For a text file containing one audio path per line:

```sh
python cli/session.py transcribe-elevenlabs /tmp/audio-files.txt \
  --diarization-threshold 0.6
```

## Lower-Level Audio Utilities

These are module-level helpers, so run them with `PYTHONPATH=src`.

Extract clips from a segment JSON:

```sh
PYTHONPATH=src python -m taelgar_utils.audio.clip_extract \
  --segments /path/to/segments.json \
  --audio-file /path/to/session.wav \
  --output-dir /tmp/clips \
  --mode sample \
  --n 50 \
  --min-sec 2 \
  --max-sec 5 \
  --audio-profile passthrough
```

Sample clips across session/chunk directories:

```sh
PYTHONPATH=src python -m taelgar_utils.audio.clip_sampling \
  --sessions-root /path/to/sessions \
  --output-root /tmp/sampled-clips \
  --per-session-target 50 \
  --min-per-chunk 5
```

Normalize diarization manifests into segment JSON:

```sh
PYTHONPATH=src python -m taelgar_utils.audio.diarization_segments \
  --manifest /path/to/manifest.csv \
  --output-dir /tmp/diarization-segments \
  --gap-threshold 0.25 \
  --force
```

Split an audio file into per-speaker tracks from WebVTT:

```sh
PYTHONPATH=src python -m taelgar_utils.audio.vtt_speaker_tracks \
  --audio /path/to/session.wav \
  --webvtt /path/to/session.vtt \
  --output /tmp/speaker-tracks \
  --chunk 15
```

Count speaker words in all `.vtt` files under the current directory:

```sh
cd /path/to/vtt/root
PYTHONPATH=/Users/tim/RPGs/taelgar-utils/src \
  python -m taelgar_utils.audio.vtt_speaker_counts
```

That writes `vtt_speaker_word_counts.json` in the current directory.

## Beat-First Session Recap Pipeline

After `prepare-source`, the Codex skill-backed pipeline goes from prepared
source to `session-recap.md`.

Required starting files:

```text
cleaned/<bundle-stem>-session.yaml
cleaned/<bundle-stem>-source-prepared.md
```

Canonical downstream outputs:

```text
cleaned/<bundle-stem>-source-cleaned.md
cleaned/<bundle-stem>-beats.json
cleaned/<bundle-stem>-beats-preview.md
cleaned/<bundle-stem>-beat-facts.json
cleaned/<bundle-stem>-beat-facts-preview.md
cleaned/<bundle-stem>-session-summary-context.json
cleaned/<bundle-stem>-session-recap.md
```

For transcript bundles, clean
`cleaned/<bundle-stem>-source-prepared.md` into
`cleaned/<bundle-stem>-source-cleaned.md`, preserving line IDs, speaker labels,
timestamps, and ordering. Then generate the deterministic cleanup artifacts:

```sh
python skills/transcript-cleaner/scripts/report_cleanup_diff.py \
  --original /path/to/cleaned/<bundle-stem>-source-prepared.md \
  --cleaned /path/to/cleaned/<bundle-stem>-source-cleaned.md \
  --output-dir /path/to/cleaned/cleanup-artifacts \
  --file-prefix <bundle-stem>
```

For non-transcript bundles, create the cleaned source with `normalize-source`:

```sh
python cli/session.py normalize-source \
  --session /path/to/cleaned/<bundle-stem>-session.yaml \
  --output-dir /path/to/cleaned \
  --file-prefix <bundle-stem>
```

Validate and render beats:

```sh
python skills/transcript-splitter/scripts/manage_beats.py \
  --transcript /path/to/cleaned/<bundle-stem>-source-cleaned.md \
  --session /path/to/cleaned/<bundle-stem>-session.yaml \
  --beats-json /path/to/cleaned/<bundle-stem>-beats.json \
  --output-dir /path/to/cleaned \
  --file-prefix <bundle-stem>
```

Extract beat context:

```sh
python skills/beat-annotator/scripts/extract_beat_context.py \
  --transcript /path/to/cleaned/<bundle-stem>-source-cleaned.md \
  --session /path/to/cleaned/<bundle-stem>-session.yaml \
  --beats-json /path/to/cleaned/<bundle-stem>-beats.json \
  --output-dir /path/to/cleaned/annotation-context \
  --file-prefix <bundle-stem>
```

Validate and render beat facts:

```sh
python skills/beat-annotator/scripts/manage_beat_facts.py \
  --session /path/to/cleaned/<bundle-stem>-session.yaml \
  --beats-json /path/to/cleaned/<bundle-stem>-beats.json \
  --beat-facts-json /path/to/cleaned/<bundle-stem>-beat-facts.json \
  --output-dir /path/to/cleaned \
  --file-prefix <bundle-stem>
```

Build summary context:

```sh
python skills/session-summary/scripts/build_session_summary_context.py \
  --session /path/to/cleaned/<bundle-stem>-session.yaml \
  --beats-json /path/to/cleaned/<bundle-stem>-beats.json \
  --beat-facts-json /path/to/cleaned/<bundle-stem>-beat-facts.json \
  --output-dir /path/to/cleaned \
  --file-prefix <bundle-stem>
```

Build the recap scaffold:

```sh
python skills/session-summary/scripts/build_session_recap.py \
  --context-json /path/to/cleaned/<bundle-stem>-session-summary-context.json \
  --output-dir /path/to/cleaned \
  --file-prefix <bundle-stem>
```

After filling in the prose fields in
`cleaned/<bundle-stem>-session-recap.md`, validate it:

```sh
python skills/session-summary/scripts/manage_session_recap.py \
  --context-json /path/to/cleaned/<bundle-stem>-session-summary-context.json \
  --session-recap-md /path/to/cleaned/<bundle-stem>-session-recap.md
```

The orchestration skill `skills/session-note-prep/SKILL.md` contains the same
stage order for Codex-driven interactive or automatic runs.

## Website Build

The website tooling lives in this repo, but it is normally run from the
Taelgarverse website repository root, where `website.json`, `mkdocs.yml`,
`taelgar-static/`, and `docs/` live.

From the website repository root:

```sh
python taelgar-utils/website/build_site.py check
python taelgar-utils/website/build_site.py export
python taelgar-utils/website/build_site.py build
python taelgar-utils/website/build_site.py serve
python taelgar-utils/website/build_site.py deploy --message "autobuild"
python taelgar-utils/website/build_site.py publish --message "autobuild"
```

Equivalent explicit-config form:

```sh
python taelgar-utils/website/build_site.py --config website.json check
```

Command behavior:

- `check`: validate config, links, assets, nav generation, and required Python
  modules without writing exported files.
- `export`: read `taelgar-static`, transform notes and assets, and write
  MkDocs-ready files into `docs/`.
- `build`: run `export`, then `mkdocs build`.
- `serve`: run `export`, `mkdocs build`, then `mkdocs serve`.
- `deploy`: run `export`, `mkdocs build`, `git add`, `git commit`, and
  `git push` in the website repository.
- `publish`: run `mkdocs build`, `git add`, `git commit`, and `git push`
  without running `export` first.

The canonical config example is `website/website_config_example.json`, and the
MkDocs example is `website/mkdocs_example.yml`.

Before exporting, refresh `taelgar-static` from the Obsidian vault when source
notes or Dataview materialization code have changed:

```sh
node "/Users/tim/Library/Mobile Documents/iCloud~md~obsidian/Documents/Taelgar/_scripts/materialize-dataview/materialize-dataview.mjs" \
  --vault "/Users/tim/Library/Mobile Documents/iCloud~md~obsidian/Documents/Taelgar" \
  --out "/Users/tim/RPGs/taelgarverse/taelgar-static" \
  --header-type website \
  --no-strict \
  --timeout 600
```

More website-specific configuration detail is in
`website/website_build_instructions.md`.

## Vault Export Wrapper

`cli/vault.py export` is a compatibility wrapper around the website build CLI.
Run it from the website repository root if you prefer the older entry point:

```sh
python /Users/tim/RPGs/taelgar-utils/cli/vault.py export --config website.json check
python /Users/tim/RPGs/taelgar-utils/cli/vault.py export --config website.json build
```

## Discord Export

`cli/discord-export.py` wraps DiscordChatExporter, downloads media, and converts
JSON exports into one markdown file per local day.

Create a YAML or JSON config with at least:

```yaml
executable_path: /absolute/path/to/DiscordChatExporter.Cli
channel_id: "123456789012345678"
format: Json
last_retrieved_date:
```

Then run:

```sh
python cli/discord-export.py \
  --config /path/to/discord-export.yaml \
  --output /path/to/export/channel.json
```

Outputs are written next to the JSON export:

```text
/path/to/export/channel.json
/path/to/export/assets/
/path/to/export/md/
```

To regenerate markdown from an existing JSON export without calling Discord:

```sh
python cli/discord-export.py \
  --config /path/to/discord-export.yaml \
  --output /path/to/export/channel.json \
  --reprocess-only \
  --force
```

After a successful run, the command prints a timestamp you can copy into
`last_retrieved_date` for future incremental exports.

## Markdown Utilities

Merge all markdown files in one directory into one document:

```sh
python cli/markdown-utils.py merge \
  --input-dir /path/to/notes \
  --output-file /tmp/combined.md
```

Extract selected YAML front matter fields into CSV:

```sh
python cli/markdown-utils.py extract \
  /path/to/notes \
  /tmp/session-fields.csv
```

Generate an index from markdown files in a directory:

```sh
python cli/markdown-utils.py make-index /path/to/notes \
  --link_style relative \
  --sort_order sessionNumber \
  --tie_breaker file_name \
  --template "{link_text} - {event_date_str}"
```

`make-index` prints to stdout, so redirect it when you want a file:

```sh
python cli/markdown-utils.py make-index /path/to/notes > /tmp/index.md
```

## Experimental Speaker Classifier

The speaker-classifier code is under
`src/taelgar_utils/experimental/speaker_classifier/`. It is experimental and
heavier than the rest of the repo because it can use scikit-learn, torch,
transformers, SpeechBrain, and pyannote models.

Build a training corpus from diarized sessions. The config must define
`sessions_dir`, `recordings_dir`, `clips_dir`, `diarization_glob`,
`speaker_mapping_glob`, and `player_allowlist`.

```sh
PYTHONPATH=src python -m taelgar_utils.experimental.speaker_classifier.build_corpus \
  --config /path/to/corpus-config.yaml \
  --dry-run
```

Train a model:

```sh
PYTHONPATH=src python -m taelgar_utils.experimental.speaker_classifier.train \
  --manifest /tmp/speaker-corpus/manifest.jsonl \
  --output-dir /tmp/speaker-model \
  --feature-type mfcc \
  --classifier linear-svm
```

Assign canonical speaker names to diarized segments:

```sh
PYTHONPATH=src python -m taelgar_utils.experimental.speaker_classifier.assign \
  --diarization /path/to/diarization.json \
  --audio /path/to/session.wav \
  --model /tmp/speaker-model/speaker_classifier.joblib \
  --output /tmp/assigned-speakers.json
```

Use each command's `--help` for the full option set. Some backends require a
Hugging Face token and local access to the selected model.

## Troubleshooting

If `ModuleNotFoundError` appears for a project module such as
`taelgar_utils`, either use a wrapper under `cli/` or run the module with
`PYTHONPATH=src`.

If an audio command fails before doing useful work, check that `ffmpeg` is
installed and visible:

```sh
ffmpeg -version
```

If the website build reports missing MkDocs plugins, reinstall the requirements
inside the active Python environment:

```sh
python -m pip install -r requirements.txt
```

If a command tries to overwrite an existing artifact, pass its documented
`--force` or `--overwrite` option only after confirming the old output is no
longer needed.
