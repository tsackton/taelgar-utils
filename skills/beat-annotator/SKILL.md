---
name: beat-annotator
description: Produce `beat-facts.json` from finalized session beats without editing `beats.json`. Use to capture beat-level date-linked facts for summaries, locations, NPCs, items, organizations, and combats, either for a whole session or one specific `beatId`.
---

# Beat Annotator

Use this skill when working from a cleaned session bundle:

- `session.yaml`
- cleaned source (`source.cleaned.md`, `source-cleaned.md`, or equivalent)
- finalized `beats.json`
- optional campaign glossary or dictionary

The goal is to produce a separate `beat-facts.json` artifact.
Do not edit `beats.json`.
`beats.json` defines beat boundaries only.

## Allowed Inputs

Primary evidence:

- `session.yaml`
- the current cleaned source
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
Do not use it to invent facts that are not supported by the current cleaned source and beat ranges.

## Output Scope

This version of the skill produces only `beat-facts.json`.

Each beat fact entry may include:

- `beatId`
- `dateStart`
- optional `dateEnd`
- optional `timeWindow`
- `shortSummary`
- `longSummary`
- `location`
- `npcs`
- `items`
- `organizations`
- `combat`

Do not add events, timeline facts, hooks, or open questions.

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
  "context": "Nura's house, where the party is sheltering",
  "notes": "The party is sheltering here."
}
```

For a journey beat:

```json
{
  "kind": "journey",
  "from": "Melusa (Addermarch)",
  "to": "Raven's Hold (Addermarch)",
  "context": "travel by road through the pass",
  "notes": "The beat covers the departure and overland travel."
}
```

If the location is not explicitly restated in a beat, prefer inheriting the same location as the previous beat unless the source clearly indicates a move or travel transition.
Prefer the larger named place for `primary` on fixed beats, and put the more specific room, corridor, chamber, building, or local sub-area in `context`.
For journey beats between sub-areas of a larger named place, use parenthetical forms in `from` and `to`, for example `warm fissure chamber (Zefya's Labyrinth)`.

If a location is clearly present before it is properly named later in the session, still annotate it in the earlier beat.
When annotating the full session, use the later canonical name for the earlier beat if the identity is clear.
If the identity is still uncertain, use a compact descriptive placeholder in `primary`, `from`, or `to`, and clarify in `notes`.

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

If an NPC is clearly present before they are properly named later in the session, still annotate them in the earlier beat.
When annotating the full session, use the later canonical name for the earlier beat if the identity is clear.
If the identity is still uncertain, use a compact descriptive placeholder name and explain the uncertainty in `notes`.

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

## Summary Model

Each beat should also include two summary fields:

- `shortSummary`
- `longSummary`

`shortSummary` should be one sentence and work as the high-level zoomed-out view of the beat.

`longSummary` should be one short paragraph and work as the medium-detail view of the beat.

For short note-based or other non-transcript sources, prefer a lightly cleaned rendering of the source material where possible.
Stay close to the original event wording, sequence, and emphasis rather than aggressively paraphrasing.
Condense only when the source is repetitive, fragmented, or too awkward to read directly.

The detailed view remains the source itself.

## Combat Model

If the beat is not part of a combat, use:

```json
{
  "isCombat": false
}
```

If the beat is part of a combat, use:

```json
{
  "isCombat": true,
  "phase": "start",
  "mainEnemies": [
    {
      "name": "Blackened Claw raiders",
      "notes": "Primary hostile force in the fight."
    }
  ],
  "notes": "The ambush begins as the party reaches the pass."
}
```

Use one combat phase from:

- `start`
- `middle`
- `end`
- `full`

Use `full` when the entire combat is contained within one beat.
`mainEnemies` does not need a `role`; hostility is already implied by the field name.

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
      "shortSummary": "The party reaches Nura's house and takes shelter for the night.",
      "longSummary": "The party arrives in Melusa and is taken in by Nura, Kalima's sister. The beat centers on reaching safety, orienting themselves in town, and settling into temporary shelter.",
      "location": {
        "kind": "fixed",
        "primary": "Melusa",
        "context": "Nura's house, where the party takes shelter",
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
      "organizations": [],
      "combat": {
        "isCombat": false
      }
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
- Do not tag PCs or session participants as NPCs unless the source clearly refers to a distinct in-world NPC with the same name.
- Keep `shortSummary` to one sentence.
- Keep `longSummary` to one short paragraph.
- For short note-based or other non-transcript sources, `longSummary` should preserve as much of the cleaned source phrasing and event order as possible.
  Do not flatten a multi-step note into a generic one-sentence paraphrase just because the beat is short.
- Do not list every incidental mention.
  Only include NPCs, locations, items, and organizations that matter to understanding the beat.
- Keep facts local to the beat.
  Use broader context only to confirm names or to inherit the prior beat's location when the source supports continuity.
- Do not skip an NPC or location just because the transcript has not named it yet.
  If later beats make the identity clear, back-apply the canonical name to earlier beats in the same session.
  If later beats do not make the identity clear, keep a compact descriptive placeholder and explain it briefly in `notes`.

## Workflow

1. Read `session.yaml`, the cleaned source, and finalized `beats.json`.
2. If a glossary or dictionary is provided, load it once before annotating any beat.
3. Run the helper script to extract beat context from the cleaned source.

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
6. Run the validator to generate the canonical JSON and review preview:

```bash
python skills/beat-annotator/scripts/manage_beat_facts.py \
  --session /path/to/session.yaml \
  --beats-json /path/to/beats.json \
  --beat-facts-json /path/to/beat-facts.json \
  --output-dir /path/to/annotation-artifacts \
  --file-prefix addermarch-campaign-007
```

7. Review for:
   - unsupported NPCs or locations
   - PCs incorrectly tagged as NPCs
   - locations that should have been inherited from the prior beat
   - journey beats mislabeled as fixed beats
   - items or organizations that are too incidental to matter
   - combat phases that do not match the source flow
   - summaries that are either too vague or too detailed

## Helper Outputs

The helper script writes:

- `<prefix>-beat-contexts.json`
- `<prefix>-beat-context-index.md`
- `contexts/<beatId>.md` for each selected beat

The Markdown context files are for agent review.
The JSON file is for downstream tooling.

## Annotation Guidance

Use these meanings:

- `shortSummary`: one-sentence high-level summary of the beat
- `longSummary`: short-paragraph medium-detail summary of the beat
- `location`: where the beat happens, or the route it covers if it is a travel beat; prefer the larger named place in `primary`, and use `context` or parenthetical `from` / `to` values for more specific sublocations
- `npcs`: named non-player characters who materially matter in the beat
- `items`: named objects, documents, clues, treasures, or quest-significant things that matter in the beat
- `organizations`: named factions, groups, tribes, cults, units, or institutions that matter in the beat
- `combat`: whether the beat contains combat, which phase it represents, and the main enemies involved

For deferred naming:

- annotate NPCs and locations even when they are only described at first
- when a later beat clearly reveals the name of the same NPC or location, use that canonical name in earlier beats too
- when the identity is still uncertain, use a short descriptive placeholder rather than omitting the entity

Avoid clutter:

- do not write ornate summaries or session-note prose
- for short note-based inputs, prefer lightly cleaned source phrasing over generic recap language
- condense only when the source is repetitive, duplicative, or too fragmented to read clearly
- do not include vague place descriptions unless they identify a meaningful location
- do not include generic enemies unless they are named or treated as a distinct meaningful group
- do not include incidental gear unless it matters in the beat
- do not include organizations that are only casually referenced without affecting the beat

For item and organization roles:

- use `encountered` when the beat involves direct contact, active interaction, possession, travel through, confrontation with, or immediate presence
- use `mentioned` when the thing is discussed, recalled, referenced, or planned around but not directly encountered in the beat
