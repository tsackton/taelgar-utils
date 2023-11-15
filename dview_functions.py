from metadataUtils import *

## DVIEW FUNCTIONS

def get_PageDatedValue(metadata):

    # Setting default values
    defaultPreexistError = "**(doesn't yet exist)**"
    defaultStart = "created"
    defaultEnd = "destroyed"
    defaultEndStatus = "destroyed"
    pageStartDate = get_page_start_date(metadata)
    pageEndDate = get_page_end_date(metadata)
    currentDate = get_current_date(metadata)

    # Set start, end, text for each type
    if metadata["type"] in ["NPC", "PC", "Ruler"]:
        defaultPreexistError = "**(not yet born)**"
        defaultStart = "b."
        defaultEnd = "d."
        defaultEndStatus = "died"
    elif metadata["type"] == "Building":
        defaultPreexistError = "**(not yet built)**"
        defaultStart = "built"
    elif metadata["type"] == "Item":
        defaultPreexistError = "**(not yet created)**"
        defaultStart = "created"
    elif metadata["type"] == "Place":
        defaultPreexistError = "**(not yet founded)**"
        defaultStart = "founded"

    # Overriding defaults with metadata values if they exist
    preExistError = metadata.get("preExistError", defaultPreexistError)
    startPrefix = metadata.get("startPrefix", defaultStart)
    endPrefix = metadata.get("endPrefix", defaultEnd)
    endStatus = metadata.get("endStatus", defaultEndStatus)

    # Logic to determine the output based on various conditions
    
    ## Page start in future:  ```(not exist text)```
    if pageStartDate and pageStartDate > currentDate:
        return preExistError

    ## Page start and page end defined, start after end: ```Time Traveler, Check your YAML```

    if pageStartDate and pageEndDate and pageStartDate > pageEndDate:
        return "**(timetraveler, check your YAML)**"
    
    ## Page start and page end defined, end in past: ```(startPrefix) (existenceDate) - (end prefix) (end date) (endStatus) at (age) years```
    
    if pageStartDate and pageEndDate and pageEndDate <= currentDate:
        age = get_age(pageEndDate, pageStartDate)
        return f"{startPrefix} {display_date(pageStartDate, full=False)} - {endPrefix} {display_date(pageEndDate, full=False)} {endStatus} at {age} years old"
  
    ## Page start and page end defined, end in future: ```(startPrefix) (existenceDate) ((age) years old)```

    if pageStartDate and pageEndDate and pageEndDate > currentDate:
        age = get_age(currentDate, pageStartDate)
        return f"{startPrefix} {display_date(pageStartDate, full=False)} ({age} years old)"
    
    ## Page start defined and page end not defined: ```(startPrefix) (existenceDate) ((age) years old)```

    if pageStartDate and not pageEndDate:
        age = get_age(currentDate, pageStartDate)
        return f"{startPrefix} {display_date(pageStartDate, full=False)} ({age} years old)"
    
    ## Page start not defined page end defined, page end in future: empty

    if not pageStartDate and pageEndDate and pageEndDate > currentDate:
        return ""
   
    ## Page start not defined page end defined, page end in past: ```(end prefix) (end date) (endStatus)```

    if not pageStartDate and pageEndDate and pageEndDate <= currentDate:
        return f"{endPrefix} {display_date(pageEndDate, full=False)} {endStatus}"
 
    ## Page start not defined, page end not defined: empty
    
    if not pageStartDate and not pageEndDate:
        return ""

def get_RegnalValue(metadata):
    currentDate = get_current_date(metadata)
    reignStartDate = clean_date(metadata["reignStart"]) if "reignStart" in metadata else None
    reignEndDate = clean_date(metadata["reignEnd"], end=True) if "reignEnd" in metadata else None
    pageStartDate = get_page_start_date(metadata)
    pageEndDate = get_page_end_date(metadata)
    
    # If the reignStart is not set, output nothing.

    if not reignStartDate:
        return ""
    
    # If the reignStart is after the target date, output nothing.

    if reignStartDate > currentDate:
        return ""
    
    # If the reignEnd is not set, set to page end date
    if reignEndDate is None:
        reignEndDate = pageEndDate 

    # If the reignEnd and in the past, is defined: ```reigned (reign start) - (reign end) ((age) years)```
    if reignEndDate and reignEndDate <= currentDate:
        age = get_age(reignEndDate, reignStartDate)
        return f"reigned {display_date(reignStartDate, full=False)} - {display_date(reignEndDate, full=False)} ({age} years)"
    
    # # If the reignEnd is not defined, or in the future: ```reigning since (reign start) ((age) years)```
    if (reignEndDate and reignEndDate > currentDate) or reignEndDate is None:
        age = get_age(currentDate, reignStartDate)
        return f"reigning since {display_date(reignStartDate, full=False)} ({age} years)"

def get_HomeWhereabouts(metadata): 
    # Gets the Page Existence Date and the Target Date (see Page Dates)

    pageStartDate = get_page_start_date(metadata)
    pageEndDate = get_page_end_date(metadata)
    currentDate = get_current_date(metadata)

    # Sets the "page exists" flag to true if the Page End Date is defined Page End Date is before the Target Date
    pageExists = True if ((pageEndDate and pageEndDate >= currentDate) or (pageEndDate is None)) else False

    # If the Page Existence Date is defined Target Date is before the Page Existence Date, it exits with no output.
    if pageStartDate and pageStartDate > currentDate:
        return ""
    
    # calculate known whereabouts
    locations = parse_whereabouts(metadata, debug=False)
    # It outputs between 1 and 2 lines.
    # Line 1: If the origin output flag is true: "Originally from: (origin)"
    # Line 2: If the home output flag is true, and the page exists flag is true: "Based in: (home)"
    # Line 2: If the home output flag is true, and the page exists flag is false: "Lived in: (home)"

    output_string = []

    if locations["origin"]["output"]:
        output_string.append(f"Originally from: {parse_loc_string(locations['origin']['value'],metadata)}")
    if locations["home"]["output"] and pageExists:
        output_string.append(f"Based in: {parse_loc_string(locations['home']['value'],metadata)}")
    if locations["home"]["output"] and not pageExists:
        output_string.append(f"Lived in: {parse_loc_string(locations['home']['value'],metadata)}")

    return "\n".join(output_string)

def get_CurrentWhereabouts(metadata):

    pageStartDate = get_page_start_date(metadata)
    pageEndDate = get_page_end_date(metadata)
    currentDate = get_current_date(metadata)

    # Sets the "page exists" flag to true if the Page End Date is defined Page End Date is before the Target Date
    pageExists = True if ((pageEndDate and pageEndDate >= currentDate) or (pageEndDate is None)) else False

    # If the Page Existence Date is defined Target Date is before the Page Existence Date, it exits with no output.
    if pageStartDate and pageStartDate > currentDate:
        return ""
    
     # calculate known whereabouts
    locations = parse_whereabouts(metadata, debug=False)

    output_string = []

        
    # It outputs between 1 and 2 lines.
    # Line 1: If the last known location output flag is true, "Last known Location (as of lastknown.date): (lastknown)"
    # Line 2: If the current location output flag is true, and the page exists flag is true: "Current location (as of target date): (current)"

    if locations["last"]["output"]:
        output_date = display_date(locations['last']['date'])
        output_string.append(f"Last known location (as of {output_date}): {parse_loc_string(locations['last']['value'],metadata)}")
    if locations["current"]["output"] and pageExists:
        output_string.append(f"Current location (as of {display_date(currentDate)}): {parse_loc_string(locations['current']['value'],metadata)}")

    return "\n".join(output_string) 