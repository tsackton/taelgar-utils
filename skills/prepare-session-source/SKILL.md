---
name: prepare-session-source
description: Prepare a Taelgar session source bundle before the agentic session-note-prep pipeline. Use when the user has a new RPG session recording or transcript and wants to create, verify, and run the `taelgar-utils` `prepare-source` config plus transcript speaker mapping for a campaign bundle under the vault `_sessions` directory.
---

# Prepare Session Source

## Overview

Prepare the maintained step-0 session bundle for the Taelgar session pipeline.
This skill stops before `session-note-prep`; its job is to create or update the source prep YAML and speaker mapping JSON, show them to the user for verification, and then run `python cli/session.py prepare-source` only after explicit approval.

## Required Context

Start by gathering or inferring:

- recording or transcript path, usually under `/Users/tim/Documents/RPGs/sessions/recordings/`
- campaign name as it should appear in `campaign`
- vault output directory, usually `/Users/tim/Library/Mobile Documents/iCloud~md~obsidian/Documents/Taelgar/_sessions/<campaign-slug>`
- session number and real-world date
- in-world `drStart`, `drEnd`, `drStartTime`, and `drEndTime`
- participant roster path
- speaker mapping strategy: existing mapping JSON, new mapping JSON, or `--interactive-speakers`

If the user gives only a recording directory, inspect it read-only to find the likely transcript source.
Prefer `*.transcript.vtt` as `sourcePath` when present.
The `.m4a` recording with the same stem is inferred by `prepare-source` and will become `sourceAudioPath` in the manifest; add `sourceAudioPath` to the config only when inference is not obvious or the user wants an explicit path.

## Discovery

Read existing nearby configs before drafting:

```bash
find /path/to/vault/_sessions/<campaign-slug> -maxdepth 2 -type f \
  \( -name '*source-prep.yaml' -o -name '*speaker-mappings.json' -o -name '*participants.yaml' \)
```

Use the latest prior session as the model for:

- source-prep filename pattern, for example `feywild-ep04-source-prep.yaml`
- speaker-mapping filename pattern, for example `feywild-ep04-speaker-mappings.json`
- participant roster path
- campaign display name
- output directory
- `drStart` and `drEnd` defaults when the session continues directly

Do not invent dates, session numbers, player identities, or in-world dates.
Ask the user to confirm anything that cannot be inferred from the new recording path, filename, existing configs, or prior bundle manifests.

## Draft Files

Create or update two files in the campaign `_sessions` directory:

```text
<campaign-prefix>-epNN-source-prep.yaml
<campaign-prefix>-epNN-speaker-mappings.json
```

The config should use this shape for transcript sessions:

```yaml
sourcePath: /absolute/path/to/GMT..._Recording.transcript.vtt
sourceType: transcript
outputDir: "/absolute/path/to/Taelgar/_sessions/<campaign-slug>"

campaign: Campaign Display Name
sessionNumber: 4
realWorldDate: YYYY-MM-DD
drStart: YYYY-MM-DD
drEnd: YYYY-MM-DD
drStartTime:
drEndTime:

participantsPath: "/absolute/path/to/Taelgar/_sessions/<campaign-slug>/<participants>.yaml"

transcriptFormat: auto
narrativeUnit: sentence
minSpeakerFraction: 0.01
```

For transcript sessions, `prepare-source` requires exactly one of:

- `--speaker-mappings /path/to/<campaign-prefix>-epNN-speaker-mappings.json`
- `--interactive-speakers`

Prefer a mapping JSON when a prior session already has stable speaker labels.
Use this shape:

```json
{
  "DM": ["Transcript Speaker Label"],
  "Character Name": ["Transcript Speaker Label", "Alternate Label"]
}
```

Before finalizing the mapping, inspect the new transcript's speaker labels, for example:

```bash
awk -F: '/^[A-Za-z][^:]{0,80}:/ {print $1}' /path/to/session.transcript.vtt | sort | uniq -c
```

Confirm any unmatched, new, or ambiguous speaker labels with the user.

## Verification Gate

Before running `prepare-source`, print both full artifacts for review:

```text
--- <source-prep.yaml path> ---
<complete YAML>

--- <speaker-mappings.json path> ---
<complete JSON>
```

Then state the exact command that will be run.
Ask the user for explicit confirmation.
Do not run the command until the user confirms.

## Run Command

Run from the `taelgar-utils` repo root:

```bash
cd /Users/tim/RPGs/taelgar-utils
python cli/session.py prepare-source \
  --config "/absolute/path/to/<campaign-prefix>-epNN-source-prep.yaml" \
  --speaker-mappings "/absolute/path/to/<campaign-prefix>-epNN-speaker-mappings.json"
```

Use `--interactive-speakers` instead of `--speaker-mappings` only when the user chose an interactive mapping pass.
Use `--force` only after the user explicitly confirms overwriting an existing bundle or partial output.

## Expected Output

For `campaign: Lost in the Feywild` and `sessionNumber: 4`, `prepare-source` writes:

```text
<outputDir>/lost-in-the-feywild-004/
  sources/
  cleaned/
    lost-in-the-feywild-004-session.yaml
    lost-in-the-feywild-004-source-prepared.md
    lost-in-the-feywild-004-speaker-stats.json
```

After the command finishes, report:

- files written by the command
- any warnings about unknown speakers
- the bundle root to pass to `session-note-prep`
