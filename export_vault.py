import shutil
import yaml
import json
import re
import os
import pathspec
from pathlib import Path
from slugify import slugify
from PIL import Image
from taelgar_lib.ObsNote import ObsNote
from taelgar_lib.WikiLinkReplacer import WikiLinkReplacer

## GLOBALS ##
WIKILINK_RE = ObsNote.WIKILINK_RE

# Custom dumper for handling empty values
class CustomDumper(yaml.SafeDumper):
    def represent_none(self, _):
        return self.represent_scalar('tag:yaml.org,2002:null', '')

# Add custom representation for None (null) values
CustomDumper.add_representer(type(None), CustomDumper.represent_none)

class MkDocsNavigationGenerator:
    def __init__(self, template_path, file_frontmatter, docs_dir):
        self.template_path = template_path
        self.file_frontmatter = file_frontmatter
        self.source_dir = Path(docs_dir)

    @staticmethod
    def count_indentation(line):
        """ Count the number of leading spaces or tabs to determine the depth """
        return (len(line) - len(line.lstrip(' '))) // 4  # Assuming 4 spaces per indentation level

    def generate_markdown_list_from_directory(self, directory_list, depth=0, exclude_files=None, flatten=False):
        """ Generate markdown list entries from a directory based on file_frontmatter info """
        markdown_list = []
        indent = '    ' * depth  # 4 spaces for each level of nesting

        if not exclude_files:
            exclude_files = []

        files = []
        subdirs = []
        ## if flatten is true, we just care about files and want to just get all the files recursively from all dirs in directory list
        if flatten:
            if isinstance(directory_list, Path):
                directory_list = [directory_list]
            for directory in directory_list:
                full_path = self.source_dir / Path(directory)
                files = files + [item for item in full_path.rglob("*.md") if item.is_file() and item.name not in exclude_files]
        else:
            if isinstance(directory_list, Path):
                directory_list = [directory_list]
            for directory in directory_list:
                full_path = self.source_dir / Path(directory)
                files = files + [item for item in full_path.glob("*.md") if item.is_file() and item.name not in exclude_files]
                subdirs = subdirs + [item for item in full_path.iterdir() if item.is_dir()]

        # Process files
        for file_path in sorted(files, key=lambda x: self.file_frontmatter.get(x.stem, {}).get('title', '').lower()):
            file_display_path = file_path.relative_to(self.source_dir)
            title = self.file_frontmatter.get(file_path.stem, {}).get('title', '~Unnamed~')
            unlisted = self.file_frontmatter.get(file_path.stem, {}).get('unlisted', False)
            if unlisted:
                continue
            markdown_list.append(f"{indent}- [{title}]({file_display_path.as_posix()})")

        # Process subdirectories
        for subdir in sorted(subdirs, key=lambda x: x.name.lower()):
            subdir_path = subdir.relative_to(self.source_dir)
            index_file = subdir_path / f"{subdir.name}.md"

            if (self.source_dir / index_file).is_file() and index_file.stem in self.file_frontmatter:
                title = self.file_frontmatter[index_file.stem].get('title', ObsNote.title_case(subdir.stem.replace("-", " ")))
                markdown_list.append(f"{indent}- [{title}]({index_file.as_posix()})")
                exclude_files.append(index_file.name)
            else:
                # title case subdir name
                subdir = ObsNote.title_case(subdir.name.replace("-", " "))
                markdown_list.append(f"{indent}- {subdir}")
            markdown_list.extend(self.generate_markdown_list_from_directory(subdir_path, depth + 1, exclude_files=exclude_files))

        return markdown_list

    def process_template(self):
        """ Process the template file and replace glob patterns with generated markdown lists """
        processed_lines = []

        with open(self.template_path, 'r') as template_file:
            for line in template_file:
                if '{glob:' in line:
                    # Extract directory path, calculate depth, and parse optional exclude pattern
                    flatten = False
                    parts = line.split(',')
                    dir_paths = parts[0].split('{glob:')[-1].strip().replace('}', '').split(";")
                    if len(dir_paths) > 1:
                        if 'flatten' in dir_paths:
                            flatten = True
                    dir_path = [dir for dir in dir_paths if dir != 'flatten']
                    exclude_files = None
                    if len(parts) > 1 and 'exclude:' in parts[1]:
                        exclude_files = parts[1].split('exclude:')[-1].strip().strip('}').split(";")
                    depth = self.count_indentation(line)
                    processed_lines.extend(
                        self.generate_markdown_list_from_directory(
                            dir_path, depth, exclude_files=exclude_files, flatten=flatten
                        )
                    )
                else:
                    processed_lines.append(line.rstrip())

        return processed_lines

