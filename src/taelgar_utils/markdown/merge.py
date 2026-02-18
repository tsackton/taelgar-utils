#!/usr/bin/env python3
import os
import glob
import yaml
import argparse

def process_file(path):
    """
    1) Strip out the YAML frontmatter (between the first pair of '---' lines).
    2) Parse it via PyYAML so we can re‐emit each key/value pair as plain text.
    3) After the title line, skip any consecutive blockquote lines (those starting with '>').
    4) Return a string containing:
         - the title line (# …)
         - the frontmatter fields as plain text
         - a blank line
         - the rest of the body (after removing the 'info' blockquotes).
    """
    with open(path, 'r', encoding='utf-8') as f:
        raw_lines = f.read().splitlines()

    # 1) Extract frontmatter
    fm = {}
    idx = 0
    if idx < len(raw_lines) and raw_lines[idx].strip() == '---':
        idx += 1
        fm_lines = []
        while idx < len(raw_lines) and raw_lines[idx].strip() != '---':
            fm_lines.append(raw_lines[idx])
            idx += 1
        # skip the closing '---'
        idx += 1
        # 2) Parse frontmatter via PyYAML
        try:
            fm = yaml.safe_load("\n".join(fm_lines)) or {}
        except Exception:
            fm = {}

    # Now idx points at the first line after frontmatter (hopefully the title)
    lines = raw_lines[idx:]
    output = []

    if not lines:
        return ""

    # 3) Copy the title (# …)
    title_line = lines[0]
    output.append(title_line)

    # 4) Emit each frontmatter key: value as plain text under the title
    for key, val in fm.items():
        output.append(f"{key}: {val}")
    output.append("")  # blank line

    # 5) Skip any consecutive '>' lines immediately after the title
    i = 1
    while i < len(lines) and lines[i].lstrip().startswith(">"):
        i += 1

    # 6) Append the rest of the body (from i onward)
    output.extend(lines[i:])

    return "\n".join(output)

def main():
    parser = argparse.ArgumentParser(
        description="Combine multiple Markdown files (with YAML frontmatter) into one document."
    )
    parser.add_argument(
        "-i", "--input-dir",
        default=".",
        help="Directory containing .md files to process (default: current directory)"
    )
    parser.add_argument(
        "-o", "--output-file",
        default="combined.md",
        help="Filename for the combined output (default: combined.md)"
    )
    args = parser.parse_args()

    input_dir = args.input_dir
    output_path = args.output_file

    # Pattern to find all Markdown files in the specified directory
    pattern = os.path.join(input_dir, "*.md")
    md_files = sorted(glob.glob(pattern))

    processed_parts = []
    for md in md_files:
        transformed = process_file(md)
        if transformed.strip():
            processed_parts.append(transformed)

    # Join each processed file with "\n---\n"
    combined = "\n---\n".join(processed_parts)

    with open(output_path, "w", encoding="utf-8") as outfile:
        outfile.write(combined)

if __name__ == "__main__":
    main()
