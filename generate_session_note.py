import os
import json
import sys
import yaml  # For loading and saving metadata YAML files
from dotenv import load_dotenv
from openai import OpenAI
from pydub import AudioSegment

########################
## METADATA FUNCTIONS ##
########################

# Directory for logs and transcriptions
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

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
    if os.path.exists(metadata.get('raw_transcript_file')):
        status['audio'] = 'processed'
    elif os.path.exists(metadata.get('diarization_file')):
        status['audio'] = 'transcribe'
    elif os.path.exists(metadata.get('audio_file')):
        status['audio'] = 'diarize'
    else:
        status['audio'] = 'missing'

    # Step 2: check if scene files exist
    scene_files = metadata.get('scene_files', [])
    if all(os.path.exists(scene) for scene in scene_files):
        status['scenes'] = 'processed'
    
    # Check if cleaned scene files exist
    cleaned_scene_files = metadata.get('cleaned_scene_files', [])
    if all(os.path.exists(cleaned) for cleaned in cleaned_scene_files):
        status['cleaned'] = 'processed'
    
    # Check if summary and timeline files exist
    if os.path.exists(metadata.get('summary_file')) and os.path.exists(metadata.get('timeline_file')):
        status['summarized'] = 'processed'
    
    # Check if the final note exists
    if os.path.exists(metadata.get('final_note')):
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

#############################
## TRANSCRIPTION FUNCTIONS ##
#############################

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

def chunk_audio_file(audio_file, chunk_size_mb=20, overlap_ms=1000, output_format="mp3", sample_rate=16000):
    """
    Chunk the audio file into pieces of approximately 20 MB with a 1000 ms overlap, and export in a compressed format.
    If the chunk metadata already exists, it will skip the chunking process.
    
    :param audio_file: Path to the input audio file.
    :param chunk_size_mb: Desired chunk size in MB.
    :param overlap_ms: Overlap between chunks in milliseconds.
    :param output_format: Desired output format for chunks (e.g., "mp3", "m4a").
    :param sample_rate: Target sample rate for downsampling.
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
    bytes_per_ms = (audio.frame_rate * audio.frame_width * audio.channels) / 1000
    chunk_length_ms = int((chunk_size_mb * 1024 * 1024) / bytes_per_ms)

    chunk_dir = "audio_chunks"
    os.makedirs(chunk_dir, exist_ok=True)

    chunks_metadata = []
    for i in range(0, len(audio), chunk_length_ms - overlap_ms):
        chunk = audio[i:i + chunk_length_ms]
        chunk_file = os.path.join(chunk_dir, f"chunk_{i // chunk_length_ms}.{output_format}")
        chunk.export(chunk_file, format=output_format)
        chunks_metadata.append({
            "chunk_file": chunk_file,
            "start": i / 1000,  # Convert ms to seconds
            "end": (i + chunk_length_ms) / 1000
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
                timestamp_granularities=["segment"]
            )
            
        # Adjust timestamps by adding the chunk's start time (offset)
        adjusted_segments = []
        chunk_start_time = chunk_metadata['start']  # Get the start time of the chunk
    
        for segment in response.segments:
            segment.start += chunk_start_time
            segment.end += chunk_start_time
            adjusted_segments.append(segment)
        
        response.segments = adjusted_segments

        # Save the transcription to a file
        with open(transcription_file, 'w') as f:
            json.dump(response, f, indent=4)

        return response

    except Exception as e:
        print(f"An error occurred during transcription: {e}")
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
        for segment in chunk:
            segment['start'] += offset
            segment['end'] += offset
            full_transcript.append(segment)
        # Update the offset based on the last chunk's end time
        offset = full_transcript[-1]['end']
    
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

        speaker = matching_speakers[0]['speaker'] if matching_speakers else "Unknown"
        synchronized_transcript.append({
            'speaker': speaker,
            'start': start_time,
            'end': end_time,
            'text': segment['text']
        })
    
    return synchronized_transcript


def save_transcript_to_file(transcript, output_file):
    """
    Save the final synchronized transcript to a text file.
    
    :param transcript: Final transcript with speaker labels.
    :param output_file: Path to the output file.
    """
    with open(output_file, 'w') as f:
        for entry in transcript:
            f.write(f"Speaker {entry['speaker']} ({entry['start']:.2f} - {entry['end']:.2f}): {entry['text']}\n")


def transcribe_session(metadata, whisper_api_key):
    """
    Main function to handle transcription of a session using diarization results and Whisper API.
    
    :param metadata_file: Path to the session metadata YAML file.
    :param whisper_api_key: API key for Whisper.
    """
    # Step 1: Load diarization results
    diarization_results = load_diarization_results(metadata_file)
    
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
    final_transcript = sync_transcript_with_diarization(combined_transcript, diarization_results)
    
    # Step 7: Save the final transcript to a file
    save_transcript_to_file(final_transcript, raw_transcript_file)
    print(f"Final transcript saved to {raw_transcript_file}")
    write_metadata(metadata, metadata_file)
    print("Metadata updated.")


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
else: 
    print("Audio file is already processed.")

## to be continued...