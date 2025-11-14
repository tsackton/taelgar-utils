# taelgar-utils

Utilities that support the Taelgar campaign vault, with a focus on processing
session audio/transcripts and keeping the Obsidian vault in sync.

---

## Session Processing

These scripts form the current audio → transcript → cleaned output pipeline.

There are intended to be three ways to produce a standarized cleaned output, defined here as a raw transcript in a standard format with normalized speaker names (to the extent possible). 

### Option 1: WebVTT from Zoom

If you have a Zoom transcript, the process is simple, as the only requirement is to normalize speaker names and extract speaker information and diarization from the WebVTT output. 

Run:
```
process_zoom_sessions.py --zoom-dir PATH/TO/ZOOM --sessions-root PATH/TO/OUTPUT --speaker-roster (optional json with known speaker mappings)
```

Note this code currently:
(a) hard codes the campaign prefix, as a variable at the top of the script
(b) assumes that session number can be identified from `re.search(r"(\d+)", name)`, which should generally work as long as there are no other numbers in the directory name

Under the hood, this runs:
- `normalize_transcript.py`
- `synchronize_transcripts.py`
- `clean_speakers.py`

### Option 2: Diarized Audio

When you already have a good diarization track (Zoom, ElevenLabs, pyannote, etc.), use `transcribe_with_whisper.py` to re-transcribe the raw audio and keep the diarization you trust. The runner:

```
transcribe_with_whisper.py \
  --session-id dufr-000 \
  --method whisper-raw \
  --out-dir /path/to/sessions \
  PATH/TO/audio.wav
```

What it does:
- Chunks the source audio with `session_pipeline.chunking.prepare_audio_chunks` (silence-aware splits, no trimming, manifests saved beside the session).
- Submits each chunk to OpenAI Whisper/GPT for transcription (parallel-safe, per-chunk JSON logged immediately).
- Produces a merged `method.whisper.json` ready for `normalize_transcript.py --input-format whisper_diarization --diarization YOUR_FILE.json` so the existing normalize → synchronize → clean_speakers flow works unchanged.

This path is ideal for rerunning old sessions with better ASR backends while keeping diarization quality high.

### Option 3: Raw Audio

If you have an audio recording only, with no diarization, this is your path. This is for, e.g. voice notes from in person sessions and similar. This code will submit the audio recording ElevenLabs scribe-v2, get back a diarized output and a transcript, and then process the diarized transcript, optionally running through a classifier to assign names to diarized segments. 

The key distinction here is that Option 2 assumes you have a high quality diarization with little or no need for extensive cleaning, while option 3 assumes the diarization is messy. 

Both option 2 and option 3 will likely share some audio preprocessing steps, and both will handle splitting audio and merging with correct timestamps. 

*This code does not exist in robust form yet*


1. **Audio preparation**
   - Run `preprocess_audio.py PATH/TO/audio-or-dir` to standardize sources.
   - Profiles:
     - `passthrough` – convert/containerize only.
     - `normalize-only` – light in-memory gain ride to −10 dBFS.
     - `zoom-audio` – band-limit + gentle adaptive loudness/compression (default for Option 2).
     - `voice-memo` – adds RNNoise denoise plus stronger compression (default for Option 3).
   - Outputs 16 kHz mono, 16-bit PCM WAV by default; override with `--output-format`, `--sample-rate`, etc.

2. **`transcribe_with_elevenlabs.py`**
   - Accepts a single WAV file or a file-of-paths list.
   - Automatically chunks any file that exceeds one hour using
     `session_pipeline.audio.chunk_audio_file`, preserving the 16 kHz mono PCM
     format.
   - Uploads each chunk to the ElevenLabs Speech-to-Text API with diarization
     enabled by default and stores the raw JSON response beside the audio.

   **`transcribe_with_whisper.py`** (Option 2 companion)
   - Mirrors the chunking pipeline but targets OpenAI Whisper/GPT models.
   - Writes every per-chunk response immediately and produces a merged `method.whisper.json` so Option 2 sessions drop directly into `normalize_transcript.py`.

3. **`normalize_transcript.py`**
   - Converts raw ElevenLabs JSON, Whisper+diarization JSON, plain-text logs, or WebVTT files into a normalized JSON bundle with segments, word-level detail (when available), speaker hints, and source metadata.
   - Supports offset alignment via `get_audio_offsets.py` outputs so each chunk knows its absolute session start time.

4. **`synchronize_transcripts.py`**
   - Constructs method-specific bundles with session-relative timestamps and emits:
     - `method.whisper.json` (L&A-compatible format with `method`, `duration`, `text`, and a `words` array),
     - `method.diarization.json` (namespaced speaker IDs per chunk),
     - `method.vtt` (speaker: text cues ready for review or speaker cleanup),
     - `method.speakers.json` (summary of all speaker IDs seen in the bundle),
     - `method.speakers.blank.json` (pre-populated roster template with empty canonical names),
     - `method.speakers.csv` (speaker statistics for spreadsheet-friendly review).
    - Pass `--verbose-speakers` if you still need the legacy method/source namespaces inside `speaker_id`.
    - Provide `--speaker-guesses path/to/roster.json` to auto-fill known canonical names inside the blank roster file.
   - Outputs are written under `<session_id>/<method_name>/…`, making it easy to compare different transcription methods side-by-side.

