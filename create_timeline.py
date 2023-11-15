import argparse
import json
import yaml
import os
import re
import sys
import datetime

def parse_date(datestring, get_first):
    default_month = 1 if get_first else 12
    default_day = 1 if get_first else 31

    if type(datestring) == str:
        year,*parts = datestring.split("-")
        month = parts[0] if len(parts) >= 1 else default_month
        day = parts[1] if len(parts) >= 2 else default_day
        return datetime.date(int(year),int(month),int(day))
    elif isinstance(datestring,datetime.date):
        return datestring
    elif type(datestring) == int:
        # presumably we just have a year that wasn't correctly parsed
        return datetime.date(datestring, default_month, default_day)


def get_md_files(directory):
    markdown_files = []
    for root, dirs, files in os.walk(directory):
        markdown_files += [os.path.join(root, file) for file in files if file.endswith('.md')]
    return markdown_files

def parse_daily_notes(text, metadata, file_name):
    # split text by '---' and parse each event separately
    events = text.split("---")
    events_array = []

    for event in events:
        if event == "" or event == "\n":
            continue

        event_lines = [i for i in event.split("\n") if i]
        try: 
            event_metadata = json.loads(event_lines[1])
        except json.decoder.JSONDecodeError:
            print("Failed to parse metadata at " + file_name + ", skipping events.", file=sys.stderr)
            return events_array
        
        event_metadata["header"] = event_lines[0].strip("# ")
        event_text = ''.join(event_lines[2:])

        events_array.append({ "text" : event_text, "metadata" : event_metadata })

    return events_array


def parse_event(text, metadata, file_name):
    # split text by '---' and parse each event separately
    events_array = []
    
    event_lines = text.split("\n")
    metadata["header"] = event_lines[1].strip("# ")
    event_text = ''.join(event_lines[2:])

    events_array.append({ "text" : event_text, "metadata" : metadata })

    return events_array


parser = argparse.ArgumentParser()
parser.add_argument('--dir', '-d', required=True, nargs="*")
parser.add_argument('--term', '-t', required=False, nargs="*")
parser.add_argument('--campaign', '-c', required=False, nargs="*")
parser.add_argument('--start', '-s',  required=False)
parser.add_argument('--end', '-e', required=False)
parser.add_argument("--style", default="note", required=False, choices=['note', 'section'])
args = parser.parse_args()

start_date = parse_date(args.start, True) if args.start else datetime.date(1, 1, 1)
end_date = parse_date(args.end, False) if args.end else datetime.date(9999, 12, 31)

md_file_list = []
for dir in args.dir:
    md_file_list += get_md_files(dir)

all_events = {}

## copied from convert_markdown, should abstract to a function

for file_name in md_file_list:
    # Open the input file
    with open(file_name, 'r', 2048, "utf-8") as input_file:
        lines = input_file.readlines()

    # if file is blank, move on
    if len(lines) == 0:
        continue

    # Check if the file starts with a metadata block
    metadata = dict()
    text_start = 0
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
            text_start = len(metadata_block) + 1
    
    file_text = ""
    if metadata and metadata.get("type") == "Event":
        file_text = ''.join(lines[text_start:]) 
        file_date = parse_date(metadata["taelgar-date"],True)
        if type(file_date) == int:
            file_date = datetime.date(file_date, 1, 1)

        if metadata.get("subtype") == "Daily Note":
            events = parse_daily_notes(file_text, metadata, file_name)
        else:
            events = parse_event(file_text, metadata, file_name)
    
        if file_date in all_events:
            all_events[file_date] = all_events[file_date] + events
        else:
            all_events[file_date] = events

#print out what you want

for date in sorted(all_events.keys()):
    datestring = str(date)
    display_events = []
    for date_event in all_events[date]:
        keep_event = True
        this_meta = date_event["metadata"]
        this_text= date_event["text"]

        # check for campaign
        if (args.campaign and keep_event):
            event_campaigns = this_meta.get("campaign", [])
            if any(i in event_campaigns for i in args.campaign):
                keep_event = True
            else:
                keep_event = False
        
        #check for terms
        if (args.term and keep_event):
            if any(i in this_meta.get("people", []) for i in args.term):
                # tagged with a term in the search lis
                keep_event = True
            elif any(x in this_text for x in args.term):
                # need to search
                keep_event = True
            else:
                keep_event = False
        
        #check for dates
        if keep_event and date >= start_date and date <= end_date:
            keep_event = True
        else:
            keep_event = False
        
        if keep_event:
            display_events.append(date_event)
        
    if display_events:
        secret_texts = []
        formatted_date = "- (DR:: " + datestring + ")"
        for pe in display_events:
            header = pe["metadata"].get("header", "Other Event")
            text = pe.get("text", "")
            secret = pe["metadata"].get("secret", False)
            if secret == False:
                display_string = formatted_date + " *(" + header + ")*: " + text
                print (display_string)
            else: 
                display_string = formatted_date + " *(" + header + ")*: " + text
                print (display_string)