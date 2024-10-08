import os
import json
import csv
import sys

def load_csv_mapping(csv_path):
    """
    Load the CSV file and return a dictionary mapping job_id to chunk_name.
    """
    mapping = {}
    try:
        with open(csv_path, mode='r', newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                chunk_name = row.get('chunk_name')
                job_id = row.get('job_id')
                if chunk_name and job_id:
                    mapping[job_id] = chunk_name
                else:
                    print(f"Warning: Missing chunk_name or job_id in row: {row}")
        return mapping
    except FileNotFoundError:
        print(f"Error: CSV file '{csv_path}' not found.")
        sys.exit(1)
    except Exception as e:
        print(f"Error reading CSV file '{csv_path}': {e}")
        sys.exit(1)

def load_diarization_json(json_path):
    """
    Load a diarization JSON file and return its content.
    """
    try:
        with open(json_path, 'r', encoding='utf-8') as file:
            data = json.load(file)
        return data
    except json.JSONDecodeError as e:
        print(f"Warning: JSON decode error in file '{json_path}': {e}")
        return None
    except Exception as e:
        print(f"Warning: Could not read file '{json_path}': {e}")
        return None

def reformat_diarization(identifications):
    """
    Reformat the diarization identifications into the desired structure without changing speaker names.
    """
    formatted = []
    for entry in identifications:
        speaker = entry.get('speaker', 'Unknown')
        start = entry.get('start', 0.0)
        end = entry.get('end', 0.0)
        formatted_entry = {
            "speaker": speaker,
            "segment": {
                "start": start,
                "end": end
            }
        }
        formatted.append(formatted_entry)
    return formatted

def process_diarizations(diarizations_dir, mapping_dict, output_dir):
    """
    Process each diarization JSON file and save the reformatted JSON.
    """
    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)
    
    # List all JSON files in the diarizations directory
    json_files = [f for f in os.listdir(diarizations_dir) if f.endswith('.json')]
    
    if not json_files:
        print(f"No JSON files found in directory '{diarizations_dir}'.")
        return
    
    for json_file in json_files:
        json_path = os.path.join(diarizations_dir, json_file)
        data = load_diarization_json(json_path)
        if not data:
            print(f"Skipping file '{json_file}' due to loading issues.")
            continue
        
        job_id = data.get('jobId')
        status = data.get('status')
        
        if not job_id:
            print(f"Warning: 'jobId' not found in file '{json_file}'. Skipping.")
            continue
        
        if status.lower() != 'succeeded':
            print(f"Info: Diarization job '{job_id}' in file '{json_file}' has status '{status}'. Skipping.")
            continue
        
        chunk_name = mapping_dict.get(job_id)
        if not chunk_name:
            print(f"Warning: No chunk mapping found for job_id '{job_id}' in file '{json_file}'. Skipping.")
            continue
        
        identifications = data.get('output', {}).get('identification', [])
        if not identifications:
            identifications = data.get('output', {}).get('diarization', [])
            if not identifications:
                print(f"Warning: No 'identification' data found in file '{json_file}'. Skipping.")
                continue
        
        # Reformat diarization data without changing speaker names
        formatted_diarization = reformat_diarization(identifications)
        
        # Define output file name
        chunk_base_name = os.path.splitext(chunk_name)[0]
        output_file_name = f"{chunk_base_name}_diarization.json"
        output_path = os.path.join(output_dir, output_file_name)
        ## make sure the output file does not already exist
        if os.path.exists(output_path):
            # update name with a number
            i = 1
            while True:
                output_file_name = f"{chunk_base_name}_diarization_{i}.json"
                output_path = os.path.join(output_dir, output_file_name)
                if not os.path.exists(output_path):
                    break
                i += 1

        
        # Save the formatted diarization to the output directory
        try:
            with open(output_path, 'w', encoding='utf-8') as outfile:
                json.dump(formatted_diarization, outfile, indent=4)
            print(f"Processed and saved: '{output_file_name}'")
        except Exception as e:
            print(f"Error: Could not write to file '{output_file_name}': {e}")

def main():
    # Define paths
    current_dir = os.getcwd()
    diarizations_dir = os.path.join(current_dir, 'Voiceprints')
    csv_path = os.path.join(current_dir, 'merged_mappings.csv')
    output_dir = os.path.join(current_dir, 'formatted_diarizations')
    
    # Load the CSV mapping
    mapping_dict = load_csv_mapping(csv_path)
    
    # Process diarization JSON files
    process_diarizations(diarizations_dir, mapping_dict, output_dir)
    
    print("\nAll available diarization JSON files have been processed.")

if __name__ == "__main__":
    main()
