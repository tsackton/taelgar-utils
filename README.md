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

If you have an audio recording and a diarization, this option is intended to allow easy processing using OpenAI whisper to transcribe the audio with word-level timestamps, and then map speakers using the diarization. Optionally this might allow transcribing multi-channel audio and then mapping channels to speakers via overlaps with diarizations. This will likely be developed with whisper only, but optionally could be extended to use ElevenLabs scribe-v2 or OpenAI gpt-4o-transcribe or other targets. 

The main use case here is expected to be reprocessing audio with updated transcription backends, e.g. rerunning old Zoom sessions with better transcription, or reprocessing audio from option 3, below, without having to rerun diarization. 

*This code does not exist in robust form yet*

### Option 3: Raw Audio

If you have an audio recording only, with no diarization, this is your path. This is for, e.g. voice notes from in person sessions and similar. This code will submit the audio recording ElevenLabs scribe-v2, get back a diarized output and a transcript, and then process the diarized transcript, optionally running through a classifier to assign names to diarized segments. 

The key distinction here is that Option 2 assumes you have a high quality diarization with little or no need for extensive cleaning, while option 3 assumes the diarization is messy. 

Both option 2 and option 3 will likely share some audio preprocessing steps, and both will handle splitting audio and merging with correct timestamps. 

*This code does not exist in robust form yet*


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
   - `session_pipeline/audio.py` – silence-aware chunking helper (now defaulting
     to 16 kHz mono PCM WAV output and rebalancing trailing chunks to avoid tiny
     leftovers).
   - `get_audio_offsets.py` – compute per-chunk offsets from waveform alignment so normalized bundles can be aligned to the full session timeline.
   - `process_m4a_sessions.sh` – shell wrapper for batch transcoding and
     transcription runs.

---

## Session Note Generation

This will be a pipeline to go from a raw transcript to a final session note. This will be designed to have a variety of flexible inputs and optional processing steps, and should be able to handle:
- Full run: start from raw transcript, clean the transcript, split into scenes, summarize each scene, produce full session note
- Cleaned start: as above, but starting from a cleaned transcript
- Summary start: as above, but starting from a summary of each scene (e.g., from session without audio)
- Gap filling: starting with a session note that has some pieces (e.g., maybe a narrative but nothing else) will fill in missing components per a template (good for, e.g. Cleenseau sessions where the input is a long blog post from a player).

*None of this is written yet*

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
- **`replace_speaker_names.py`** – apply a finalized speaker mapping to a canonical bundle (and optional Whisper/diarization pair) to emit fully named JSON/VTT outputs.
- **`process_zoom_sessions.py`** – batch helper that ingests Zoom transcript folders,
  normalizes them, runs synchronization (optionally seeding speaker guesses with `--speaker-roster`),
  pauses for roster edits, and launches `clean_speakers.py` once each session’s
  `*.speakers.blank.json` is ready.
- **`_old_stuff/`** – archival scripts kept for reference; new projects should
  prefer the modern pipeline described above.

See `requirements.txt` for Python dependencies. System-level tools such as
FFmpeg are expected to be installed separately when working with audio.
