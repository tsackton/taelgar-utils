
import os
from pathlib import Path
import urllib.parse 
import sys
from dateFunctions import *

"""
Helper functions for output control
"""

def get_link(string, metadata):
    """
    Takes a string and a metadata dictionary that has a links field and a file name
    Returns a markdown link to the string if it is in the links field, otherwise returns the string
    """
    links = metadata["links"]
    file = metadata["file"]
    if string in links:
        dest = links[string]
        orig = links[Path(file).stem].parent
        linkpath = os.path.relpath(dest,orig)
        return "[" + string + "](" + urllib.parse.quote(linkpath) + ")"
    else:
        return string

def get_tags_to_output():
    """
    Returns a list of tags to output even if they are not included in spec
    """
    return(["sessionStartTime", "sessionEndDate", "sessionEndTime", "summary"])

def parse_loc_string(string, metadata):
    """
    Adds links to pieces of a comma-separated location string
    """
    pieces = string.split(",")
    for piece in pieces:
        piece = piece.strip()
        piece = get_link(piece, metadata)
    return ", ".join(pieces)

def loc_join(l):
    """
    Takes a string or a list of location elements, potentially including one or more empty strings or Nones
    Returns a string with the elements joined by commas, with empty strings and Nones removed
    Returns "" if given a falsey value
    """

    if not l:
        return ""
    
    if isinstance(l, str):
        return l

    # Check if the input is a list
    if isinstance(l, list):
        # Process each element in the list
        processed_list = [item if isinstance(item, str) else str(list(item.values())[0]) for item in l if item is not None and item != ""]

        if len(processed_list) == 1:
            return processed_list[0]
        else:
            return ', '.join(processed_list)

    # Return an empty string for other types
    return ""


"""
Helper functions to clean and update metadata
"""

