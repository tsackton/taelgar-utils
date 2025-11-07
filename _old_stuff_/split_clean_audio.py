import os
import argparse
import subprocess
from pydub import AudioSegment
from pydub.silence import split_on_silence
from tqdm import tqdm
import multiprocessing
import re

def normalize_audio(audio, target_dBFS=-20.0, headroom=1.0):
    """
    Normalize the audio to the target RMS dBFS and prevent clipping.
    
    Parameters:
        audio (AudioSegment): The audio to normalize.
        target_dBFS (float): The target RMS dBFS.
        headroom (float): The headroom below 0 dBFS to prevent clipping.
        
    Returns:
        AudioSegment: The normalized audio.
    """
    original_dBFS = audio.dBFS
    print(f"Original average dBFS: {original_dBFS:.2f} dBFS")
    
    # Calculate the gain needed to reach target dBFS
    change_in_dBFS = target_dBFS - original_dBFS
    print(f"Applying gain of {change_in_dBFS:.2f} dB to reach target dBFS of {target_dBFS} dBFS")
    normalized_audio = audio.apply_gain(change_in_dBFS)
    
    # Prevent clipping by limiting the peak to (0 - headroom) dBFS
    peak_dBFS = normalized_audio.max_dBFS
    print(f"Peak dBFS after normalization: {peak_dBFS:.2f} dBFS")
    
    if peak_dBFS > (-headroom):
        clipping_gain = (-headroom) - peak_dBFS
        print(f"Peak dBFS exceeds the headroom of {-headroom} dBFS. Applying additional gain of {clipping_gain:.2f} dB to prevent clipping.")
        normalized_audio = normalized_audio.apply_gain(clipping_gain)
        print(f"Peak dBFS after clipping prevention: {normalized_audio.max_dBFS:.2f} dBFS")
    else:
        print("No clipping detected. No additional gain applied.")
    
    final_dBFS = normalized_audio.dBFS
    final_peak = normalized_audio.max_dBFS
    print(f"Final normalized average dBFS: {final_dBFS:.2f} dBFS")
    print(f"Final normalized peak dBFS: {final_peak:.2f} dBFS")
    
    return normalized_audio

def detect_silences_ffmpeg(input_file, silence_thresh=-40, min_silence_len=1000):
    """
    Detect silences in the audio file using FFmpeg's silencedetect filter.
    
    Returns a list of tuples indicating the start and end times (in ms) of silences.
    """
    print("Detecting silences using FFmpeg...")
    # Construct the FFmpeg command
    cmd = [
        'ffmpeg',
        '-i', input_file,
        '-af', f'silencedetect=noise={silence_thresh}dB:d={min_silence_len/1000}',
        '-f', 'null',
        '-'
    ]
    
    # Execute the FFmpeg command
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stdout, stderr = process.communicate()
    
    # Parse the stderr for silence information
    silence_starts = []
    silence_ends = []
    
    for line in stderr.split('\n'):
        if 'silence_start' in line:
            try:
                silence_start = float(re.findall(r'silence_start: (\d+\.\d+)', line)[0])
                silence_starts.append(silence_start)
            except IndexError:
                pass
        elif 'silence_end' in line:
            try:
                silence_end = float(re.findall(r'silence_end: (\d+\.\d+)', line)[0])
                silence_ends.append(silence_end)
            except IndexError:
                pass
    
    # Combine starts and ends into list of tuples
    silences = list(zip(silence_starts, silence_ends))
    print(f"Detected {len(silences)} silences.")
    return silences

def split_audio_on_silence(audio, silences):
    """
    Split audio based on detected silences.
    
    Returns a list of AudioSegment chunks.
    """
    print("Splitting audio based on detected silences...")
    chunks = []
    previous_end = 0  # in ms
    for silence_start, silence_end in silences:
        chunk = audio[previous_end: silence_start * 1000]  # silence_start is in seconds
        if len(chunk) > 0:
            chunks.append(chunk)
        previous_end = silence_end * 1000  # silence_end is in seconds
    # Add the last chunk
    last_chunk = audio[previous_end:]
    if len(last_chunk) > 0:
        chunks.append(last_chunk)
    print(f"Number of chunks after silence splitting: {len(chunks)}")
    return chunks

def combine_chunks(chunks, max_length_ms):
    """
    Combine smaller chunks to ensure each chunk is as close as possible to max_length_ms without exceeding it.
    
    Returns a list of combined AudioSegment chunks.
    """
    print(f"Combining chunks to ensure each is up to {max_length_ms / 60000:.2f} minutes long...")
    combined_chunks = []
    current_chunk = AudioSegment.empty()
    
    for chunk in tqdm(chunks, desc="Combining Chunks"):
        if len(current_chunk) + len(chunk) <= max_length_ms:
            current_chunk += chunk
        else:
            if len(current_chunk) > 0:
                combined_chunks.append(current_chunk)
            current_chunk = chunk
    # Append any remaining chunk
    if len(current_chunk) > 0:
        combined_chunks.append(current_chunk)
    
    print(f"Number of final combined chunks: {len(combined_chunks)}")
    return combined_chunks

