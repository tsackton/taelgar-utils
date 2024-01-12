import shutil
import yaml
import json
import re
import os
from datetime import datetime
from pathlib import Path
from slugify import slugify

###############################
####### REGEXES ###############
###############################

# For Regex, match groups are:
#       0: Whole roamlike link e.g. [[filename#title|alias|widthxheight]]
#       1: Filename e.g. filename.md
#       2: #title
#       3: alias
#       4: width
#       5: height
WIKILINK_RE = r"""\[\[(.*?)(\#.*?)?(?:\|([\D][^\|\]]+[\d]*))?(?:\|(\d+)(?:x(\d+))?)?\]\]"""

################################
##### FUNCTIONS - MAY MOVE #####
################################

class WikiLinkReplacer:
    """
    Adapted from  https://github.com/Jackiexiao/mkdocs-roamlinks-plugin
    """
    def __init__(self, base_docs_url, page_url, path_dict, slug):
        self.base_docs_url = base_docs_url
        self.page_url = page_url
        self.path_dict = path_dict
        self.slug = slug

    def simplify(self, filename):
        """ ignore - _ and space different, replace .md to '' so it will match .md file,
        if you want to link to png, make sure you filename contain suffix .png, same for other files
        but if you want to link to markdown, you don't need suffix .md """
        return re.sub(r"[\-_ ]", "", filename.lower()).replace(".md", "")

    def gfm_anchor(self, title):
        """Convert to gfw title / anchor
        see: https://gist.github.com/asabaylus/3071099#gistcomment-1593627"""
        if title:
            title = title.strip().lower()
            title = re.sub(r'[^\w\u4e00-\u9fff\- ]', "", title)
            title = re.sub(r' +', "-", title)
            return title
        else:
            return ""

    def __call__(self, match):
        # Name of the markdown file
        whole_link = match.group(0)
        filename = match.group(1).strip() if match.group(1) else ""
        title = match.group(2).strip() if match.group(2) else ""
        format_title = self.gfm_anchor(title)
        alias = match.group(3) if match.group(3) else ""
        width = match.group(4) if match.group(4) else ""
        height = match.group(5) if match.group(5) else ""

        # Absolute URL of the linker
        abs_linker_url = os.path.dirname(
            os.path.join(self.base_docs_url, self.page_url))

        # Find directory URL to target link
        rel_link_url = ''
        # Walk through all files in docs directory to find a matching file
        if filename:
            if filename in self.path_dict:
                alias = str(filename) if alias == "" else alias
                if SLUG:
                    filename = str(self.path_dict[filename]['file'])
                else:
                    filename = str(self.path_dict[filename]['orig'])
            else:
                ## check to see if we have a broken obsidian path
                # this is not the best way to do this
                parts = filename.split('/')
                if parts[-1] in self.path_dict:
                    alias = str(parts[-1]) if alias == "" else alias
                    if SLUG:
                        filename = str(self.path_dict[parts[-1]]['file'])
                    else:
                        filename = str(self.path_dict[parts[-1]]['orig'])
            if '/' in filename:
                if 'http' in filename: # http or https
                    rel_link_url = filename
                else:
                    rel_file = filename
                    if not '.' in filename:   # don't have extension type
                        rel_file = filename + ".md"

                    abs_link_url = os.path.dirname(os.path.join(
                        self.base_docs_url, rel_file))
                    # Constructing relative path from the linker to the link
                    rel_link_url = os.path.join(
                            os.path.relpath(abs_link_url, abs_linker_url), os.path.basename(rel_file))
                    if title:
                        rel_link_url = rel_link_url + '#' + format_title
            else:
                for root, dirs, files in os.walk(self.base_docs_url, followlinks=True):
                    for name in files:
                        # If we have a match, create the relative path from linker to the link
                        if self.simplify(name) == self.simplify(filename):
                            # Absolute path to the file we want to link to
                            abs_link_url = os.path.dirname(os.path.join(
                                root, name))
                            # Constructing relative path from the linker to the link
                            rel_link_url = os.path.join(
                                    os.path.relpath(abs_link_url, abs_linker_url), name)
                            if title:
                                rel_link_url = rel_link_url + '#' + format_title
            if rel_link_url == '':
                print(f"Cannot find {filename} in directory {self.base_docs_url}")
                return whole_link
        else:
            rel_link_url = '#' + format_title

        # Construct the return link
        # Windows escapes "\" unintentionally, and it creates incorrect links, so need to replace with "/"
        rel_link_url = rel_link_url.replace("\\", "/")

        if filename:
            if alias:
                link = f'[{alias}](<{rel_link_url}>)'
            else:
                link = f'[{filename+title}](<{rel_link_url}>)'
        else:
            if alias:
                link = f'[{alias}](<{rel_link_url}>)'
            else:
                link = f'[{title}](<{rel_link_url}>)'

        if width and not height:
            link = f'{link}{{ width="{width}" }}'
        elif not width and height:
            link = f'{link}{{ height="{height}" }}'
        elif width and height:
            link = f'{link}{{ width="{width}"; height="{height}" }}'

        return link

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

