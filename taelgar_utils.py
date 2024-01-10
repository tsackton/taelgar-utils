import argparse
from pathlib import Path
import yaml
import json
import re
import sys
from datetime import datetime

################################
##### FUNCTIONS - MAY MOVE #####
################################

def parse_markdown_file(file_path):
    """
    Reads a markdown file and returns its frontmatter as a dictionary and the rest of the text as a string.

    :param file_path: Path to the markdown file.
    :return: A tuple containing a dictionary of the frontmatter and a string of the markdown text.
    """
    with open(file_path, 'r', encoding='utf-8') as file:
        content = file.read()

    # Split the content at the triple dashes
    parts = content.split('---')

    # Check if there is frontmatter
    if len(parts) < 3:
        return {}, content

    frontmatter = yaml.safe_load(parts[1])  # Parse the frontmatter
    markdown_text = '---'.join(parts[2:])   # Join back the remaining parts

    return frontmatter, markdown_text

def find_end_of_frontmatter(lines):
    for i, line in enumerate(lines):
        # Check for '---' at the end of a line (with or without a newline character)
        if line.strip() == '---' and i != 0:
            return i
    return 0  # Indicates that the closing '---' was not found

def find_tag_line(lines):
    for i, line in enumerate(lines):
        # Check for '---' at the end of a line (with or without a newline character)
        if line.startswith("tags:"):
            return i
    return None # Indicates that the closing '---' was not found

def strip_comments(s):
    """
    Takes a string as input, and strips all text between %% markers, or between a %% and EOF if there is an unmatched %%.
    Properly handles nested comments - strips only from %% to the next %%.
    Additionally, it handles cases where there is an unmatched %% by removing everything from that %% to the end of the file.
    """
    return re.sub(r'%%.*?%%|%%.*', '', s, flags=re.DOTALL)

def strip_campaign_content(s, text):
    """
    Given a string s, it finds strings of the format:
    %%^Campaign:text%%
    some text here
    %%^End%%
    It keeps all text between %%^Campaign:text%% and %%^End%% if the argument text matches the text in the %% line, 
    and removes it otherwise.
    """
    # This function will be used to determine whether to keep or remove the matched text
    def keep_or_remove(match):
        campaign_text = match.group(1)
        content = match.group(2)
        return content if text.lower() == campaign_text.lower() else ""

    pattern = r'%%\^Campaign:(.*?)%%(.*?)%%\^End%%'
    return re.sub(pattern, keep_or_remove, s, flags=re.DOTALL | re.IGNORECASE)

def parse_date(date_str):
    """
    Tries to parse the date string in various formats and returns a datetime object.
    """
    for fmt in ['%Y', '%Y-%m', '%Y-%m-%d']:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    raise ValueError(f"Date '{date_str}' is not in a recognized format")

def strip_date_content(s, input_date_str):
    """
    Removes text between %%^Date:YYYY-MM-DD%% and %%^End%% if the input_date is before the date in the %% comment.
    The date in the comment and the input date can be in the formats YYYY, YYYY-MM, or YYYY-MM-DD.
    """
    # Convert input_date_str to datetime
    input_date = parse_date(input_date_str)

    def replace_func(match):
        # Extract the date from the comment
        comment_date_str = match.group(1)
        # Parse the comment date
        comment_date = parse_date(comment_date_str)

        # Compare the dates
        if input_date < comment_date:
            return ""  # Remove the text if input_date is before comment_date
        else:
            return match.group(0)  # Keep the text otherwise

    # Define the regular expression pattern
    pattern = r'%%\^Date:(.*?)%%(.*?)%%\^End%%'
    # Replace matching sections
    return re.sub(pattern, replace_func, s, flags=re.DOTALL)

def clean_for_export(s, input_date = None, campaign = None):
    text = strip_date_content(s, input_date) if input_date else s
    text = strip_campaign_content(text, campaign) if campaign else text
    text = strip_comments(text)
    return text

