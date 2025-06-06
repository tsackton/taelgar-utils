import os
import yaml
import json
import re
import argparse
import datetime
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI
from taelgar_lib.ObsNote import ObsNote
from taelgar_lib.TaelgarDate import TaelgarDate

### SYSTEM PROMPT ###
### FOR SUMMARIZING SESSION NOTES ###

summary_sys_prompt = "You are a creative and careful assistant who is skilled in extracting summaries and meaningful content from text. "\
    "You will receive a query that consists of some context, followed by text. "\
    "This text will describe a narrative of one or more days, describing the events that happened in a fictional world. Your job is to summarize these narratives. "\
    "You will return a JSON object that contains five things: "\
    "1. title: this is a 1-5 word title that captures the main event of the narrative and would be suitable to use as a chapter title in a book; "\
    "2. tagline: this is a tagline of 5-10 words that could be used as a subtitle for the text; "\
    "it should capture the main event of the narrative succinctly and clearly, and ALWAYS start with the words *in which* "\
    "3. summary: this is no more than 100 words, in the form of a markdown list. each element of the list should succinctly, clearly, and accurately summarize a "\
    "main event from the narrative. Choose carefully to ONLY summarize the PRIMARY OR MOST IMPORTANT parts of the narrative. "\
    "Use the fewest possible items in the list to capture the main events of the narrative. "\
    "4. short_summary: this EXACTLY ONE SENTENCE and captures the primary gist of the narrative. "\
    "5. location: this is the location of the narrative, which can be either one or possibly two major places the events happen at or a phrase like on the road "\
    "between place1 and place2, although you will prefer to choose a single location if possible. "\
    "Your primary concern is summarization. Your goal is to extract the most important and relevant information from the text. "\
    "You will remember that this text describes events in a fictional world. The text you receive will be formatted in markdown format, "\
    "and you will ignore markdown formatting characters in your responses."


### NEED TO REFACTOR TO PULL COMMON FUNCTIONS INTO A SEPARATE FILE ###

# Custom dumper for handling empty values
class CustomDumper(yaml.SafeDumper):
    def represent_none(self, _):
        return self.represent_scalar('tag:yaml.org,2002:null', '')

# Add custom representation for None (null) values
CustomDumper.add_representer(type(None), CustomDumper.represent_none)


def split_markdown_by_sections(markdown_lines):
    """
    Splits a Markdown document (provided as a list of lines) into sections and returns a dictionary.
    The keys of the dictionary are the section names (with '#' removed), and the values are the text of each section.

    Args:
        markdown_lines (list of str): The Markdown document, split into lines.

    Returns:
        dict: A dictionary where keys are section names and values are the corresponding section text.
    """
    section_indices = [i for i, line in enumerate(markdown_lines) if re.match(r'^#+\s+.*$', line)]
    sections_dict = {}

    for i in range(len(section_indices)):
        start = section_indices[i] + 1  # Start from the line after the header
        header = markdown_lines[start - 1].lstrip('#').strip()
        end = section_indices[i + 1] if i + 1 < len(section_indices) else len(markdown_lines)
        section_content = [line for line in markdown_lines[start:end] if line.strip() != '']  # Exclude blank lines
        if header == "Narrative":
            sections_dict[header] = '\n\n'.join(section_content)
        else:
            sections_dict[header] = '\n'.join(section_content)
            
    return sections_dict

def get_session_summary(prompt, model="gpt-4o", system_prompt=summary_sys_prompt):
    input_messages = []
    input_messages.append({"role": "system", "content": system_prompt})
    input_messages.append({"role": "user", "content": prompt})
    response = client.chat.completions.create(
        model=model,
        messages=input_messages,
        top_p=1.0,
        frequency_penalty=0.0,
        presence_penalty=0.0,
        temperature=0.75,
    )
    return response

### MAIN ###

parser = argparse.ArgumentParser()
parser.add_argument('--file', '-f', required=True)
parser.add_argument('--gens', '-g', required=False)
parser.add_argument('--verbose', '-v', required=False, action="store_true")
parser.add_argument('--debug', '-vv', required=False, action="store_true")
parser.add_argument('--context', '-c', required=False)
parser.add_argument('--reload', '-r', required=False)
parser.add_argument('--backup', '-b', required=False, action="store_true")
parser.add_argument('--prompt', '-p', required=False)
args = parser.parse_args()
session_note_file = Path(args.file)
num_generations = 1 if not args.gens else int(args.gens)

## If context is provided as an argument, open the file and read it into context
if args.context:
    with open(args.context, 'r', encoding='utf-8') as file:
        context = file.read()
else:
    context = "the following narrative describes events happening to a group of adventurers called the Dunmar Fellowship, occurring in the D&D world of Taelgar."
context = "Context: " + context.strip() + "\n===\n"

## If context is provided as an argument, open the file and read it into context
if args.prompt:
    with open(args.prompt, 'r', encoding='utf-8') as file:
        summary_sys_prompt = file.read()


