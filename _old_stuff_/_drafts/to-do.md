## Ideas for extensions of taelgar-utils

### Generate composite texts

Useful to have a way to generate clean text in markdown format with trimmed/removed metadata for searching, AI, etc.

Would use the export_vault.py function (should wrap this into a class?) to parse notes for each markdown file in a directory, recursively, following config options.

Would then export clean text, possibly with metadata inserts, into a new markdown file, possibly with headers corrected, possibly in a sensible sort order

(perhaps use generate_index_note.md)

Would potentially be useful to abstract generate index note, export vault funtions into a general class/function for building a possibly-ordered dict of notes.

Could then export:
- plain markdown
- embeddings database? might want to do something like load embeddings db, remove chunks that no longer exist, add new chunks, so you don't need to recalculate all embeddings
- context queries for keywords? e.g. could just do a simple keyword search where for each name, search in raw text for name and add that line +/- 1-2 lines to a name.context file

That could then be part of a "summarize thing X" code
Could also be part of a "generate Dalle-3 or midjourney prompt" or even an automatic image generation function, although I think dalle probably easier to use interactively and potentially costly to automatically run? But maybe not. 

Summarize X probably better as part of an ipython notebook for interactive use. Could generate a prompt for chatGPT summarization, a prompt for chatGPT image creation, a prompt for midjourney image creation, and optionally also run the chat and dalle prompts automatically via API. 

Use would be that you have it open while you work, and can just copy/paste as needed.

### Generate metadata from session notes

WIP

Generate:
- party whereabouts line
- NPC whereabouts line
- NPC interaction lines
- what else would be useful?

Based on gpt-4 API calls, so need to optimize the prompt. 

### proper TaelgarDate class

Would need to handle DR, CY dates
Sort function
Convert function
Internal date representation as hours or days or minutes since creation
Possibly handle fuzzy dates, possibly handle parts of days (morning, etc)

Need consistent string representation to parse from yaml, tags, etc

Would need to replace all date functions with TaelgarDates instead of relying on datetime

### add whereabouts to ObsNote

Would probably just need to handle current, home, origin, probably via properties. Don't really ever care about last known, but that might be easy to implement as well. 
Would need to handle died/destroyed dates