def get_md_dict(path):
    """
    Returns a dictionary of Markdown files in a given directory and its subdirectories, 
    or the file itself if it's a Markdown file. The dictionary keys are the basenames of the files.

    :param path: A pathlib.Path object representing a file or directory.
    :return: A dictionary with basenames as keys and pathlib.Path objects as values.
    :raises ValueError: If there are duplicate file basenames.
    """
    md_files = {}

    if path.is_file() and path.suffix == '.md':
        md_files[path.stem] = path
    elif path.is_dir():
        for file in path.rglob('*.md'):
            if not any(part.startswith('.') for part in file.parts) and not any(part.startswith('_') for part in file.parts):
                basename = file.stem
                fullname = file
                if basename in md_files:
                  raise ValueError(f"Duplicate file basename found: {fullname}")
                md_files[basename] = file
    else:
        raise ValueError("Path is neither a Markdown file nor a directory")

    return md_files

def get_yaml_frontmatter_from_md(file_path):
    """
    Extracts and parses the YAML frontmatter from a Markdown file.

    :param file_path: Path to the Markdown file.
    :return: A dictionary containing the parsed YAML frontmatter.
    """
    with open(file_path, 'r', 2048, "utf8") as file:
        content = file.read()

    # Regex pattern to extract YAML frontmatter
    pattern = r'^---\s+(.*?)\s+---'
    match = re.search(pattern, content, re.DOTALL)

    if match:
        frontmatter = match.group(1)
        # Parse the YAML frontmatter
        try:
            return yaml.safe_load(frontmatter)
        except:
            print(f"Error parsing YAML frontmatter in {file_path}", file=sys.stderr)
            return {}

    return {}

# Custom dumper for handling empty values
class CustomDumper(yaml.SafeDumper):
    def represent_none(self, _):
        return self.represent_scalar('tag:yaml.org,2002:null', '')

# Add custom representation for None (null) values
CustomDumper.add_representer(type(None), CustomDumper.represent_none)

################################
##### COMMAND LINE OPTIONS #####
################################

parser = argparse.ArgumentParser(
    prog='taelgar_utils.py',
    formatter_class=argparse.ArgumentDefaultsHelpFormatter)

# Required positional argument
parser.add_argument('dir', help="File or directory of files to process. Obsidian Vault path is prepended by default. Use '.' to process your entire Vault")

# Output options
output_group = parser.add_argument_group('Input and Output Options')
output_mutex_group = output_group.add_mutually_exclusive_group(required=True)
output_mutex_group.add_argument('--overwrite', action='store_true', help="Update input in place (one of --overwrite or --output must be specified).")
output_mutex_group.add_argument('--output', help="Output to directory (one of --overwrite or --output be specified). By default, obsidian base dir is not prepended.")
output_group.add_argument('--bare-input', action='store_true', help="Do not preprend Obsidian Vault path to dir.")
output_group.add_argument('--obs-output', action='store_true', help="Preprend Obsidian Vault path to output directory.")
output_group.add_argument('--backup', help="**NOT IMPLEMENTED** Create copy of files in specified directory before processing. If specified, obsidian path is never prepended.")

# File processing options
file_processing_group = parser.add_argument_group('File Processing Options')
file_processing_group.add_argument('--dview', action='store_true', help="**DISABLED** Replace dv.view() calls with dview_functions.py calls (optional)")
file_processing_group.add_argument('--yaml', action='store_true', help="**DISABLED** Check yaml against metadata spec and clean up (optional)")
file_processing_group.add_argument('--filter-text', action='store_true', help="Filter out text based on campaign and date information (optional)")
file_processing_group.add_argument('--filter-page', action='store_true', help="*NOT IMPLEMENTED* Remove pages that don't exist yet (optional)")
file_processing_group.add_argument('--add-tag', default=None, help="Adds the specified tag to all pages (optional)")

# Info options
info_group = parser.add_argument_group('Info Options')
info_group.add_argument('--campaign', help="Campaign prefix (optional)")
info_group.add_argument('--date', help="Target date in YYYY or YYYY-MM-DD format (optional, overrides current date determined from fantasy calendar)")

# Utility options
utility_group = parser.add_argument_group('Optional Utility Options')
utility_group.add_argument('-c', '--config', default=".obsidian", help="Path to Obisidian config directory relative to obsidian vault directory, defaults to .obsidian")
utility_group.add_argument('-j', '--json-config-file', default='config.json', help="Path to taelgar-utils json config file, defaults to config.json")
utility_group.add_argument('-v', '--verbose', action='store_true', help="Verbose mode")

