import os
import shutil
import json
import sys
import webvtt
import yaml 
from dotenv import load_dotenv
from openai import OpenAI
from pydub import AudioSegment
from pydantic import BaseModel, Field
from typing import List, Literal

######################
## HELPER FUNCTIONS ##
######################

def convert_to_dict(obj):
    """
    Recursively convert an object to a dictionary if possible.
    
    :param obj: The object to convert.
    :return: A JSON-serializable dictionary.
    """
    if isinstance(obj, dict):
        # If it's already a dictionary, apply this function to its values
        return {k: convert_to_dict(v) for k, v in obj.items()}
    elif hasattr(obj, "__dict__"):
        # If it's an object with a __dict__ attribute, recursively convert it
        return {k: convert_to_dict(v) for k, v in obj.__dict__.items()}
    elif isinstance(obj, list):
        # If it's a list, apply this function to each element
        return [convert_to_dict(i) for i in obj]
    else:
        # Otherwise, return the object as-is (likely a primitive data type)
        return obj


########################
## METADATA FUNCTIONS ##
########################

# Directory for logs and transcriptions
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

def generate_raw_transcript_filename(metadata):
    """
    Generate the raw transcript file name based on metadata.
    
    :param metadata: Metadata dictionary containing session information.
    :return: Raw transcript file name.
    """
    session_number = metadata.get('session_number', None)
    campaign_name = metadata.get('campaign', None)
    if not session_number or not campaign_name:
        raise ValueError("Session number and campaign name are required to generate raw transcript file name.")
    metadata['raw_transcript_file'] = f"{campaign_name}_session{session_number}_raw_transcript.txt"
    return metadata

def compute_status(metadata):
    """
    Compute the status of the session by checking which files exist.
    
    :param metadata: Dictionary containing session metadata.
    :return: Updated metadata dictionary with the computed status.
    """
    status = {
        'audio': 'not_started',
        'scenes': 'not_started',
        'cleaned': 'not_started',
        'summarized': 'not_started',
        'final_note': 'not_started'
    }

    # Step 1: for transcript processing: missing = no audio; diarize = audio exists, but no diarization; transcribe = audio and diarization exist, but no transcript
    if metadata.get('raw_transcript_file') and os.path.exists(metadata.get('raw_transcript_file')):
        status['audio'] = 'processed'
    elif metadata.get('diarization_file') and os.path.exists(metadata.get('diarization_file')):
        status['audio'] = 'transcribe'
    elif metadata.get('audio_file') and os.path.exists(metadata.get('audio_file')):
        status['audio'] = 'diarize'
    else:
        status['audio'] = 'missing'
    
    if metadata.get('vtt_file') and os.path.exists(metadata.get('vtt_file')):
        status['audio'] = 'webvtt'

    # Step 2: check if scene files exist
    scene_files = metadata.get('scene_segments', [])
    if scene_files and all(os.path.exists(scene) for scene in scene_files):
        status['scenes'] = 'processed'
    elif metadata.get('scene_file') and os.path.exists(metadata.get('scene_file')):
        status['scenes'] = 'edited'
    else:
        status['scenes'] = 'missing'

    # Check if cleaned scene files exist
    cleaned_scene_files = metadata.get('cleaned_scene_files', [])
    if all(os.path.exists(cleaned) for cleaned in cleaned_scene_files):
        status['cleaned'] = 'processed'
    
    # Check if summary and timeline files exist
    if metadata.get('summary_file') and metadata.get('timeline_file') and os.path.exists(metadata.get('summary_file')) and os.path.exists(metadata.get('timeline_file')):
        status['summarized'] = 'processed'
    
    # Check if the final note exists
    if metadata.get('final_note') and os.path.exists(metadata.get('final_note')):
        status['final_note'] = 'processed'
    
    # Add the computed status to the metadata
    return status

def read_metadata(metadata_file):
    """
    Read metadata from a YAML file.
    
    :param metadata_file: Path to the metadata YAML file.
    :return: Dictionary containing the metadata.
    """
    with open(metadata_file, 'r') as f:
        return yaml.safe_load(f)

def write_metadata(metadata, metadata_file):
    """
    Write metadata to a YAML file.
    
    :param metadata: Dictionary containing the metadata.
    :param metadata_file: Path to the metadata YAML file.
    """
    with open(metadata_file, 'w') as f:
        yaml.dump(metadata, f)

