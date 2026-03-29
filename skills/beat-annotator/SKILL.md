---
name: beat-annotator
description: Annotate finalized session beats with only NPCs, locations, and items, writing the results to a separate annotation file rather than editing `beats.json`. Use for either a whole session or one specific `beatId`.
---

# Beat Annotator

Use this skill when working from a cleaned session bundle:

- `session.yaml`
- cleaned transcript (`source.cleaned.md` or equivalent)
- finalized `beats.json`
- optional campaign glossary or dictionary

The goal is to produce a separate beat annotation artifact.
Do not edit `beats.json`.
`beats.json` defines beat boundaries only.

## Allowed Inputs

Primary evidence:

- `session.yaml`
- the current cleaned transcript
- finalized `beats.json`
- an optional glossary or dictionary explicitly provided for this annotation run

Strictly ignore files in the bundle's `sources/` directory when making annotation decisions.
Those files are archival inputs and are not valid evidence for beat annotations.

Secondary evidence is allowed, but subordinate to the primary evidence above.
This can include:

- prior cleaned transcripts
- earlier session outputs
- relevant notes elsewhere in the vault

Use secondary evidence only to confirm canonical naming.
Do not use it to invent entities that are not supported by the current cleaned transcript and beat ranges.

## Scope

This version of the skill annotates only:

- `npcs`
- `locations`
- `items`

Do not add summaries, combat, events, timeline facts, hooks, open questions, or any other annotation categories.

## Modes

The skill supports two modes:

- annotate all beats in a session
- annotate one specific beat by `beatId`

Use the deterministic helper first in either mode so the annotation pass works from exact beat-scoped context instead of manually slicing transcript ranges.

## Rules

- Do not edit `beats.json`.
- Write annotations to a separate JSON file.
- Annotate only what is supported by the current beat context.
- Prefer omission over guessing.
- Canonicalize names when the glossary or broader campaign context clearly supports that identity.
- Do not tag PCs or session participants as NPCs unless the transcript clearly refers to a distinct in-world NPC with the same name.
- Do not list every incidental mention.
  Only include NPCs, locations, and items that are meaningfully present in the beat.
- Keep evidence local to the beat.
  If you need broader context for naming, use it only to confirm names, not to override the beat transcript.

## Canonical Output

The canonical output should be a separate annotation file, for example:

- `<prefix>-beat-annotations.json`

The annotation file should contain an ordered list of beat annotations.
Each entry should have exactly:

- `beatId`
- `npcs`
- `locations`
- `items`

Each entity entry should be compact and include:

- `name`
- optional `confidence`
- optional `evidence`

Suggested shape:

```json
{
  "schemaVersion": "1.0",
  "beatsPath": "/path/to/beats.json",
  "annotations": [
    {
      "beatId": "b01",
      "npcs": [
        {
          "name": "Candrosa",
          "confidence": "high",
          "evidence": ["u0123", "u0131"]
        }
      ],
      "locations": [
        {
          "name": "Raven's Hold",
          "confidence": "medium",
          "evidence": ["u0204"]
        }
      ],
      "items": [
        {
          "name": "Cloak of Rainbows",
          "confidence": "medium",
          "evidence": ["u0278"]
        }
      ]
    }
  ]
}
```

If a beat has none for one category, use an empty list.

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
5. Produce a separate annotation JSON file containing only:
   - `beatId`
   - `npcs`
   - `locations`
   - `items`
6. Review for:
   - unsupported entities
   - duplicate entities under multiple spellings
   - PCs incorrectly tagged as NPCs
   - entities copied in from adjacent beats without support

## Helper Outputs

The helper script writes:

- `<prefix>-beat-contexts.json`
- `<prefix>-beat-context-index.md`
- `contexts/<beatId>.md` for each selected beat

The Markdown context files are for agent review.
The JSON file is for downstream tooling.

## Annotation Guidance

Use these meanings:

- `npcs`: named non-player characters who are present, acting, speaking, or materially discussed in the beat
- `locations`: places where the beat occurs or clearly moves to
- `items`: named objects, treasure, documents, clues, or quest-significant things introduced, discussed, gained, lost, or pursued in the beat

Avoid clutter:

- do not include generic enemies unless they are named or clearly treated as a distinct relevant group
- do not include vague place descriptions unless they identify a meaningful location
- do not include incidental gear unless it matters in the beat
