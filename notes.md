## Code

We want four pipelines - three different starting points for raw data -> standardized raw transcript, and then a flexible set of raw transcript -> session note scripts

### Raw Data -> Raw Transcript

**Zoom VTT -> Raw Transcript**
This is done, involves various vtt handling scripts for input, then the normalize -> synch -> clean speakers pipeline

**Diarized audio -> Raw Transcript**
This is done, involves transcribe with whisper, then the normalize -> synch -> clean speakers pipline
Could potentially use some tweaks to the normalize script to handle slight discrepancies in the diarization / boundry issues

**Raw audio -> Raw Transcript**
This is in progress; the basic pieces are there but it needs a better way to assign speaker_num to a person based on voiceprints to improve diarization results

There are a few possible overall tweaks to the code base:
- There is almost never a reason to run just one of the normalize -> synch -> clean pipeline; it might make sense to combine those into a single script rather than needing a runner. If the merging pieces part is handled by the input scripts (process zoom; transcribe with whisper; transcribe with elevenlabs) then we can generally just dump into normalize etc. This could clean up the workflow a little. 
- Audio processing now lives in Python via `preprocess_audio.py` and `session_pipeline/audio_processing.py`; extend those helpers instead of shell scripts. 
- Fix audio chunking and other details so that only text is ever written to the sessions output, in case want to manage with git

### Raw Transcript -> Clean Transcript

This involves fixing various errors in the raw transcript, semi-automatically. Some experimentation suggests: 
- fixing mispellings and unknown speakers is pretty hard; cleaning puncuation, sentence structure, and general messiness is pretty easy
- many (recent) zoom transcripts already seem to have a punctuation/cleanup step, and don’t benefit from further general cleanup
- mispellings are probably easier to fix with a dictionary approach, especially to the extent the same misspellings appear to occur in multiple transcripts
- unknown speakers might be easiest to fix with a guided manual process (surface unknown, plus few lines before, few lines after, give a key entry for which known speaker it is, with an option for “delete” and an option for “leave unknown”). 

While the code exists in pieces, still need to operationalize this into a robust pipeline. Probably something like:
- run a preprocess step that extracts proper nouns, but also identifies number of unknown speaker lines, and maybe does a quick llm classification of text quality
- depending on the results, either do llm preprocessing or just go straight to semi-automated manual processing

So ultimately want probably three scripts:
- preprocess_raw_transcript: incorporates current extract proper nouns, plus some other stuff to generate a sense of overall quality; might also be nice to find a way to extract a session glossary from obsidian vault somehow? 
- clean_transcript_llm : the current llm-based transcript cleaner
- clean_transcript_manual : the current non-llm transcript cleaner (just dictionary replace), combined with something to surface unknown speaker lines for replacement
 
### Clean Transcript -> Session Note

This does three steps:
- clean transcript to scenes : split by scene (automatic or manual), then summarize each scene with bullet points; optionally should be able to pass a “previously on” summary from prior session notes
- generate narrative : makes a narrative writeup for each scene; consider also whether this code can produce a short timeline? 
- generate session note: takes a cleaned narrative, timeline, bullet points, and yaml config, and makes a session note. this builds various pieces and arranges them based on a template, while archiving all outputs. should have a “rebuild note from outputs’ option to change template without rerunning llm. should ideally extract combats here too.

None of this is written, really, though some pieces exist in old session note code. 

## Files 

The “sessions” directory will hold all this information in a nice way; maybe consider managing with git? 

Basically, for every session, want a session directory. This should have:
- all the processing for any raw data that exists (see above)
- a session manifest
- all the raw pieces of session notes and a backup of the final md prior to Obsidian import/linking

The session manifest needs:
- real world date
- Taelgar start date, Taelgar end date (or unknown if not placed in time)
- players (can be auto-computed from processing)
- characters (matched to players)
- npc companions (to the extent this is obvious / easy)
- a campaign key
- potentially - speaker stats when available
- potentially - npcs, places, combat, various other things like that
- other stuff that ends up yaml frontmatter in Obsidian

### Progress


Riswynn and Oskar, Addermarch, and Great Library are in the “no recordings” - these are not worth including, and have a variety of session note formats. 

Might consider adding addermarch if I move to writing dense bullet point summaries after each session and then processing with generate_session_note code, but will be missing some older notes (unless “back compute” bullet points from narrative)

Dunmar - almost entirely recorded
Mawar - 3 of 4 episodes recorded
Lab Lost - all three episdoes recorded
Into the Chasm - will all be recorded

What else? What to do with Cleenseau? 


## Session Note Formatting Ideas


generally have three rough styles of session notes. 

- the lowest detail is the Great Library, which is basically a short summary of each session with a timeline, although detail tends to increase in later notes. this is kind of an artifact of not having great notes from early on, but works fine for a simple form of session notes; could probably replicate this roughly from memory and dm notes for Riswynn and Oksar Adventures?
- the middle detail is the kind of Addermarch/Mawar style; this is a per-day summary, organized by date, with some meta information attached. this is a good format and could be cleaned up and extended a little
- the most detail is dunmar frontier, which could also be cleaned up and extended a little

Main thing to consider:
- the info box is great
- opening sentence should be longer and provide a full outline of the session in 2-4 sentences, good for skimming
- the summary bullet points are kind of redundant and probably should be removed
- the timeline is good
- meta information could be extended: roster of characters is very useful; places visited might be useful; plus information about combats, leveling up, and treasure could be good if it can be backfilled easily

One strategy would be to have a combinatorial option:
- AI summarization can generate combats, roster of characters, treasure, places visited, opening sentence, info box
- Narrative style can be full narrative or day-by-day
- Timeline can be auto generated if possible, but will require manual tweaking most likely

That gives you several pieces you can select for a note format. The strategy would be:
- first, generate narrative
- then, feed narrative + any other details, like a yaml file for dates and bullet points if you have them from a transcript, to AI tool to output meta pieces which are built into a session note based on formatting options. 
