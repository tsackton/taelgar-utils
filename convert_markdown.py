import argparse
import yaml
import re
import os
import sys
from pathlib import Path
from metadataUtils import *
from dateFunctions import *
import importlib.util
import shutil

"""
TODO:
- Add --filter2 option
- Fix functions so that rather than overloading metadata dict, create a new "globs" object to pass around
- Add --verebose option for debugging
"""

debug = True

## import dview_functions.py as module
dview_file_name = "dview_functions"
dview_functions = importlib.import_module(dview_file_name)

# Custom dumper for handling empty values
class CustomDumper(yaml.SafeDumper):
    def represent_none(self, _):
        return self.represent_scalar('tag:yaml.org,2002:null', '')

# Add custom representation for None (null) values
CustomDumper.add_representer(type(None), CustomDumper.represent_none)


def find_end_of_frontmatter(lines):
    for i, line in enumerate(lines):
        # Check for '---' at the end of a line (with or without a newline character)
        if line.strip() == '---' and i != 0:
            return i
    return 0  # Indicates that the closing '---' was not found



def dict_to_yaml(d):
    yaml_lines = []
    for key, value in d.items():
        if value is None:
            # Output the key without a value
            yaml_lines.append(f"{key}:\n")
        else:
            # Use yaml.dump for other values
            yaml_value = yaml.dump({key: value}, Dumper=CustomDumper, sort_keys=False, default_flow_style=False, allow_unicode=True)
            yaml_lines.append(yaml_value)
    return ''.join(yaml_lines)

def is_function(module, attribute):
    attr = getattr(module, attribute)
    return callable(attr)

def get_links_dict(files):
    links = {}
    for file in files:
        filepath = Path(file)
        links[filepath.stem] = filepath
    return links

def get_md_files(directory):
    markdown_files = []
    for root, dirs, files in os.walk(directory):
        markdown_files += [os.path.join(root, file) for file in files if file.endswith('.md') and not root.startswith('./_')]
    return markdown_files

def process_string(s, metadata):
    def callback(match):
        function_name = match.group(1).split(",", maxsplit=1)[0].strip('\"').split("/")[-1]

        # Check if the function exists in the module and is a callable
        if function_name in dir(dview_functions) and is_function(dview_functions, function_name):
            dview_call = getattr(dview_functions, function_name)
            # Now you can call the function
            result = dview_call(metadata)
        else:
            result = print(f"Function {function_name} not implemented in conversion code.", file=sys.stderr)
            result = ""
        return result

    pattern = "\`\$\=dv\.view\((.*)\)\`"
    return re.sub(pattern, callback, s)

parser = argparse.ArgumentParser(
    prog='convert_markdown.py',
    formatter_class=argparse.ArgumentDefaultsHelpFormatter)
parser.add_argument('-c', '--config', required=True, help="Path to config directory (required)")
parser.add_argument('-d', '--dir', required=True, help="Path to directory containing markdown files (required)")
parser.add_argument('-o', '--output', required=False, help="Path to output directory (optional, default is to overrite input files)")
parser.add_argument('--campaign', required=False, help="Campaign prefix (optional)")
parser.add_argument('--date', required=False, help="Target date in YYYY or YYYY-MM-DD format (optional, overrides current date in config file)")
parser.add_argument('--dview', required=False, default=False,  action='store_true', help="Replace dv.view() calls with dview_functions.py calls (optional)")
parser.add_argument('--yaml', required=False, default=False,  action='store_true', help="Check yaml against metadata spec and clean up (optional)")
parser.add_argument('--export-null', required=False, default=False,  action='store_true', help="Convert empty strings to null values in yaml frontmatter (optional)")
parser.add_argument('--filter', required=False, default=False,  action='store_true', help="Filter out text based on campaign and date information (optional)")
parser.add_argument('--filter2', required=False, default=False, action='store_true', help="*NOT IMPLEMENTED* Remove pages that don't exist yet (optional)")
parser.add_argument('-b', '--backup', required=False, help="Create backup files in the specified directory (optional)")

args = parser.parse_args()

# Get the date, campaign, and directory name from the command line arguments
dir_name = args.dir
output_dir = args.output if args.output else None
input_campaign = args.campaign
override_year = clean_date(args.date) if args.date else None
filter_text = args.filter
clean_yaml = args.yaml
replace_dview = args.dview
create_backup = args.backup if args.backup else None

