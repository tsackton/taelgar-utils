import os
import yaml
import csv
import argparse

def extract_yaml_to_csv(input_dir, output_csv):
    # Fields to extract from the YAML front matter
    fields_to_extract = ['sessionNumber', 'realWorldDate', 'DR', 'DR_end', 'players']

    # List to store extracted data
    data = []

    # Iterate through each Markdown file in the directory
    for filename in os.listdir(input_dir):
        if filename.endswith('.md'):
            filepath = os.path.join(input_dir, filename)
            with open(filepath, 'r', encoding='utf-8') as file:
                content = file.read()
                if content.startswith('---'):
                    # Extract YAML front matter
                    yaml_part = content.split('---')[1].strip()
                    yaml_data = yaml.safe_load(yaml_part)
                    
                    # Collect the desired fields
                    row = {}
                    for field in fields_to_extract:
                        value = yaml_data.get(field, '')
                        # Special handling for the 'players' field
                        if field == 'players' and isinstance(value, list):
                            value = ', '.join(sorted(value))
                        row[field] = value
                    # Append to the data list
                    data.append(row)

    # Write extracted data to CSV
    with open(output_csv, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fields_to_extract)
        writer.writeheader()
        writer.writerows(data)

    print(f"Data has been written to {output_csv}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract YAML front matter from Markdown files and save to a CSV.")
    parser.add_argument("input_dir", help="Path to the directory containing Markdown files")
    parser.add_argument("output_csv", help="Path to the output CSV file")
    args = parser.parse_args()

    extract_yaml_to_csv(args.input_dir, args.output_csv)
