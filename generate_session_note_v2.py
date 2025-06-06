import os
import shutil
import json
import sys
import webvtt
import yaml
import logging
from json import JSONDecodeError
import json
import yaml
from pathlib import Path
from datetime import date
from taelgar_lib.TaelgarDate import TaelgarDate
from dotenv import load_dotenv
from openai import OpenAI
from pydub import AudioSegment
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import re

# Prompts for scene summarization
PLAIN_BULLETS_PROMPT = """
You will receive the raw text of a single scene.
Return a JSON object with two keys:
1. "scene_title": a 3–8 word descriptive title for this scene.
2. "bullet_points": an array of 4–6 concise, precise bullet strings that capture the primary events in this scene. Focus on detail and accuracy. 
No extra keys. No narrative—just title and bullets.
"""

IN_WORLD_NARRATIVE_PROMPT = """
You are a summarizer of D&D session transcripts.
Your job: write a short, self-contained retelling the events of this scene as an in-world narrative,
avoiding any meta-game language (no "DM", "rolls", etc.). Your narrative should be between 100-250 words. 
Focus on key happenings, and character actions, while avoiding flowerly language and carefully following the style guide below.
Style Guide: 
- The narrative style is clear, grounded, and concise, balancing practical descriptions of actions with subtle atmospheric detail. 
- It maintains a strong focus on characters' specific deeds, decisions, and interactions, clearly noting important magical elements or artifacts. 
- Sentences are typically direct, with restrained use of evocative language, ensuring clarity and readability. 
- Combat and exploration scenes are described methodically but briefly, emphasizing key strategies, magical effects, and decisive outcomes. 
- Dialogue and character interactions are succinctly summarized rather than fully quoted. 
- Occasional descriptive flourishes enhance the sense of atmosphere or mood, yet the prose consistently avoids excessive dramatization or overly ornate language.
"""

SESSION_SUMMARY_PROMPT = """
Summarize the D&D session described below. Return a JSON object with the following keys:
1. "title": A short, evocative session title (max 6 words), that would be suitable to use as a chapter title in a book
2. "tagline": 5-10 words that could be used as a subtitle for the text; it should capture the main event of the narrative succinctly and clearly, 
    and ALWAYS start with the words *in which* 
3. "short_summary": Exactly one sentence summarizing the primary gist of the session (for use as a preview).
4. "summary": An array of 4–8 bullet points highlighting the most important events, discoveries, and plot developments.
5. "location": The main in-world location(s) where the session takes place, which can be either one or possibly two major places
     the events happen at or a phrase like on the road between place1 and place2, although you will prefer to choose a single location if possible.
Do not include any extra keys. Be specific and use in-world names and terminology where possible.
"""