def clean_code_blocks(note, template_dir, source_files, abs_path_root):
    def codeblock_cleaner(match):
        if match.group(2):
            # code block
            codeblock_type, sep, codeblock_content = match.group(2).partition('\n')
            codeblock_template = Path(template_dir) / Path(codeblock_type.strip() + ".html")
            if codeblock_type.strip() == "mermaid":
                return match.group(0)
            if codeblock_template.is_file():
                with open(codeblock_template, 'r') as file:
                    template_text = file.read()
                template_content = yaml.safe_load(codeblock_content)
                if codeblock_type.strip() == "leaflet":
                    ## fix image path
                    image_file_name = str(template_content["image"][0]).replace("[", "").replace("]", "").replace('\'', "")
                    page_path = source_files[image_file_name].target_path
                    note.outlinks = note.outlinks + [source_files[image_file_name].target_path.name]
                    template_content["image"] = abs_path_root + str(page_path.as_posix())
                return(template_text.format(**template_content))
            else:
                return ""

    pattern = r'(```([^`]+)```|~~~([^~]+)~~~|`([^`]*)`)'
    note.clean_text = re.sub(pattern, codeblock_cleaner, note.clean_text, flags=re.DOTALL)

def replace_audio_tags(note, abs_path_root):
    # Regular expression pattern to match the specific format
    pattern = r'!\[\[(.*?\.mp3)\]\]'
    
    # Function to create replacement text based on the found mp3 file name
    def replacement(match):
        file_name = match.group(1)
        return f'<audio controls>\n    <source src="{abs_path_root}assets/audio/{file_name}">\n</audio>'
    
    # Replace all matches in the text using the pattern and replacement function
    replaced_text = re.sub(pattern, replacement, note.clean_text)
    return replaced_text


def parse_ignore_file(file_path):
    """ Parse the .gitignore file with pathspec """
    with open(file_path, 'r') as file:
        spec = pathspec.PathSpec.from_lines('gitwildmatch', file)
    return spec

def build_md_list(path, config, ignore_spec=None):
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

            # skip if in ignore list
            if ignore_spec and ignore_spec.match_file(str(file.relative_to(path))):
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
            relative_path_parents = str(file.relative_to(path).parent).split(os.path.sep)

            # slugified full path
            slug = Path(*[slugify(part) for part in relative_path_parents]) / slug_file_name
            orig = file.relative_to(path).parent / file.name

            # get text and frontmatter
            add_file = True
            note = ObsNote(file, config, process)

            # Handle unnamed files
            unnamed_file_handler = note.config.get("unnamed_files", None)
            if note.is_unnamed and unnamed_file_handler:
                if unnamed_file_handler == "skip":
                    add_file = False
                elif unnamed_file_handler == "unlist":
                    note.metadata["unlisted"] = True
                else:
                    raise ValueError(f"Unknown unnamed file handler: {unnamed_file_handler}")
            
            # Handle stub files
            stub_file_handler = note.config.get("stub_files", None)
            if note.is_stub and stub_file_handler:
                if stub_file_handler == "skip":
                    add_file = False
                elif stub_file_handler == "unlist":
                    note.metadata["unlisted"] = True
                else:
                    raise ValueError(f"Unknown stub file handler: {stub_file_handler}")
            
            # Handle future dated files
            if note.is_future_dated and note.config.get("skip_future_dated", False):
                add_file = False
            
            # Handle publish exclusion
            publish_exclusion = note.metadata.get("excludePublish", None)
            if publish_exclusion and isinstance(publish_exclusion, str):
                campaign_exclusion = publish_exclusion.split(",")
            elif publish_exclusion and isinstance(publish_exclusion, list):
                campaign_exclusion = publish_exclusion
            else:
                campaign_exclusion = []
            
            if "all" in campaign_exclusion:
                add_file = False
            # exclude if any campaign in campaign list is in exclusion list
            if any(comp in [i.lower() for i in note.campaign] for comp in [item.lower() for item in campaign_exclusion]):
                add_file = False

            note.target_path = slug if config.get("slugify", True) else orig
            
            if add_file:
                md_files[orig_file_name] = note

    return md_files