def export_chunk(args):
    """
    Export a single audio chunk.
    
    Parameters:
        args: Tuple containing (chunk, output_dir, base_filename, index, format, bitrate)
    """
    chunk, output_dir, base_filename, index, format, bitrate = args
    chunk_filename = os.path.join(output_dir, f"{base_filename}_chunk{index}.{format}")
    # Export the chunk
    chunk.export(chunk_filename, format=format, bitrate=bitrate)
    return chunk_filename

def export_chunks_multiprocessing(chunks, output_dir, base_filename, format="mp3", bitrate="192k"):
    """
    Export audio chunks using multiprocessing for faster performance.
    
    Returns a list of exported file paths.
    """
    print("Exporting chunks with multiprocessing...")
    os.makedirs(output_dir, exist_ok=True)
    
    # Prepare arguments for each chunk
    export_args = [
        (chunk, output_dir, base_filename, i+1, format, bitrate)
        for i, chunk in enumerate(chunks)
    ]
    
    # Use multiprocessing Pool to export chunks in parallel
    with multiprocessing.Pool() as pool:
        results = list(tqdm(pool.imap(export_chunk, export_args), total=len(export_args), desc="Exporting Chunks"))
    
    print(f"All chunks have been exported to '{output_dir}'.")
    return results

def main():
    parser = argparse.ArgumentParser(description="Split large audio files into smaller MP3 chunks based on silence, with normalization and maximum length control.")
    parser.add_argument('--input', '-i', required=True, help="Path to the input audio file.")
    parser.add_argument('--output_dir', '-o', default='output_chunks', help="Directory to save the output audio chunks. Default is 'output_chunks'.")
    parser.add_argument('--min_silence_len', '-m', type=int, default=1000, help="Minimum length of silence (in ms) to consider for a split. Default is 1000 ms.")
    parser.add_argument('--silence_thresh', '-s', type=int, default=-40, help="Silence threshold in dBFS. Default is -40 dBFS.")
    parser.add_argument('--keep_silence', '-k', type=int, default=500, help="Amount of silence (in ms) to retain at each split. Default is 500 ms.")
    parser.add_argument('--max_length', '-x', type=float, default=15.0, help="Maximum length of each chunk in minutes. Default is 15 minutes.")
    parser.add_argument('--format', '-f', type=str, default='mp3', choices=['mp3', 'wav', 'ogg'], help="Output audio format. Default is 'mp3'.")
    parser.add_argument('--bitrate', '-b', type=str, default='192k', help="Bitrate for MP3 export. Default is '192k'. Only applicable for MP3 format.")
    
    args = parser.parse_args()
    
    input_file = args.input
    output_dir = args.output_dir
    min_silence_len = args.min_silence_len
    silence_thresh = args.silence_thresh
    keep_silence = args.keep_silence
    max_length_min = args.max_length
    audio_format = args.format
    bitrate = args.bitrate
    
    # Validate input file
    if not os.path.isfile(input_file):
        print(f"Error: Input file '{input_file}' does not exist.")
        exit(1)
    
    # Load audio file
    print(f"Loading audio file: {input_file}")
    audio = AudioSegment.from_file(input_file)
    print(f"Original audio duration: {len(audio)/60000:.2f} minutes")
    
    # Normalize audio
    # Adjust target_dBFS as needed based on your audio's original levels
    target_dBFS = -10.0  # Example: set to -10 dBFS
    headroom = 1.0        # 1 dB headroom to prevent clipping
    audio = normalize_audio(audio, target_dBFS=target_dBFS, headroom=headroom)
    
    # Detect silences using FFmpeg
    silences = detect_silences_ffmpeg(input_file, silence_thresh, min_silence_len)
    
    # Split audio based on silences
    initial_chunks = split_audio_on_silence(audio, silences)
    
    # Define maximum chunk length in milliseconds
    max_length_ms = max_length_min * 60 * 1000  # Convert minutes to milliseconds
    
    # Combine chunks to meet the maximum length
    final_chunks = combine_chunks(initial_chunks, max_length_ms)
    
    # Get base filename without extension
    base_filename = os.path.splitext(os.path.basename(input_file))[0]
    
    # Export chunks using multiprocessing
    export_chunks_multiprocessing(final_chunks, output_dir, base_filename, format=audio_format, bitrate=bitrate)

if __name__ == "__main__":
    main()