def update_metadata(metadata, metadata_orig):

    """
    delete endStatus, startPrefix, endPrefix, etc and create displayDefaults instead
    delete lastSeenByParty and create campaignInfo instead
    delete type and instead add relevant tag (person, place, thing, etc, with for now person/pc and person/ruler)
    delete blank metadata except for a small handful of key things: tags, name,
      born/species/ancestry/gender for people, player for PC, reignStart for rulers, partOf, placeType for locations

    329 type: NPC
    33 type: Ruler
    42 type: PC   
    22 type: Organization
    6 type: Building
    8 type: Item
    12 type: Location
    2 type: Place

    4 type: Session Notes
    10 type: SessionNote
    1 type: Testing

    """
    # print("Checking metadata", file=sys.stderr)

    ## set type of metadata to "place" if in gazeeter
    basename=Path(metadata["file"]).stem
    pathtext = str(metadata["file"].lower())
    # print(pathtext, file=sys.stderr)
    if ("type" in metadata and metadata["type"] is None) or ("type" not in metadata):
        if "gazetteer" in pathtext:
            # print("place", file=sys.stderr)
            metadata["type"] = "Place"
        elif "people" in pathtext:
            metadata["type"] = "Person"

    metadata_default = { "tags" : [], 
                      "displayDefaults" : { "startStatus" : "created",
                                           "startPrefix" : "created",
                                           "endPrefix" : "destroyed",
                                           "endStatus" : "destroyed"}, 
                      "campaignInfo" : [],
                      "name" : metadata["name"] if "name" in metadata else basename }
    
    clean_metadata = metadata_default.copy()

    ## First we update tags, to insert type
    if "type" in metadata and metadata["type"] is not None:
        if metadata["type"] in ["PC", "Ruler", "NPC"]:
            clean_metadata["tags"].append("person")
            if metadata["type"] != "NPC":
                clean_metadata["tags"].append(metadata["type"].lower())   
        elif metadata["type"] in ["Place", "Location", "Building"]: 
            clean_metadata["tags"].append("place")
            if metadata["type"] == "Building":
                clean_metadata["tags"].append("place/building")
        elif metadata["type"] == "Organization":
            clean_metadata["tags"].append("organization")
        elif metadata["type"] == "Item":
            clean_metadata["tags"].append("thing")
            clean_metadata["tags"].append("thing/item")
        elif metadata["type"] == "Session Notes" or metadata["type"] == "SessionNote":
            clean_metadata["tags"].append("session-note")
    
    old_tags = metadata["tags"] if "tags" in metadata else None
    if old_tags is not None:
        for tag in old_tags:
            if tag is None: 
                continue
            tag = tag.lower()
            if tag == "stub":
                clean_metadata["tags"].append("status/stub")
            elif tag.startswith("npc/"):
                ## remove NPC prefix from NPC heirarchical tags
                ## e.g., NPC/DuFr/met -> DuFr/met
                tag_parts = tag.split("/")
                if len(tag_parts) > 2:
                   clean_metadata["tags"].append("/".join(tag_parts[1:]))
                if len(tag_parts) == 2:
                    clean_metadata["tags"].append(tag_parts[1])
            else:
                clean_metadata["tags"].append(tag)
    
    ## Next we update displayDefaults
    ## Tags contain things like person, person/pc
    ## first check to see if we have a person, place, thing, etc

    tag_set = {item for s in clean_metadata["tags"] for item in s.split('/')}

    if "person" in tag_set:
        clean_metadata["displayDefaults"]["startStatus"] = "born"
        clean_metadata["displayDefaults"]["startPrefix"] = "b."
        clean_metadata["displayDefaults"]["endPrefix"] = "d."
        clean_metadata["displayDefaults"]["endStatus"] = "died"
        new_metadata = { "born" : metadata["born"] if "born" in metadata else None,
                         "species" : metadata["species"] if "species" in metadata else None,
                         "ancestry": metadata["ancestry"] if "ancestry" in metadata else None,
                         "gender" : metadata["gender"] if "gender" in metadata else None }
        if "species" in metadata and metadata["species"] == "elf":
            new_metadata = { "born" : metadata["born"] if "born" in metadata else None,
                            "ka" : metadata["ka"] if "ka" in metadata else None,
                            "species" : metadata["species"] if "species" in metadata else None,
                            "ancestry": metadata["ancestry"] if "ancestry" in metadata else None,
                            "gender" : metadata["gender"] if "gender" in metadata else None }
        if "pc" in tag_set:
            new_metadata["player"] = metadata["player"] if "player" in metadata else None
        if "ruler" in tag_set:
            new_metadata["reignStart"] = metadata["reignStart"] if "reignStart" in metadata else None

    elif "place" in tag_set:
        clean_metadata["displayDefaults"]["startStatus"] = "founded"
        clean_metadata["displayDefaults"]["startPrefix"] = "founded"
        clean_metadata["displayDefaults"]["endPrefix"] = "destroyed"
        clean_metadata["displayDefaults"]["endStatus"] = "destroyed"

        if "partOf" in metadata and metadata["partOf"] is not None:
            partOf = metadata["partOf"]
        elif "parentLocation" in metadata and metadata["parentLocation"] is not None:
            partOf = metadata["parentLocation"]
        else:
            partOf = None

        new_metadata = { "placeType" : metadata["placeType"] if "placeType" in metadata else None,
                         "partOf" : partOf }
        
    elif "organization" in tag_set:
        clean_metadata["displayDefaults"]["startStatus"] = "founded"
        clean_metadata["displayDefaults"]["startPrefix"] = "founded"
        clean_metadata["displayDefaults"]["endPrefix"] = "disbanded"
        clean_metadata["displayDefaults"]["endStatus"] = "disbanded"
        new_metadata = {}
    else:
        clean_metadata["displayDefaults"]["startStatus"] = "created"
        clean_metadata["displayDefaults"]["startPrefix"] = "created"
        clean_metadata["displayDefaults"]["endPrefix"] = "destroyed"
        clean_metadata["displayDefaults"]["endStatus"] = "destroyed"
        new_metadata = {}

    ## Next we update campaignInfo
    if "lastSeenByParty" in metadata and metadata["lastSeenByParty"] is not None and metadata["lastSeenByParty"]:
        for partyInfo in metadata["lastSeenByParty"]:
            campaignInfo = {"campaign" : partyInfo["prefix"], "date" : partyInfo["date"], "type" : "met"}
            clean_metadata["campaignInfo"].append(campaignInfo)

    # add new_metadata to clean_metadata even if None
    for key in new_metadata:
        # print(key, new_metadata[key], file=sys.stderr)
        clean_metadata[key] = new_metadata[key]

    ## now pass along non-empty keys from original metadata
    for key in metadata:
        if metadata[key] is not None and metadata[key] and key not in clean_metadata:
            if key not in ["tags", "startStatus", "endStatus", "startPrefix", "endPrefix", "preExistError", 
                           "lastSeenByParty", "born", "species", "reignStart", "ancestry", "gender", "parentLocation", 
                           "placeType", "partOf", "player", "name", "file", "override_year", "directory", "links", "type"]:
                clean_metadata[key] = metadata[key]
    ## print(clean_metadata, file=sys.stderr)

    clean_metadata["tags"] = list(set(clean_metadata["tags"]))

    if clean_metadata == metadata_default:
        return None
    return clean_metadata

