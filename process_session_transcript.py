import re
import textwrap
import argparse
import json
import tiktoken
import os
from dotenv import load_dotenv
from pathlib import Path
from openai import OpenAI

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
        #print("Warning: gpt-4 may update over time. Returning num tokens assuming gpt-4-0613.")
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

def clean_webvtt_transcription(text, wrap_length=None, names=None):
    # Split the text into lines and remove the first line "WEBVTT"
    lines = text.split('\n')[1:]

    cleaned_text = ""
    current_speaker = None
    current_line = ""

    for line in lines:
        # Skip empty lines and timestamp lines
        if line.strip() == "" or re.match(r'\d+\n?$', line) or "-->" in line:
            continue

        # Check if the line starts with a speaker name
        match = re.match(r'(^.+?):\s*(.*)', line)
        if match:
            speaker, content = match.groups()
            if speaker == current_speaker:
                # Continue the sentence for the same speaker
                current_line += " " + content
            else:
                # Finish the sentence for the previous speaker and start a new one
                if current_speaker:
                    if wrap_length:
                        wrapped_text = textwrap.fill(current_speaker + ": " + current_line.strip(), wrap_length, subsequent_indent='  ')
                        cleaned_text += wrapped_text + '\n'
                    else:
                        cleaned_text += current_speaker + ": " + current_line.strip() + '\n'
                current_speaker = speaker
                current_line = content.capitalize() + " "
        else:
            # Continue the sentence if no speaker is found
            current_line += " " + line

    # Add the last line
    if current_speaker:
        if wrap_length:
            wrapped_text = textwrap.fill(current_speaker + ": " + current_line.strip(), wrap_length)
            cleaned_text += wrapped_text
        else:
            cleaned_text += current_speaker + ": " + current_line.strip()

    # Post-processing: replace ' i ' with ' I '
    cleaned_text = re.sub(r'\bi\b', 'I', cleaned_text)

    # Post-processing: remove extra spaces
    cleaned_text = re.sub(r' +', ' ', cleaned_text)

    # Post-processing: replace names
    if names:
        # Replace names
        for name in names:
            speaker_text = name + ":"
            replacement_text = names[name] + ":"
            cleaned_text = cleaned_text.replace(speaker_text, replacement_text)

    return cleaned_text

def clean_raw_transcript(raw_transcript_file, globs):
    """
    Takes a raw Zoom transcript and cleans it up, producing a more readable transcript.
    :param: raw_transcript_file: the name of the raw transcript file
    :param: names: a dict of names to replace in the transcript
    :param: wrap_length: the maximum number of characters per line
    """

    wrap_length = globs.get('wrap_length')
    names = globs.get('names')

    # Read the raw transcript file
    with open(raw_transcript_file, 'r') as f:
        text = f.read()
    
    # Clean up the text
    text = clean_webvtt_transcription(text, wrap_length, names)

    # write the cleaned text to a new file
    cleaned_transcript = raw_transcript_file.with_suffix('.cleaned.txt')

    if cleaned_transcript.is_file():
        print("NOTICE: " + str(cleaned_transcript) + " already exists, not modifying.")
        return cleaned_transcript
    else:
        with open(cleaned_transcript, 'w') as f:
            f.write(text)

    return cleaned_transcript

def summarize_scenes(cleaned_transcript, globs):
    """
    This funcion reads in a cleaned transcript, splits it by scenes, and then generates a rolling summary of the scenes.
    :param: cleaned_transcript: the name of the cleaned transcript file
    """

    # Read the cleaned transcript file
    with open(cleaned_transcript, 'r') as f:
        text = f.readlines()

    detailed_summary = cleaned_transcript.with_suffix('.summary.txt')
    if detailed_summary.is_file():
        print("NOTICE: " + str(detailed_summary) + " already exists, not modifying.")
        return detailed_summary
    
    # Split the text into scenes, using markdown headers as scene markers and retaining scene titles
    scene_indexes = [i for i, line in enumerate(text) if re.match(r'^#+\s+.*$', line)]
    scenes = {}

    for i in range(len(scene_indexes)):
        start = scene_indexes[i] + 1  # Start from the line after the header
        header = text[start - 1].lstrip('#').strip()
        end = scene_indexes[i + 1] if i + 1 < len(scene_indexes) else len(text)
        scene_content = [line for line in text[start:end] if line.strip() != '']  # Exclude blank lines
        scenes[header] = '\n'.join(scene_content)
        
    # Generate a rolling summary of the scenes
    summary, context = summarize_scenes_helper(scenes, globs)

    summary_text = "# Detailed Summary\n\n" + summary + "\n\n# Short Summary\n\n" + context + "\n"

    with open(detailed_summary, 'w') as f:
        f.write(summary_text)

    return detailed_summary