######################
## WEBVTT FUNCTIONS ##
######################

def parse_webvtt(vtt_file):
    """
    Parse a WebVTT file and extract speaker information and text.
    
    :param vtt_file: Path to the WebVTT file.
    :return: List of parsed segments containing speaker, start time, end time, and text.
    """
    parsed_segments = []

    for caption in webvtt.read(vtt_file):
        # WebVTT timestamps are in 'HH:MM:SS.mmm' format
        start_time = time_to_seconds(caption.start)
        end_time = time_to_seconds(caption.end)

        # Separate speaker from text (assuming the format 'Speaker: text')
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

    return parsed_segments

def time_to_seconds(timestamp):
    """
    Convert WebVTT timestamp 'HH:MM:SS.mmm' to seconds.
    
    :param timestamp: WebVTT timestamp string.
    :return: Time in seconds as a float.
    """
    # Split on the period to handle milliseconds separately
    parts = timestamp.split('.')
    
    if len(parts) == 2:
        # We have milliseconds
        seconds = float(f"0.{parts[1]}")  # Milliseconds as fractional seconds
    else:
        seconds = 0.0  # No milliseconds part
    
    # Now handle the HH:MM:SS part
    time_parts = list(map(float, parts[0].split(':')))
    
    # Depending on the format, it could have 3 (HH:MM:SS) or 2 (MM:SS) parts
    if len(time_parts) == 3:
        hours, minutes, seconds_base = time_parts
    elif len(time_parts) == 2:
        hours = 0.0
        minutes, seconds_base = time_parts
    else:
        raise ValueError(f"Invalid timestamp format: {timestamp}")
    
    return hours * 3600 + minutes * 60 + seconds_base + seconds


#############################
## TRANSCRIPTION FUNCTIONS ##
#############################

def chunk_audio_file(audio_file, chunk_size_mb=20, overlap_ms=1000, output_format="mp3", sample_rate=16000, bitrate="64k"):
    """
    Chunk the audio file into pieces of approximately 20 MB with a 1000 ms overlap, and export in a compressed format.
    If the chunk metadata already exists, it will skip the chunking process.
    
    :param audio_file: Path to the input audio file.
    :param chunk_size_mb: Desired chunk size in MB.
    :param overlap_ms: Overlap between chunks in milliseconds.
    :param output_format: Desired output format for chunks (e.g., "mp3", "m4a").
    :param sample_rate: Target sample rate for downsampling.
    :param bitrate: Desired bitrate for compression (e.g., "64k" for 64kbps).
    :return: List of chunk file paths and metadata.
    """
    # Check if chunk metadata exists
    chunk_metadata_file = os.path.join(LOG_DIR, f"{os.path.basename(audio_file)}_chunks.json")
    if os.path.exists(chunk_metadata_file):
        print("Loading existing chunk metadata...")
        with open(chunk_metadata_file, 'r') as f:
            return json.load(f)

    # Load the audio file and create chunks
    audio = AudioSegment.from_file(audio_file).set_frame_rate(sample_rate).set_channels(1)

    # Calculate bytes per second for the target bitrate
    bytes_per_second = int(bitrate.replace("k", "")) * 1000 / 8  # Convert kbps to bytes per second
    # Calculate chunk duration based on the desired chunk size
    target_chunk_size_bytes = chunk_size_mb * 1024 * 1024  # 20 MB in bytes
    chunk_length_ms = int((target_chunk_size_bytes / bytes_per_second) * 1000)  # Convert seconds to milliseconds

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

    # Save chunk metadata to log
    with open(chunk_metadata_file, 'w') as f:
        json.dump(chunks_metadata, f, indent=4)
    
    return chunks_metadata


