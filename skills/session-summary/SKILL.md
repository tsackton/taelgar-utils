---
name: session-summary
description: Build a structured machine-parseable `session-recap.md` from `session-summary-context.json`. Use when turning `beats.json` and `beat-facts.json` into a human-reviewable session recap that can later drive deterministic note generation.
---

# Session Summary

Use this skill when working from a cleaned session bundle with finalized:

- `session.yaml`
- `beats.json`
- `beat-facts.json`

The goal is to produce a structured markdown review artifact, not an intermediate summary JSON.

This skill has three stages:

1. deterministic context building
2. constrained LLM drafting of `session-recap.md`
3. deterministic markdown validation

## Stage 1: Build Context

Generate the canonical input artifact:

```bash
python skills/session-summary/scripts/build_session_summary_context.py \
  --session /path/to/session.yaml \
  --beats-json /path/to/beats.json \
  --beat-facts-json /path/to/beat-facts.json \
  --output-dir /path/to/session-summary-artifacts \
  --file-prefix addermarch-campaign-007
```

This writes:

- `<prefix>-session-summary-context.json`

The context artifact is the source of truth for:

- timeline block boundaries
- recap block boundaries, including adjacent combat collapse
- encountered vs mentioned world candidates
- recap extras candidates

## Stage 2: Draft `session-recap.md`

Generate the structured markdown scaffold:

```bash
python skills/session-summary/scripts/build_session_recap.py \
  --context-json /path/to/session-summary-context.json \
  --output-dir /path/to/session-summary-artifacts \
  --file-prefix addermarch-campaign-007
```

This writes:

- `<prefix>-session-recap.md`

Then fill in the prose fields in that markdown file.
Do not add YAML front matter.
The markdown sections and bullets are the machine-parseable structure.

Rules:

- Keep the markdown shape intact.
- Do not change block IDs, beat IDs, transcript ranges, refs, dates, or world facts.
- Do an actual cleanup and synthesis pass.
  Do not copy beat-fact short or long summaries verbatim into the final recap.
  Rewrite for clarity, coherence, and compression.
- Timeline entries should be highly compact.
  Write them as plain in-world event-log entries, not as session commentary.
  Keep them blunt, matter-of-fact, and minimally descriptive.
  Avoid meta language like `session`, `beat`, `this beat`, `this block`, `recap`, or `transcript`.
  Timeline headings should use human-readable date display like `Jan 25th, 1730 (afternoon)`.
  Keep the `Timeline Segment` and `Timeline Key` bullets intact.
  The `Short` form must be exactly one short sentence that captures only the single most important development in the segment.
  Keep it to the absolute minimum text needed to state the central point clearly.
  The `Long` form may use one or two short sentences, but it should still stay extremely tight.
  The `Short` form is the central point only.
  The `Long` form may add only the most necessary secondary detail needed to cover the segment.
  Do not pad either form with setup, transition language, mood, analysis, or extra explanation.
- Beat-by-beat recap metadata should list only encountered NPCs, locations, organizations, and items.
  Mentioned-only entities belong in the world sections, not in recap block headers.
- Each recap block preserves three zoom levels:
  - `Short`
  - `Intermediate`
  - `Long`
  At each zoom level, the block summaries must read as one continuous recap when joined in block order.
  Each block at a given zoom level must follow directly from the previous block at that same zoom level.
  When reading only the `Short` summaries in order, they should feel like consecutive sentences in one recap.
  The same rule applies independently to the `Intermediate` sequence and the `Long` sequence.
  Do not reset the scene, restate already-established context, or reframe the action as if starting fresh in each block.
  Do not try to make one block's short, intermediate, and long summaries read together with each other.
  Write each block as the immediate continuation of the prior block at that zoom level, not as a standalone analytical blurb.
  Avoid structural framing like `The opening establishes`, `This combat unfolds`, `The conversation shifts`, or `The final stretch`.
  Prefer direct event/state prose that carries forward the situation from the prior block.
  Use the richer per-beat context in `sourceEntries` when present, not just the flattened source summaries.
  Preserve the concrete causal chain of the scene when the transcript supports it.
  If the source includes distinctive specifics that are central to understanding the scene, prefer those over abstract labels.
  For example, prefer `Gaudin's disguise, Loria's telepathic translation, Folcan's toxic blast, and Loria's panic fog cloud`
  over vague phrasing like `the bluff fails and a skirmish starts`.
  In transcript-driven sessions, `Long` recap prose may read like a compact scene narrative paragraph as long as it remains tight, factual, and clearly continuous with adjacent recap blocks.
- Adjacent combat beats already come in as one recap block.
  Summarize them once, not per beat.
- Combat recap blocks must name the enemies involved.
- World sections are deterministic and compact.
  Each world entry should stay terse but include a short context line that can support later cast / places summaries.
  Encountered entries should render as a compact heading line plus dated history lines.
  Mentioned-only entries should stay single-line unless more structure is required later.
  Do not add whereabouts objects or expand the world facts.
  In `## Locations`, each encountered place must use the structured form:
  place name, `Summary`, `Sublocations`, and `Date Visited`.
  The `Summary` must be a brief overview of the featured place in the session, not a list of rooms or scene fragments.
  Use `Sublocations` to name the specific rooms, approaches, or sub-areas that matter inside that place.
  `Date Visited` should record the date or date span from the session timeline.
  For example, prefer `Perdoli Manor` + `Summary: ruined manor estate used by goblins as a holding site for prisoners`
  and put `prison cell, abandoned smithy, adjoining storage room` under `Sublocations`.
- In `Session Header`:
  - `Desc Title` must be generated by the LLM, not inferred deterministically later.
  - Treat `Desc Title` as a TV-episode-style descriptive title for the session.
  - It should be distinct from `Title` and should not include the campaign/session label or episode number.
  - `Tagline` must start with `in which` and stay under 10 words.
  - `One-Sentence Summary` must be exactly one sentence.
  - Parse PCs from `session.yaml` by taking every participant whose `gameRole` is not `DM`.
  - Add a `DM` line for the participant whose `gameRole` is `DM`.
- In `Combat`:
  - each combat block needs a short combat title in the heading
  - an explicit enemy list
  - one brief `Context / Outcome` line

## Stage 3: Validate `session-recap.md`

Validate the reviewed markdown:

```bash
python skills/session-summary/scripts/manage_session_recap.py \
  --context-json /path/to/session-summary-context.json \
  --session-recap-md /path/to/session-recap.md
```

This checks:

- required section headings
- timeline block coverage/order
- recap block coverage/order
- presence of `Short` / `Intermediate` / `Long` subsections
- required human-filled header fields like title, tagline, and one-sentence summary
- removal of remaining `TODO` placeholders before final validation

## Writing Rules

- Treat the context artifact as fixed structure.
- Do not invent new events, hooks, or lore.
- Compress aggressively in the timeline view.
- Treat timeline `Short` and `Long` fields as strict compression targets, not miniature recaps.
- In recap, polish and condense, but keep the three zoom levels aligned.
- Recap and timeline prose must be rewritten from the beat facts, not merely ported over.
- Preserve recap block segmentation.
  Later short / intermediate / long whole-session views are built by joining the same subsection across blocks in order.
- Keep the markdown shape machine-parseable.
