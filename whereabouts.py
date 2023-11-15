from metadataUtils import *

def filter_whereabouts(whereabouts, target_date, type=None, allow_past=False):
    """
    Takes a whereabouts list of dicts, a target date, and optionally a type
    Returns all valid whereabouts for the specified type on the target date
    """

    target_date = clean_date(target_date)

    valid_whereabouts = []

    for entry in whereabouts:
        if type is not None and entry['type'] != type:
            continue
        else:
            #valid type, or no type specified
            start_date = clean_date(entry['start']) if "start" in entry and entry['start'] else date.min
            end_date = clean_date(entry['end'], end=True) if "end" in entry and entry['end'] else date.max
            entry["recency"] = (target_date - start_date).days
            entry["duration"] = (end_date - start_date).days
            entry["start_date"] = start_date
            entry["end_date"] = end_date
            if allow_past and start_date <= target_date:
                valid_whereabouts.append(entry)
            elif start_date <= target_date and end_date >= target_date:
                valid_whereabouts.append(entry)


    return valid_whereabouts

def get_whereabouts(metadata, target_date):
    """
    Takes a metadata dict and a target date
    Returns a list of whereabouts dicts for the target date
    """

    # Get whereabouts from metadata
    whereabouts = metadata.get('whereabouts', [])
    born = metadata.get('born', date.min)

    # Get valid locations for each type
    valid_homes = filter_whereabouts(whereabouts, target_date, type='home', allow_past=False)
    valid_origins = filter_whereabouts(whereabouts, target_date, type='home', allow_past=True)
    valid_current = filter_whereabouts(whereabouts, target_date, allow_past=False)
    valid_known = filter_whereabouts(whereabouts, target_date, allow_past=True)

    # Get current home as the valid home with the smallest recency, with ties broken by order in the metadata.
    if not valid_homes:
        current_home = None
    else:
        current_home = min(valid_homes, key=lambda x: x["recency"]) #this is not quite right as it will return the first home in the list if there are multiple with the same recency, not the last
    
    # Get current location as the valid location with the smallest recency, with ties broken by duration, then order in the metadata.

    if not valid_current:
        current_location = None
    else:
        current_location = min(valid_current, key=lambda x: (x["recency"], x["duration"])) #this is not quite right as it will return the first location in the list if there are multiple with the same recency and duration, not the last
        if "end_date" in current_location and current_location["end_date"] is None or "end_date" not in current_location:
            current_location = None

    # Get the origin as the earliest home in the metadata where start date >= born
    if not valid_origins:
        origin = None
    else:
        origin = min(valid_origins, key=lambda x: x["start_date"])
        if clean_date(origin['start_date']) < born:
            origin = None
    
    # Get the known location as the latest defined location in the metadata, where 
    if not valid_known:
        known_location = None
    known_location = max(valid_known, key=lambda x: x["start_date"])

    return { "home" : current_home, "current" : current_location, "origin" : origin, "known" : known_location }

