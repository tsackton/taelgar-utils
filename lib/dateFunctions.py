from datetime import datetime, date
import re
import sys
import os
import json
from datetime import datetime, date

def convert_date(value, from_format, to_format, return_string = False):
    """
    Takes as input a date in some format and two calendar systems and returns a date in the second calendar system
    Can convert arbitrary DR dates to CY dates, but can only convert CY years to DR years
    """

    def dr_to_cy(value):
        """
        Takes as input a date in DR format and returns a date in CY format
        Dwarven calendar (CY) is 365 days from March 17 - March 16. Day 1 is March 17, Day 365 is March 16 of the following year
        DR "date 1" begins on January 1st, 4133 CY
        So Jan 1, 1 DR is Day 289 of CY 4133. 
        Mar 17, 1 DR is Day 1 of CY 4134

        A DR date from Jan 1 to Mar 16 is CY 4133-DR-1, and the CY day is 365 - (Mar 16 - DR day)
        A DR date from Mar 17 to Dec 31 is CY 4134-DR-1, and the CY day is DR day - Mar 16
        """
        year,month,day = clean_date(value, return_string=True).split('-')
        if int(month) < 3 or int(month) == 3 and int(day) < 17:
            cy_day = str(365 - (date(1,3,16)-date(1,int(month),int(day))).days)
            cy_date = datetime.strptime("2001" + "-" + cy_day, "%Y-%j").strftime("%Y-%m-%d")
            cy_year = 4133 + int(year) - 1
            return date(cy_year, int(cy_date.split('-')[1]), int(cy_date.split('-')[2]))
        else:
            cy_day = str((date(1,int(month),int(day))-date(1,3,16)).days)
            cy_date = datetime.strptime("2001" + "-" + cy_day, "%Y-%j").strftime("%Y-%m-%d")
            cy_year = 4133 + int(year)
            return date(cy_year, int(cy_date.split('-')[1]), int(cy_date.split('-')[2]))
    
    def cy_to_dr(value):
        """
        Takes as input a date in CY format and returns a date in DR format
        Simple version
        """
        dy_year = int(value) - 4133
        return dy_year
    
    converted_date = None

    if from_format == "DR" and to_format == "CY":
        if isinstance(value, int) and value < 1:
            # return approx value that doesn't account for differences in when years start
            converted_date = date(4132+value, 1, 1)
        else:
            converted_date = dr_to_cy(value)
    elif from_format == "CY" and to_format == "DR":
        if isinstance(value, int) and value > 0:
            # return approx value that doesn't account for differences in when years start
            return int(cy_to_dr(value))
        else:
            raise ValueError("CY dates have positive years.")
    else:
        raise ValueError("From format and to format must be DR or CY")
    
    if return_string:
        return converted_date.strftime("%Y-%m-%d")
    else:
        return converted_date

def clean_date(value, end = False, debug = False, return_string = False):   
    """
    Takes as input a date in some format and returns a datetime object
    If end is true, returns the last possible day in an incomplete date (e.g., 2001 returns 2001-12-31)
    If end is false, returns the earliest possible day in an incomplete date (e.g., 2001 returns 2001-01-01)

    Allowable formats:
    - datetime object
    - date object
    - integer (year)
    - string in YYYY, YYYY-MM, or YYYY-MM-DD format

    If return_string is true, returns a string in YYYY-MM-DD format

    Does not allow negative years; convert to CY first if needed
    """

    def sanitize(input_string):
        return re.sub(r'\D', '', input_string)

    if debug:
        print(value, type(value), file=sys.stderr)
    
    clean_date = None

    # If value is None, return None
    if value is None or not value:
        return None

    if isinstance(value, datetime):
        clean_date=date(value.year, value.month, value.day)
    
    # If the value is already a datetime object, return it as is
    if isinstance(value, date):
        clean_date = value

    if isinstance(value, int):
        if value < 1:
            raise ValueError("Input year cannot be negative.")
        # Assuming the integer is a year
        if (end):
            clean_date = date(value, 12, 31)
        else:
            clean_date = date(value, 1, 1)

    if isinstance(value, str):

        if value.startswith("-"):
            raise ValueError("Input year cannot be negative.")
        
        parts = value.split('-')

        year = int(sanitize(parts[0]))
        if len(parts) == 1: 
            if (end):
                clean_date = date(year, 12, 31)
            else:
                clean_date = date(year, 1, 1)
        elif len(parts) == 2:
            if (end): 
                clean_date = date(year, int(sanitize(parts[1])), 31)
            else:
                clean_date = date(year, int(sanitize(parts[1])), 1)
        elif len(parts) == 3:
            clean_date = date(year, int(sanitize(parts[1])), int(sanitize(parts[2])))
        else:
            raise ValueError("Input must be a datetime object, an integer, or a string in YYYY, YYYY-MM, or YYYY-MM-DD format.")
        
    if clean_date is None:
        raise ValueError("Input must be a datetime object, an integer, or a string in YYYY, YYYY-MM, or YYYY-MM-DD format.")

    if return_string:
        return clean_date.strftime("%Y-%m-%d")
    else:
        return clean_date

def display_date(date, full = True, cr = "DR"):
    """
    Takes as input a date object and returns a formatted string
    The default short format is DR YYYY, but the DR can be changed by passing a different cr value
    The default long format is Mon DD, YYYY, triggered by setting full to True
    """
    
    if (date is None) or (date == ""):
        return None

    if (full):
        return date.strftime("%b %d, %Y")
    else:
        return cr + " " + date.strftime("%Y")

def get_age(age1, age2):
    """
    Takes two dates and returns the difference in years
    Always returns a positive value; the input order does not matter
    """

    age1 = clean_date(age1)
    age2 = clean_date(age2)

    if age1 > age2:
        younger = age1
        older = age2
    elif age2 > age1:
        younger = age2
        older = age1
    else:
        return 0
    
    return younger.year - older.year - ((younger.month, younger.day) < (older.month, older.day))

def get_page_start_date(metadata):
    """
    Computes start date for page based on metadata
    """
    if "created" in metadata:
        pageStartDate = clean_date(metadata["created"])
    elif "born" in metadata:
        pageStartDate = clean_date(metadata["born"])
    else:
        pageStartDate = None
    return clean_date(pageStartDate)

def get_page_end_date(metadata):
    """
    Computes end date for a page based on metadata
    """
    if "destroyed" in metadata:
        pageEndDate = clean_date(metadata["destroyed"], end=True)
    elif "died" in metadata:
        pageEndDate = clean_date(metadata["died"], end=True)
    else:
        pageEndDate = None
    return pageEndDate

def get_current_date(metadata):
    """
    FIXME: use globs instead of overloaded metadata
    """
    directory = metadata["directory"]
    target_date = metadata.get("pageTargetDate", None)
    if target_date is not None:
        return clean_date(metadata["pageTargetDate"])
    if metadata["override_year"] is not None:
        return clean_date(metadata["override_year"])
    with open(os.path.join(directory, 'plugins', 'fantasy-calendar', 'data.json'), 'r', 2048, "utf-8") as f:
        data = json.load(f)
        current_data_string = str(data['calendars'][0]['current']['year']) + "-" + str(data['calendars'][0]['current']['month']+1) + "-" + str(data['calendars'][0]['current']['day'])
        return clean_date(current_data_string)
