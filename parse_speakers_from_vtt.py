import os
import json
from collections import defaultdict
from webvtt import WebVTT

def process_vtt_file(filepath):
    """
    Process a single VTT file to extract speaker names and their word counts.
    """
    speakers = defaultdict(int)
    
    try:
        for caption in WebVTT().read(filepath):
            lines = caption.text.split("\n")
            for line in lines:
                if ":" in line:  # Assume speaker names are followed by ":"
                    speaker, speech = line.split(":", 1)
                    word_count = len(speech.split())
                    speakers[speaker.strip()] += word_count
    except Exception as e:
        print(f"Error processing {filepath}: {e}")
    
    return speakers

def process_vtt_directories(base_dir):
    """
    Process all VTT files in each directory under the base directory.
    """
    data = []
    
    for dirpath, dirnames, filenames in os.walk(base_dir):
        directory_name = os.path.basename(dirpath)
        directory_data = {"directory_name": directory_name, "speakers": defaultdict(int)}
        
        for filename in filenames:
            if filename.endswith(".vtt"):
                filepath = os.path.join(dirpath, filename)
                speakers = process_vtt_file(filepath)
                for speaker, count in speakers.items():
                    directory_data["speakers"][speaker] += count
        
        # Only include directories with VTT files
        if directory_data["speakers"]:
            directory_data["speakers"] = dict(directory_data["speakers"])  # Convert defaultdict to dict
            data.append(directory_data)
    
    return data

# Base directory containing subdirectories with .vtt files
base_directory = "."

# Process all directories and collect data
result = process_vtt_directories(base_directory)

# Save the result to a JSON file
output_json_path = "vtt_speaker_word_counts.json"
with open(output_json_path, "w", encoding="utf-8") as json_file:
    json.dump(result, json_file, indent=4)

print(f"Speaker word counts saved to {output_json_path}")
