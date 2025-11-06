# taelgar-utils

Utilities that support work on the Taelgar campaign vault.  

This reference focuses on the standalone scripts that ship with the repository (excluding the new session-processing pipeline).

## Script Reference

### `extract_yaml_fields.py`
- **Purpose:** Scan Markdown files for YAML front matter and export selected fields to CSV.
- **Usage:**
  ```bash
  python3 extract_yaml_fields.py /path/to/notes output.csv
  ```
- **Inputs:** Directory of `.md` files whose first `---` block contains the desired keys.
- **Outputs:** CSV file with columns `sessionNumber`, `realWorldDate`, `DR`, `DR_end`, `players`. The `players` field is normalised to a comma-separated list.

### `generate_index_page.py`
- **Purpose:** Build a link index for a directory of notes, with optional templating and metadata-aware sorting.
- **Usage:**
  ```bash
  python3 generate_index_page.py notes_dir \
    --link_style wiki \
    --sort_order sessionNumber \
    --tie_breaker title \
    --template "* {link_text} {people_str}"
  ```
- **Key options:**
  - `--link_style`: `relative` (default) or `wiki` style links.
  - `--sort_order`: `title` or any metadata key (numeric handling for `sessionNumber`; date parsing via `TaelgarDate` when possible).
  - `--tie_breaker`: Secondary sort key (`file_name`, `title`, `sessionNumber`, or another metadata field).
  - `--template`: Python `str.format` template with access to note metadata plus helper fields like `people_str` and `event_date_str`.
- **Inputs:** Directory of Markdown notes compatible with `taelgar_lib.ObsNote`.
- **Outputs:** Markdown link lines printed to stdout; redirect to file to create an index page.

### `merge_markdown.py`
- **Purpose:** Flatten multiple Markdown files into a single document while surfacing front-matter fields.
- **Usage:**
  ```bash
  python3 merge_markdown.py --input-dir notes_dir --output-file combined.md
  ```
- **Behaviour:** Strips YAML front matter, re-emits each key/value under the title, removes leading blockquote callouts, and joins files with `---`.
- **Outputs:** Combined Markdown written to the specified file (default `combined.md`).

### `parse_speakers.py`
- **Purpose:** Derive per-speaker audio tracks using a WebVTT transcript annotated with speaker labels.
- **Usage:**
  ```bash
  python3 parse_speakers.py \
    --audio session.mp3 \
    --webvtt session.vtt \
    --output speaker_tracks \
    --chunk 10
  ```
- **Key options:** `--chunk` defines per-file length in minutes; audio is exported as MP3 chunks after aggregating each speaker’s unique speaking segments.
- **Inputs:** Full-session audio file plus WebVTT captions formatted as `Speaker: dialogue`.
- **Outputs:** Directory of `speaker_partN.mp3` files, one series per detected speaker.

### `parse_speakers_from_vtt.py`
- **Purpose:** Walk every subdirectory, tally word counts per speaker from `.vtt` files, and dump a summary JSON report.
- **Usage:** Run in-place, e.g. `python3 parse_speakers_from_vtt.py`.
- **Inputs:** Current directory as root; any `.vtt` encountered is parsed line-by-line.
- **Outputs:** `vtt_speaker_word_counts.json` mapping each directory to its speakers and aggregated word totals.

### `split_clean_audio.py`
- **Purpose:** Normalise a large recording, locate silences, and export manageable audio chunks.
- **Usage:**
  ```bash
  python3 split_clean_audio.py \
    --input session.wav \
    --output_dir chunks \
    --min_silence_len 1200 \
    --silence_thresh -38 \
    --keep_silence 500 \
    --max_length 12 \
    --format mp3 \
    --bitrate 192k
  ```
- **Pipeline:** Normalises level, detects silences via FFmpeg, splits on silent spans, combines into chunks up to `--max_length` minutes, and exports in parallel.
- **Outputs:** Numbered chunk files in the chosen format plus console logging of the workflow.

### `upload_audio_chunks.py`
- **Purpose:** Push a directory of audio chunks to S3 and produce presigned download URLs.
- **Usage:**
  ```bash
  python3 upload_audio_chunks.py \
    --directory chunks \
    --bucket my-session-bucket \
    --output presigned_urls.json \
    --expiration 7200
  ```
- **Inputs:** Local directory path, S3 bucket name, optional expiry for the URLs.
- **Outputs:** JSON mapping filename → presigned URL; progress displayed with a per-file progress bar.

### `website/build_mkdocs_site.py`
- **Purpose:** Automate exporting the Obsidian vault via the Templater plugin and then build the MkDocs site.
- **Behaviour:** Reads `autobuild.json` to locate the vault, desired templater config, and export script (default `export_vault.py`). Backs up the active templater config, launches Obsidian through its URI scheme, waits for the process to close, executes the export script, then restores the original config.
- **Inputs:** Configuration fields in `website/autobuild.json` (`obsidian_template_config`, `obsidian_vault_id`, `obsidian_vault_root`, and optional `export_script` override).
- **Outputs:** Delegates to `export_vault.py` (not documented here per request); leaves the templater configuration restored on completion.

## Library Modules (`taelgar_lib`)

### `ObsNote`
- Parses Obsidian Markdown files: extracts front matter, cleans content, infers metadata (title, stub status, outlinks), and supports campaign/date-based content filtering. Provides helpers such as `title_case`, `strip_comments`, and `count_relevant_lines`.

### `TaelgarDate`
- Normalises Taelgar date strings (`YYYY`, `YYYY-MM`, `YYYY-MM-DD`) to `datetime` objects and formats them back into in-world notation (`Mar 15, 1492 DR`).

### `WikiLinkReplacer`
- Utility class for converting Obsidian-style wiki links to standard Markdown/HTML links, with support for image syntax, aliases, and anchor generation. Designed to work alongside `ObsNote` instances when preparing content for MkDocs.

---

For requirements, see `requirements.txt`. Most audio- and AWS-related scripts expect system dependencies (FFmpeg, boto3 credentials, etc.) to be configured separately.
