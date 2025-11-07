# taelgar-utils

Utilities that support the Taelgar campaign vault, with a focus on processing
session audio/transcripts and keeping the Obsidian vault in sync.

---

## Session Processing

These scripts form the current audio → transcript → cleaned output pipeline.

1. **Audio preparation** (outside Python)
   - Recordings are pre-cleaned with `ffmpeg` to 16 kHz mono, 16-bit PCM WAV.
   - Long sessions can optionally be normalised and denoised before entering the
     Python pipeline.
   - Use `process_m4a_sessions.sh` to clean iPhone voice memos specifically. 

2. **`transcribe_with_elevenlabs.py`**
   - Accepts a single WAV file or a file-of-paths list.
   - Automatically chunks any file that exceeds one hour using
     `session_pipeline.audio.chunk_audio_file`, preserving the 16 kHz mono PCM
     format.
   - Uploads each chunk to the ElevenLabs Speech-to-Text API with diarization
     enabled by default and stores the raw JSON response beside the audio.

3. **`normalize_transcript.py`**
   - Converts raw ElevenLabs JSON, Whisper+diarization JSON, plain-text logs, or WebVTT files into a normalized JSON bundle with segments, word-level detail (when available), speaker hints, and source metadata.
   - Supports offset alignment via `get_audio_offsets.py` outputs so each chunk knows its absolute session start time.

4. **`run_transcript_pipeline.py` + `synchronize_transcripts.py`**
   - `run_transcript_pipeline.py` reads a manifest to batch-normalize multiple transcripts and then aggregate them per method (e.g., ElevenLabs split, ElevenLabs merged, Whisper, VTT).
   - `synchronize_transcripts.py` constructs method-specific bundles with session-relative timestamps and emits:
     - `method.whisper.json` (L&A-compatible format with `method`, `duration`, `text`, and a `words` array),
     - `method.diarization.json` (namespaced speaker IDs per chunk),
     - `method.vtt` (speaker: text cues ready for review or speaker cleanup).
   - Outputs are written under `<session_id>/<method_name>/…`, making it easy to compare different transcription methods side-by-side.

5. **`clean_speakers.py`**
   - (Optional) Runs on a chosen method bundle (typically the best-quality transcript) to apply roster mappings and interactively label speakers, producing a speaker mapping, report, and canonical transcript.

6. **Supporting modules & runners**
   - `session_pipeline/audio.py` – silence-aware chunking helper (now defaulting
     to 16 kHz mono PCM WAV output and rebalancing trailing chunks to avoid tiny
     leftovers).
   - `process_m4a_sessions.sh` – shell wrapper for batch transcoding and
     transcription runs.

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
- **`taelgar_lib/`** – shared library containing `ObsNote`, `TaelgarDate`,
  wiki-link conversion utilities, and other helpers consumed by the scripts
  above.

---

## Miscellaneous Tools

Utility scripts that remain handy for specific workflows.

- **`parse_speakers.py`** – generate per-speaker audio tracks from a WebVTT file
  with labelled cues.
- **`parse_speakers_from_vtt.py`** – crawl directories of VTT files and report
  word counts per speaker.
- **`_old_stuff/`** – archival scripts kept for reference; new projects should
  prefer the modern pipeline described above.

See `requirements.txt` for Python dependencies. System-level tools such as
FFmpeg are expected to be installed separately when working with audio.