def summarize_scenes_helper(scenes, globs):
    """
    This function takes a dict of scenes and generates a rolling summary of the scenes.
    :param: scenes: a dict of scenes
    """
    summary = ""
    context = ""
    for scene in scenes:
        print("Summarizing scene: " + scene)
        summary_result = gpt_summarize_individual_scene(context, scene, scenes[scene], globs)
        events = summary_result["detailed_events"]
        if isinstance(events, list):
            summary += "## " + scene + "\n" + "\n".join(events) + "\n"
        else:
            summary += "## " + scene + "\n" + str(events) + "\n"
        if isinstance(summary_result["short_summary"], list):
            context += "## " + scene + "\n" + "\n".join(summary_result["short_summary"]) + "\n"
        else:
            context += "## " + scene + "\n" + str(summary_result["short_summary"]) + "\n"
    return summary, context

def gpt_summarize_individual_scene(context, scene, scene_text, globs):
    """
    This function takes a scene and generates a summary of the scene.
    :param: context: the context for the scene
    :param: scene: the scene to summarize
    """
    max_tokens = min(globs.get('max_tokens_completion', 4000), 4000)
    sys_prompt = globs.get('sys_prompt_scene', "")
    model = globs.get('model', "gpt-4o")
    prompt = "Context: \n" + context + "\nTranscript of " + scene + ": \n" + scene_text
    client = globs.get('client')

    if globs.get('logging'):
        logging_path = globs.get('logging_path')
    else:
        logging_path = None


    # generate prompt and check tokens
    input_messages = []
    input_messages.append({"role": "system", "content": sys_prompt})
    input_messages.append({"role": "user", "content": prompt})
    response = get_gpt_summary(client, input_messages, model=model, max_tokens=max_tokens, logging_path=logging_path)
    clean_resp = response.choices[0].message.content.replace("```", "").replace("json", "").strip()
    json_string = re.sub(r'[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F-\x9F]', '', clean_resp)
    try:
        json.loads(json_string)
    except json.JSONDecodeError as e:
        print(f"JSON decoding error: {e}")
        print(f"Offending JSON string: {json_string}")
        raise
    return json.loads(json_string)


def get_gpt_summary(client, prompt, model="gpt-4o", max_tokens=3000, logging_path=None):
    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=prompt,
        top_p=1.0,
        frequency_penalty=0.0,
        presence_penalty=0.0,
        temperature=0.85,
    )

    if logging_path:
        logfile = logging_path / (response.id + ".log")
        print("Logging response to " + str(logfile))
        with open(logfile, 'w') as f:
            f.write("Prompt: " + str(prompt) + "\n")
            f.write("Response: " + str(response.choices[0].message.content) + "\n\n")
    return response

def generate_session_narrative(detailed_summary, globs):

    # Read the detailed summary file
    with open(detailed_summary, 'r') as f:
        text = f.read()

    final_narrative = detailed_summary.with_suffix('.narrative.md')
    if final_narrative.is_file():
        print("NOTICE: " + str(final_narrative) + " already exists, not modifying.")
        return final_narrative
    
    # Generate the narrative
    sys_prompt = globs.get('sys_prompt_narrative', "")
    max_tokens = min(globs.get('max_tokens_completion', 4000), 4000)
    model = globs.get('model', "gpt-4o")
    client = globs.get('client')
    if globs.get('logging'):
        logging_path = globs.get('logging_path')
    else:
        logging_path = None
    prompt = text
    input_messages = []
    input_messages.append({"role": "system", "content": sys_prompt})
    input_messages.append({"role": "user", "content": prompt})
    response = get_gpt_summary(client, input_messages, model=model, max_tokens=max_tokens, logging_path=logging_path)
    response_text = response.choices[0].message.content
    with open(final_narrative, 'w') as f:
        f.write(response_text)

    return final_narrative

