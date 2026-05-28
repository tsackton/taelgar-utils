# Installation

This repo currently uses `requirements.txt` as the dependency source of truth.
There is no checked-in `pyproject.toml`, `environment.yml`, or `pixi.toml`.

Use Python 3.11 or 3.12 for the full install. The lighter website/test tooling
may work on newer Python versions, but the experimental audio and ML packages
are the most likely to lag behind new Python releases.

Audio commands require `ffmpeg` on `PATH`. On macOS:

```sh
brew install ffmpeg
```

## Option 1: venv

This is the simplest setup and keeps all installed packages inside `.venv/`.

```sh
cd /Users/tim/RPGs/taelgar-utils
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If `python3.12` is not installed, use another supported interpreter:

```sh
python3.11 -m venv .venv
```

Reactivate the environment in later shells with:

```sh
cd /Users/tim/RPGs/taelgar-utils
source .venv/bin/activate
```

## Option 2: mamba

Use this when you want Conda-style environment isolation and a Conda-provided
Python/ffmpeg.

```sh
cd /Users/tim/RPGs/taelgar-utils
mamba create -n taelgar-utils python=3.12 pip ffmpeg
mamba activate taelgar-utils
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If you use `conda` instead of `mamba`, the same commands work with `conda`:

```sh
conda create -n taelgar-utils python=3.12 pip ffmpeg
conda activate taelgar-utils
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Reactivate the environment in later shells with:

```sh
cd /Users/tim/RPGs/taelgar-utils
mamba activate taelgar-utils
```

## Option 3: Pixi

Pixi is project-based. Since this repo does not currently ship Pixi metadata,
these commands create a local Pixi project file and lockfile. Commit them only
if you want Pixi to become part of the repo; otherwise treat them as local setup
files.

```sh
cd /Users/tim/RPGs/taelgar-utils
pixi init .
pixi add python=3.12 pip ffmpeg
pixi run python -m pip install --upgrade pip
pixi run python -m pip install -r requirements.txt
```

Run commands inside the Pixi environment with `pixi run`:

```sh
pixi run pytest
pixi run python cli/session.py --help
pixi run python website/build_site.py --help
```

If you do not want `pixi.toml` and `pixi.lock` in your working tree after a
local experiment, delete them before committing.

## Verify The Install

Run the test suite:

```sh
pytest
```

Check the main CLIs:

```sh
python cli/session.py --help
python cli/markdown-utils.py --help
python cli/vault.py --help
python cli/discord-export.py --help
python website/build_site.py --help
```

When using Pixi, prefix those commands with `pixi run`.

## Environment Variables

Only set these for the integrations you use:

- `OPEN_API_TAELGAR` or `OPENAI_API_KEY`: OpenAI transcription.
- `ELEVEN_LABS_API` or `ELEVENLABS_API_KEY`: ElevenLabs transcription.
- `DISCORD_USER`: DiscordChatExporter token used by `cli/discord-export.py`.
- `PYANNO`, `PYANNOTE_TOKEN`, `HF_TOKEN`, `HUGGINGFACE_TOKEN`, or
  `HUGGINGFACEHUB_API_TOKEN`: Hugging Face token for some experimental
  embedding backends.

## Troubleshooting

If the full install fails on `torch`, `pyannote.audio`, `speechbrain`, or
another ML dependency, first retry with Python 3.11 or 3.12.

If an audio command fails, confirm `ffmpeg` is visible:

```sh
ffmpeg -version
```

If a direct module invocation cannot import `taelgar_utils`, either use one of
the wrappers under `cli/` or set `PYTHONPATH=src`:

```sh
PYTHONPATH=src python -m taelgar_utils.audio.offsets /path/to/audio.m4a
```
