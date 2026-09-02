---
name: session-summary
description: Build a structured machine-parseable `session-recap.md` from `session-summary-context.json`. Use when turning `beats.json` and `beat-facts.json` into a human-reviewable session recap that can later drive deterministic note generation.
---

# Session Summary

Use this skill when working from a cleaned session bundle with finalized:

- `session.yaml`
- `beats.json`
- `beat-facts.json`
- an approved `recap-scenes.json` when scene grouping has been reviewed or proposed upstream

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
  --recap-scenes-json /path/to/recap-scenes.json \
  --output-dir /path/to/session-summary-artifacts \
  --file-prefix addermarch-campaign-007
```

This writes:

- `<prefix>-session-summary-context.json`

The context artifact is the source of truth for:

- day-sliced timeline block boundaries
- recap block boundaries from the approved scene map when supplied; otherwise the legacy beat/combat grouping fallback
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

Before drafting, look for one clearly matching, human-written session note in the vault using the campaign identity and session number. Read it in full when it exists. Use it as a secondary guide for voice, emphasis, established naming, and details the human author considered important. The cleaned source, beats, and beat facts remain the evidence authority: do not copy unsupported claims, stale dates, or contradictions from the written note, and do not edit that note as part of this skill.

Rules:

- Keep the markdown shape intact.
- These structural rules constrain the agent-generated draft before initial handoff. After a human edits or accepts the recap, treat that version as authoritative and do not restore generated structure or wording merely because it no longer follows this schema.
- Treat approved scene groups as authoritative recap boundaries. Beats remain the evidence units inside each scene; do not split an approved scene back into beat-sized recap blocks or merge approved scenes during prose drafting.
- Do not change block IDs, beat IDs, transcript ranges, refs, dates, or world facts.
- Do an actual cleanup and synthesis pass.
  Do not copy beat-fact short or long summaries verbatim into the final recap.
  Rewrite for clarity, coherence, and compression.
- Timeline entries should be highly compact.
  The timeline has only one prose resolution: `Short`. Do not add a timeline `Long` subsection.
  Use one calendar date per timeline block by default and treat a multi-day timeline entry as an error to correct, not a useful compression. When a beat crosses an overnight boundary, write a separate entry for each represented day and assign events only to the day on which they occur. In particular, a travel-and-rest day and the following day's arrival belong in separate entries. Use a date range only when the underlying dates are genuinely unresolved and the evidence cannot support any meaningful day-level division; if the context contains an exact multi-day range, rebuild the context so it is day-sliced before drafting.
  Write them as plain in-world event-log entries, not as session commentary.
  Keep them blunt, matter-of-fact, and minimally descriptive.
  Avoid meta language like `session`, `beat`, `this beat`, `this block`, `recap`, or `transcript`.
  Timeline headings should use human-readable date display like `Jan 25th, 1730 (afternoon)`.
  Keep the `Timeline Segment` and `Timeline Key` bullets intact.
  The `Short` form must be exactly one short sentence that captures only the single most important development in the segment.
  Keep it to the absolute minimum text needed to state the central point clearly.
  Do not pad it with setup, transition language, mood, analysis, or extra explanation.
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
- Recap images are optional. Leave the image fields blank when no reviewed asset is available.
  When adding an image, use `Image Role` to choose its layout: `aside` for an NPC portrait or other supporting image, `figure` for an ordinary scene illustration, or `hero` for the session's single strongest wide image.
  Use `Image Size: standard` unless the composition clearly calls for `small` or `large`; `hero` always fills the narrative width.
  Placement normally follows the role, so leave `Image Placement` blank unless an override is useful: asides default to `start`, while figures and heroes default to `end`.
  Asides default to the right. Use `Image Render: left` to switch sides, or an exact numeric width such as `right|280` only as an escape hatch for unusual assets.
  To attach more than one image to the same recap block, keep the first image's existing unnumbered fields and add complete numbered sets such as `Image 2`, `Image 2 Role`, `Image 2 Size`, and the other `Image 2 ...` fields. Number additions contiguously.
  Consecutive `figure` images at the same placement become a gallery automatically. Multiple `aside` images remain separate supporting images.
  Use `Image Caption` for visible caption text and `Image Alt` for a concise visual description when the caption is not adequate alternative text.
- World sections are deterministic and compact.
  Each world entry should stay terse but include a short context line that can support later cast / places summaries.
  Encountered entries should render as a compact heading line plus dated history lines.
  Mentioned-only entries should stay single-line unless more structure is required later.
  Do not add whereabouts objects or expand the world facts.
  In the agent-generated `## Locations`, each encountered place must include its place name, `Summary`, `Sublocations`, and `Date Visited`.
  Use `Sublocations: none` when no specific room, approach, or sub-area materially helps describe the session; do not omit the field before initial validation.
  The `Summary` must be a brief overview of the featured place in the session, not a list of rooms or scene fragments.
  Otherwise, use `Sublocations` to name the specific rooms, approaches, or sub-areas that matter inside that place.
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
  - Preserve the optional human-owned `Arc` and `Table Notes` lines in the scaffold.
  - Leave both as `none` unless the user explicitly supplies their values. Do not infer an arc, level-up, milestone, or other table note from the transcript, beat facts, or an existing written session note.
- In `Combat`:
  - each combat block needs a short combat title in the heading
  - an explicit enemy list
  - one brief `Context / Outcome` line

## Stage 3: Validate the Agent-Generated `session-recap.md`

Validate the agent's completed draft before its initial handoff:

```bash
python skills/session-summary/scripts/manage_session_recap.py \
  --context-json /path/to/session-summary-context.json \
  --session-recap-md /path/to/session-recap.md
```

This checks:

- required section headings
- single-day timeline block coverage/order
- recap block coverage/order
- valid optional image roles, named sizes, placements, and contiguous numbering
- presence of timeline `Short` and recap `Short` / `Intermediate` / `Long` subsections
- required human-filled header fields like title, tagline, and one-sentence summary
- optional human-owned `Arc` and `Table Notes` fields may remain `none`
- removal of remaining `TODO` placeholders before final validation

Do not run this validator after the recap has been handed off and edited by a human unless the user explicitly asks for revalidation. Human edits may intentionally remove required fields, generated subsections, or any other generated structure; that is allowed and is never a validation failure in the downstream note-generation workflow. Never use such an edit as permission to repair, restore, normalize, or rewrite the human-edited recap.

## Writing Rules

- Treat the context artifact as fixed structure.
- Do not invent new events, hooks, or lore.
- Compress aggressively in the timeline view.
- Treat the single timeline `Short` field as a strict compression target, not a miniature recap.
- Prefer separate daily entries overwhelmingly over date ranges. An overnight rest, next-day journey, or next-day arrival is a day boundary even when all of it falls inside one beat.
- Use a clearly matching written session note as a subordinate style and content guide when one exists, while resolving every factual conflict in favor of the current cleaned source and finalized facts.
- In recap, polish and condense, but keep the three zoom levels aligned.
- Recap and timeline prose must be rewritten from the beat facts, not merely ported over.
- Preserve recap block segmentation.
  Later short / intermediate / long whole-session views are built by joining the same subsection across blocks in order.
- Keep the markdown shape machine-parseable.
