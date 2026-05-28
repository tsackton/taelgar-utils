# taelgar-utils

Utilities for the Taelgar RPG workflow.

The repo currently has four maintained surfaces:

1. Session tooling for source preparation, audio transcription, beat artifacts,
   and recap generation.
2. Website tooling for exporting `taelgar-static` into the Taelgarverse MkDocs
   site.
3. Small markdown and Discord export utilities.
4. Experimental speaker-classifier tooling.

## Start Here

- [Running everything](docs/running.md): setup, requirements, CLI commands, and
  end-to-end workflows.
- [Session pipeline overview](docs/session-pipeline-overview.md): current
  artifact design and stage status.
- [Website build instructions](website/website_build_instructions.md): detailed
  Taelgarverse website export/build configuration.

## Install

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Audio commands also require `ffmpeg` on `PATH`.

## Common Commands

```sh
pytest
python cli/session.py --help
python cli/markdown-utils.py --help
python cli/vault.py --help
python cli/discord-export.py --help
python website/build_site.py --help
```

## Source Layout

```text
.
├── _templates/json/      # JSON schemas for current session artifacts
├── cli/                  # stable command wrappers that set PYTHONPATH=src
├── docs/                 # repo documentation
├── examples/             # editable config templates
├── experimental-artifacts/
├── notebooks/            # exploratory analysis notebooks
├── skills/               # Codex skills and deterministic helper scripts
├── src/taelgar_utils/    # Python package code
├── tests/                # regression tests
└── website/              # Taelgarverse MkDocs export/build tooling
```

## Main Entry Points

- `cli/session.py`: session prep, non-transcript source normalization, audio
  processing, and transcription helpers.
- `cli/markdown-utils.py`: markdown merge, front matter extraction, and index
  generation.
- `cli/vault.py`: compatibility wrapper around the website export/build CLI.
- `cli/discord-export.py`: DiscordChatExporter wrapper plus JSON-to-markdown
  conversion.
- `website/build_site.py`: strict website check/export/build/serve/deploy CLI.