def main():
    # Set up argument parsing
    parser = argparse.ArgumentParser(description='Clean up WebVTT transcription files.')
    parser.add_argument('transcript_file', type=str, help='Path to the WebVTT transcription file.')
    parser.add_argument('-w', '--wrap', type=int, help='Wrap text to specified length.', default=None)
    parser.add_argument('-n', '--names', type=str, help='Path to the names file.', default=None)
    # log all chatgpt responses
    parser.add_argument('-l', '--log', action='store_true', help='Log all chatgpt responses.', default=False)
    
    # Parse arguments
    args = parser.parse_args()
    names = {}

    if args.names:
        # Read the names file
        with open(args.names, 'r') as f:
            names = json.load(f)

    # OpenAI API key setup
    load_dotenv()
    client = OpenAI(
        api_key=os.environ.get("OPEN_API_TAELGAR")
    )

    # Global variables
    SYS_PROMPT_SCENE = """
    You specialize in assisting Dungeon Masters (DMs) in Dungeons & Dragons (D&D) by transforming session transcripts into precise, detailed bullet points. 
    Your summaries focus on events, decisions, and outcomes with an emphasis on in-character developments. 
    IMPORTANT: you provide detailed notes with specifics from the transcript; you avoid generalities like "the party uses combat tactics". 
    You focus on summarizing in-character outcomes rather than out-of-character mechanics, such as summarizing 'combat starts' instead of detailing initiative rolls. 
    You also correct transcript errors, highlight character names and the DM role, and distinguish between in-character and out-of-character dialogue. 
    You will recieve a transcript of a scene or part of a scene from a D&D session, and optional context that summarizes what has happened leading up to this scene. 
    You will return a JSON object with two entries: 'detailed_events' and 'short_summary'.
    The 'detailed_events' entry will be a list where each element in the list is a markdown bullet point summarizing an event in the scene.
    The 'short_summary' entry will be a short summary of the scene in no more than 2 sentences.
    Please double check that your response follows these instructions. It must be JSON, and the keys must be 'detailed_events' and 'short_summary', and the content must be a list of strings and a string, respectively.
    """

    SYS_PROMPT_SUBSCENE = """
    You specialize in assisting Dungeon Masters (DMs) in Dungeons & Dragons (D&D) by transforming session transcripts into precise, detailed bullet points. 
    Your summaries focus on events, decisions, and outcomes with an emphasis on in-character developments. 
    IMPORTANT: you provide detailed notes with specifics from the transcript; you avoid generalities like "the party uses combat tactics". 
    You focus on summarizing in-character outcomes rather than out-of-character mechanics, such as summarizing 'combat starts' instead of detailing initiative rolls. 
    You also correct transcript errors, highlight character names and the DM role, and distinguish between in-character and out-of-character dialogue. 
    You will recieve a transcript that represents part of a scene, and a summary in the form of a markdown list of the scene so far.  
    You will return a JSON object with two entries: 'detailed_events' and 'short_summary'.
    The 'detailed_events' entry will list the summary bullet points included in the prompt, followed by a list of new bullet points summarizing the subscene.
    The 'short_summary' entry will be a short summary of the entire scene in no more than 2 sentences.
    """

    SYS_PROMPT_NARRATIVE = """
    You specialize in assisting Dungeon Masters (DMs) in Dungeons & Dragons (D&D) by transforming precise, detailed bullet points from session notes into a narrative.
    You focus on a straightforward, factual storytelling style, prioritizing the accurate portrayal of events, characters, and dialogue. The narratives are crafted with less
    descriptive language, ensuring clarity and factual detail. The narratives will primarily be used as reference for players or DMs to recall the events of the session and 
    record the details of what happened. You will follow the following style guide:
    1. Expository Narrative Style: The narrative extensively uses exposition to describe settings, events, and character actions, with a focus on providing comprehensive 
    background information through descriptive narration.
    2. Complex Sentence Structure: The writing frequently employs complex sentences with multiple clauses, providing detailed and nuanced descriptions and thoughts, 
    enhancing the depth of the narrative.
    3. Sequential and Detailed Progression: The text follows a clear, linear progression of events, with each scene and action described in a methodical and 
    detailed manner, emphasizing a step-by-step narrative flow.
    4. Balanced Descriptive and Dialogic Elements: There is a balance between descriptive narration and dialogue, with both elements used effectively to convey the story 
    and develop characters, ensuring a dynamic and engaging narrative.
    """

    MAX_TOKENS_CONTEXT = 48000


    ## put parameters in globs for passing around
    globs = {}
    globs['sys_prompt_scene'] = SYS_PROMPT_SCENE
    globs['sys_prompt_subscene'] = SYS_PROMPT_SUBSCENE
    globs['sys_prompt_narrative'] = SYS_PROMPT_NARRATIVE
    globs['max_tokens_context'] = MAX_TOKENS_CONTEXT
    globs['wrap_length'] = args.wrap
    globs['names'] = names
    globs['model'] = "gpt-4o"
    globs['client'] = client
    globs['logging'] = args.log
    globs['logging_path'] = Path(args.transcript_file).parent

    # Step (a) and (b)
    cleaned_transcript = clean_raw_transcript(Path(args.transcript_file), globs)

    # Step (c)
    input("Please add scene markers to the cleaned transcript file " + str(cleaned_transcript) + " and press Enter to continue...")

    # Step (d) and (e)
    detailed_summary = summarize_scenes(cleaned_transcript, globs)

    # Step (e) continued
    input("Please edit the detailed bullet points in " + str(detailed_summary) + " and press Enter to continue...")

    # Step (f)
    generate_session_narrative(detailed_summary, globs)

    print("Processing complete.")

if __name__ == "__main__":
    main()
