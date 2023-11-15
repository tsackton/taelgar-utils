import argparse
from pathlib import Path
import yaml
import json
import re
import os
import sys
import lib.dateFunctions as dates
import lib.metadataUtils as meta
import lib.generalUtils as util
import shutil

"""
TODO:
- Add --filter2 option
- Fix functions so that rather than overloading metadata dict, create a new "globs" object to pass around
- Parse obisidan information from config file
"""

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
output_group.add_argument('--backup', help="Create copy of files in specified directory before processing. If specified, obsidian path is never prepended.")

# File processing options
file_processing_group = parser.add_argument_group('File Processing Options')
file_processing_group.add_argument('--dview', action='store_true', help="Replace dv.view() calls with dview_functions.py calls (optional)")
file_processing_group.add_argument('--yaml', action='store_true', help="Check yaml against metadata spec and clean up (optional)")
file_processing_group.add_argument('--filter-text', action='store_true', help="Filter out text based on campaign and date information (optional)")
file_processing_group.add_argument('--filter-page', action='store_true', help="*NOT IMPLEMENTED* Remove pages that don't exist yet (optional)")

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
with open(configfile), 'r', 2048, "utf-8") as f:
    data = json.load(f)
    VAULT = Path(data["obsidian_path"])
    CONFIG = obs_path / obs_config
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

if args.inplace:
    # process in place
    output_dir = inputs
else:
    # have a directory, process elsewhere
    output_base = Path(args.output)
    if args.obs_output:
        # prepend obsidian vault path to output
        output_dir = obs_path / output_base
    else:
        # don't prepend
        output_dir = output_base

# if output dir is a file, get parent
if not output_dir.is_dir():
    output_dir = output_dir.parent

# resolve

try:
    output_dir = output_dir.resolve(strict=True)
except FileNotFoundError:
    print("Output directory does not exist, please check", file=sys.stderr)

#### SHOULD HAVE INPUT AND OUTPUT VARIABLES ####
# inputs = Path object pointing to a file or directory
# output_dir = Path object pointing to an output directory, might be same as input

### EDIT BELOW HERE ###

# Get the date, campaign, and directory name from the command line arguments
dir_name = args.dir
output_dir = args.output if args.output else None
input_campaign = args.campaign
override_year = dates.clean_date(args.date) if args.date else None
filter_text = args.filter
clean_yaml = args.yaml
replace_dview = args.dview
create_backup = args.backup if args.backup else None
debug = args.verbose

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
    md_file_list = util.get_md_files(output_dir)
else:
    md_file_list = util.get_md_files(dir_name)

links = util.get_links_dict(md_file_list)

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
    current_date = dates.get_current_date(metadata)

    if clean_yaml:
        if debug:
            print("Cleaning up yaml frontmatter in " + file_name, file=sys.stderr)
        
        metadata_clean = meta.update_metadata(metadata, metadata_orig)

        if metadata_clean is None:
            updated_content = lines
        else:
            new_frontmatter = yaml.dump(metadata_clean, sort_keys=False, default_flow_style=None, allow_unicode=True, Dumper=CustomDumper, width=2000)
            end_of_frontmatter = util.find_end_of_frontmatter(lines)
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
                    filter_date = dates.clean_date(match.group(3))
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
                newline = util.process_string(line,metadata)
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
 