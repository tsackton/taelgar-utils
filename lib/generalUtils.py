from pathlib import Path
import os
import sys
import re
import importlib.util

## import dview_functions.py as module
dview_file_name = "dview_functions"
dview_functions = importlib.import_module(dview_file_name)

def find_end_of_frontmatter(lines):
    for i, line in enumerate(lines):
        # Check for '---' at the end of a line (with or without a newline character)
        if line.strip() == '---' and i != 0:
            return i
    return 0  # Indicates that the closing '---' was not found


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
