---
name: beat-annotator
description: Annotate RPG session beats from a cleaned transcript and finalized `beats.json`, either for the whole session or a specific `beatId`. Use when extracting beat summaries, NPCs, places, items, combats, events, hooks, and timeline facts without changing beat boundaries.
---

# Beat Annotator

Use this skill when working from a cleaned session bundle:

- `session.yaml`
- cleaned transcript (`source.cleaned.md` or equivalent)
- finalized `beats.json`
- optional campaign glossary or dictionary

The goal is to produce structured beat annotations that later synthesis steps can trust.

## Allowed Inputs

Primary evidence:

- `session.yaml`
- the current cleaned transcript
- finalized `beats.json`
- an optional glossary or dictionary explicitly provided for this annotation run

Strictly ignore files in the bundle's `sources/` directory when making annotation decisions.
Those files are archival inputs and may contain stale transcript text or failed earlier attempts.
They are not valid evidence for beat summaries, entities, outcomes, or timeline facts.

Secondary evidence is allowed, but subordinate to the primary evidence above.
This can include:

- prior cleaned transcripts
- earlier session outputs
- relevant notes elsewhere in the vault

Use secondary evidence only to confirm identity or canonical naming.
Do not use it to invent events, outcomes, or facts that are not supported by the current cleaned transcript and beat ranges.

## Modes

The skill supports two modes:

- annotate all beats in a session
- annotate one specific beat by `beatId`

Use the deterministic helper first in either mode so the annotation pass works from exact beat-scoped context instead of manually slicing transcript ranges.

## Rules

- Do not change beat boundaries.
  `beats.json` is already canonical for segmentation.
- Do not repeat more transcript text than needed.
  Reference support with transcript `uid` values.
- Annotate only what is supported by the current beat context.
- Prefer omission or lower confidence over guessing.
- Canonicalize names when the glossary or broader campaign context clearly supports that identity.
- Keep summaries compact.
  Aim for 1 to 3 sentences per beat.
- Treat timeline facts as stricter than summaries.
  If timing or date support is weak, mark the fact as uncertain or omit it.
- If a beat is clearly non-combat, do not force combat fields beyond `isCombat: false`.
- If a beat is combat, capture the main opponents, stakes, and outcome only if the transcript supports them.

## Suggested Output Shape

The canonical annotation artifact should be a JSON object keyed by `beatId` or an ordered list of beat annotations.
Each beat annotation should aim to include:

- `beatId`
- `summary`
- `npcs`
- `locations`
- `items`
- `combat`
- `events`
- `timelineFacts`
- `hooks`
- `openQuestions`

Entity-like entries should include supporting `uid` evidence whenever practical.

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
5. Draft annotations for either:
   - every beat in order, or
   - only the requested `beatId`
6. Keep evidence local to the beat.
   If you need broader context for naming, use it only to confirm names, not to override the beat transcript.
7. Save the draft annotations as JSON.
8. Review for:
   - unsupported claims
   - duplicate entities under multiple spellings
   - timeline facts without transcript support
   - bleed-over from adjacent beats

## Helper Outputs

The helper script writes:

- `<prefix>-beat-contexts.json`
- `<prefix>-beat-context-index.md`
- `contexts/<beatId>.md` for each selected beat

The Markdown context files are for agent review.
The JSON file is for downstream tooling.

## Annotation Guidance

When extracting entities and facts, prioritize:

- named NPCs who act, speak, are discussed as decision-makers, or materially affect the beat
- locations where the beat occurs or clearly transitions to
- items, treasure, documents, clues, or objectives introduced, gained, lost, or pursued
- major decisions, discoveries, setbacks, reveals, departures, arrivals, and combat outcomes
- explicit or strongly implied timeline facts grounded in the transcript and beat dates

Avoid clutter:

- do not list every incidental mention
- do not duplicate the same event as both a summary sentence and multiple redundant event entries
- do not carry entities forward just because they mattered in earlier beats
