import sys
import itertools
from pathlib import Path
from taelgar_lib.ObsNote import ObsNote
from taelgar_lib.TaelgarDate import TaelgarDate

def generate_index_page(target_path, link_style='relative', sort_order = 'title', tie_breaker = 'file_name', template_string=None):
    target_path = Path(target_path)
    if not target_path.is_dir():
        raise ValueError(f'{target_path} must be a directory')
    
    links = {}
    
    for md_file in target_path.glob('*.md'):
        obs_note = ObsNote(md_file)

        if link_style == 'relative':
            link = md_file.name
            link_text = f"[{obs_note.page_title}]({link})"
        elif link_style == 'wiki':
            link = md_file.stem
            link_text = f"[[{link}|{obs_note.page_title}]]"
        else:
            raise ValueError(f'link_style must be "relative" or "wiki"')
        
        if sort_order == 'title':
            sort_value = obs_note.title
        else:
            sort_value = obs_note.metadata.get(sort_order, None)
            if sort_value is None or not sort_value or isinstance(sort_value, list) or isinstance(sort_value, dict):
                print(f'"{sort_order}" is not a valid sorting key for {md_file}, skipping this file', file=sys.stderr)
                continue
            elif sort_order == "sessionNumber":
                sort_value = int(sort_value)
            else:
                try:
                    sort_value = TaelgarDate.parse_date_string(sort_value)
                except ValueError:
                    sort_value = str(sort_value)
                except AttributeError:
                    # catches things that are already datetime objects but this isn't great
                    pass
        
        if tie_breaker == 'file_name':
            sort_value = (sort_value, md_file.name)
        elif tie_breaker == 'title':
            sort_value = (sort_value, obs_note.title)
        else:
            sort_value = (sort_value, obs_note.metadata.get(tie_breaker, ""))

        if template_string:
            obs_note.metadata["link"] = link
            obs_note.metadata["link_text"] = link_text
            try:
                line_text = template_string.format(**obs_note.metadata)
            except KeyError:
                print(f'"{template_string}" is not a valid template string for {md_file}, using just link text for this file', file=sys.stderr)
                line_text = link_text
        else:
            line_text = link_text

        links[obs_note.page_title] = { "text" : line_text, "sort" : sort_value }
    
    # First, sort by primary key
    sorted_links = sorted(links.items(), key=lambda k: k[1]["sort"][0])

    # Then, within each group of ties, sort by secondary key
    final_sorted_links = []
    for key, group in itertools.groupby(sorted_links, key=lambda k: k[1]["sort"][0]):
        final_sorted_links.extend(sorted(group, key=lambda k: str(k[1]["sort"][1])))

    for key, value in final_sorted_links:
        print(value["text"])


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Generate an index page from a directory of markdown files')
    parser.add_argument('target_path', type=str, help='Path to the directory containing the markdown files')
    parser.add_argument('--link_style', type=str, default='relative', help='The style of links to generate.  Options are "relative" or "wiki"')
    parser.add_argument('--sort_order', type=str, default='title', help='The field to sort the links by.  Options are "title", "date", or any metadata field.')
    parser.add_argument('--template', type=str, default=None, help='A template string to use for each link.  The template string can contain any metadata field as a variable in curly braces.  For example, "{title} ({date})"')
    parser.add_argument('--tie_breaker', type=str, default='file_name', help='The field to use as a tie breaker when sorting.  Options are "file_name", "title", or any metadata field.')
    args = parser.parse_args()
    generate_index_page(args.target_path, args.link_style, args.sort_order,args.tie_breaker, args.template)
        
        
