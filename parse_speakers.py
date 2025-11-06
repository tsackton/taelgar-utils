import os
import re
import argparse
from collections import defaultdict
from typing import List, Tuple

import webvtt
from pydub import AudioSegment

def parse_webvtt(webvtt_file: str) -> List[Tuple[str, float, float]]:
    """
    Parses a WebVTT file and extracts speaker segments.

    Returns:
        A list of tuples containing speaker name, start time in seconds, and end time in seconds.
    """
    speaker_segments = []
    speaker_pattern = re.compile(r'^(?P<speaker>[^:]+):\s*(?P<text>.+)$')

    for caption in webvtt.read(webvtt_file):
        match = speaker_pattern.match(caption.text.strip())
        if match:
            speaker = match.group('speaker').strip()
            start_time = time_str_to_seconds(caption.start)
            end_time = time_str_to_seconds(caption.end)
            speaker_segments.append((speaker, start_time, end_time))
        else:
            # Handle captions without explicit speaker labels if necessary
            pass

    return speaker_segments

def time_str_to_seconds(time_str: str) -> float:
    """
    Converts a WebVTT timestamp to seconds.

    Example:
        "00:01:15.123" -> 75.123 seconds
    """
    parts = time_str.split(':')
    if len(parts) == 3:
        hours, minutes, seconds = parts
    elif len(parts) == 2:
        hours = 0
        minutes, seconds = parts
    else:
        raise ValueError(f"Invalid time format: {time_str}")

    # Handle possible comma instead of dot as decimal separator
    seconds = seconds.replace(',', '.')
    total_seconds = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    return total_seconds

def compute_unique_segments(speaker_segments: List[Tuple[str, float, float]]) -> List[Tuple[str, float, float]]:
    """
    Computes unique segments where only one speaker is active.

    Args:
        speaker_segments: List of tuples containing speaker name, start time, and end time.

    Returns:
        A list of tuples with speaker name, unique start time, and unique end time.
    """
    # Create a list of all events
    events = []
    for speaker, start, end in speaker_segments:
        events.append((start, 'start', speaker))
        events.append((end, 'end', speaker))

    # Sort events by time, with 'start' events before 'end' events at the same time
    events.sort(key=lambda x: (x[0], 0 if x[1] == 'start' else 1))

    active_speakers = set()
    unique_segments = []
    prev_time = None

    for time, event_type, speaker in events:
        if prev_time is not None and prev_time < time:
            if len(active_speakers) == 1:
                active_speaker = next(iter(active_speakers))
                unique_segments.append((active_speaker, prev_time, time))
        if event_type == 'start':
            active_speakers.add(speaker)
        elif event_type == 'end':
            active_speakers.discard(speaker)
        prev_time = time

    return unique_segments

def extract_speaker_tracks(audio_file: str, unique_segments: List[Tuple[str, float, float]], output_dir: str, chunk_duration_ms: int = 15 * 60 * 1000):
    """
    Extracts and combines unique audio segments for each speaker, then chunks into specified durations.

    Args:
        audio_file: Path to the input audio file.
        unique_segments: List of tuples containing speaker name, unique start time, and unique end time.
        output_dir: Directory to save speaker tracks.
        chunk_duration_ms: Duration of each chunk in milliseconds (default is 15 minutes).
    """
    # Load the full audio
    print(f"Loading audio file: {audio_file}")
    audio = AudioSegment.from_file(audio_file)

    # Organize unique segments by speaker
    speakers = defaultdict(list)
    for speaker, start, end in unique_segments:
        # Convert seconds to milliseconds for pydub
        start_ms = int(start * 1000)
        end_ms = int(end * 1000)
        speakers[speaker].append(audio[start_ms:end_ms])

    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)

    # Export each speaker's audio in chunks
    for speaker, segments in speakers.items():
        print(f"Processing speaker: {speaker}")
        combined = AudioSegment.empty()
        for segment in segments:
            combined += segment

        # Split combined audio into chunks
        total_length = len(combined)
        num_chunks = (total_length + chunk_duration_ms - 1) // chunk_duration_ms  # Ceiling division

        for i in range(num_chunks):
            start_ms = i * chunk_duration_ms
            end_ms = min((i + 1) * chunk_duration_ms, total_length)
            chunk = combined[start_ms:end_ms]

            # Clean speaker name for filename
            safe_speaker = re.sub(r'[^\w\- ]', '_', speaker)
            output_filename = f"{safe_speaker}_part{i+1}.mp3"
            output_path = os.path.join(output_dir, output_filename)

            # Export the chunk to MP3
            chunk.export(output_path, format="mp3")
            print(f"Exported {speaker} - Part {i+1} to {output_path}")

def parse_arguments():
    """
    Parses command-line arguments.

    Returns:
        Parsed arguments.
    """
    parser = argparse.ArgumentParser(
        description="Separate audio tracks by speaker based on a WebVTT file."
    )
    parser.add_argument(
        '-a', '--audio',
        required=True,
        help="Path to the input audio file."
    )
    parser.add_argument(
        '-w', '--webvtt',
        required=True,
        help="Path to the input WebVTT file."
    )
    parser.add_argument(
        '-o', '--output',
        default='output_speakers',
        help="Directory to save the output speaker tracks. Default is 'output_speakers'."
    )
    parser.add_argument(
        '-c', '--chunk',
        type=int,
        default=15,
        help="Chunk length in minutes. Default is 15 minutes."
    )

    return parser.parse_args()

def main():
    args = parse_arguments()

    audio_file = args.audio
    webvtt_file = args.webvtt
    output_dir = args.output
    chunk_length_minutes = args.chunk

    # Validate input files
    if not os.path.isfile(audio_file):
        print(f"Error: Audio file '{audio_file}' does not exist.")
        exit(1)
    if not os.path.isfile(webvtt_file):
        print(f"Error: WebVTT file '{webvtt_file}' does not exist.")
        exit(1)

    # Validate chunk length
    if chunk_length_minutes <= 0:
        print("Error: Chunk length must be a positive integer representing minutes.")
        exit(1)

    chunk_duration_ms = chunk_length_minutes * 60 * 1000

    print("Parsing WebVTT file...")
    speaker_segments = parse_webvtt(webvtt_file)
    print(f"Found {len(speaker_segments)} speaker segments.")

    print("Computing unique non-overlapping segments...")
    unique_segments = compute_unique_segments(speaker_segments)
    print(f"Found {len(unique_segments)} unique speaker segments.")

    print("Extracting and exporting speaker tracks...")
    extract_speaker_tracks(audio_file, unique_segments, output_dir, chunk_duration_ms)
    print("All speaker tracks have been exported successfully.")

if __name__ == "__main__":
    main()