def clean_metadata_old(metadata, metadata_default, guess_type=False):

    """
    Doesn't work anymore
    """

    # takes as input an metadata dictionary, and returns an updated metadata dictionary according to the speck
    # if guess_type is true, attempts to guess the type based on path

    # for each key in metadata_default, check to see if key exists in metadata. if yes, take value. else, use default or leave blank

    metadata_fixed = dict()

    for key in metadata_default:
        if key in metadata and metadata[key] is not None:
            metadata_fixed[key] = metadata[key]
        else:
            metadata_fixed[key] = metadata_default[key]
    
    # special cleanup for whereabouts

    ## if we have old home, origin, location tags, convert those to whereabouts; location tags get current date
    ## if we have whereabouts, check each entry and fix up, but return in same order

    ## procedure is: first check for whereabouts in fixed, and clean up
    ## then add additional whereabouts lines as needed from home, origin, location, tags
    
    if "whereabouts" in metadata_fixed:
        #we have whereabouts
        #get born date to remove from start if needed
        born = clean_date(metadata_fixed["born"]) if "born" in metadata_fixed else None
        metadata_fixed["whereabouts"] = clean_whereabouts(metadata_fixed["whereabouts"],born)
    
    if ("origin" in metadata and metadata["origin"]) or ("originRegion" in metadata and metadata["originRegion"]): 
        place = metadata["origin"] if "origin" in metadata else None
        region = metadata["originRegion"] if "originRegion" in metadata else None
        new_home = {'type': "home", 'start': "", 'end': "", 'location': loc_join([place,region])}
        metadata_fixed["whereabouts"].append(new_home)

    if ("home" in metadata and metadata["home"]) or ("homeRegion" in metadata and metadata["homeRegion"]): 
        place = metadata["home"] if "home" in metadata else None
        region = metadata["homeRegion"] if "homeRegion" in metadata else None
        new_home = {'type': "home", 'start': "", 'end': "", 'location': loc_join([place,region])}
        metadata_fixed["whereabouts"].append(new_home)
    
    if ("location" in metadata and metadata["location"]) or ("locationRegion" in metadata and metadata["locationRegion"]): 
        place = metadata["location"] if "location" in metadata else None
        region = metadata["locationRegion"] if "locationRegion" in metadata else None
        date=display_date(get_current_date(metadata))
        new_loc = {'type': "away", 'start': date, 'end': "", 'location': loc_join([place,region])}
        metadata_fixed["whereabouts"].append(new_loc)

    ## update obselete tags

    # yearOverride - replaced by pageTargetDate

    metadata_fixed["pageTargetDate"] = metadata["yearOverride"] if "yearOverride" in metadata else metadata_fixed["pageTargetDate"]
    
    # campaign - replaced by affiliations
    # Assuming 'type' is a variable you've defined earlier
    if type == "PC" and "campaign" in metadata:
        # Initialize metadata_fixed["affiliations"] as a list if it doesn't exist or is None
        if "affiliations" not in metadata_fixed or metadata_fixed["affiliations"] is None:
            metadata_fixed["affiliations"] = []

        # Now safely append to metadata_fixed["affiliations"]
        metadata_fixed["affiliations"].append(metadata["campaign"])
    
    # home, homeRegion, location, locationRegion, origin, originRegion - replaced by whereabouts, seea bove

    # realDate: replaced with realWorldDate
    if "realWorldDate" in metadata_fixed:
        metadata_fixed["realWorldDate"] = metadata["realDate"] if "realDate" in metadata else metadata_fixed["realWorldDate"]
    
    # taelgar-date: replaced with DR
    # taelgar-date-end: replaced with DR_end
    # DR-end replaced with DR_end

    if "DR" in metadata_fixed:
        metadata_fixed["DR"] = metadata["taelgar-date"] if "taelgar-date" in metadata else metadata_fixed["DR"]
    if "DR_end" in metadata_fixed:
        metadata_fixed["DR_end"] = metadata["taelgar-date-end"] if "taelgar-date-end" in metadata else metadata_fixed["DR_end"]
        metadata_fixed["DR_end"] = metadata["DR-end"] if "DR-end" in metadata else metadata_fixed["DR_end"]

    # currentOwner: replaced with owner

    if "owner" in metadata_fixed:
        metadata_fixed["owner"] = metadata["currentOwner"] if "currentOwner" in metadata else metadata_fixed["owner"]
    
    # dbbLink: replace with ddbLink (d d beyond link)
    if "ddbLink" in metadata_fixed:
        metadata_fixed["ddbLink"] = metadata["dbbLink"] if "dbbLink" in metadata else metadata_fixed["ddbLink"]

    # tag: typo for tags; replace with tags
    if "tag" in metadata:
        metadata_fixed["tags"].append(metadata["tag"])

    if "created" in metadata_fixed:
        metadata_fixed["created"] = metadata["built"] if "built" in metadata else metadata_fixed["created"]

    return(metadata_fixed)