def build_md_list(path):
    """
    Given a path, makes a dictionary of all the markdown files in the path.
    The dictionary has the original file name as the key, and a dict with two keys as the value:
    - 'file' contains the slugified file name
    - 'path' contains the path relative to the source directory to the file, with slugified directories
    """

    md_files = {}

    for file in path.rglob('*'):
        # skip files that start with a dot or underscore; will eventually fix this to a true ignore list
        if not any(part.startswith('.') for part in file.parts) and not any(part.startswith('_') for part in file.parts):
            
            # skip if directory
            if file.is_dir():
                continue

            # get the original file name, without md if present
            orig_file_name = file.stem + "".join(suffix_part for suffix_part in file.suffixes if suffix_part != ".md")

            # get the slugified file name
            slug_file_name = slugify(file.stem) + "".join(file.suffixes)

            # check if the file is a markdown file
            process = True if file.suffix == '.md' and len(file.suffixes) == 1 else False

            if slug_file_name in md_files:
                raise ValueError(f"Duplicate file basename found: {file}\n", md_files[slug_file_name])

            # get the relative path to the file, relative to source
            relative_path_parents = str(file.relative_to(path).parent).split('/')

            # slugified full path
            slug = Path(*[slugify(part) for part in relative_path_parents]) / slug_file_name
            orig = file.relative_to(path).parent / file.name
            
            md_files[orig_file_name] = { 'file': slug, 'orig': orig, 'process': process }
    return md_files

# Custom dumper for handling empty values
class CustomDumper(yaml.SafeDumper):
    def represent_none(self, _):
        return self.represent_scalar('tag:yaml.org,2002:null', '')

# Add custom representation for None (null) values
CustomDumper.add_representer(type(None), CustomDumper.represent_none)


################################
##### PARSE WEBSITE CONFIG #####
################################

configfile = "website.json"
with open((configfile), 'r', 2048, "utf-8") as f:
    data = json.load(f)
    SOURCE = Path(data["source"])
    OUTPUT = Path(data["build"])
    DATE = data.get("export_date", None)
    CAMPAIGN = data.get("campaign", None)
    SLUG = data.get("slugify", True)

## SOURCE is input files
## OUTPUT is output directory

print("Source: " + str(SOURCE))
print("Output: " + str(OUTPUT))

SOURCE_FILES = build_md_list(SOURCE)

for file_name in SOURCE_FILES:
    # Construct new path
    if SLUG:
        new_file_path = OUTPUT / SOURCE_FILES[file_name]["file"]
    else:
        new_file_path = OUTPUT / SOURCE_FILES[file_name]["orig"]
    
    # Create directories if they don't exist
    new_file_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Copy files that won't be processed
    if not SOURCE_FILES[file_name]['process']:
        # just straight copy
        shutil.copy(SOURCE / SOURCE_FILES[file_name]["orig"], new_file_path)
        continue

    # Open the input file
    fm, text = parse_markdown_file(SOURCE / SOURCE_FILES[file_name]['orig'])

    # Get the mkdocs page path
    if SLUG:
        page_path = SOURCE_FILES[file_name]['file']
    else:
        page_path = SOURCE_FILES[file_name]['orig']
    new_frontmatter = yaml.dump(fm, sort_keys=False, default_flow_style=None, allow_unicode=True, Dumper=CustomDumper, width=2000)

    # clean up markdown text
    new_text = strip_date_content(text, DATE) if DATE else text
    new_text = strip_campaign_content(text, CAMPAIGN) if CAMPAIGN else new_text
    new_text = strip_comments(text)
    new_text = re.sub(WIKILINK_RE, WikiLinkReplacer(OUTPUT, page_path, SOURCE_FILES, SLUG), new_text)
    output = "---\n" + new_frontmatter + "---\n" + new_text

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
 