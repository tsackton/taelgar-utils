import os
import argparse
from pydub import AudioSegment
from pydub.silence import split_on_silence

def normalize_audio(audio, target_dBFS=-20.0):
    """
    Normalize the audio to the target dBFS.
    """
    change_in_dBFS = target_dBFS - audio.max_dBFS
    print(f"Normalizing audio by {change_in_dBFS:.2f} dB")
    return audio.apply_gain(change_in_dBFS)

def split_audio_on_silence(audio, min_silence_len=1000, silence_thresh=-40, keep_silence=500):
    """
    Split audio based on silence.
    """
    print("Splitting audio into chunks based on silence...")
    chunks = split_on_silence(
        audio,
        min_silence_len=min_silence_len,
        silence_thresh=silence_thresh,
        keep_silence=keep_silence
    )
    print(f"Number of initial chunks after silence splitting: {len(chunks)}")
    return chunks

def combine_chunks(chunks, max_length_ms):
    """
    Combine smaller chunks to ensure each chunk is as close as possible to max_length_ms without exceeding it.
    """
    print(f"Combining chunks to ensure each is up to {max_length_ms / 60000:.2f} minutes long...")
    combined_chunks = []
    current_chunk = AudioSegment.empty()
    
    for i, chunk in enumerate(chunks, start=1):
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

def export_chunks(chunks, output_dir, base_filename, format="mp3", bitrate="192k"):
    """
    Export audio chunks to the specified format.
    """
    os.makedirs(output_dir, exist_ok=True)
    for i, chunk in enumerate(chunks, start=1):
        chunk_filename = os.path.join(output_dir, f"{base_filename}_chunk{i}.{format}")
        print(f"Exporting chunk {i}: {chunk_filename} (Duration: {len(chunk)/1000:.2f} seconds)")
        chunk.export(chunk_filename, format=format, bitrate=bitrate)
    print(f"All chunks have been exported to '{output_dir}'.")

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
    audio = normalize_audio(audio)
    
    # Split audio on silence
    initial_chunks = split_audio_on_silence(audio, min_silence_len, silence_thresh, keep_silence)
    
    # Define maximum chunk length in milliseconds
    max_length_ms = max_length_min * 60 * 1000  # Convert minutes to milliseconds
    
    # Combine chunks to meet the maximum length
    final_chunks = combine_chunks(initial_chunks, max_length_ms)
    
    # Get base filename without extension
    base_filename = os.path.splitext(os.path.basename(input_file))[0]
    
    # Export chunks
    export_chunks(final_chunks, output_dir, base_filename, format=audio_format, bitrate=bitrate)

if __name__ == "__main__":
    main()