def clean_whereabouts(whereabouts, born):

    whereabouts_clean = []

    for loc in whereabouts:
        if "start" in loc:
            start = loc["start"]
        elif "date" in loc:
            start = loc["date"]
        else:
            start = ""

        if "end" in loc:
            end = loc["end"]
        else:
            end = ""
        
        if "location" in loc:
            location = loc["location"]
        elif "place" in loc or "region" in loc:
            place = loc["place"] if "place" in loc else None
            region = loc["region"] if "region" in loc else None
            location = loc_join([place, region])
        else:
            location = ""
        
        if "type" in loc:
            type = loc["type"]
            if type == "home" or type == "origin":
                type = "home"
            else:
                type = "away"
        else:
            type = "away"
    
        #check start date
        if display_date(clean_date(start),full=True) == display_date(clean_date(born),full=True):
            start = ""

        new_loc = {"type": type, "start": start, "end": end, "location": location}
        whereabouts_clean.append(new_loc)

    return whereabouts_clean

### NOT EDITED BELOW HERE

def parse_whereabouts(metadata, target_date, debug = False):
    """
    Takes as input a metadata dictionary, and optionally a current date
    Reports as output a dict of dicts, with one dict for each type of location:
        current: the exact known whereabouts at target date
        home: the home whereabouts at target date
        origin: the origin whereabouts
        last: the last known whereabouts
    
    Each location dict has the following fields:
        value: the location string
        date: the date of the location
        duration: the duration of the location in days, with fractional days allowed

    """

    ## get target date for page: this is current date
    ## defined as pageTargetDate if it exists, otherwise target_date passed to function
    if "pageTargetDate" in metadata and metadata["pageTargetDate"] is not None:
        target_date = clean_date(metadata["pageTargetDate"])
    else:
        target_date = clean_date(target_date)




    whereabouts = metadata["whereabouts"]
    target_date = get_current_date(metadata)
    died_date = clean_date(metadata["died"]) if "died" in metadata else None
    if died_date is not None:
        target_date = died_date

    locations = {"exact": {}, "home": {}, "origin": {}, "last": {}, "current": {}}

    locations["exact"]["value"] = None
    locations["exact"]["output"] = False
    locations["exact"]["date"] = None
    locations["exact"]["duration"] = None
    locations["home"]["value"] = None
    locations["home"]["output"] = False
    locations["home"]["date"] = None
    locations["home"]["duration"] = None
    locations["origin"]["value"] = None
    locations["origin"]["output"] = False
    locations["origin"]["date"] = None
    locations["origin"]["duration"] = None
    locations["last"]["value"] = None
    locations["last"]["output"] = False
    locations["last"]["date"] = None
    locations["last"]["duration"] = None
    locations["last"]["end"] = None
    locations["current"]["value"] = None
    locations["current"]["output"] = False
    locations["current"]["date"] = None
    locations["current"]["duration"] = None

    home_count = 0 

    for whereabout in whereabouts:
        ## define variables ##

        # a logical end date is the start date if the end date is undefined, otherwise the start date
        start = clean_date(whereabout["start"]) if "start" in whereabout else None
        end = clean_date(whereabout["end"], end=True) if "end" in whereabout else None
        logical_end = end if end is not None else start
        type = whereabout["type"] if whereabout["type"] is not None else None
        if type is None:
            raise ValueError("Whereabouts must have a type")
        elif type == "away" and start is None:
            raise ValueError("Away whereabouts must have a start date")
        
        type = "home" if type == "origin" else type #clean up old origin type, which is now home

        # a location is constructed from the location , place, and region fields
        # location field is preferred if multiple fields exist
        location = whereabout["location"] if "location" in whereabout else None
        place = whereabout["place"] if "place" in whereabout else None
        region = whereabout["region"] if "region" in whereabout else None
        value = location if location is not None else ",".join([place, region])
        if value is None:
            value = "Unknown"
        
        home_count = home_count + 1 if type == "home" else home_count
        
        # Find the "exact known whereabouts".
        # Candidate set = Take all of the whereabouts with type = away
        # Start is defined and before or equal to target date
        # Logical end is after or equal to target date
        # If there are multiple items in the candidate set, select the one with the smallest duration between the logic end date and the start date
        # If there are no items, the "exact known whereabouts" is undefined

        if type == "away" and start is not None and start <= target_date and (logical_end >= target_date):
            if locations["exact"]["value"] is None or (logical_end - start) < locations["exact"]["duration"]:
                locations["exact"]["value"] = value
                locations["exact"]["date"] = target_date
                locations["exact"]["duration"] = logical_end - start
                locations["exact"]["output"] = True
    
        # Find the "home whereabouts".
        # Candidate set = Take all of the whereabouts with type = home
        # Start is unset or before or equal to target date and end (not logical end) is after or equal to target date
        # Start is unset or before or equal to target date and end is unset
        # If there are multiples reduce the set to all of the items with the latest start date that is before the target date. 
        # An unset start date should be treated as the earliest possible date
        # If there are still multiples (because multiple items have the same or blank start date), take the one that is lexically last in the yaml
        # If there are no items, the "home whereabouts" is undefined

        if type == "home" and ((start is None or start <= target_date) and (end is None or end >= target_date)):
            home_implied_start = start if start is not None else clean_date(int(1))
            # if we don't have a home, set one
            if locations["home"]["value"] is None:
                locations["home"]["value"] = value
                locations["home"]["date"] = home_implied_start
                locations["home"]["output"] = True
            # if we have a home, skip if the start is earlier than the current home
            elif home_implied_start < locations["home"]["date"]:
                continue
            # we have a home, but we've encountered a new home listed later in the yaml
            # or a new home with a later date
            # replace old home with new home
            else: 
                locations["home"]["value"] = value
                locations["home"]["date"] = home_implied_start
                locations["home"]["output"] = True
        
        # Find the "last known whereabout"
        # Candidate set = Take all of the whereabouts where type = away
        # Start is before or equal to target
        # If there are multiples, take start date that is closest to the target date

        if type == "away" and start is not None and start <= target_date:
            if locations["last"]["value"] is None or start > locations["last"]["date"]:
                locations["last"]["value"] = value
                locations["last"]["date"] = start
                locations["last"]["output"] = True
                locations["last"]["end"] = end
        
        # Find the "origin whereabout"
        # Candidate set = Take all of the whereabouts where type = home and start = undefined
        # If there are multiples, select the lexically first one in the yaml
        if type == "home" and start is None:
            if locations["origin"]["value"] is None:
                locations["origin"]["value"] = value
                locations["origin"]["output"] = True
    
    # clean up output flags
    # An origin location is defined as
    # Value: the origin whereabout
    # Output: origin whereabout is defined and whereabouts with type home > 1 or the origin whereabout is defined and there is no home whereabout

    # if home_count == 1:
    # home = True and origin = False if home value is defined, otherwise origin = True and home = False
    # logic is if home_count == 1, should always just output home unless home has an end date, implying no current home
    # by definition if home_count == 1, origin and home must have the same value if both defined, so don't need to check
    # if home_count > 1, we need to check if home and origin have the same value. 
    # if they have the same value, that means the only valid home is the origin, so we output origin True and home True but set home value to "Unknown"

    if home_count == 0:
        locations["origin"]["output"] = False
        locations["home"]["output"] = False
    elif home_count == 1:
        locations["origin"]["output"] = False
        locations["home"]["output"] = True
        if locations["home"]["value"] is None or locations["home"]["value"] == "Unknown":
            locations["home"]["output"] = False
            locations["origin"]["output"] = True
    else:
        locations["home"]["output"] = True
        locations["origin"]["output"] = True
        if locations["home"]["value"] == locations["origin"]["value"]:
            locations["home"]["value"] = "Unknown"
            locations["home"]["output"] = False

    # A current location is defined as
    # Value:
    # If there is an exact known whereabouts, use that and set the output flag to true
    # Otherwise, if there is both a home and last known whereabouts where
    # The last known whereabouts has a defined end and
    # The last known whereabouts end date is in the past compared to the target date
    # Then use the home whereabout as the current location and set the output flag to false
    # Otherwise, the current location is Unknown and set the output flag to true
    # Output: See algorithm above

    if locations["exact"]["value"] is not None:
        locations["current"]["value"] = locations["exact"]["value"]
        locations["current"]["output"] = True
    elif locations["home"]["value"] is not None:
        if locations["last"]["end"] is not None and locations["last"]["end"] < target_date:
            locations["current"]["value"] = locations["home"]["value"]
            locations["current"]["output"] = False
        elif locations["last"]["value"] is None:
            locations["current"]["value"] = locations["home"]["value"]
            locations["current"]["output"] = False
        else:
            locations["current"]["value"] = "Unknown"
            locations["current"]["output"] = True
    else:
        locations["current"]["value"] = "Unknown"
        locations["current"]["output"] = True

    # a last known location is defined as
    # Value: the last known whereabouts
    # Output: the last known whereabouts is defined and the current location is Unknown
    # Date: the last known whereabouts date
    if locations["current"]["value"] == "Unknown" and locations["last"]["value"] is not None:
        locations["last"]["output"] = True
    else:
        locations["last"]["output"] = False

    """
    # if you are dead, current location should never be output
    if died_date is not None and target_date > died_date:
        locations["current"]["output"] = False
    
    """


    if debug:
        print(metadata["name"], locations, file=sys.stderr)

    return locations

