import argparse
from pathlib import Path
import yaml
import json
import re
import sys
from obs_convert.date_manager import DateManager as dm
from obs_convert.name_manager import NameManager as nm
from obs_convert.whereabouts_manager import WhereaboutsManager as wm
from obs_convert.location_manager import LocationManager as lm
import importlib.util

"""
TODO:
- Add --filter2 option
- convert old functions
- figure out if I need to change linking for website building
- regnal bugs
- fix display dates, just year if year -> rebuild date structure to have an object that has date, display date, calendar era, display_as
- general cleanup and organization
"""

## import dview_functions.py as module
dview_file_name = "obs_convert.dview_functions"
dview_functions = importlib.import_module(dview_file_name)

################################
##### FUNCTIONS - MAY MOVE #####
################################


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

def is_function(module, attribute):
    attr = getattr(module, attribute)
    return callable(attr)

def process_string(s, metadata, dm, nm, lm, wm):
    def callback(match):
        function_name = match.group(1).split(",", maxsplit=1)[0].strip('\"').split("/")[-1]

        # Check if the function exists in the module and is a callable
        if function_name in dir(dview_functions) and is_function(dview_functions, function_name):
            dview_call = getattr(dview_functions, function_name)
            # Now you can call the function
            result = dview_call(metadata, dm, nm, lm, wm)
        else:
            result = print(f"Function {function_name} not implemented in conversion code.", file=sys.stderr)
            result = ""
        return result

    pattern = "\`\$\=dv\.view\((.*)\)\`"
    return re.sub(pattern, callback, s)


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
file_processing_group.add_argument('--dview', action='store_true', help="Replace dv.view() calls with dview_functions.py calls (optional)")
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
CACHED_METADATA = dict()
for file_name in VAULT_FILES:
    CACHED_METADATA[file_name] = get_yaml_frontmatter_from_md(VAULT_FILES[file_name])

CAMPAIGN = args.campaign
OVERRIDE_DATE = args.date if args.date else None

### LOAD CORE METADATA ###
CORE_META = json.load(open(CONFIG / Path("metadata.json"), 'r', 2048, "utf-8"))

## OPTIONAL FILTERS ##

filter_text = args.filter_text
clean_yaml = args.yaml
replace_dview = args.dview
create_backup = args.backup if args.backup else None
debug = args.verbose
add_tag = args.add_tag

## CLASSES ##
date_manager = dm(CONFIG, OVERRIDE_DATE)
name_manager = nm(CORE_META, VAULT_FILES, CACHED_METADATA)
location_manager = lm(date_manager, name_manager)
whereabouts_manager = wm(date_manager, name_manager, location_manager)
location_manager.set_whereabouts_manager(whereabouts_manager)

for file_name in PROCESS_FILES:
    # Open the input file
    print("Processing " + str(PROCESS_FILES[file_name]), file=sys.stderr)
    with open(PROCESS_FILES[file_name], 'r', 2048, "utf-8") as input_file:
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

    if clean_yaml:
        if debug:
            print("Cleaning up yaml frontmatter in " + file_name, file=sys.stderr)
        
        metadata_clean = metadata.copy()

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
    elif add_tag:
        ## first check if there is metadata:
        if metadata is None:
            updated_content = ['---\n', "tags: [" + add_tag + "]\n", '---\n'].append(lines)
        else:
            ## check if there is a tag line
            tags = metadata.get("tags", None)
            if tags:
                # have tags
                tags.append(add_tag)
                metadata["tags"] = tags
            else:
                # no tags
                metadata["tags"] = [add_tag]
            ## now update lines with new frontmatter
            new_frontmatter = yaml.dump(metadata, sort_keys=False, default_flow_style=None, allow_unicode=True, Dumper=CustomDumper, width=2000)
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
                    filter_date = date_manager.normalize_date(match.group(3))
                    filter_block = True if date_manager.default_date < filter_date else filter_block
                elif match.group(2) == "Campaign":
                    # we have a campaign filter
                    filter_block = True if CAMPAIGN != match.group(3) else filter_block
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
                newline = process_string(line,metadata, date_manager, name_manager, location_manager, whereabouts_manager)
            else:
                newline=line
            newlines.append(newline)
        
        # now need to check filter_end and reset filter_block if we are at the end

        if filter_end:
            filter_block = False

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
        output_file.writelines(newlines)
 