import csv
import re
from pathlib import Path
import argparse
import os

MONTHNUM = {"Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04", "May": "05", "Jun": "06", "Jul": "07", "Aug": "08", "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12" }

parser = argparse.ArgumentParser()
parser.add_argument('--csv', "-i", required=True, help="The csv file to parse.")
parser.add_argument('--dir', "-d", required=True, help="Directory to write daily notes to. Events will be appended to existing notes by default.")
parser.add_argument('--secret', "-s", required=False, action="store_true", help="Optional. Sets all events from this file to secret.")
parser.add_argument('--people', "-p", required=False, nargs='*', help="Optional. Will add people specified to the people: metadata for all events from this file.")
parser.add_argument('--campaign', "-c", required=False, nargs='*', help="Optional. Will add campaigns specificed to the campaign: metadata for all events from this file, overwriting any column header logic.")
parser.add_argument('--cleanup', required=False, action="store_true", help="Clean up [ ] and { } information from old timelines.")
args = parser.parse_args()

## read each row

headers = []

with open(args.csv, 'r', encoding='utf-8-sig', newline='') as tl:
    timeline = csv.reader(tl, dialect='excel')
    for day in timeline:
        # skip header row and assign to headers list
        if day[0] == "Date":
            headers = day
            continue

        # parse the date assumes day month year format, with month a text string

        date_parts = day[0].split()
        print("Parsing date: " + "-".join(date_parts))
        event_date = date_parts[2] + "-" + MONTHNUM[date_parts[1][0:3]] + "-" + date_parts[0].zfill(2)

        # go through each column and print appropriate information

        for idx, day_event in enumerate(day):
            try:
                header = headers[idx]
            except IndexError:
                header = "Other Events"
            
            if header == "Date":
                continue

            # catch blank headers in csv
            if header == "" or header is None:
                header = "Other Events"

            ## make output dir
            event_dir = args.dir + "/" + date_parts[2] + "/" + MONTHNUM[date_parts[1][0:3]] 
            Path(event_dir).mkdir(parents=True, exist_ok=True)

            # open a file with the correct name
            event_file = event_dir + "/" + date_parts[0].zfill(2) + ".dailynote.md"

            
            # old code to make per-campaign notes 
            """
            fc_cat = "World Events"
            fc_name = "DM Events, " +  date_parts[0].zfill(2) + " " + date_parts[1][0:3]
            fc_tags = "event/unsorted"    
            frontmatter = ""
            endmatter = ""       

            if header == "Dunmari Frontier" or header == "Rumors and News":
                event_file = event_file + "_DunmarEvent.md"
                fc_cat = "Dunmari Frontier Events"
                fc_tags = "event/DuFr"
                fc_name = "Dunmari Frontier, " +  date_parts[0].zfill(2) + " " + date_parts[1][0:3]
                frontmatter = "%%^Campaign:DuFr%%"
                endmatter = "%%^End%%"
            elif header == "Great Library":
                event_file = event_file + "_GreatLibraryEvent.md"
                fc_cat = "Great Library Events"
                fc_tags = "event/GrLi"
                fc_name = "Great Library, " +  date_parts[0].zfill(2) + " " + date_parts[1][0:3]
                frontmatter = "%%^Campaign:GrLi%%"
                endmatter = "%%^End%%"
            elif header == "Secrets":
                event_file = event_file + "_DMEvent.md"
                fc_tags == "event/secret"
            else:
                event_file = event_file + "_WorldEvent.md"
            """
            
            if day_event:
                if args.cleanup:
                    # remove {GL} and other {} tags
                    day_event = re.sub(r'{\w+}', '', day_event)
                    day_event = re.sub(r'\[(.+?)\]', 'Learned from \g<1>.', day_event)

                # event metadata
                secret = "true" if (header == "Secrets" or args.secret) else "false"
                if header == "Great Library":
                    event_campaign = "\"GrLi\""
                elif header == "Dunmari Frontier" or header == "Rumors and News":
                    event_campaign = "\"DuFr\""
                else:
                    event_campaign = "\"\""
                
                if (args.campaign):
                    event_campaign = ",".join('"'+x+'"' for x in args.campaign)
                if (args.people):
                    event_people = ",".join('"'+x+'"' for x in args.people)
                else:
                    event_people = "\"\""

                header_string = "## " + header
                metadata_string = "{\"secret\": " + secret + ", \"campaign\": [ " + event_campaign + " ], \"title\": null, \"people\": [ " + event_people + " ], \"subtype\": null}\n"
                end_string = "\n---"

                # check if file already exists
                if os.path.isfile(event_file):
                    with open(event_file, "a") as ef:
                        print(header_string, file=ef)
                        print(metadata_string, file = ef)
                        print(day_event, file=ef)
                        print("\n---", file = ef)
                else: 
                    # file doesn't exist
                    with open(event_file, "w") as ef:
                        print("---", file=ef)
                        print("type: Event", file=ef)
                        print("subtype: Daily Note", file=ef)
                        print("taelgar-date: " + event_date, file=ef)
                        # print("fc-calendar: Taelgar", file=ef)
                        # print("fc-category: " + fc_cat, file=ef)
                        # print("fc-date: " + event_date, file=ef)
                        # print("fc-display-name: " + fc_name, file=ef)
                        # print("tags: [timeline, event/all, " + fc_tags + "]", file=ef)
                        print("---\n---", file=ef)
                        # end yaml  
                        print(header_string, file=ef)
                        print(metadata_string, file = ef)
                        print(day_event, file=ef)
                        print("\n---", file = ef)