5. **`clean_speakers.py`**
   - (Optional) Runs on a chosen method bundle (typically the best-quality transcript) to apply roster mappings and interactively label speakers, producing a speaker mapping, report, and canonical transcript (speaker lines merge short pauses and show `[HH:MM:SS.pp - …] Speaker: text` ranges).
   - Point it at the session directory plus `--method <name>` (or directly at the method folder) to consume `<method>.vtt`; legacy `*.synced.json` bundles are still supported via `--bundle`.
   - If `<method>.speakers.blank.json` exists, it is automatically used as the roster template (you can still override with `--roster`).

6. **Supporting modules & runners**
   - `preprocess_audio.py` – CLI for applying the shared audio profiles to files or directories.
   - `session_pipeline/audio_processing.py` – profile definitions + ffmpeg/pydub helpers (also used by the `transcribe_with_*` scripts).
   - `session_pipeline/audio.py` – silence-aware chunking helper (always exports
     16 kHz mono PCM WAV and rebalances trailing chunks to avoid tiny leftovers).
   - `get_audio_offsets.py` – compute per-chunk offsets from waveform alignment so normalized bundles can be aligned to the full session timeline.

---

## Libraries

- **`session_pipeline/`** – home for the reusable pipeline primitives that the
  runner scripts import. `audio_processing.py` defines the shared preprocessing
  profiles, `audio.py` and `chunking.py` handle silence-aware segmentation,
  `transcription.py` encapsulates chunk fan-out + result collation, and
  modules such as `io_utils.py`, `offsets.py`, `segments.py`, `time_utils.py`,
  and `runner_utils.py` keep file-system, timestamp, and manifest logic in one
  place.
- **`taelgar_lib/`** – small collection of shared Obsidian helpers. `ObsNote`
  wraps vault Markdown metadata, `TaelgarDate` keeps the in-world calendar
  consistent, and `WikiLinkReplacer` plus friends provide wikilink
  normalization that the vault/export scripts rely on.

---

## Taelgar Corpus

`taelgar_corpus/` stores the frozen indexes that power downstream searches:

- `transcripts_index.json` – manifest of transcript files with IDs, hashes, and
  relative vault paths for deduped lookups.
- `vault_index.json` – lighter-weight index of Obsidian notes that ties
  canonical IDs to their on-disk location.
- `lexicon.json` and `stage0_tokens.tsv` – vocabulary exports that feed the
  LLM- and search-facing tooling.

Run `generate_corpus.py` whenever new transcripts land; it walks the vault,
regenerates the indexes above, and keeps the artifacts in sync with the latest
session outputs.

---

## Obsidian Vault Tools

Scripts used to curate and publish the campaign Obsidian vault.

- **`extract_yaml_fields.py`** – scrape YAML front matter from Markdown notes and
  export selected fields to CSV.
- **`generate_index_page.py`** – build link indexes with templating and
  metadata-aware sorting.
- **`merge_markdown.py`** – merge multiple Markdown files into a single document
  while inlining key metadata.
- **`export_vault.py`** – helper invoked by the build scripts to export the
  vault for publication.
- **`website/build_mkdocs_site.py`** – orchestration script that triggers an
  Obsidian templater export and then builds the MkDocs site.

---

## Miscellaneous Tools

Utility scripts that remain handy for specific workflows.

- **`parse_speakers.py`** – generate per-speaker audio tracks from a WebVTT file
  with labelled cues.
- **`parse_speakers_from_vtt.py`** – crawl directories of VTT files and report
  word counts per speaker.

See `requirements.txt` for Python dependencies. System-level tools such as
FFmpeg are expected to be installed separately when working with audio.

---

## Work Plan

Short-term priorities for the remaining pipeline pieces:

1. **Option 3 – Raw Audio w/ Messy Diarization**
   - Wire up ElevenLabs scribe-v2 / GPT-4o diarization for single-track recordings.
   - Share chunk manifests with Option 2 so both paths feed the same normalize/sync scripts.
   - Build converters that reshape each diarization flavor into the schema `normalize_transcript.py` expects.
   - Deliver an orchestration script (audio prep → diarization/transcription → normalize → synchronize → clean_speakers).

2. **Cleaned Transcript → Scenes → Bullets**
   - Investigate timestamp gap + speaker-change heuristics to split scenes.
   - Define structured prompts that summarize each scene (bullets + tagged NPCs/locations/loot) and persist fully logged outputs for traceability.
   - Allow re-running individual scenes to iterate on glossary/mistake dictionaries.

3. **Bullets → Session Notes**
   - Map bullet summaries into the Obsidian session-note template (synopsis, scene recap, NPCs, hooks, loot, tags).
   - Support alternate starting points (cleaned transcript, player summaries, partial notes) and gap-filling for Cleenseau-style blog posts.
   - Reuse the raw-response logging pattern so we can refine prompts and build a shared `mistakes.json` for future passes.