def transcribe_audio_chunk(chunk_metadata, whisper_api_key):   
    # Initialize the OpenAI client
    client = OpenAI(api_key=whisper_api_key)

    transcription_file = os.path.join(LOG_DIR, f"{os.path.basename(chunk_metadata['chunk_file'])}_transcription.json")
    
    # Check if transcription already exists
    if os.path.exists(transcription_file):
        print(f"Loading existing transcription for {chunk_metadata['chunk_file']}...")
        with open(transcription_file, 'r') as f:
            return json.load(f)

    try:
        with open(chunk_metadata['chunk_file'], "rb") as audio_file:
            response = client.audio.transcriptions.create(
                model="whisper-1", 
                file=audio_file, 
                response_format="verbose_json",
                timestamp_granularities=["word"]
            )
            
        # Adjust timestamps by adding the chunk's start time (offset)
        adjusted_segments = []
        chunk_start_time = chunk_metadata['start']  # Get the start time of the chunk
    
        for segment in response.words:
            segment.start += chunk_start_time
            segment.end += chunk_start_time
            adjusted_segments.append(segment)
        
        response.words = adjusted_segments

        response_dict = convert_to_dict(response)

        # Save the transcription to a file
        with open(transcription_file, 'w') as f:
            json.dump(response_dict, f, indent=4)

        return response_dict

    except Exception as e:
        print(f"An error occurred during transcription: {e}")
        # Ensure no empty JSON file is created
        if os.path.exists(transcription_file):
            os.remove(transcription_file)
        return None

def load_diarization_results(metadata):
    """
    Load diarization results from metadata YAML file.
    
    :param metadata: Dictionary containing session metadata.
    :return: Diarization results as a list of dictionaries.
    """
    diarization_file = metadata.get('diarization_file')
    if diarization_file and os.path.exists(diarization_file):
        with open(diarization_file, 'r') as f:
            diarization_results = json.load(f)
        return diarization_results
    else:
        raise FileNotFoundError(f"Diarization file {diarization_file} not found.")

def combine_transcriptions(chunk_transcriptions):
    """
    Combine transcriptions from multiple chunks into a single transcript.
    
    :param chunk_transcriptions: List of transcribed chunks (each chunk is a list of segments).
    :return: Full combined transcript.
    """
    full_transcript = []
    offset = 0.0  # Keep track of time offsets between chunks

    for chunk in chunk_transcriptions:
        # Ensure that the chunk contains 'segments'
        if 'words' in chunk:
            for segment in chunk['words']:
                # Ensure segment is a dictionary and has 'start' and 'end' keys
                if isinstance(segment, dict) and 'start' in segment and 'end' in segment:
                    segment['start'] += offset
                    segment['end'] += offset
                    full_transcript.append(segment)
                else:
                    print(f"Warning: Invalid segment format {segment}")
        else:
            print(f"Warning: No 'segments' key found in chunk {chunk}")
    
    return full_transcript


def sync_transcript_with_diarization(transcript, diarization_results):
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

        # Find the corresponding diarization segment for each transcription segment
        matching_speakers = [diarization for diarization in diarization_results 
                             if diarization['segment']['start'] <= start_time 
                             and diarization['segment']['end'] >= end_time]

        # Select the shortest matching speaker
        if matching_speakers:
            shortest_speaker = min(matching_speakers, key=lambda s: s['segment']['end'] - s['segment']['start'])
            speaker = shortest_speaker['speaker']
        else:
            speaker = "Unknown"

        synchronized_transcript.append({
            'speaker': speaker,
            'start': start_time,
            'end': end_time,
            'text': segment['word']
        })
    
    return synchronized_transcript

##########################################
## TRANSCRIPT POST-PROCESSING FUNCTIONS ##
##########################################

def concatenate_adjacent_speakers(synchronized_transcript):
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
            # If the speaker is the same as the previous, concatenate the text
            current_text.append(text)
        else:
            # If we encounter a new speaker, save the current speaker's dialogue
            if current_speaker is not None:
                final_transcript.append({
                    'speaker': current_speaker,
                    'text': ' '.join(current_text)
                })
            # Start a new entry for the new speaker
            current_speaker = speaker
            current_text = [text]
    
    # Add the last speaker's dialogue
    if current_speaker is not None:
        final_transcript.append({
            'speaker': current_speaker,
            'text': ' '.join(current_text)
        })

    return final_transcript

def save_transcript_to_file(transcript, output_file):
    """
    Save the final synchronized transcript to a text file.
    
    :param transcript: Final transcript with speaker labels.
    :param output_file: Path to the output file.
    """
    with open(output_file, 'w') as f:
        for entry in transcript:
            f.write(f"Speaker {entry['speaker']}: {entry['text']}\n")

###############################
## SCENE SPLITTING FUNCTIONS ##
###############################


