## Code

We want four pipelines - three different starting points for raw data -> standardized raw transcript, and then a flexible set of raw transcript -> session note scripts

### Raw Data -> Raw Transcript

**Zoom VTT -> Raw Transcript**
This is done, involves various vtt handling scripts for input, then the normalize -> synch -> clean speakers pipeline. Possible improvements: consolidate to one script.

**Diarized audio -> Raw Transcript**
This is done, involves transcribe with whisper, then the normalize -> synch -> clean speakers pipline
Possible improvements: some tweaks to the normalize script to handle slight discrepancies in the diarization / boundry issues; extension of transcribe with whisper to work with gpt-4o-transcribe or gemini models.

**Raw audio -> Raw Transcript**
This has a lot still to do. Right now the biggest challenge is diarization. 

(1) Working on a speaker verification model, which hopefully will be reasonably good when trained on actual voice recordings. 
(2) Most likely the best solution here is to just build a pipeline that either does VAD/speaker change detection natively, or uses something like pyannotate locally, assuming that we can clean up locally with our speaker verification model. 
(3) Alternatively, look into some kind of package, https://goodsnooze.gumroad.com/l/macwhisper
https://voicewriter.io/speech-recognition-leaderboard


### Raw Transcript -> Clean Transcript

Lots of experimentation here.

Scene splitting is very hard to do except: (a) manually or chat-assisted via the transcript, or (b) automatically via line or word counts

ChatGPT is great at both correcting puncutation/sentence structure and fixing mispellings. Cleaning up unknown speakers is harder. Likely even better if given a list of known in world terms. This is best with small-ish scenes. 

I have not successfully translated this to API, and am not sure how expensive it would get and whether it is worthwhile. 

From cleaned scenes to bullet points / timeline / narrative, probably an interactive approach with Codex is the fastest. 

Old notes are here but might be superceded:

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

## Into the Chasm Episode 1 Process

Here is the current workflow I used to go from a Zoom VTT to a Session Note:

(1) Run the normalize/synchronize/clean_speakers code to produce a raw transcript with correct speaker names.
(2) Make a copy of the raw transcript, and, guided by ChatGPT in places, add chapter/scene headers (`--- title ---`)
(3) Run split_transcript_by_scene.py to produce raw transcripts for each scene and blank "cleaned" files
(4) Paste each raw transcript into my D&D Transcript Cleaner GPT, copying the results into the cleaned file. After 2-3 scenes it is better to open a new chat as context gets full and performance degrads. 
(5) Copy the empty summary.md file and the cleaned transcript files to _sessions/session-name-number in the Obsidian vault
(6) Use Codex with gpt-5.1-high (but could also try Gemini 3 or Copilot) to process each cleaned transcript file, extract possible ASR errors (tagged with `<original>[replacement|reason]` from D&D Transcript Cleaner GPT), and fix. 
(7) Do a few additional rounds of transcript cleaning with Codex to synchronize names and fix other minor issues. 
(8) Use Codex to generate scene bullet points and a narrative summary in summary.md. 
(9) Manually edit summary.md, adding a timeline and fixing some text in the bullet points and narrative summary
(10) Copy timeline, bullet points, and narrative summary to a session note
(11) Add minimal metadata to header (DR, DR_end, realWorldDate, tags)
(12) Have Codex generate a session manifest from the session note
(13) Have Codex add an info box, cast of characters, important places, combat summary to session note from manifest
(14) Manual polish of codex-generated text

- Manually splitting a transcript by scene does not take long and is tolerable even for processing hundreds of old sessions.
- Copying each section to the D&D Transcript Cleaner GPT, waiting, copying the results back is tedious at best, and likely would need to be automated. If automated, it would probably be better to have it generate a final transcript not an ASR-marked transcript? Here could go back to the idea of generating diffs. 
- If the D&D Transcript Cleaner was automated, then moving the scene-cleaned transcripts to the vault and doing a single codex pass to identify mistakes, or going back to the Taelgar corpus idea and doing automated cleaning, might be useful.
- From a set of cleaned transcripts, the work in Codex to generate a bullet points, 

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
