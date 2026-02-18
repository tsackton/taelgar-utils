# taelgar-utils

Utilities for the Taelgar D&D workflow.

The codebase is organized around two primary domains:

1. `session`: audio/VTT/transcript processing.
2. `vault`: markdown/Obsidian export processing.

Supporting domains:
- `audio`: shared audio utilities.
- `markdown`: generic markdown helpers.
- `utilities`: generic one-off utilities (currently Discord export).
- `experimental`: speaker-classifier training/inference pipeline.

## CLI Entrypoints

- `cli/session.py`
  - `preprocess-audio`
  - `transcribe-whisper`
  - `transcribe-elevenlabs`
  - `normalize`
  - `synchronize`
  - `clean-speakers`
  - `process-zoom`
- `cli/vault.py`
  - `export`
- `cli/discord-export.py`
- `cli/markdown-utils.py`
  - `merge`
  - `extract`
  - `make-index`

## Website Tooling

- `website/build_site.py` runs the current strict MkDocs check/export/build/serve/deploy workflow.
- `website/site_builder/` contains the maintained exporter, scanner, link index, nav generator, and validation code.
- `website/website_build_instructions.md` is the canonical website build reference.
- `tests/test_website_build.py` covers the current website export behavior.

## Source Layout

```text
.
├── src/taelgar_utils/
│   ├── session/
│   ├── vault/
│   ├── audio/
│   ├── markdown/
│   ├── utilities/
│   ├── experimental/
│   └── common/
├── cli/
├── configs/
├── docs/
├── examples/
├── website/
├── experimental-artifacts/
└── _old_stuff_/
```

## Configs and Docs

- `configs/core/`
- `configs/experimental/`
- `docs/planning/`
- `examples/manifests/`

## Archived / Legacy

- `_old_stuff_/` contains legacy code and retired artifacts.
- Retired corpus state is archived at `_old_stuff_/taelgar_corpus/`.
- Archived test fixture data is at `_old_stuff_/tests/data/`.
