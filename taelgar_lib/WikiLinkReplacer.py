import re
import os
from pathlib import Path
from .ObsNote import ObsNote

class WikiLinkReplacer:
    """
    Adapted from  https://github.com/Jackiexiao/mkdocs-roamlinks-plugin
    """
    def __init__(self, base_docs_url, page_url, path_dict):
        self.base_docs_url = base_docs_url
        self.page_url = page_url
        self.path_dict = path_dict

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
            if filename in self.path_dict or filename.lower() in self.path_dict:
                if filename.lower() in self.path_dict:
                    filename = filename.lower()
                alias = str(filename) if alias == "" else alias
                filename = str(self.path_dict[filename].target_path)
            else:
                ## check to see if we have a broken obsidian path
                # this is not the best way to do this
                parts = filename.split('/')
                clean_name = parts[-1].replace('.md', '').rstrip("\\/")
                if clean_name in self.path_dict or clean_name.lower() in self.path_dict:
                    alias = str(clean_name) if alias == "" else alias
                    filename = str(self.path_dict[clean_name].target_path)
            if "http://" in filename or "https://" in filename:
                rel_link_url = filename
            else:
                if os.path.sep in filename:
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
                # print(f"Cannot find {filename} in directory {self.base_docs_url}")
                if alias:
                    return alias
                else:
                    if not "." in filename and not "[" in filename:
                        # prevents stripping nested [] from bounds in leaflet blocks
                        return filename
                    else:
                        return whole_link
        else:
            rel_link_url = '#' + format_title

        # Construct the return link
        # Windows escapes "\" unintentionally, and it creates incorrect links, so need to replace with "/"
        rel_link_url = rel_link_url.replace("\\", "/")

        # define image link as: filename has is xxx.png, xxx.jpg, xxx.jpeg, xxx.gif, or alias = right or left, or width or height is not empty
        image_link = re.search(r".*\.(png|jpg|jpeg|gif|heic)$", filename) or alias in ["right", "left"] or width or height

        if image_link:
            # alias becomes align = right or left
            # width and height becomes width and height
            # convert -_ to space in filename, remove extension, and title case for alias
            alignment = f'align="{alias}"' if alias in ["right", "left"] else ""
            width = f'width="{width}"' if width else ""
            height = f'height="{height}"' if height else ""
            alias = ObsNote.title_case(Path(filename).stem.replace("-", " ").replace("_", " "))
            if alignment or width or height:
                image_params = "{" + "; ".join([param for param in [alignment, width, height] if param]) + "}"
            else:
                image_params = ""
            link = f'[{alias}]({rel_link_url}){image_params}'
                               
        else:
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

        return link