################################
##### PARSE WEBSITE CONFIG #####
################################

configfile = "website.json"
with open((configfile), 'r', 2048, "utf-8") as f:
    config = json.load(f)

# set defaults

## SOURCE is input files
## OUTPUT is output directory

source_dir = Path(config.get("source", "taelgar"))
output_dir = Path(config.get("output", "docs"))
    
if not source_dir.exists():
    raise ValueError("Source directory does not exist: " + str(source_dir))

print("Source: " + str(source_dir))
print("Output: " + str(output_dir))

if config.get("clean_build_dir", True):
    print("Cleaning output directory " + str(output_dir) + " before building")
    if output_dir.exists():
        shutil.rmtree(output_dir)

output_dir.mkdir(parents=True, exist_ok=True)

if config.get("home_source", None):
    home_source = config.get("home_source")
    home_dest = config.get("home_dest", "index.md")
    print("Copying " + home_source + " to " + str(source_dir) + "/" + home_dest)
    shutil.copy(Path(home_source), Path(source_dir / Path(home_dest)))

if config.get("overrides_source", None):
    overrides_source = config.get("overrides_source")
    overrides_dest = config.get("overrides_dest", "overrides")
    print("Copying CSS and other site extras from " + overrides_source + " to " + str(overrides_dest))
    shutil.copytree(overrides_source, Path(overrides_dest), dirs_exist_ok=True)

if config.get("ignore_file", None):
    ignore_file = config.get("ignore_file")
    print("Processing ignore file " + ignore_file)
    ignore_spec = parse_ignore_file(ignore_file)
else:
    ignore_spec = None
    
###########################
##### PROCESS FILES #######
###########################

source_files = build_md_list(source_dir, config, ignore_spec)
metadata = {}
linked_images = []

print("Processing files")

if config.get("resize_images", False):
    resize_images = True
    max_width = config.get("max_width", 1200)
    max_height = config.get("max_height", 1200)
    print("Resizing images with max width " + str(max_width) + " and max height " + str(max_height))
else:
    resize_images = False