load_dotenv()
client = OpenAI(
    # This is the default and can be omitted
    api_key=os.environ.get("OPEN_API_TAELGAR"),
)

session_note_path = session_note_file.parent
session_note_name = session_note_file.stem

## make backup ##
if args.backup:
    session_note_backup = session_note_path / (session_note_name + ".bak")
    session_note_backup.write_text(session_note_file.read_text())

note = ObsNote(session_note_file, {})
markdown_text = split_markdown_by_sections(note.raw_text.splitlines())
narrative = ""
timeline = ""
if "Narrative" in markdown_text:
    narrative = markdown_text["Narrative"]
if "Timeline" in markdown_text:
    timeline = markdown_text["Timeline"]

if narrative and timeline:
    session_prompt = f"## Narrative\n{narrative}\n## Timeline\n{timeline}"
elif narrative:
    session_prompt = f"## Narrative\n{narrative}\n"
elif timeline:
    narrative = "\n".join([markdown_text[section] for section in markdown_text if section != "Timeline"])
    session_prompt = f"## Narrative\n{narrative}\n## Timeline\n{timeline}"
else:
    session_prompt = f"## Narrative\n{note.raw_text}\n"

if args.verbose or args.debug:
    print(f"Processing session note: {session_note_file}")

if args.debug:
    print(f"Using context: {context}")
    print(f"Using session prompt: {session_prompt}")

outputs = []

prompt = context + session_prompt
if args.reload:
    resp_data = json.loads(Path(args.reload).read_text())
else:
    for i in range(num_generations):
        if args.verbose:
            print(f"Generation {i+1} of {num_generations}")

        summary = get_session_summary(prompt)

        if args.verbose:
            print(f"Response: {summary.choices[0].message.content}")

        
        outputs.append(summary.choices[0].message.content)

        ## Parse the response
        clean_resp = summary.choices[0].message.content.replace("```", "").replace("json", "").strip()
        resp_data = json.loads(clean_resp)

        ## Save the response
        resp_id = None if args.reload else summary.id
        session_note_json = session_note_path / (session_note_name + "." + resp_id + ".json")
        session_note_json.write_text(json.dumps(resp_data, indent=4))

# Parse response
tagline = (resp_data["tagline"][0].lower() + resp_data["tagline"][1:]).strip()
info_box_title = resp_data["title"].strip()
summary = resp_data["summary"]
short_summary = resp_data["short_summary"].strip()
location = resp_data["location"].strip()
characters = ", ".join(["[[" + character + "]]" for character in note.metadata["players"]])

#replace Dunmar Fellowship or Fellowship with party
tagline = tagline.replace("Dunmar Fellowship", "party").replace("Fellowship", "party")

# Add to metadata
note.metadata["tagline"] = tagline
note.metadata["descTitle"] = info_box_title
if not note.metadata.get("name", None):
    note.metadata["name"] = note.metadata["campaign"] + " - Session " + str(note.metadata["sessionNumber"])
title = note.metadata["name"]

# Write to file
try:
    start_date = str(note.metadata["DR"])
except KeyError:
    start_date = None

try:
    end_date = str(note.metadata["DR_end"])
except KeyError:
    end_date = start_date

if start_date and start_date == end_date:
    taelgar_date_string = TaelgarDate.get_dr_date_string(start_date, dr=True)
elif start_date and end_date:
    taelgar_date_string = TaelgarDate.get_dr_date_string(start_date, dr=True) + " to " + TaelgarDate.get_dr_date_string(end_date, dr=True)
else:
    taelgar_date_string = "Unknown"
    
real_world_date_string = note.metadata["realWorldDate"].strftime("%A %b %d, %Y")
output_metadata = yaml.dump(note.metadata, sort_keys=False, default_flow_style=None, allow_unicode=True, width=2000, Dumper=CustomDumper)

with open(session_note_file, 'w', encoding='utf-8') as file:
    file.write(f"---\n{output_metadata}---\n")
    file.write(f"# {title}\n\n")
    file.write(f">[!info] {info_box_title}: {tagline}\n")
    file.write(f"> *Featuring: {characters}*\n")
    file.write(f"> *In Taelgar: {taelgar_date_string}*\n")
    file.write(f"> *On Earth: {real_world_date_string}*\n")
    file.write(f"> *{location}*\n\n")
    file.write(short_summary + "\n\n")
    if num_generations > 1:
        file.write("%% Other Generations\n")
        for i, output in enumerate(outputs):
            if i != num_generations - 1:
                file.write(f"Generation {i+1}\n")
                file.write(output + "\n")
        file.write("%%\n")
    file.write(f"## Session Info\n")
    file.write(f"### Summary\n- ")
    file.write("\n- ".join(summary))
    if (timeline):
        file.write(f"\n\n### Timeline\n{timeline}\n")
    for section in markdown_text:
        if section not in ["Narrative", "Timeline"]:
            file.write(f"\n### {section}\n{markdown_text[section]}\n\n")
    file.write(f"\n\n## Narrative\n{narrative}\n")

if args.verbose:
    print(f"Successfully wrote to {session_note_file}")