if create_backup:
    # Create backup directory if it doesn't exist
    if not os.path.exists(create_backup):
        os.makedirs(create_backup)

    # Copy all files to backup directory
    shutil.copytree(dir_name, create_backup, dirs_exist_ok=True)

if output_dir:
    # Create backup directory if it doesn't exist
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # Copy all files to backup directory
    shutil.copytree(dir_name, output_dir, dirs_exist_ok=True)
    md_file_list = get_md_files(output_dir)
else:
    md_file_list = get_md_files(dir_name)

links = get_links_dict(md_file_list)

for file_name in md_file_list:
    # Open the input file
    with open(file_name, 'r', 2048, "utf-8") as input_file:
        lines = input_file.readlines()

    # if file is blank, move on
    if len(lines) == 0:
        continue

    # Check if the file starts with a metadata block
    metadata = dict()
    if lines[0].strip() == '---':
        metadata_block = []
        start_metadata = True
        for line in lines[1:]:
            if start_metadata and line.strip() == '---':
                start_metadata = False
            elif start_metadata:
                metadata_block.append(line)
            else:
                break
        if metadata_block:
            metadata = yaml.safe_load(''.join(metadata_block))
    
    metadata_orig = metadata.copy()
    metadata["campaign"] = input_campaign
    metadata["override_year"] = override_year
    metadata["directory"] = args.config
    metadata["links"] = links
    metadata["file"] = file_name
    current_date = get_current_date(metadata)

    if clean_yaml:
        if debug:
            print("Cleaning up yaml frontmatter in " + file_name, file=sys.stderr)
        
        metadata_clean = update_metadata(metadata, metadata_orig)

        if metadata_clean is None:
            updated_content = lines
        else:
            new_frontmatter = yaml.dump(metadata_clean, sort_keys=False, default_flow_style=None, allow_unicode=True, Dumper=CustomDumper, width=2000)
            end_of_frontmatter = find_end_of_frontmatter(lines)
            if end_of_frontmatter != -1:
                end_of_frontmatter += 1  # Adjust to get the line after '---'
                updated_content = ['---\n', new_frontmatter, '---\n'] + lines[end_of_frontmatter:]
            else:
                # Handle the case where the frontmatter is not properly closed
                print(f"Error: Frontmatter not properly closed in {file_name}", file=sys.stderr)
                updated_content = lines
    else:
        updated_content = lines

    #Process the rest of the file with access to the metadata information
    filter_start = False
    filter_end = False
    filter_block = False
    newlines = []
    for line in updated_content:
        filter_start = line.startswith(("%%^", ">%%^", ">>%%^", ">>>%%^"))
        line_start = ""
        filter_end = line.endswith(("%%^End%%\n","%%^End%%"))

        # check if line is just %%^End%%
        if line.startswith("%%^End"):
            filter_start = False

        # get filter type if filter start
        if filter_start:
            match = re.search(r'^(.*?)%%\^([A-Za-z]+):\s*(\w+).*?\s*%%', line)
            if match:
                if match.group(2) == "Date":
                    # we have a date filter
                    filter_date = clean_date(match.group(3))
                    filter_block = True if current_date < filter_date else filter_block
                elif match.group(2) == "Campaign":
                    # we have a campaign filter
                    filter_block = True if metadata["campaign"] != match.group(3) else filter_block
                else:    
                    # filter we don't know
                    print("Found unknown filter in file " + file_name + ": " + match.group(2), file=sys.stderr)
                line_start = match.group(1)
            else:
                print("In file " + file_name + ", couldn't parse filter at line: " + line, end="", file=sys.stderr)
        
        if (filter_text and not filter_block) or (not filter_text):
            # if filter text is true, print line only if filter block is false
            # if filter text is false, print line
            if replace_dview:
                newline = process_string(line,metadata)
            else:
                newline=line
            newlines.append(newline)
        
        # now need to check filter_end and reset filter_block if we are at the end

        if filter_end:
            filter_block = False

    # Write the updated lines to a new file
    with open(file_name, 'w', 2048, "utf-8") as output_file:
        '''
        Would replace text with this if we wanted to add a note that the thing doesn't exist yet
        if not thing_exist:
            newlines = metadata_block
            newlines.append("# " + metadata.get("name", "unnamed entity") + "\n")
            newlines.append("**This does not exist yet!**\n")
        '''
        output_file.writelines(newlines)
 