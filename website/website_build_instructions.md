# Taelgarverse Website Build

The website build now starts from `taelgar-static`, a generated static export of
the main vault. The MkDocs pipeline does not open Obsidian, does not update
submodules, and does not write to the source vault.

## Commands

Run these from the website repository root:

```sh
python taelgar-utils/website/build_site.py check
python taelgar-utils/website/build_site.py export
python taelgar-utils/website/build_site.py build
python taelgar-utils/website/build_site.py serve
python taelgar-utils/website/build_site.py deploy
python taelgar-utils/website/build_site.py publish
```

`autobuild_website.sh` is the website-repo wrapper for composing the
materializer with this CLI.

## Refreshing `taelgar-static`

Before running `export`, `build`, `serve`, or `deploy`, refresh `taelgar-static`
from the Obsidian vault when the source notes or Dataview materialization code
have changed.

The materializer is run from the command line, but the rendering happens inside
Obsidian through the official Obsidian CLI. Obsidian must have the CLI enabled,
and the Taelgar vault must have the `taelgar-dataview-materializer`, Dataview,
and CustomJS plugins enabled.

From the website repository root:

```sh
node "/Users/tim/Library/Mobile Documents/iCloud~md~obsidian/Documents/Taelgar/_scripts/materialize-dataview/materialize-dataview.mjs" \
  --vault "/Users/tim/Library/Mobile Documents/iCloud~md~obsidian/Documents/Taelgar" \
  --out "/Users/tim/RPGs/taelgarverse/taelgar-static" \
  --header-type website \
  --no-strict \
  --timeout 600
```

`--header-type website` regenerates page headers with the website-specific
`OutputHandler.generateWebsiteHeader` output before Dataview blocks are
materialized. Use `--header-type static` for the older static Obsidian callout
header, or `--header-type none` to leave existing headers in place.

`--no-strict` writes the static vault even if a small number of unsupported or
errored DataviewJS blocks remain; those issues are listed in
`taelgar-static/.dataview-materialization-report.json`. Use `--strict` when the
remaining errors should fail the run.

The materializer does not rewrite the source vault. Write mode requires an
output path, rejects in-place materialization, and rejects output paths inside
the source vault.

## Pipeline

1. A separate upstream process generates or refreshes `taelgar-static`.
2. `build_site.py export` reads `website.json`, scans `taelgar-static`, resolves
   links from a single index, and writes MkDocs-ready files into `docs`.
3. Only linked assets, plus configured always-include assets, are copied into
   `docs`. Linked image assets are resized unless they match
   `resize_exclude_assets`; use this for full-resolution maps and other assets
   that must remain untouched.
4. `.website-build/export-manifest.json` tracks generated outputs so later runs
   can skip unchanged notes/assets and remove stale generated files.
5. `build` runs the export first, then calls MkDocs.
6. `serve` runs the export first, checks `mkdocs build`, then starts
   `mkdocs serve`.
7. `publish` runs MkDocs and pushes the current generated site files without
   refreshing `taelgar-static` or exporting `docs`.

## Configuration

`website.json` is strict. Unknown keys are errors. Old names such as `source`,
`build`, `output`, `clean_build`, `clean_build_dir`, `target_date`,
`abs_path_root`, and `hide_tocs_tags` are intentionally unsupported.

All path values are resolved relative to the directory containing
`website.json` unless the option explicitly says it is relative to `docs_dir`.
Optional path values can be omitted, set to `null`, or set to an empty string.

The current canonical example is in `website_config_example.json`.

### Directory And Output Options

| Key | Type | Default | Description |
| --- | --- | --- | --- |
| `source_dir` | path | required | Static source tree to export. For this site this should be `taelgar-static`. The exporter only reads from this directory. |
| `docs_dir` | path | required | MkDocs source directory written by the exporter. For this site this should be `docs`. |
| `overrides_source` | optional path | none | Directory containing website override files to copy before export, normally `taelgar-utils/website/overrides`. |
| `overrides_dir` | optional path | none | Destination for copied override files, normally `overrides`. This is relative to `website.json`, not `docs_dir`. |
| `slugify` | boolean | `true` | Converts exported path components and Markdown stems to URL-safe lowercase slugs. If disabled, source-relative paths are preserved. |
| `clean_docs` | boolean | `false` | Deletes `docs_dir` before export. This forces a full rewrite and bypasses incremental manifest reuse for that run. |
| `manifest_path` | path | `.website-build/export-manifest.json` | Incremental export manifest. It tracks generated files, source signatures, linked assets, and stale output cleanup. |

### Content Filtering And Cleaning