def prompt_user_to_edit_file(scene_file):
    """
    Prompt the user to edit the scene file and insert scene breaks.
    
    :param scene_file: Path to the scene file to edit.
    """
    print(f"Please open {scene_file} and insert scene breaks (`---`) where appropriate.")
    input("Press Enter once you have finished editing the file...")

def split_on_scene_breaks(scene_file):
    """
    Read the scene file, split it on scene breaks (`---`), and return the scenes.
    
    :param scene_file: Path to the scene file.
    :return: List of scenes (each scene is a string).
    """
    with open(scene_file, 'r') as f:
        content = f.read()

    # Split the file content on the scene breaks (`---`)
    scenes = content.split('---')

    # Strip any extra whitespace from each scene
    scenes = [scene.strip() for scene in scenes if scene.strip()]

    return scenes

def write_scenes_to_files(scenes, scene_file):
    """
    Write each scene to its own file in the 'scenes' subdirectory and return the list of scene file paths.
    
    :param scenes: List of scenes to write.
    :param scene_file: Original scene file path (used to generate scene filenames).
    :return: List of new scene file paths.
    """
    # Create the 'scenes' subdirectory if it doesn't exist
    scene_dir = os.path.join(os.path.dirname(scene_file), "scenes")
    os.makedirs(scene_dir, exist_ok=True)

    base_filename = os.path.splitext(os.path.basename(scene_file))[0]  # Remove the extension from the scene file
    scene_files = []

    for i, scene in enumerate(scenes):
        scene_filename = os.path.join(scene_dir, f"{base_filename}_scene_{i + 1}.txt")
        with open(scene_filename, 'w') as f:
            f.write(scene)
        scene_files.append(scene_filename)

    return scene_files

def update_metadata_with_scenes(metadata, scene_file, scene_files):
    """
    Update the metadata to include the original scene file and the split scene files.
    
    :param metadata: Metadata dictionary to update.
    :param scene_file: Path to the original scene file.
    :param scene_files: List of new scene file paths.
    :return: Updated metadata dictionary.
    """
    # Add the original scene file
    metadata['scene_file'] = scene_file

    # Add the new scene files
    metadata['scene_segments'] = scene_files

    return metadata

#############################
## SCENE CLEANUP FUNCTIONS ##
#############################

class SpeakerModel(BaseModel):
    name: str = Field(..., description="The name of the speaker.")
    in_world_character: str = Field(..., description="The in-world character name associated with the speaker.")

class TranscriptModel(BaseModel):
    transcript: str = Field(..., description="The cleaned text of the entire transcript.")
    speakers: List[SpeakerModel] = Field(..., description="List of speakers in the transcript.")


def extract_unique_speakers(transcript):
    """
    Extract unique speakers from the transcript by identifying all the text
    before the first colon ':' on each line.
    
    :param transcript: The raw transcript as a string.
    :return: A set of unique speakers found in the transcript.
    """
    speakers = set()

    # Split the transcript into lines and process each line
    for line in transcript.splitlines():
        # Check if the line contains a colon
        if ':' in line:
            # Extract the text before the first colon as the speaker name
            speaker = line.split(':', 1)[0].strip()
            speakers.add(speaker)
    
    return speakers

def get_cleaned_transcript_from_openai(transcript_text: str, system_prompt: str, openai_api_key: str, PydanticModel: BaseModel) -> dict:
    """
    Call OpenAI to clean the transcript using the structured output format.

    :param transcript_text: The raw transcript as input.
    :param system_prompt: System prompt to guide the GPT model.
    :param openai_api_key: OpenAI API key.
    :param PydanticModel: The dynamically generated Pydantic model for validation.
    :return: Dictionary with cleaned transcript and list of speakers.
    """
    client = OpenAI.Client(openai_api_key)

    completion = client.beta.chat.completions.parse(
        model="gpt-4o-2024-08-06",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": transcript_text},
        ],
        response_format=PydanticModel,  # Pass the Pydantic model here
    )

    message = completion.choices[0].message
    if message.parsed:
        return {
            "transcript": message.parsed.transcript,
            "speakers": message.parsed.speakers
        }
    else:
        raise Exception("Failed to parse response")


####################
## MAIN FUNCTIONS ##
####################

