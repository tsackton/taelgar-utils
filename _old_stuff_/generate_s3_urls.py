import boto3
import json
import os
from botocore.exceptions import NoCredentialsError, PartialCredentialsError, ClientError

def generate_presigned_urls(bucket_name, output_json, expiration=3600):
    """
    Generate pre-signed URLs for all objects in an S3 bucket and save to a JSON file as a dictionary.
    
    :param bucket_name: Name of the S3 bucket.
    :param output_json: Path to the output JSON file.
    :param expiration: Time in seconds for the pre-signed URL to remain valid. Default is 3600 seconds (1 hour).
    """
    # Initialize S3 client
    s3_client = boto3.client('s3')

    try:
        # Verify if the bucket exists and is accessible
        s3_client.head_bucket(Bucket=bucket_name)
    except ClientError as e:
        error_code = int(e.response['Error']['Code'])
        if error_code == 404:
            print(f"Error: Bucket '{bucket_name}' does not exist.")
        else:
            print(f"Error accessing bucket '{bucket_name}': {e}")
        return
    except NoCredentialsError:
        print("Error: AWS credentials not found. Please configure your AWS credentials.")
        return
    except PartialCredentialsError:
        print("Error: Incomplete AWS credentials found.")
        return

    # Prepare data structure to hold filename and URLs
    presigned_data = {}

    # Use paginator to handle large buckets
    paginator = s3_client.get_paginator('list_objects_v2')
    page_iterator = paginator.paginate(Bucket=bucket_name)

    object_count = 0
    filename_set = set()

    for page in page_iterator:
        # Check if 'Contents' key exists in the page
        if 'Contents' not in page:
            print(f"No objects found in bucket '{bucket_name}'.")
            break

        for obj in page['Contents']:
            object_key = obj['Key']
            file_name = os.path.basename(object_key)

            # Check for duplicate filenames
            if file_name in presigned_data:
                print(f"Warning: Duplicate filename '{file_name}' found in different paths. Overwriting the previous URL.")
            
            try:
                # Generate pre-signed URL
                presigned_url = s3_client.generate_presigned_url(
                    'get_object',
                    Params={'Bucket': bucket_name, 'Key': object_key},
                    ExpiresIn=expiration
                )
            except ClientError as e:
                print(f"Error generating pre-signed URL for '{object_key}': {e}")
                presigned_url = None

            # Add to dictionary if URL was generated successfully
            if presigned_url:
                presigned_data[file_name] = presigned_url
                object_count += 1

    if not presigned_data:
        print(f"No pre-signed URLs generated for bucket '{bucket_name}'.")
        return

    # Save the data to a JSON file
    try:
        with open(output_json, 'w', encoding='utf-8') as json_file:
            json.dump(presigned_data, json_file, indent=4)
        print(f"Generated pre-signed URLs for {object_count} objects in bucket '{bucket_name}'.")
        print(f"Output saved to '{output_json}'.")
    except Exception as e:
        print(f"Error writing to JSON file '{output_json}': {e}")

if __name__ == "__main__":
    import argparse

    # Set up command-line argument parsing
    parser = argparse.ArgumentParser(description="Generate pre-signed URLs for all objects in an S3 bucket and export to a JSON dictionary.")
    parser.add_argument('bucket', help='Name of the S3 bucket.')
    parser.add_argument('output', help='Path to the output JSON file.')
    parser.add_argument('--expiration', type=int, default=3600, help='Expiration time for the pre-signed URLs in seconds (default: 3600).')

    args = parser.parse_args()

    generate_presigned_urls(args.bucket, args.output, args.expiration)