for file_to_process in source_files:
    note = source_files[file_to_process]

    # Construct new path and add to image
    new_file_path = output_dir / note.target_path    
    
    # Copy files that won't be processed
    if note.is_markdown is False:
        # just straight copy
        new_file_path.parent.mkdir(parents=True, exist_ok=True)
        # special processing for image files
        if note.original_path.suffix in ['.png', '.jpg', '.jpeg', '.gif'] and resize_images and all(substring not in note.filename for substring in ["fullsize", "map", "region"]):
            # resize images
            img = Image.open(note.original_path)
            width, height = img.size
            if width > max_width or height > max_height:
                if width >= height:
                    new_width = max_width
                    new_height = int(height * (max_width / width))
                else:
                    new_height = max_height
                    new_width = int(width * (max_height / height))
                img = img.resize((new_width, new_height))
            img.save(new_file_path)
        else:
            shutil.copy(note.original_path, new_file_path)
        continue

    page_path = note.target_path
    if config.get("clean_code_blocks", False) and config.get("codeblock_template_dir", None):
        clean_code_blocks(note, config.get("codeblock_template_dir"), source_files, config.get("abs_path_root", ""))
    if config.get("replace_audio_tags", True):
        note.clean_text = replace_audio_tags(note, config.get("abs_path_root", ""))
    if config.get("fix_links", True):
        note.clean_text = re.sub(WIKILINK_RE, WikiLinkReplacer(output_dir, page_path, source_files), note.clean_text)

    # exclude toc from selected tags #
    tags = note.metadata.get("tags", [])
    hide_tocs_tags = config.get("hide_tocs_tags", [])
    if tags and hide_tocs_tags:
        clean_tags = list(set([piece for tag in tags for piece in tag.split("/")]))
        if any(tag in clean_tags for tag in hide_tocs_tags):
            note.metadata["hide_toc"] = True

    # exclude backlinks from selected tags #
    hide_backlinks_tags = config.get("hide_backlinks_tags", [])
    if tags and hide_backlinks_tags:
        clean_tags = list(set([piece for tag in tags for piece in tag.split("/")]))
        if any(tag in clean_tags for tag in hide_backlinks_tags):
            note.metadata["hide_backlinks"] = True

    hide_nav = False
    hide_nav_tags = config.get("hide_nav_tags", [])
    if tags and hide_nav_tags:
        clean_tags = list(set([piece for tag in tags for piece in tag.split("/")]))
        if any(tag in clean_tags for tag in hide_nav_tags):
            hide_nav = True

    # if both toc and backlink are hidden, hide entire toc nav #
    if note.metadata.get("hide_backlinks", False) and note.metadata.get("hide_toc", False):
        note.metadata["hide"] = ["toc", "navigation"] if hide_nav else ["toc"]
    elif hide_nav:
        note.metadata["hide"] = ["navigation"]

    basename = Path(new_file_path).stem

    for outlink in note.outlinks:
        if Path(outlink).suffix in ['.png', '.jpg', '.jpeg', '.gif']:
            if config.get("slugify", True):
                outlink = slugify(Path(outlink).stem) + "".join(Path(outlink).suffixes)
            linked_images.append(outlink)
    
    # need to update metadata to replace obsidian title with mkdocs title
    new_metadata = note.metadata
    new_metadata["title"] = note.page_title
    metadata[basename] = new_metadata

    # write out new file
    new_file_path.parent.mkdir(parents=True, exist_ok=True)
    new_frontmatter = yaml.dump(new_metadata, sort_keys=False, default_flow_style=None, allow_unicode=True, Dumper=CustomDumper, width=2000)
    output = "---\n" + new_frontmatter + "---\n" + note.clean_text

    with open(new_file_path, 'w', 2048, "utf-8") as output_file:
        output_file.writelines(output)
 
## generate literate nav

if config.get("literate_nav_source", False):
    nav_source = config.get("literate_nav_source")
    nav_dest = config.get("literate_nav_dest", "toc.md")
    print("Generating nav file from template " + nav_source + " to " + nav_dest)
    nav_generator = MkDocsNavigationGenerator(nav_source, metadata, output_dir)
    processed_template = nav_generator.process_template()
    nav_path = output_dir / Path(nav_dest)
    with open(nav_path, 'w', -1, "utf8") as output_file:
        output_file.write('\n'.join(processed_template))

# remove unused images
        
if config.get("delete_unlinked_images", False) and config.get("image_path", None):
    print("Found images: " + str(len(linked_images)))
    image_path = output_dir / Path(config.get("image_path"))
    print("Removing unused images from " + str(image_path))
    for file in image_path.rglob('*'):
        if file.is_file() and file.suffix in ['.png', '.jpg', '.jpeg', '.gif']:
            if file.name not in linked_images:
                print("Removing unused image: " + file.name)
                file.unlink()