def transcribe_session(metadata, whisper_api_key):
    """
    Main function to handle transcription of a session using diarization results and Whisper API.
    
    :param metadata_file: Path to the session metadata YAML file.
    :param whisper_api_key: API key for Whisper.
    """
    # Step 1: Load diarization results
    diarization_results = load_diarization_results(metadata)
    
    # Step 2: Generate raw transcript file name
    metadata = generate_raw_transcript_filename(metadata)
    raw_transcript_file = metadata.get('raw_transcript_file')
    
    # Step 3: Chunk the audio file
    audio_file = metadata.get('audio_file')
    audio_chunks_metadata = chunk_audio_file(audio_file)
    
    # Step 4: Run Whisper on each chunk
    chunk_transcriptions = []
    for chunk_metadata in audio_chunks_metadata:
        transcription = transcribe_audio_chunk(chunk_metadata, whisper_api_key)
        chunk_transcriptions.append(transcription)
    
    # Step 5: Combine chunks into timestamped transcript
    combined_transcript = combine_transcriptions(chunk_transcriptions)
    
    # Step 6: Synchronize with diarization results
    raw_transcript = sync_transcript_with_diarization(combined_transcript, diarization_results)
    final_transcript = concatenate_adjacent_speakers(raw_transcript)
    
    # Step 7: Save the final transcript to a file
    save_transcript_to_file(final_transcript, raw_transcript_file)
    print(f"Final transcript saved to {raw_transcript_file}")
    return metadata

def generate_final_transcript_from_vtt(metadata):
    """
    Main function to parse a WebVTT file and generate a final cleaned transcript.
    
    :param vtt_file: Path to the WebVTT file.
    :param output_file: Path to save the final cleaned transcript.
    """
    metadata = generate_raw_transcript_filename(metadata)
    raw_transcript_file = metadata.get('raw_transcript_file')
    vtt_file = metadata.get('vtt_file')
    parsed_segments = parse_webvtt(vtt_file)
    final_transcript = concatenate_adjacent_speakers(parsed_segments)
    save_transcript_to_file(final_transcript, raw_transcript_file)
    print(f"Final transcript saved to {raw_transcript_file}")
    return metadata


def process_transcript_into_scenes(metadata):
    """
    Copy the raw transcript file to the scene file, prompt the user to edit it, and split it into scenes.
    
    :param metadata: Metadata containing the path to the raw transcript.
    :return: Updated metadata with scene files.
    """
    status = compute_status(metadata)
    raw_transcript_file = metadata.get('raw_transcript_file')
    scene_file = raw_transcript_file.replace('.txt', '_scene.txt')

    print(status)

    if status['scenes'] == 'processed':
        print("Scenes have already been processed.")
        return metadata
    
    if status['scenes'] == 'missing':
        # Step 1: Copy raw transcript to the scene file
        shutil.copy(raw_transcript_file, scene_file)
        print(f"Copied {raw_transcript_file} to {scene_file}.")

        # Step 2: Prompt the user to insert scene breaks (`---`)
        prompt_user_to_edit_file(scene_file)

        # Step 3: Read the edited scene file and split it into scenes
        scenes = split_on_scene_breaks(scene_file)
        status['scenes'] = 'edited'
    
    if status['scenes'] == 'edited':
        # Step 4: Write each scene to its own file
        scene_files = write_scenes_to_files(scenes, scene_file)
        print(f"Scenes have been written to individual files: {scene_files}")
        metadata = update_metadata_with_scenes(metadata, scene_file, scene_files)
        status['scenes'] = 'processed'
    
    return metadata

## MAIN ##

# load metadata from a YAML file, from system arguments
metadata_file = sys.argv[1]
metadata = read_metadata(metadata_file)

# compute the status of the session
status = compute_status(metadata)

load_dotenv()
hf_token = os.getenv("HF_TOKEN")
whisper_api_key = os.getenv("OPEN_API_TAELGAR")

# check audio status and run functions:
if status['audio'] == 'missing':
    print("Audio file is missing.")
elif status['audio'] == 'diarize':
    print("Need to diarize the audio file with Colab.")
elif status['audio'] == 'transcribe':
    print("Transcribing the audio file with Whisper.")
    metadata = transcribe_session(metadata, whisper_api_key)
elif status['audio'] == 'webvtt':
    print("Processing WebVTT file.")
    metadata = generate_final_transcript_from_vtt(metadata)
else: 
    print("Audio file is already processed.")

metadata = process_transcript_into_scenes(metadata)

write_metadata(metadata, metadata_file)
print("Metadata updated.")