# Parse arguments
args = parser.parse_args()

# Validate conditions
if args.obs_output and not args.output:
    parser.error("--obs-output can only be used with --output.")


###########################
##### PARSE ARGUMENTS #####
###########################

### get the obsidian path as a Pathlib object ###
### get the obisidian config directory as a Pathlib object

VAULT = None
CONFIG = args.config
configfile = args.json_config_file
with open((configfile), 'r', 2048, "utf-8") as f:
    data = json.load(f)
    VAULT = Path(data["obsidian_path"])
    CONFIG = VAULT / Path(args.config)
if not VAULT or not CONFIG:
    raise ValueError("Must have a valid obsidian path and obsidian config.")

## VAULT is path to Obsidian vault
## CONFIG is path to Obsidian config directory

### get the files to process ###
inputs = None
if args.bare_input:
    ## don't prepend obsidian path
    inputs = Path(args.dir)
else:
    inputs = VAULT / Path(args.dir)
if (inputs is None) or (inputs and not inputs.exists()):
     raise ValueError("No files to process, existing")

## inputs is a Path object that can be either a file or a directory to process
## will be passed to a function later that will check if it is a dir and get a list of files to process from this

### get output location ###
# if inputs is a file, output location is either the dir the file lives in with --inplace, or --output
# if inputs is a directory, output location is either inputs or --output

### TO DO ###
# clean up overwrite / not overwrite for input/output

if args.overwrite:
    # process in place
    output_dir = inputs
else:
    # have a directory, process elsewhere
    output_base = Path(args.output)
    if args.obs_output:
        # prepend obsidian vault path to output
        output_dir = VAULT / output_base
    else:
        # don't prepend
        output_dir = output_base

# if output dir is a file, get parent
if output_dir.is_file():
    output_dir = output_dir.parent

# resolve
try:
    output_dir = output_dir.resolve(strict=True)
except FileNotFoundError:
    print("Output directory does not exist, please check", file=sys.stderr)

#### SHOULD HAVE INPUT AND OUTPUT VARIABLES ####
# inputs = Path object pointing to a file or directory
# output_dir = Path object pointing to an output directory, might be same as input

VAULT_FILES = get_md_dict(VAULT)
PROCESS_FILES = get_md_dict(inputs)
CAMPAIGN = args.campaign.lower() if args.campaign else None
OVERRIDE_DATE = args.date if args.date else None

### LOAD CORE METADATA ###
CORE_META = json.load(open(CONFIG / Path("metadata.json"), 'r', 2048, "utf-8"))

## OPTIONAL FILTERS ##

filter_text = args.filter_text
clean_yaml = args.yaml
create_backup = args.backup if args.backup else None
debug = args.verbose
add_tag = args.add_tag

for file_name in PROCESS_FILES:
    # Open the input file
    if debug:
        print("Processing " + str(PROCESS_FILES[file_name]), file=sys.stderr)
    fm, text = parse_markdown_file(PROCESS_FILES[file_name])
    new_frontmatter = yaml.dump(fm, sort_keys=False, default_flow_style=None, allow_unicode=True, Dumper=CustomDumper, width=2000)
    new_text = clean_for_export(text, OVERRIDE_DATE, CAMPAIGN)
    output = new_frontmatter + new_text

    # Construct new path
    relative_path = PROCESS_FILES[file_name].relative_to(inputs)
    new_file_path = output_dir / relative_path

    # Create directories if they don't exist
    new_file_path.parent.mkdir(parents=True, exist_ok=True)

    # Write the updated lines to a new file
    with open(new_file_path, 'w', 2048, "utf-8") as output_file:
        '''
        Would replace text with this if we wanted to add a note that the thing doesn't exist yet
        if not thing_exist:
            newlines = metadata_block
            newlines.append("# " + metadata.get("name", "unnamed entity") + "\n")
            newlines.append("**This does not exist yet!**\n")
        '''
        output_file.writelines(output)
 