# Configure logging
logging.basicConfig(
    filename='session_note.log',
    filemode='a',
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

class SpeakerModel(BaseModel):
    name: str = Field(..., description="The name of the speaker.")
    in_world_character: Optional[str] = Field(None, description="The in-world character name associated with the speaker.")

class TranscriptModel(BaseModel):
    transcript: str = Field(..., description="The cleaned text of the entire transcript.")
    speakers: List[SpeakerModel] = Field(..., description="List of speakers in the transcript.")

class MetadataModel(BaseModel):
    # required metadata
    session_number: int
    campaign: str
    campaign_name: str
    characters: List[str]
    dm: str

    # optional metadata
    world_info_file: Optional[str] = None
    style_guide_file: Optional[str] = None  # Path to a JSON style guide for transcript cleaning

    # either vtt or audio file is required to start processing
    audio_file: Optional[str] = None
    diarization_file: Optional[str] = None
    vtt_file: Optional[str] = None

    # generated metadata
    raw_transcript_file: Optional[str] = None
    cleaned_transcript_file: Optional[str] = None
    scene_file: Optional[str] = None
    scene_segments: Optional[List[str]] = []
    speaker_mapping_file: Optional[str] = None

    # new fields for examples and scene summaries
    example_session_files: Optional[List[str]] = None  # paths to markdown files with example narratives
    scene_summary_files: Optional[List[str]] = None    # paths to generated scene summary JSON files

    # not yet implemented
    summary_file: Optional[str] = None
    timeline_file: Optional[str] = None
    final_note: Optional[str] = None

    # optional metadata for final session note
    session_date: Optional[date] = None
    DR: Optional[str] = None
    DR_end: Optional[str] = None

    # Add additional fields as necessary

    class Config:
        arbitrary_types_allowed = True


# Model for scene summaries
class SceneSummaryModel(BaseModel):
    scene_title: str
    bullet_points: List[str]
    narrative: Optional[str] = None



class SessionNote:
    LOG_DIR = "logs"

    def __init__(self, metadata_file: str):
        self.metadata_file = metadata_file
        self.metadata = self.read_metadata()
        self.status = self.compute_status()
        self.world_info = self.get_world_info()
        if self.metadata.audio_file:
            self.audio_config = self.get_audio_config()
        os.makedirs(self.LOG_DIR, exist_ok=True)
        load_dotenv()
        self.openai_api_key = os.getenv("OPEN_API_TAELGAR")
        logging.info(f"Initialized SessionNote for session {self.metadata.session_number} in campaign {self.metadata.campaign}.")

    ######################
    ## METADATA METHODS ##
    ######################

    def get_audio_config(self) -> Dict[str, Any]:
        return {'audio_file': self.metadata.audio_file,
                'chunk_size_mb': 20,
                'overlap_ms': 1000,
                'output_format': 'mp3',
                'sample_rate': 16000,
                'bitrate': "64k" }

    def get_world_info(self) -> List[str]:
        """
        Extract world-specific information from the metadata.

        :return: List of world-specific terms and names.
        """
        world_info = ["Drankor", "Vindristjarna", "Taelgar", "Chardon", "Dunmar", 
                      "Faldrak", "Riswynn", "Delwath", "Seeker", "Wellby", "Kenzo",
                      "Mos Numena", "Sembara", "Hkar", "Cha'mutte", "Apollyon",
                      "halfling", "halflings", "elf", "elves", "dwarf", "dwarves", "stoneborn", "lizardfolk"]

        if self.metadata.world_info_file and os.path.exists(self.metadata.world_info_file):
            with open(self.metadata.world_info_file, 'r') as f:
                lines = f.readlines()
            world_info.extend(lines)
            logging.info(f"Extracted {len(world_info)} world-specific terms.")

        # remove any duplicates in world info
        world_info = list(set(world_info))

        return world_info

    def read_metadata(self) -> MetadataModel:
        """
        Read metadata from a YAML file.

        :param metadata_file: Path to the metadata YAML file.
        :return: MetadataModel instance containing the metadata.
        """
        metadata_file = self.metadata_file
        try:
            with open(metadata_file, 'r') as f:
                data = yaml.safe_load(f)
            metadata = MetadataModel(**data)
            logging.info(f"Metadata loaded from {metadata_file}.")
            return metadata
        except Exception as e:
            logging.error(f"Failed to read metadata from {metadata_file}: {e}")
            raise

    def write_metadata(self):
        """
        Write metadata to the YAML file.
        """
        try:
            # Convert MetadataModel instance to a dictionary
            metadata_dict = self.metadata.dict()

            # Write dictionary to YAML file
            with open(self.metadata_file, 'w') as f:
                yaml.dump(metadata_dict, f, default_flow_style=False)
            
            logging.info(f"Metadata written to {self.metadata_file}.")
        except Exception as e:
            logging.error(f"Failed to write metadata to {self.metadata_file}: {e}")
            raise


    def compute_status(self) -> Dict[str, str]:
        """
        Compute the status of the session by checking which files exist.

        :return: Dictionary with the computed status.
        """
        status = {
            'audio': None,
            'cleaned': None,
            'scenes': None,
            'summaries': None,
            'final_note': None
        }

        # Audio status
        if self.metadata.raw_transcript_file and os.path.exists(self.metadata.raw_transcript_file):
            status['audio'] = 'processed'
        elif self.metadata.diarization_file and os.path.exists(self.metadata.diarization_file):
            status['audio'] = 'transcribe'
        elif self.metadata.audio_file and os.path.exists(self.metadata.audio_file):
            status['audio'] = 'diarize'
        else:
            status['audio'] = 'missing'

        if self.metadata.vtt_file and os.path.exists(self.metadata.vtt_file) and status['audio'] != 'processed':
            status['audio'] = 'webvtt'

        # Cleaned transcript status
        # requires: raw_transcript_file, cleaned_transcript_file, speaker_character_mapping_file
        if (self.metadata.cleaned_transcript_file and self.metadata.speaker_mapping_file and
            os.path.exists(self.metadata.cleaned_transcript_file) and os.path.exists(self.metadata.speaker_mapping_file)):
            status['cleaned'] = 'processed'
        else:
            status['cleaned'] = 'missing'

        # Scenes status
        scene_files = self.metadata.scene_segments or []
        if scene_files and all(os.path.exists(scene) for scene in scene_files):
            status['scenes'] = 'processed'
        elif self.metadata.scene_file and os.path.exists(self.metadata.scene_file):
            status['scenes'] = 'edited'
        else:
            status['scenes'] = 'missing'

        # Summaries status
        summary_files = self.metadata.scene_summary_files or []
        if summary_files and all(os.path.exists(f) for f in summary_files):
            status['summaries'] = 'processed'
        else:
            status['summaries'] = 'missing'
        

        logging.info(f"Computed status: {status}")
        return status

    ######################
    ## HELPER METHODS ##
    ######################
    def _load_example_narratives(self) -> str:
        """
        Load narrative examples from markdown files listed in metadata.example_session_files.
        Extract the first paragraph under "## Narrative" in each and return as joined examples.
        """
        examples = []
        for path in self.metadata.example_session_files or []:
            if os.path.exists(path):
                md = open(path, 'r').read()
                if "## Narrative" in md:
                    part = md.split("## Narrative", 1)[1]
                    para = part.strip().split("\n\n", 1)[0].strip()
                    examples.append(para)
        return "\n\n".join(f"Example Narrative:\n{e}" for e in examples)

    def call_openai_responses(self, instructions: str, input: str, response_format, temperature: float = 1.0):
        """
        Wrapper for OpenAI Responses endpoint.
        Handles text, JSON mode, or structured JSON schema output.
        """
        # Ensure instructions mention JSON when expecting JSON output
        if response_format == "json" or isinstance(response_format, dict):
            instructions = "Please respond with valid JSON only.\n" + instructions
        client = OpenAI(api_key=self.openai_api_key)
        kwargs = {
            "model": "gpt-4.1-2025-04-14",
            "instructions": instructions,
            "input": input,
            "temperature": temperature,
        }
        if response_format == "json":
            # Structured Outputs for generic JSON object
            kwargs["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "json_output",
                    "schema": {
                        "type": "object",
                        "additionalProperties": True
                    },
                    "strict": True
                }
            }
        elif isinstance(response_format, dict):
            # Structured JSON Schema Mode: wrap raw schema in the required format
            kwargs["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "structured_output",
                    "schema": response_format,
                    "strict": True
                }
            }
        # else: text mode, no extra
        response = client.responses.create(**kwargs)
        raw_output = response.output_text
        if response_format == "json" or isinstance(response_format, dict):
            try:
                data = json.loads(raw_output)
            except JSONDecodeError as e:
                logging.error(f"JSON decode error in call_openai_responses: {e}")
                logging.error(f"Offending output: {repr(raw_output)}")
                raise
            logging.debug(f"Parsed JSON data keys: {list(data.keys())}")
            return data
        else:
            return raw_output

    def summarize_scene(self, scene_path: str) -> SceneSummaryModel:
        """
        Summarize a single scene: get title + bullets and in-world narrative.
        """
        text = open(scene_path, 'r').read()
        # Bullets + title using structured JSON schema
        scene_schema = {
            "type": "object",
            "properties": {
                "scene_title": {"type": "string", "description": "3–8 word descriptive title"},
                "bullet_points": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 4,
                    "maxItems": 6,
                    "description": "4–6 concise bullet strings"
                }
            },
            "required": ["scene_title", "bullet_points"],
            "additionalProperties": False
        }
        bullets_data = self.call_openai_responses(
            instructions=PLAIN_BULLETS_PROMPT,
            input=text,
            response_format={
                "type": "json_schema",
                "name": "scene_summary",
                "schema": scene_schema,
                "strict": True
            }
        )
        logging.debug(f"Scene bullets raw data: {bullets_data}")
        summary = SceneSummaryModel.parse_obj(bullets_data)
        # In-world narrative with examples
        narrative_instr = IN_WORLD_NARRATIVE_PROMPT
        narrative_instr += "\n\n" + self._load_example_narratives()
        narrative_text = self.call_openai_responses(
            instructions=narrative_instr,
            input=text,
            response_format="text"
        ).strip()
        summary.narrative = narrative_text
        return summary

    def generate_session_summary(self, session_text: str, system_prompt: str) -> dict:
        """
        Build a prompt combining metadata context and full merged markdown,
        call the provided OpenAI wrapper, and return the parsed JSON dict.
        """
        ctx = self.metadata.dict().get("context", "")
        prompt = f"Context: {ctx}\n===\n{session_text}"
        logging.debug(f"Generating session summary with prompt (first 500 chars): {repr(prompt[:500])}")
        # Structured JSON schema to enforce valid session summary
        summary_schema = {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "tagline": {"type": "string"},
                "short_summary": {"type": "string"},
                "summary": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 4,
                    "maxItems": 8
                },
                "location": {"type": "string"}
            },
            "required": ["title", "tagline", "short_summary", "summary", "location"],
            "additionalProperties": False
        }
        resp = self.call_openai_responses(
            instructions=system_prompt,
            input=prompt,
            response_format=summary_schema
        )
        logging.debug(f"Session summary response dict keys: {list(resp.keys())}")
        return resp

    def write_session_markdown(self, file_path: Path, resp_data: dict):
        """
        Prepend frontmatter and summary block to the existing markdown file.
        """
        original = file_path.read_text(encoding="utf-8")
        # Extract fields
        title      = resp_data.get("title", "").strip()
        tagline    = resp_data.get("tagline", "").strip()
        desc_title = title
        one_liner  = resp_data.get("short_summary", "").strip()
        bullets    = resp_data.get("summary", [])
        location   = resp_data.get("location", "").strip()

        # Metadata fields
        campaign   = self.metadata.campaign_name
        sess_num   = self.metadata.session_number
        players    = self.metadata.characters or []
        companions = getattr(self.metadata, "companions", []) or []

        # Date fields
        start_date = self.metadata.DR
        end_date = self.metadata.DR_end or start_date

        if start_date and start_date == end_date:
            taelgar_date_string = TaelgarDate.get_dr_date_string(start_date, dr=True)
        elif start_date and end_date:
            taelgar_date_string = (
                f"{TaelgarDate.get_dr_date_string(start_date, dr=True)} "
                f"to {TaelgarDate.get_dr_date_string(end_date, dr=True)}"
            )
        else:
            taelgar_date_string = "Unknown"

        if self.metadata.session_date:
            real_world_date_string = self.metadata.session_date.strftime("%A %b %d, %Y")
            real_world_date_iso = self.metadata.session_date.isoformat()
        else:
            real_world_date_string = "Unknown"
            real_world_date_iso = ""

        # Build frontmatter lines
        header = [
            "---",
            "tags: [session-note]",
            f"name: {campaign} - Session {sess_num}",
            f"campaign: {campaign}",
            f"sessionNumber: {sess_num}",
            f"realWorldDate: {real_world_date_iso}",
            f"DR: {start_date}",
            f"DR_end: {end_date}",
            f"players: [{', '.join(players)}]",
            f"companions: [{', '.join(companions)}]",
            f"tagline: {tagline}",
            f"descTitle: {desc_title}",
            "---",
            f"# {campaign} - Session {sess_num}",
            "",
            f">[!info] {desc_title}: {tagline}",
            f"> *Featuring: {', '.join([f'[[{player}]]' for player in players])}*"
        ]

        if companions:
            header.append(f"> *Companions: {', '.join([f'[[{comp}]]' for comp in companions])}*")
        
        header.append(f"> *In Taelgar: {taelgar_date_string}*")
        header.append(f"> *On Earth: {real_world_date_string}*")
        header.append(f"> *Location: {location}*")

        # Add one-sentence summary and bullets
        header += ["", one_liner, "", "## Session Info", "### Summary"]
        for b in bullets:
            header.append(f"- {b}")
        header.append("")

        file_path.write_text("\n".join(header) + original, encoding="utf-8")

    def merge_summaries_to_markdown(self):
        """
        Merge individual scene summary JSON files into a final Markdown session note.
        """
        session_num = self.metadata.session_number
        output_file = f"Session{session_num}.md"
        lines = []

        # Narrative section
        lines.append("## Narrative\n\n")
        for summary_path in self.metadata.scene_summary_files or []:
            with open(summary_path, 'r') as f:
                data = json.load(f)
            narrative = data.get('narrative', '').strip()
            if narrative:
                lines.append(narrative + "\n\n")

        # Separator
        lines.append("%%\n\n")

        # Detailed Summary
        lines.append("## Detailed Summary\n\n")
        for summary_path in self.metadata.scene_summary_files or []:
            with open(summary_path, 'r') as f:
                data = json.load(f)
            title = data.get('scene_title', 'Untitled Scene')
            bullets = data.get('bullet_points', [])
            lines.append(f"### {title}\n\n")
            for bullet in bullets:
                lines.append(f"- {bullet}\n")
            lines.append("\n")

        lines.append("%%\n")

        # Write to file
        with open(output_file, 'w') as f:
            f.writelines(lines)
        logging.info(f"Final session note merged into {output_file}")

        # Update metadata
        self.metadata.final_note = output_file
        self.write_metadata()

    def generate_final_session_note(self):
        """
        Produce final session note by summarizing the merged scenes markdown
        and prepending frontmatter + summary info.
        """
        merged_path = Path(self.metadata.final_note)
        merged_md   = merged_path.read_text(encoding="utf-8")
        # call the new summary helper
        resp = self.generate_session_summary(merged_md, SESSION_SUMMARY_PROMPT)
        # prepend frontmatter + summary
        self.write_session_markdown(merged_path, resp)

    def convert_to_dict(self, obj: Any) -> Any:
        """
        Recursively convert an object to a dictionary if possible.

        :param obj: The object to convert.
        :return: A JSON-serializable dictionary.
        """
        if isinstance(obj, dict):
            return {k: self.convert_to_dict(v) for k, v in obj.items()}
        elif hasattr(obj, "__dict__"):
            return {k: self.convert_to_dict(v) for k, v in obj.__dict__.items()}
        elif isinstance(obj, list):
            return [self.convert_to_dict(i) for i in obj]
        else:
            return obj

    def time_to_seconds(self, timestamp: str) -> float:
        """
        Convert WebVTT timestamp 'HH:MM:SS.mmm' to seconds.

        :param timestamp: WebVTT timestamp string.
        :return: Time in seconds as a float.
        """
        parts = timestamp.split('.')
        if len(parts) == 2:
            seconds = float(f"0.{parts[1]}")
        else:
            seconds = 0.0

        time_parts = list(map(float, parts[0].split(':')))
        if len(time_parts) == 3:
            hours, minutes, seconds_base = time_parts
        elif len(time_parts) == 2:
            hours = 0.0
            minutes, seconds_base = time_parts
        else:
            raise ValueError(f"Invalid timestamp format: {timestamp}")

        total_seconds = hours * 3600 + minutes * 60 + seconds_base + seconds
        return total_seconds

    ########################
    ## WEBVTT METHODS ##
    ########################

    def parse_webvtt(self) -> List[Dict[str, Any]]:
        """
        Parse a WebVTT file and extract speaker information and text.

        :param vtt_file: Path to the WebVTT file.
        :return: List of parsed segments containing speaker, start time, end time, and text.
        """
        vtt_file = self.metadata.vtt_file

        if not vtt_file or not os.path.exists(vtt_file):
            logging.error(f"WebVTT file {vtt_file} not found.")
            raise FileNotFoundError(f"WebVTT file {vtt_file} not found.")
        
        parsed_segments = []

        for caption in webvtt.read(vtt_file):
            start_time = self.time_to_seconds(caption.start)
            end_time = self.time_to_seconds(caption.end)

            if ':' in caption.text:
                speaker, text = caption.text.split(':', 1)
                speaker = speaker.strip()
                text = text.strip()
            else:
                speaker = "Unknown"
                text = caption.text.strip()

            parsed_segments.append({
                'speaker': speaker,
                'start': start_time,
                'end': end_time,
                'text': text
            })

        logging.info(f"Parsed {len(parsed_segments)} segments from {vtt_file}.")
        return parsed_segments


    def generate_final_transcript_from_vtt(self):
        """
        Parse a WebVTT file and generate a final cleaned transcript.
        """
        try:
            self.generate_transcript_filenames()
            vtt_file = self.metadata.vtt_file
            if not vtt_file or not os.path.exists(vtt_file):
                logging.error(f"WebVTT file {vtt_file} not found.")
                raise FileNotFoundError(f"WebVTT file {vtt_file} not found.")

            parsed_segments = self.parse_webvtt()
            final_transcript = self.concatenate_adjacent_speakers(parsed_segments)
            self.save_transcript_to_file(final_transcript, self.metadata.raw_transcript_file)
            logging.info(f"Final transcript generated from WebVTT and saved to {self.metadata.raw_transcript_file}.")
        except Exception as e:
            logging.error(f"An error occurred while processing WebVTT: {e}")
            raise

    #############################
    ## TRANSCRIPTION METHODS ##
    #############################

    def chunk_audio_file(self) -> List[Dict[str, Any]]:
        """
        Chunk the audio file into pieces of approximately 20 MB with a 1000 ms overlap, and export in a compressed format.
        :return: List of chunk file paths and metadata.
        """

        # set parameters
        audio_file = self.audio_config['audio_file']
        chunk_size_mb = self.audio_config['chunk_size_mb']
        overlap_ms = self.audio_config['overlap_ms']
        output_format = self.audio_config['output_format']
        sample_rate = self.audio_config['sample_rate']
        bitrate = self.audio_config['bitrate']

        chunk_metadata_file = os.path.join(self.LOG_DIR, f"{os.path.basename(audio_file)}_chunks.json")
        if os.path.exists(chunk_metadata_file):
            logging.info(f"Loading existing chunk metadata from {chunk_metadata_file}.")
            with open(chunk_metadata_file, 'r') as f:
                return json.load(f)

        try:
            audio = AudioSegment.from_file(audio_file).set_frame_rate(sample_rate).set_channels(1)
            bytes_per_second = int(bitrate.replace("k", "")) * 1000 / 8
            target_chunk_size_bytes = chunk_size_mb * 1024 * 1024
            chunk_length_ms = int((target_chunk_size_bytes / bytes_per_second) * 1000)

            chunk_dir = "audio_chunks"
            os.makedirs(chunk_dir, exist_ok=True)

            chunks_metadata = []
            for idx, i in enumerate(range(0, len(audio), chunk_length_ms - overlap_ms)):
                chunk = audio[i:i + chunk_length_ms]
                chunk_file = os.path.join(chunk_dir, f"chunk_{idx}.{output_format}")
                chunk.export(chunk_file, format=output_format, bitrate=bitrate)
                chunks_metadata.append({
                    "chunk_file": chunk_file,
                    "start": i / 1000,  # Convert ms to seconds
                    "end": (i + len(chunk)) / 1000  # Adjust for actual chunk length
                })

            with open(chunk_metadata_file, 'w') as f:
                json.dump(chunks_metadata, f, indent=4)
            logging.info(f"Audio file {audio_file} chunked into {len(chunks_metadata)} chunks.")
            return chunks_metadata
        except Exception as e:
            logging.error(f"Failed to chunk audio file {audio_file}: {e}")
            raise

    def transcribe_audio_chunk(self, chunk_metadata) -> Optional[Dict[str, Any]]:
        """
        Transcribe a single audio chunk using the Whisper API.
        :param chunk_metadata: Metadata for the audio chunk.
        :return: Transcription result as a dictionary or None if failed.
        """
        client = OpenAI(api_key=self.openai_api_key)
        transcription_file = os.path.join(self.LOG_DIR, f"{os.path.basename(chunk_metadata['chunk_file'])}_transcription.json")

        prompt = "This is a transcript of a D&D session, with the following terms: "
        prompt_tokens = len(prompt.split()) * 1.33
        max_word_info = (240 - prompt_tokens) * 0.75
        if self.world_info and len(self.world_info) < max_word_info:
            prompt += ", ".join(self.world_info)
        else:
            prompt += ", ".join(self.world_info[:max_word_info])
        
        if os.path.exists(transcription_file):
            logging.info(f"Loading existing transcription for {chunk_metadata['chunk_file']}.")
            with open(transcription_file, 'r') as f:
                return json.load(f)

        try:
            with open(chunk_metadata['chunk_file'], "rb") as audio_file:
                response = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    response_format="verbose_json",
                    timestamp_granularities=["word"],
                    prompt=prompt
                )

            # Adjust timestamps by adding the chunk's start time (offset)
            adjusted_segments = []
            chunk_start_time = chunk_metadata['start']

            # Iterate over each TranscriptionWord object in the response
            for segment in response.words:
                # Create a new dictionary with adjusted timestamps
                adjusted_segment = {
                    "word": segment.word,
                    "start": segment.start + chunk_start_time,
                    "end": segment.end + chunk_start_time
                }
                adjusted_segments.append(adjusted_segment)

            # Replace the words in the response with the adjusted segments
            response_dict = {
                "language": response.language,
                "duration": response.duration,
                "text": response.text,
                "words": adjusted_segments
            }

            # Save the adjusted transcription to a JSON file
            with open(transcription_file, 'w') as f:
                json.dump(response_dict, f, indent=4)
            logging.info(f"Transcribed chunk {chunk_metadata['chunk_file']} and saved to {transcription_file}.")

            return response_dict

        except Exception as e:
            logging.error(f"An error occurred during transcription of {chunk_metadata['chunk_file']}: {e}")
            if os.path.exists(transcription_file):
                os.remove(transcription_file)
            return None

    def combine_transcriptions(self, chunk_transcriptions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Combine transcriptions from multiple chunks into a single transcript.

        :param chunk_transcriptions: List of transcribed chunks.
        :return: Full combined transcript.
        """
        full_transcript = []

        for chunk in chunk_transcriptions:
            if not chunk:
                continue
            for segment in chunk.get('words', []):
                if isinstance(segment, dict) and 'start' in segment and 'end' in segment:
                    full_transcript.append(segment)
                else:
                    logging.warning(f"Invalid segment format: {segment}")

        logging.info(f"Combined transcription contains {len(full_transcript)} segments.")
        return full_transcript

    def sync_transcript_with_diarization(self, transcript: List[Dict[str, Any]], diarization_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Synchronize the transcription with the diarization results using timestamps.

        :param transcript: List of transcribed segments from Whisper.
        :param diarization_results: Diarization results with speaker labels.
        :return: Final transcript with speaker labels.
        """
        synchronized_transcript = []

        for segment in transcript:
            start_time = segment['start']
            end_time = segment['end']

            matching_speakers = [
                diarization for diarization in diarization_results
                if diarization['segment']['start'] <= start_time
                and diarization['segment']['end'] >= end_time
            ]

            if matching_speakers:
                shortest_speaker = min(
                    matching_speakers,
                    key=lambda s: s['segment']['end'] - s['segment']['start']
                )
                speaker = shortest_speaker['speaker']
            else:
                speaker = "Unknown"

            synchronized_transcript.append({
                'speaker': speaker,
                'start': start_time,
                'end': end_time,
                'text': segment.get('word', '')
            })

        logging.info("Synchronized transcript with diarization results.")
        return synchronized_transcript

    def concatenate_adjacent_speakers(self, synchronized_transcript: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        """
        Concatenate adjacent dialogue from the same speaker and remove timestamps.

        :param synchronized_transcript: List of transcript entries with speaker labels.
        :return: Cleaned-up transcript with adjacent speakers concatenated.
        """
        final_transcript = []
        current_speaker = None
        current_text = []

        for entry in synchronized_transcript:
            speaker = entry['speaker']
            text = entry['text']

            if speaker == current_speaker:
                current_text.append(text)
            else:
                if current_speaker is not None:
                    final_transcript.append({
                        'speaker': current_speaker,
                        'text': ' '.join(current_text)
                    })
                current_speaker = speaker
                current_text = [text]

        if current_speaker is not None:
            final_transcript.append({
                'speaker': current_speaker,
                'text': ' '.join(current_text)
            })

        logging.info(f"Concatenated transcript into {len(final_transcript)} speaker segments.")
        return final_transcript

    def save_transcript_to_file(self, transcript: List[Dict[str, str]], output_file: str):
        """
        Save the final synchronized transcript to a text file.

        :param transcript: Final transcript with speaker labels.
        :param output_file: Path to the output file.
        """
        try:
            with open(output_file, 'w') as f:
                for entry in transcript:
                    f.write(f"{entry['speaker']}: {entry['text']}\n")
            logging.info(f"Transcript saved to {output_file}.")
        except Exception as e:
            logging.error(f"Failed to save transcript to {output_file}: {e}")
            raise

    ##############################
    ## DIARIZATION METHODS ##
    ##############################

    def load_diarization_results(self) -> List[Dict[str, Any]]:
        """
        Load diarization results from the metadata.

        :return: Diarization results as a list of dictionaries.
        """
        diarization_file = self.metadata.diarization_file
        if diarization_file and os.path.exists(diarization_file):
            try:
                with open(diarization_file, 'r') as f:
                    diarization_results = json.load(f)
                logging.info(f"Loaded diarization results from {diarization_file}.")
                return diarization_results
            except Exception as e:
                logging.error(f"Failed to load diarization results from {diarization_file}: {e}")
                raise
        else:
            logging.error(f"Diarization file {diarization_file} not found.")
            raise FileNotFoundError(f"Diarization file {diarization_file} not found.")

    ##########################
    ## TRANSCRIPT METHODS ##
    ##########################

    def transcribe_session(self):
        """
        Handle transcription of a session using diarization results and Whisper API.
        """
        try:
            # Generate raw transcript file name
            self.generate_transcript_filenames()

            # Chunk the audio file
            self.audio_chunks_metadata = self.chunk_audio_file()

            # Run Whisper on each chunk
            chunk_transcriptions = []
            for chunk_metadata in self.audio_chunks_metadata:
                transcription = self.transcribe_audio_chunk(chunk_metadata)
                if transcription:
                    chunk_transcriptions.append(transcription)

            # Combine chunks into timestamped transcript
            combined_transcript = self.combine_transcriptions(chunk_transcriptions)

            # Load diarization results
            diarization_results = self.load_diarization_results()

            # Synchronize with diarization results
            raw_transcript = self.sync_transcript_with_diarization(combined_transcript, diarization_results)

            # Concatenate adjacent speakers
            final_transcript = self.concatenate_adjacent_speakers(raw_transcript)

            # Save the final transcript to a file
            self.save_transcript_to_file(final_transcript, self.metadata.raw_transcript_file)
            logging.info(f"Transcription process completed for {self.metadata.raw_transcript_file}.")

        except Exception as e:
            logging.error(f"An error occurred during transcription: {e}")
            raise

    def generate_transcript_filenames(self):
        """
        Generate the raw transcript file name based on metadata.
        """
        session_number = self.metadata.session_number
        campaign_name = self.metadata.campaign
        if not session_number or not campaign_name:
            logging.error("Session number and campaign name are required to generate raw transcript file name.")
            raise ValueError("Session number and campaign name are required to generate raw transcript file name.")
        self.metadata.raw_transcript_file = f"{campaign_name}_session{session_number}_raw_transcript.txt"
        self.metadata.cleaned_transcript_file = f"{campaign_name}_session{session_number}_cleaned_transcript.txt"
        self.metadata.scene_file = f"{campaign_name}_session{session_number}_scenes_marked_transcript.txt"
        logging.info(f"Generated transcript filenames: {self.metadata.raw_transcript_file}, {self.metadata.cleaned_transcript_file}, {self.metadata.scene_file}.")

    #############################
    ## SCENE SPLITTING METHODS ##
    #############################

    def prompt_user_to_edit_file(self):
        """
        Prompt the user to edit the scene file and insert scene breaks.
        """
        scene_file = self.metadata.scene_file
        print(f"Please open {scene_file} and insert scene breaks (`---`) where appropriate.")
        input("Press Enter once you have finished editing the file...")
        logging.info(f"User prompted to edit scene file {scene_file}.")

    def split_on_scene_breaks(self) -> List[str]:
        """
        Read the scene file, split it on scene breaks (`---`), and return the scenes.
        :return: List of scenes.
        """
        scene_file = self.metadata.scene_file

        try:
            with open(scene_file, 'r') as f:
                content = f.read()
            scenes = [scene.strip() for scene in content.split('---') if scene.strip()]
            logging.info(f"Split scene file {scene_file} into {len(scenes)} scenes.")
            return scenes
        except Exception as e:
            logging.error(f"Failed to split scene file {scene_file}: {e}")
            raise

    def write_scenes_to_files(self, scenes: List[str]) -> List[str]:
        """
        Write each scene to its own file in the 'scenes' subdirectory and return the list of scene file paths.

        :param scenes: List of scenes to write.
        :return: List of new scene file paths.
        """
        scene_file = self.metadata.scene_file
        try:
            scene_dir = os.path.join(os.path.dirname(scene_file), "scenes")
            os.makedirs(scene_dir, exist_ok=True)
            base_filename = os.path.splitext(os.path.basename(scene_file))[0]
            scene_files = []

            for i, scene in enumerate(scenes):
                scene_filename = os.path.join(scene_dir, f"{base_filename}_scene_{i + 1}.txt")
                with open(scene_filename, 'w') as f:
                    f.write(scene)
                scene_files.append(scene_filename)

            logging.info(f"Wrote {len(scene_files)} scenes to {scene_dir}.")
            return scene_files
        except Exception as e:
            logging.error(f"Failed to write scenes to files: {e}")
            raise

    def update_metadata_with_scenes(self, scene_file: str, scene_files: List[str]):
        """
        Update the metadata to include the original scene file and the split scene files.

        :param scene_file: Path to the original scene file.
        :param scene_files: List of new scene file paths.
        """
        try:
            self.metadata.scene_file = scene_file
            self.metadata.scene_segments = scene_files
            self.write_metadata()
            logging.info(f"Updated metadata with scene files.")
        except Exception as e:
            logging.error(f"Failed to update metadata with scenes: {e}")
            raise

    def process_transcript_into_scenes(self):
        """
        Copy the raw transcript file to the scene file, prompt the user to edit it, and split it into scenes.
        """

        try:
            if self.status['scenes'] == 'processed':
                logging.info("Scenes have already been processed.")
                return

            cleaned_transcript_file = self.metadata.cleaned_transcript_file
            if not cleaned_transcript_file or not os.path.exists(cleaned_transcript_file):
                logging.error(f"Cleaned transcript file {cleaned_transcript_file} not found.")
                raise FileNotFoundError(f"Cleaned transcript file {cleaned_transcript_file} not found.")

            scene_file = self.metadata.scene_file

            # For edited status, load scenes from metadata or scene breaks
            if self.status['scenes'] == 'edited':
                # metadata.scene_segments holds raw scene texts
                scenes = self.metadata.scene_segments or self.split_on_scene_breaks()

            if self.status['scenes'] == 'missing':
                if os.path.exists(scene_file):
                    logging.info(f"Scene file {scene_file} already exists.")
                else: # Copy cleaned transcript to scene file
                    shutil.copy(cleaned_transcript_file, scene_file)
                    logging.info(f"Copied {cleaned_transcript_file} to {scene_file}.")
                
                self.prompt_user_to_edit_file()
                scenes = self.split_on_scene_breaks()
                self.metadata.scene_segments = scenes
                self.status['scenes'] = 'edited'

            if self.status['scenes'] == 'edited':
                scene_files = self.write_scenes_to_files(scenes)
                logging.info(f"Scenes have been written to individual files: {scene_files}")
                self.update_metadata_with_scenes(scene_file, scene_files)
                self.status['scenes'] = 'processed'

        except Exception as e:
            logging.error(f"An error occurred during scene processing: {e}")
            raise

    ###############################
    ## TRANSCRIPT POST-PROCESSING##
    ###############################

    def generate_transcript_cleaner_prompt(self, speakers: set) -> str:
        """
        Generate a prompt for the OpenAI API to clean the transcript.

        :param speakers: Set of unique speakers in the transcript.
        :return: System prompt for the OpenAI API.
        """

        characters = ", ".join(self.metadata.characters or [])
        world_info = ", ".join(self.world_info or [])
        speakers = ", ".join(speakers)

        if self.metadata.vtt_file:
            # System prompt guiding the transcript cleaner
            prompt = """
            You are an expert transcript cleaner for tabletop roleplaying game sessions. Your goal is to take an automated or messy transcript chunk and return a fully cleaned version, preserving every line of dialogue in order while correcting only actual errors.

            Tasks & Scope
            1. Error Types to Fix:
               - Spelling mistakes (including proper nouns)
               - Filler words (e.g., “um,” “uh,” “like”)
               - Broken punctuation and capitalization
               - Mis-attributed speakers and timestamp artefacts
            2. Structure & Content Preservation:
               - Keep the exact sequence and timing of utterances
               - Do not remove any non-filler content or shorten dialogue
               - Preserve all speaker labels; correct typos only
            3. Style & Terminology Reference:
               - Refer to the JSON style guide file if provided by the metadata
            4. Chunk Context:
               - Chunks may overlap by a few sentences—use that for continuity but clean only this chunk

            Example
            Input:
            “um I think we shoud– ran… . . . Delwth: hey DM can we move on?”
            Output:
            “I think we should run…
            Delwath: Hey DM, can we move on?”

            Output Format:
            Return a JSON object with:
            - "transcript": the full cleaned text
            - "speakers": list of {"name": "...", "in_world_character": "..."} entries

            """
            return prompt

        if self.metadata.audio_file and not self.metadata.vtt_file:
            prompt = """
            You are a transcript cleaner for tabletop roleplaying game sessions, particularly for Dungeons & Dragons. You will receive a transcript that
            was produced with automated transcription software, and may have errors. Your goal is to **maintain the original intent, tone, length, and content** 
            of the transcript while **cleaning up spelling, grammar, readabilit, and especially transcription errors**. 

            You should focus on the following points:
            1. **Do not remove any content** unless it is clearly a filler word (e.g., "um," "uh," "like") or a repeated phrase. Ensure the dialogue flows naturally.
            2. **Do not remove or shorten dialogue** or descriptive content. The cleaned transcript should be **as close in length as the original**, while 
            improving flow, clarity, and readability.

            Follow these STRICT RULES for updating speakers:
            1. **Preserve David Kong, David Schwartz, and Eric Rosenbaum speaker names precisely as they are in the input**. 
            2. The audio transcription software may have trouble distinguishing between Tim Sackton (who is the DM) and Mike Sackton (who plays the character Delwath).
            Please attempt to guess which dialogue lines are DM lines and which are Delwath's lines, and correct assignment errors. You may in this case 
            replace dialogue assignments and labels with the correct speaker. HOWEVER, DO NOT CHANGE OTHER SPEAKER NAMES. Other speakers who are not Tim
            Sackton, Mike Sackton, or Unknown should be preserved.
            3. There are some dialogue lines that are assigned to an unknown speaker. You can assign these lines to the correct speaker** based on the context, 
            if it is obvious who is speaking. If it is not clear, you can leave the speaker as Unknown. Only assign Unkown speakers if you are confident in the prediction.
            
            Correct spelling of in-world characters and locations:
            """
            prompt += world_info + "\n"

            prompt += """

            ### Output Instructions:
            1. **Return the cleaned transcript** that is equal in length to the original. Every speaker's dialogue must be preserved.
            2. **Return a list of speakers found in the transcript**, mapping each speaker to a known character in the game. Note this may be altered by 
            error correction. 
            """
            prompt += "\n**Known Speakers:**" + speakers
            prompt += "\n**Known Characters:**" + characters + ", DM\n"
            prompt += """

            """
            return prompt
    
        # if we get here, we don't have a vtt and we don't have audio. throw an error
        raise ValueError("No audio or VTT file found. Cannot generate transcript cleaner prompt.")


    def extract_unique_speakers(self, transcript_text: str) -> set:
        """
        Extract unique speakers from the transcript by identifying all the text
        before the first colon ':' on each line.

        :param transcript_text: The raw transcript as a string.
        :return: A set of unique speakers found in the transcript.
        """
        speakers = set()
        for line in transcript_text.splitlines():
            if ':' in line:
                speaker = line.split(':', 1)[0].strip()
                speakers.add(speaker)
        logging.info(f"Extracted {len(speakers)} unique speakers from transcript.")
        return speakers

    def get_cleaned_transcript_from_openai(
        self,
        transcript_text: str,
        system_prompt: str,
        PydanticModel: BaseModel
    ) -> Dict[str, Any]:
        """
        Call OpenAI to clean the transcript using the structured output format.

        :param transcript_text: The raw transcript as input.
        :param system_prompt: System prompt to guide the GPT model.
        :param PydanticModel: The Pydantic model for validation.
        :return: Dictionary with cleaned transcript and list of speakers.
        """
        # Prepare instructions by appending style guide if available
        instructions = system_prompt
        if self.metadata.style_guide_file and os.path.exists(self.metadata.style_guide_file):
            with open(self.metadata.style_guide_file, 'r') as sg:
                instructions += "\n\nJSON Style Guide:\n" + sg.read()
        # Define the transcript schema for structured outputs
        transcript_schema = {
            "type": "object",
            "properties": {
                "transcript": {"type": "string"},
                "speakers": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "in_world_character": {"type": ["string", "null"]}
                        },
                        "required": ["name", "in_world_character"],
                        "additionalProperties": False
                    }
                }
            },
            "required": ["transcript", "speakers"],
            "additionalProperties": False
        }
        # Call through helper to enforce structured JSON output
        response_data = self.call_openai_responses(
            instructions=instructions,
            input=transcript_text,
            response_format=transcript_schema
        )
        # Parse into Pydantic model
        parsed = PydanticModel.parse_obj(response_data)
        result = {
            "transcript": parsed.transcript,
            "speakers": parsed.speakers
        }
        logging.info("Cleaned transcript obtained via helper.")
        return result

    def produce_cleaned_transcript(self):
        """
        Clean the transcript for each scene and save the cleaned versions.
        """

        raw_transcript = self.metadata.raw_transcript_file
        aggregated_speaker_character = {}
        cleaned_pieces = []

        # Step 1: Split raw transcript into chunks of around 3000 words
        raw_pieces = self.split_transcript_into_chunks(raw_transcript, word_limit=3000)

        try:
            chunk_count = 1
            for transcript_chunk in raw_pieces:
                logging.info(f"Processing transcript chunk {chunk_count} of {len(raw_pieces)}")

                # Process each chunk
                cleaned_transcript, speakers_list = self.process_transcript_chunk(transcript_chunk, chunk_count)

                # Append cleaned transcript to list
                cleaned_pieces.append(cleaned_transcript)

                # Step 5: Aggregate speaker->character mappings
                self.aggregate_speaker_character_mappings(aggregated_speaker_character, speakers_list)

                chunk_count += 1

            # Step 7: Write aggregated speaker->character mapping to a JSON file
            self.save_speaker_character_mapping(aggregated_speaker_character)

            # Step 8: Write cleaned chunks to a file
            self.write_cleaned_transcript(cleaned_pieces)

            # Step 9: Update metadata
            self.write_metadata()

        except Exception as e:
            logging.error(f"An error occurred while producing cleaned transcripts for scenes: {e}")
            raise


    def split_transcript_into_chunks(self, raw_transcript, word_limit=2000):
        """Split the transcript into chunks of approximately word_limit words."""
        with open(raw_transcript, 'r') as f:
            transcript_text = f.read()
        transcript_pieces = transcript_text.split('\n')
        
        raw_pieces = []
        chunk = ''
        for piece in transcript_pieces:
            if len(chunk.split()) + len(piece.split()) < word_limit:
                chunk += piece + '\n'
            else:
                raw_pieces.append(chunk)
                chunk = piece + '\n'
        
        if chunk:
            raw_pieces.append(chunk)
        
        return raw_pieces


    def process_transcript_chunk(self, transcript_chunk, chunk_count):
        """Process a single transcript chunk and log the response."""
        # Step 2: Identify unique speakers
        speakers = self.extract_unique_speakers(transcript_chunk)
        logging.info(f"Identified speakers in chunk {chunk_count}: {speakers}")

        # Step 3: Generate system prompt
        system_prompt = self.generate_transcript_cleaner_prompt(speakers)
        logging.info(f"Generated system prompt for chunk {chunk_count}")
        logging.debug(f"System prompt for chunk {chunk_count}:\n{system_prompt}")

        # Step 4: Get cleaned transcript and speaker->character mapping from OpenAI
        cleaned_result = self.get_cleaned_transcript_from_openai(
            transcript_text=transcript_chunk,
            system_prompt=system_prompt,
            PydanticModel=TranscriptModel
        )
        
        # Log the cleaned transcript and speakers from OpenAI
        cleaned_transcript = cleaned_result.get('transcript', '')
        speakers_list = cleaned_result.get('speakers', [])
        logging.info(f"Cleaned transcript for chunk {chunk_count}.")
        logging.debug(f"Speaker mapping for chunk {chunk_count}: {speakers_list}")
        
        # Optional: Save cleaned transcript to a temporary file for each chunk (for further analysis if needed)
        cleaned_chunk_path = os.path.join(self.LOG_DIR, f"cleaned_transcript_chunk{chunk_count}.txt")
        with open(cleaned_chunk_path, 'w') as f:
            f.write(cleaned_transcript)
        logging.info(f"Saved cleaned transcript chunk {chunk_count} to {cleaned_chunk_path}")

        return cleaned_transcript, speakers_list


    def aggregate_speaker_character_mappings(self, aggregated_mapping, speakers_list):
        """Aggregate speaker to character mappings."""
        for speaker in speakers_list:
            speaker_name = speaker.name
            character_name = speaker.in_world_character
            if speaker_name in aggregated_mapping:
                if aggregated_mapping[speaker_name] != character_name:
                    logging.warning(
                        f"Speaker '{speaker_name}' has conflicting character mappings: "
                        f"'{aggregated_mapping[speaker_name]}' and '{character_name}'."
                    )
                    continue
            else:
                aggregated_mapping[speaker_name] = character_name


    def save_speaker_character_mapping(self, aggregated_mapping):
        """Save speaker to character mapping to JSON file."""
        mapping_file = os.path.join(self.LOG_DIR, f"speaker_character_mapping_session{self.metadata.session_number}.json")
        self.metadata.speaker_mapping_file = mapping_file
        with open(mapping_file, 'w') as f:
            json.dump(aggregated_mapping, f, indent=4)
        logging.info(f"Speaker to character mapping saved to {mapping_file}")


    def write_cleaned_transcript(self, cleaned_pieces):
        """Write cleaned transcript to file."""
        # strip blank lines
        cleaned_transcript = '\n'.join([line for line in cleaned_pieces if line.strip()])
        cleaned_transcript_file = self.metadata.cleaned_transcript_file
        with open(cleaned_transcript_file, 'w') as f:
            f.write(cleaned_transcript)
        logging.info(f"Cleaned transcript saved to {cleaned_transcript_file}")


    ####################
    ## MAIN EXECUTION ##
    ####################

    def execute(self):
        """
        Execute the processing based on the current status and entry point.
        """
        try:
            if self.status['audio'] == 'missing':
                logging.warning("Audio file is missing.")
                print("Audio file is missing.")
            elif self.status['audio'] == 'diarize':
                logging.info("Need to diarize the audio file with Colab.")
                print("Need to diarize the audio file with Colab.")
            elif self.status['audio'] == 'transcribe':
                logging.info("Transcribing the audio file with Whisper.")
                print("Transcribing the audio file with Whisper.")
                self.transcribe_session()
            elif self.status['audio'] == 'webvtt':
                logging.info("Processing WebVTT file.")
                print("Processing WebVTT file.")
                self.generate_final_transcript_from_vtt()
            else:
                logging.info("Raw transcript already exists.")
                print("Raw transcript already exists.")

            # generate transcript files
            self.generate_transcript_filenames()
            if self.status['cleaned'] == 'missing':
                logging.info("Cleaning the transcript.")
                print("Cleaning the transcript.")
                self.produce_cleaned_transcript()

            if self.status['scenes'] == 'missing' or self.status['scenes'] == 'edited':
                logging.info("Processing transcript into scenes.")
                print("Processing transcript into scenes.")
                self.process_transcript_into_scenes()

            # Summaries step
            if self.status['summaries'] == 'missing' and self.status['scenes'] == 'processed':
                # Summarize each scene automatically
                summaries = []
                for scene_file in self.metadata.scene_segments or []:
                    summ = self.summarize_scene(scene_file)
                    summary_path = scene_file.replace(".txt", ".summary.json")
                    with open(summary_path, 'w') as f:
                        json.dump(summ.dict(), f, indent=2)
                    summaries.append(summary_path)
                self.metadata.scene_summary_files = summaries
                self.write_metadata()
                # Recompute status now that summaries exist
                self.status = self.compute_status()
                logging.info("Summaries completed successfully.")
                print("Summaries updated.")
                # After summaries are updated, merge into final markdown
                self.merge_summaries_to_markdown()
                # after merging scene summaries, generate final summary
                self.generate_final_session_note()
                print(f"Final session note written to {self.metadata.final_note}")

            # Final merge step if summaries already exist but final note not yet created
            if self.status['summaries'] == 'processed':
                self.merge_summaries_to_markdown()
                # after merging scene summaries, generate final summary
                self.generate_final_session_note()
                print(f"Final session note written to {self.metadata.final_note}")
        except Exception as e:
            logging.error(f"An error occurred during execution: {e}")
            print(f"An error occurred: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python session_note.py <metadata_file.yaml>")
        sys.exit(1)

    metadata_file = sys.argv[1]
    session_note = SessionNote(metadata_file)
    session_note.execute()
