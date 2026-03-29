---
name: beat-annotator
description: Produce `beat-facts.json` from finalized session beats without editing `beats.json`. Use to capture beat-level date-linked facts for locations, NPCs, items, and organizations, either for a whole session or one specific `beatId`.
---

# Beat Annotator

Use this skill when working from a cleaned session bundle:

- `session.yaml`
- cleaned transcript (`source.cleaned.md` or equivalent)
- finalized `beats.json`
- optional campaign glossary or dictionary

The goal is to produce a separate `beat-facts.json` artifact.
Do not edit `beats.json`.
`beats.json` defines beat boundaries only.

## Allowed Inputs

Primary evidence:

- `session.yaml`
- the current cleaned transcript
- finalized `beats.json`
- an optional glossary or dictionary explicitly provided for this annotation run

Strictly ignore files in the bundle's `sources/` directory when making annotation decisions.
Those files are archival inputs and are not valid evidence for beat facts.

Secondary evidence is allowed, but subordinate to the primary evidence above.
This can include:

- prior cleaned transcripts
- earlier session outputs
- relevant notes elsewhere in the vault

Use secondary evidence only to confirm canonical naming.
Do not use it to invent facts that are not supported by the current cleaned transcript and beat ranges.

## Output Scope

This version of the skill produces only `beat-facts.json`.

Each beat fact entry may include:

- `beatId`
- `dateStart`
- optional `dateEnd`
- optional `timeWindow`
- `location`
- `npcs`
- `items`
- `organizations`

Do not add summaries, combat, events, timeline facts, hooks, or open questions.

## Location Model

Each beat should have one location object when possible.

Use one of:

- fixed-location beat
- journey beat

For a fixed-location beat:

```json
{
  "kind": "fixed",
  "primary": "Melusa",
  "context": "Nura's house",
  "notes": "The party is sheltering here."
}
```

For a journey beat:

```json
{
  "kind": "journey",
  "from": "Melusa",
  "to": "Raven's Hold",
  "context": "travel by road through the pass",
  "notes": "The beat covers the departure and overland travel."
}
```

If the location is not explicitly restated in a beat, prefer inheriting the same location as the previous beat unless the transcript clearly indicates a move or travel transition.

## NPC Model

Each NPC entry should be compact and use one role label from:

- `companion`
- `enemy`
- `mentioned`
- `encountered`

Each NPC may include:

- `name`
- `role`
- optional `context`
- optional `notes`

Suggested example:

```json
{
  "name": "Nura",
  "role": "encountered",
  "context": "host",
  "notes": "Kalima's sister in Melusa, sheltering the party."
}
```

## Item And Organization Model

Items and organizations should stay minimal.

Each item may include:

- `name`
- optional `role`
- optional `notes`

Each organization may include:

- `name`
- optional `role`
- optional `notes`

For both items and organizations, prefer one role label from:

- `mentioned`
- `encountered`

## Canonical Output

The canonical output should be a separate annotation file, for example:

- `<prefix>-beat-facts.json`

Suggested shape:

```json
{
  "schemaVersion": "1.0",
  "beatsPath": "/path/to/beats.json",
  "facts": [
    {
      "beatId": "b01",
      "dateStart": "1372-05-14",
      "dateEnd": null,
      "timeWindow": "evening",
      "location": {
        "kind": "fixed",
        "primary": "Melusa",
        "context": "Nura's house",
        "notes": "The party takes shelter here."
      },
      "npcs": [
        {
          "name": "Nura",
          "role": "encountered",
          "context": "host",
          "notes": "Kalima's sister in Melusa, sheltering the party."
        }
      ],
      "items": [],
      "organizations": []
    }
  ]
}
```

If a beat has none for one category, use an empty list.
Copy `dateStart`, `dateEnd`, and `timeWindow` directly from `beats.json`.
Do not re-infer them unless the beat definitions themselves are later corrected upstream.

## Modes

The skill supports two modes:

- annotate all beats in a session
- annotate one specific beat by `beatId`

Annotating all beats in order is preferred, because location often carries forward from the previous beat.

If annotating only one beat, check for an existing `beat-facts.json` first so prior beat location can be inherited when appropriate.

## Rules

- Do not edit `beats.json`.
- Write facts to a separate JSON file.
- Annotate only what is supported by the current beat context.
- Prefer omission over guessing.
- Canonicalize names when the glossary or broader campaign context clearly supports that identity.
- Do not tag PCs or session participants as NPCs unless the transcript clearly refers to a distinct in-world NPC with the same name.
- Do not list every incidental mention.
  Only include NPCs, locations, items, and organizations that matter to understanding the beat.
- Keep facts local to the beat.
  Use broader context only to confirm names or to inherit the prior beat's location when the transcript supports continuity.

## Workflow

1. Read `session.yaml`, the cleaned transcript, and finalized `beats.json`.
2. If a glossary or dictionary is provided, load it once before annotating any beat.
3. Run the helper script to extract beat context from the cleaned transcript.

For all beats:

```bash
python skills/beat-annotator/scripts/extract_beat_context.py \
  --transcript /path/to/source.cleaned.md \
  --session /path/to/session.yaml \
  --beats-json /path/to/beats.json \
  --output-dir /path/to/annotation-context \
  --file-prefix addermarch-campaign-007
```

For one beat:

```bash
python skills/beat-annotator/scripts/extract_beat_context.py \
  --transcript /path/to/source.cleaned.md \
  --session /path/to/session.yaml \
  --beats-json /path/to/beats.json \
  --output-dir /path/to/annotation-context \
  --file-prefix addermarch-campaign-007 \
  --beat-id b03
```

4. Use the generated beat context file or files as the primary annotation input.
5. Produce `<prefix>-beat-facts.json` containing only beat-level facts.
6. Review for:
   - unsupported NPCs or locations
   - PCs incorrectly tagged as NPCs
   - locations that should have been inherited from the prior beat
   - journey beats mislabeled as fixed beats
   - items or organizations that are too incidental to matter

## Helper Outputs

The helper script writes:

- `<prefix>-beat-contexts.json`
- `<prefix>-beat-context-index.md`
- `contexts/<beatId>.md` for each selected beat

The Markdown context files are for agent review.
The JSON file is for downstream tooling.

## Annotation Guidance

Use these meanings:

- `location`: where the beat happens, or the route it covers if it is a travel beat
- `npcs`: named non-player characters who materially matter in the beat
- `items`: named objects, documents, clues, treasures, or quest-significant things that matter in the beat
- `organizations`: named factions, groups, tribes, cults, units, or institutions that matter in the beat

Avoid clutter:

- do not include vague place descriptions unless they identify a meaningful location
- do not include generic enemies unless they are named or treated as a distinct meaningful group
- do not include incidental gear unless it matters in the beat
- do not include organizations that are only casually referenced without affecting the beat

For item and organization roles:

- use `encountered` when the beat involves direct contact, active interaction, possession, travel through, confrontation with, or immediate presence
- use `mentioned` when the thing is discussed, recalled, referenced, or planned around but not directly encountered in the beat