| Key | Type | Default | Description |
| --- | --- | --- | --- |
| `campaigns` | list of strings | `[]` | Campaign IDs to include. Used for `excludePublish` front matter and `%%^Campaign:name%%...%%^End%%` blocks. |
| `export_date` | string or omitted | none | Taelgar date used for date-block filtering and future-dated note exclusion. |
| `strip_comments` | boolean | `true` | Removes Obsidian comments such as `%%comment%%` after campaign/date block handling. |
| `strip_campaign_blocks` | boolean | `true` | Processes `%%^Campaign:name%%...%%^End%%` blocks. Matching campaign blocks are kept; nonmatching campaign blocks are removed. |
| `strip_date_blocks` | boolean | `true` | Processes `%%^Date:...%%...%%^End%%` blocks against `export_date`. `b` blocks are removed on or after the marker date; `a` blocks are removed on or before it. |
| `clean_inline_tags` | boolean | `true` | Rewrites inline Obsidian-style fields such as `(DR:: 1749-03-17)` into readable text. |
| `skip_future_dated` | boolean | `true` | Skips notes whose `activeYear` front matter is later than `export_date`. Has no effect without `export_date`. |
| `unnamed_files` | `skip`, `unlist`, or `include` | `unlist` | Controls notes whose filename or generated title starts with `~`. `skip` omits them; `unlist` exports them but leaves them out of generated nav; `include` treats them normally. |
| `stub_files` | `skip`, `unlist`, or `include` | `skip` | Controls notes with no meaningful body content after cleaning. `skip` omits them; `unlist` exports them but leaves them out of generated nav; `include` treats them normally. |

### Home And Navigation

| Key | Type | Default | Description |
| --- | --- | --- | --- |
| `home_source` | optional path | none | Markdown template/source for the website home page. It is transformed like any other note. |
| `home_dest` | docs-relative path | `index.md` | Destination for `home_source` inside `docs_dir`. Absolute paths are invalid. |
| `nav_source` | optional path | none | Literate-nav template source. Lines containing `{glob:...}` are expanded from exported notes. |
| `nav_dest` | docs-relative path | `toc.md` | Destination for generated navigation inside `docs_dir`. Absolute paths are invalid. |
| `hide_toc_tags` | list of strings | `[]` | If a note has any matching tag segment, the exporter adds front matter that hides the page table of contents. Tag segments are split on `/`. |
| `hide_nav_tags` | list of strings | `[]` | If a note has any matching tag segment, the exporter adds front matter that hides MkDocs navigation for that page. |
| `hide_backlinks_tags` | list of strings | `[]` | If a note has any matching tag segment, the exporter adds front matter that hides backlinks for that page. |

### Website-Only Session Views

Session notes can opt into a website-only zoomable narrative with front matter:

```yaml
websiteSessionView: zoomable
sessionKey: campaign-session-1
```

The Obsidian-facing note remains unchanged. During export, the website builder
uses `session_artifact_roots` to locate the matching reviewed
`session-recap.md`, slices the cleaned transcript by each recap block's Source
Range, writes transcript data under `assets/session-zoom/`, and replaces only
the published `## Narrative` section. The generated scene titles are normal
Markdown headings so MkDocs Material can provide the page table of contents.

### Links, Code Blocks, And Assets

| Key | Type | Default | Description |
| --- | --- | --- | --- |
| `ignore_file` | optional path | none | Ignore spec applied while scanning `source_dir`. Uses `pathspec` gitwildmatch rules when available, with a simpler fnmatch fallback. |
| `base_path` | string | `/` | Absolute URL prefix for rewritten root-relative asset links and generated embedded asset URLs. A trailing slash is added automatically. |
| `clean_code_blocks` | boolean | `true` | Enables code-block template replacement. Mermaid blocks are preserved. Unknown code-block template types are removed. |
| `codeblock_template_dir` | optional path | none | Directory containing `{type}.html` templates for code-block replacement. Leaflet blocks use this to render map embeds and resolve their images. |
| `asset_dir` | docs-relative path | `assets` | Reserved canonical asset directory setting. The current exporter preserves source-relative asset paths instead of remapping everything into this directory. |
| `resize_images` | boolean | `false` | Resizes copied linked image assets when they exceed `max_image_width` or `max_image_height`. Requires Pillow and fails if Pillow is missing. |
| `resize_exclude_assets` | list of glob strings | `[]` | Asset path or filename patterns that must be copied without resizing. Use this for full-size maps and other large source images. |
| `max_image_width` | positive integer | `1600` | Maximum resized image width, preserving aspect ratio. |
| `max_image_height` | positive integer | `1600` | Maximum resized image height, preserving aspect ratio. |
| `delete_unlinked_assets` | boolean | `true` | Accepted by the strict schema. Current asset copying is driven by linked assets, always-include assets, and stale manifest cleanup. |
| `always_include_assets` | list of glob strings | `[]` | Source-relative asset patterns to copy even when no exported page links to them. Patterns use `Path.match`, for example `assets/**/*.png`. |
| `session_artifact_roots` | list of paths | `[]` | Optional `_sessions` roots used by website-only session renderers. Notes with `websiteSessionView: zoomable` use `sessionKey` to find reviewed recap and cleaned transcript artifacts under these roots. |
