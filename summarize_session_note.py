import os
import yaml
import json
import re
import tiktoken
from dotenv import load_dotenv
from openai import OpenAI

### SYSTEM PROMPT ###
### FOR SUMMARIZING SESSION NOTES ###

summary_sys_prompt = "You are a creative and careful assistant who is skilled in extracting summaries and meaningful content from text. "\
    "You will receive a query that consists of some context, followed by text. "\
    "This text will describe a narrative of one or more days, describing the events that happened in a fictional world. Your job is to summarize these narratives. "\
    "You will return a JSON object that contains four things: "\
    "1. tagline: this is a tagline of 3-8 words that could be used as a subtitle for the text; "\
    "it should capture the main event of the narrative succinctly and clearly, and ALWAYS start with the words *in which* "\
    "2. summary: this is no more than 100 words, in the form of a markdown list. each element of the list should succinctly, clearly, and accurately summarize a "\
    "main event from the narrative. Choose carefully to ONLY summarize the PRIMARY OR MOST IMPORTANT parts of the narrative. "\
    "Use the fewest possible items in the list to capture the main events of the narrative. "\
    "3. short_summary: this EXACTLY ONE SENTENCE and captures the primary gist of the narrative. "\
    "4. location: this is the location of the narrative, which can be either one or possibly two major places the events happen at or a phrase like on the road "\
    "between place1 and place2, although you will prefer to choose a single location if possible. "\
    "Your primary concern is summarization. Your goal is to extract the most important and relevant information from the text. "\
    "You will remember that this text describes events in a fictional world. The text you receive will be formatted in markdown format, "\
    "and you will ignore markdown formatting characters in your responses."


### NEED TO REFACTOR TO PULL COMMON FUNCTIONS INTO A SEPARATE FILE ###

def num_tokens_from_messages(messages, model="gpt-3.5-turbo-0613"):
    """From OpenAI cookbook: https://github.com/openai/openai-cookbook/blob/main/examples/How_to_count_tokens_with_tiktoken.ipynb"""
    """Return the number of tokens used by a list of messages."""
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        print("Warning: model not found. Using cl100k_base encoding.")
        encoding = tiktoken.get_encoding("cl100k_base")
    if model in {
        "gpt-3.5-turbo-0613",
        "gpt-3.5-turbo-16k-0613",
        "gpt-4-0314",
        "gpt-4-32k-0314",
        "gpt-4-0613",
        "gpt-4-32k-0613",
        }:
        tokens_per_message = 3
        tokens_per_name = 1
    elif model == "gpt-3.5-turbo-0301":
        tokens_per_message = 4  # every message follows <|start|>{role/name}\n{content}<|end|>\n
        tokens_per_name = -1  # if there's a name, the role is omitted
    elif "gpt-3.5-turbo" in model:
        print("Warning: gpt-3.5-turbo may update over time. Returning num tokens assuming gpt-3.5-turbo-0613.")
        return num_tokens_from_messages(messages, model="gpt-3.5-turbo-0613")
    elif "gpt-4" in model:
        print("Warning: gpt-4 may update over time. Returning num tokens assuming gpt-4-0613.")
        return num_tokens_from_messages(messages, model="gpt-4-0613")
    else:
        raise NotImplementedError(
            f"""num_tokens_from_messages() is not implemented for model {model}. See https://github.com/openai/openai-python/blob/main/chatml.md for information on how messages are converted to tokens."""
        )
    num_tokens = 0
    for message in messages:
        num_tokens += tokens_per_message
        for key, value in message.items():
            num_tokens += len(encoding.encode(value))
            if key == "name":
                num_tokens += tokens_per_name
    num_tokens += 3  # every reply is primed with <|start|>assistant<|message|>
    return num_tokens

def parse_markdown_file(file_path):
    """
    Reads a markdown file and returns its frontmatter as a dictionary and the rest of the text as a string.

    :param file_path: Path to the markdown file.
    :return: A tuple containing a dictionary of the frontmatter and a string of the markdown text.
    """
    with open(file_path, 'r', encoding='utf-8') as file:
        lines = file.readlines()

    # Check if the file starts with frontmatter (triple dashes)
    if lines and lines[0].strip() == '---':
        # Try to find the second set of triple dashes
        try:
            end_frontmatter_idx = lines[1:].index('---\n') + 1
        except ValueError:
            # Handle the case where the closing triple dashes are not found
            frontmatter = {}
            markdown_text = ''.join(lines)
        else:
            frontmatter = yaml.safe_load(''.join(lines[1:end_frontmatter_idx]))
            markdown_text = ''.join(lines[end_frontmatter_idx + 1:])
    else:
        frontmatter = {}
        markdown_text = ''.join(lines)
    return frontmatter, markdown_text

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
        sections_dict[header] = '\n'.join(section_content)

    return sections_dict

def get_session_summary(prompt, model="gpt-4-1106-preview", max_tokens=4000, system_prompt=summary_sys_prompt):
    input_messages = []
    input_messages.append({"role": "system", "content": system_prompt})
    input_messages.append({"role": "user", "content": prompt})
    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=input_messages,
        top_p=1.0,
        frequency_penalty=0.0,
        presence_penalty=0.0,
        temperature=0.75,
    )
    return response



load_dotenv()
client = OpenAI(
    # This is the default and can be omitted
    api_key=os.environ.get("OPEN_API_TAELGAR"),
)

session_note_path = "/Users/tim/Library/Mobile Documents/iCloud~md~obsidian/Documents/Taelgar/Campaigns/Dunmari Frontier/Session Notes/Session 2 (DuFr).md"
metadata, text = parse_markdown_file(session_note_path)
markdown_text = split_markdown_by_sections(text.splitlines())
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
    session_prompt = f"## Narrative\n{text}\n"

print(session_prompt)

context = "Context: this describes events happening to a group of adventurers called the Dunmar Fellowship, occurring in the D&D world of Taelgar."
prompt = context + "\n===\n" + session_prompt
summary = get_session_summary(prompt)
print(summary)

clean_resp = summary.choices[0].message.content.replace("```", "").replace("json", "").strip()
resp_data = json.loads(clean_resp)
print(resp_data)
tagline = resp_data["tagline"]
print("*" + tagline[0].lower() + tagline[1:] + "*")
print("\n## Summary\n    - ", end="")
print("\n    - ".join(resp_data["summary"]))
print("\n## Short Summary\n", end="")
print(resp_data["short_summary"])
print("\n## Location", end="")
print("\n    - " + resp_data["location"])