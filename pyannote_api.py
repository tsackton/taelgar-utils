import os
import json
import requests
from dotenv import load_dotenv
import csv
import sys
import argparse

def load_environment():
    """
    Load environment variables from the .env file.
    """
    load_dotenv()
    token = os.getenv("PYAI_TOKEN")
    webhook_url = os.getenv("SPEAKER_ID_WEBHOOK")
    if not token:
        print("Error: TOKEN not found in environment variables.")
        sys.exit(1)
    if not webhook_url:
        print("Error: WEBHOOK_URL not found in environment variables.")
        sys.exit(1)
    return token, webhook_url

def load_json_file(filepath):
    """
    Load a JSON file and return its content.
    """
    try:
        with open(filepath, 'r') as file:
            data = json.load(file)
        return data
    except Exception as e:
        print(f"Error loading {filepath}: {e}")
        sys.exit(1)

def send_diarization_request(chunk_name, url, webhook_url, voiceprints, token, num_speakers, api):
    """
    Send a POST request to the pyannote.ai API for diarization.
    
    Returns:
        tuple: (chunk_name, jobId, status) or (chunk_name, None, error_message)
    """
    if api == "diarize":
        api_url = "https://api.pyannote.ai/v1/diarize"
        payload = {
            "url": url,
            "webhook": webhook_url
        }
    elif api == "identify":
        api_url = "https://api.pyannote.ai/v1/identify"
        payload = {
            "url": url,
            "webhook": webhook_url,
            "voiceprints": voiceprints
        }
    else:
        return (chunk_name, None, "Invalid API")
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    try:
        response = requests.post(api_url, json=payload, headers=headers)
        response.raise_for_status()  # Raises stored HTTPError, if one occurred.
        data = response.json()
        job_id = data.get("jobId")
        status = data.get("status")
        return (chunk_name, job_id, status)
    except requests.exceptions.RequestException as e:
        return (chunk_name, None, str(e))
    except json.JSONDecodeError:
        return (chunk_name, None, "Invalid JSON response")

def main(chunks, voiceprints, output, num_speakers, api):
    # Load environment variables
    token, webhook_url = load_environment()
    
    # Define file paths
    chunks_file = chunks
    voiceprints_file = voiceprints
    output_file = output
    
    # Load chunks and voiceprints
    chunks = load_json_file(chunks_file)  # Should be a dict: { "chunk1.mp3": "url1", ... }
    voiceprints = load_json_file(voiceprints_file)  # Should be a list of dicts
    
    # Prepare for API requests
    total_chunks = len(chunks)
    if total_chunks == 0:
        print("No chunks found in chunks.json.")
        sys.exit(1)
    
    print(f"Total chunks to process: {total_chunks}")
    
    # Initialize CSV for mapping
    try:
        with open(output_file, mode='w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['chunk_name', 'job_id', 'status']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            
            # Iterate over each chunk
            for chunk_name, url in chunks.items():
                print(f"Processing {chunk_name}...")
                result = send_diarization_request(chunk_name, url, webhook_url, voiceprints, token, num_speakers, api)
                chunk, job_id, status = result
                if job_id:
                    print(f"Success: {chunk} -> Job ID: {job_id}")
                    writer.writerow({
                        'chunk_name': chunk,
                        'job_id': job_id,
                        'status': status
                    })
                else:
                    print(f"Error processing {chunk}: {status}")
                    writer.writerow({
                        'chunk_name': chunk,
                        'job_id': 'Error',
                        'status': status
                    })
        
        print(f"\nAll diarization requests have been processed. Mapping saved to '{output_file}'.")
    except Exception as e:
        print(f"Error writing to CSV file: {e}")
        sys.exit(1)

if __name__ == "__main__":
    # parse command line arguments: python pyannote_api.py --api diarize
    parser = argparse.ArgumentParser(description='Send to pyannote API.')
    parser.add_argument('--api', type=str, help='API to use: diarize or identify')
    parser.add_argument('--num_speakers', type=int, default=5, help='Number of speakers to detect')
    parser.add_argument('--chunks', type=str, default='chunks.json', help='Path to chunks JSON file')
    parser.add_argument('--voiceprints', type=str, default='voiceprints.json', help='Path to voiceprints JSON file')
    parser.add_argument('--output', type=str, default='mapping.csv', help='Path to output CSV file')
    args = parser.parse_args()
    if args.api:
        main(args.chunks, args.voiceprints, args.output, args.num_speakers, args.api)
    else:
        print("Please provide an API to use: diarize or identify")
        sys.exit(1)
