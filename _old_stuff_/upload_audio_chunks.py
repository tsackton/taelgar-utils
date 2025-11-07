import os
import boto3
from botocore.exceptions import NoCredentialsError, ClientError
from tqdm import tqdm

def upload_file_to_s3(file_path, bucket_name, object_name=None, expiration=3600):
    """
    Upload a file to an S3 bucket and generate a pre-signed URL.

    Parameters:
        file_path (str): Path to the file to upload.
        bucket_name (str): Name of the S3 bucket.
        object_name (str, optional): S3 object name. Defaults to file basename.
        expiration (int): Time in seconds for the pre-signed URL to remain valid.

    Returns:
        str: Pre-signed URL of the uploaded object.
    """
    # If S3 object_name was not specified, use file basename
    if object_name is None:
        object_name = os.path.basename(file_path)

    # Create an S3 client
    s3_client = boto3.client('s3')

    try:
        # Upload the file
        s3_client.upload_file(file_path, bucket_name, object_name)
    except FileNotFoundError:
        print(f"The file {file_path} was not found.")
        return None
    except NoCredentialsError:
        print("Credentials not available.")
        return None
    except ClientError as e:
        print(f"Failed to upload {file_path} to S3: {e}")
        return None

    try:
        # Generate a pre-signed URL for the uploaded file
        response = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket_name, 'Key': object_name},
            ExpiresIn=expiration
        )
    except ClientError as e:
        print(f"Failed to generate pre-signed URL for {object_name}: {e}")
        return None

    return response

def upload_directory_to_s3(directory_path, bucket_name, expiration=3600):
    """
    Upload all files in a directory to S3 and generate pre-signed URLs.

    Parameters:
        directory_path (str): Path to the directory containing files to upload.
        bucket_name (str): Name of the S3 bucket.
        expiration (int): Time in seconds for the pre-signed URLs to remain valid.

    Returns:
        dict: Dictionary mapping file names to their pre-signed URLs.
    """
    presigned_urls = {}

    # List all files in the directory
    files = [f for f in os.listdir(directory_path) if os.path.isfile(os.path.join(directory_path, f))]

    print(f"Uploading {len(files)} files to S3 bucket '{bucket_name}'...")
    for file_name in tqdm(files, desc="Uploading Files"):
        file_path = os.path.join(directory_path, file_name)
        url = upload_file_to_s3(file_path, bucket_name, object_name=file_name, expiration=expiration)
        if url:
            presigned_urls[file_name] = url

    return presigned_urls

def main():
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Upload audio chunks to Amazon S3 and generate pre-signed URLs.")
    parser.add_argument('--directory', '-d', required=True, help="Path to the directory containing audio chunks.")
    parser.add_argument('--bucket', '-b', required=True, help="Name of the S3 bucket.")
    parser.add_argument('--output', '-o', default='presigned_urls.json', help="Path to save the JSON file containing pre-signed URLs.")
    parser.add_argument('--expiration', '-e', type=int, default=3600, help="Expiration time in seconds for the pre-signed URLs. Default is 3600 seconds (1 hour).")

    args = parser.parse_args()

    directory_path = args.directory
    bucket_name = args.bucket
    output_file = args.output
    expiration = args.expiration

    # Validate directory
    if not os.path.isdir(directory_path):
        print(f"Error: Directory '{directory_path}' does not exist.")
        exit(1)

    # Upload files and get pre-signed URLs
    urls = upload_directory_to_s3(directory_path, bucket_name, expiration)

    # Save URLs to a JSON file
    with open(output_file, 'w') as f:
        json.dump(urls, f, indent=4)

    print(f"Pre-signed URLs saved to '{output_file}'.")

if __name__ == "__main__":
    main()
