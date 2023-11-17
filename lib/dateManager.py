from datetime import datetime, date
import re
import sys
import os
import json
from datetime import datetime, date

class DateManager:
    """
    Class for managing dates
    """
    def __init__(self, configPath, overrideDate = None):
        self.configPath = configPath        # Path to Obsidian config, used for getting default date
        self.overrideDate = overrideDate    # Override date from command line

    def getAge(self, age1, age2):
        """
        Takes two dates and returns the difference in years
        Always returns a positive value; the input order does not matter
        """

        age1 = self.normalizeDate(age1)
        age2 = self.normalizeDate(age2)

        if age1 > age2:
            younger = age1
            older = age2
        elif age2 > age1:
            younger = age2
            older = age1
        else:
            return 0
        
        return younger.year - older.year - ((younger.month, younger.day) < (older.month, older.day))
    
    def normalizeDate(self, value, end = False, debug = False, return_string = False):   
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
        
        cleanDate = None

        # If value is None, return None
        if value is None or not value:
            return None

        if isinstance(value, datetime):
            cleanDate=date(value.year, value.month, value.day)
        
        # If the value is already a datetime object, return it as is
        if isinstance(value, date):
            cleanDate = value

        if isinstance(value, int):
            if value < 1:
                raise ValueError("Input year cannot be negative.")
            # Assuming the integer is a year
            if (end):
                cleanDate = date(value, 12, 31)
            else:
                cleanDate = date(value, 1, 1)

        if isinstance(value, str):

            if value.startswith("-"):
                raise ValueError("Input year cannot be negative.")
            
            parts = value.split('-')

            year = int(sanitize(parts[0]))
            if len(parts) == 1: 
                if (end):
                    cleanDate = date(year, 12, 31)
                else:
                    cleanDate = date(year, 1, 1)
            elif len(parts) == 2:
                if (end): 
                    cleanDate = date(year, int(sanitize(parts[1])), 31)
                else:
                    cleanDate = date(year, int(sanitize(parts[1])), 1)
            elif len(parts) == 3:
                cleanDate = date(year, int(sanitize(parts[1])), int(sanitize(parts[2])))
            else:
                raise ValueError("Input must be a datetime object, an integer, or a string in YYYY, YYYY-MM, or YYYY-MM-DD format.")
            
        if cleanDate is None:
            raise ValueError("Input must be a datetime object, an integer, or a string in YYYY, YYYY-MM, or YYYY-MM-DD format.")

        if return_string:
            return cleanDate.strftime("%Y-%m-%d")
        else:
            return cleanDate


    def getPageDates(self, metadata, targetDate=None):
        """
        Calculate date-related statuses based on metadata and a target date.

        :param metadata: A dictionary containing metadata.
        :param targetDate: The target date for calculations.
        :return: A dictionary with various status information.
        """

        # Set targetDate to the result of getTargetDateForPage if it's not provided
        if targetDate is None:
            targetDate = self.getTargetDateForPage(metadata)

        # Initialize status dictionary
        status = {
            'startDate': None,
            'endDate': None,
            'isCreated': True,
            'isAlive': True,
            'age': None
        }

        # Set startDate based on metadata
        if 'born' in metadata:
            status['startDate'] = self.normalizeDate(metadata['born'], False)
        elif 'created' in metadata:
            status['startDate'] = self.normalizeDate(metadata['created'], False)
        elif 'DR' in metadata:
            status['startDate'] = self.normalizeDate(metadata['DR'], False)

        # Set endDate based on metadata
        if 'died' in metadata:
            status['endDate'] = self.normalizeDate(metadata['died'], True)
        elif 'destroyed' in metadata:
            status['endDate'] = self.normalizeDate(metadata['destroyed'], True)
        elif 'DR_end' in metadata:
            if metadata['DR_end']:
                status['endDate'] = self.normalizeDate(metadata['DR_end'], True)
        elif 'DR' in metadata:
            status['endDate'] = self.normalizeDate(metadata['DR'], True)

        # Calculate isCreated and isAlive statuses
        if status['startDate']:
            status['isCreated'] = status['startDate'] <= targetDate
            status['isAlive'] = (status['endDate'] >= targetDate ) if status['endDate'] else status['isCreated']

            # Calculate age
            if status['isAlive']:
                status['age'] = self.getAge(targetDate, status['startDate'])
            elif status['endDate']:
                status['age'] = self.getAge(status['endDate'], status['startDate'])

        return status

    def getRegnalDates(self, metadata, targetDate=None):
        """
        Calculate regnal dates based on metadata.

        :param metadata: A dictionary containing metadata.
        :param targetDate: The target date for calculations, optional.
        :return: A dictionary with various regnal date information.
        """

        # Set targetDate if not provided
        if targetDate is None:
            targetDate = self.getTargetDateForPage(metadata)

        # Initialize status dictionary
        status = {
            'isCreated': None,
            'isCurrent': None,
            'startDate': None,
            'endDate': None,
            'length': None
        }

        # Determine endDate and startDate
        status['endDate'] = self.normalizeDate(metadata.get('reignEnd'), True) or self.normalizeDate(metadata.get('died'), True)
        status['startDate'] = self.normalizeDate(metadata.get('reignStart'), False)

        # Calculate isCreated and isCurrent
        if status['startDate']:
            status['isCreated'] = status['startDate'] <= targetDate
            status['isCurrent'] = status['isCreated'] and (status['endDate'] is None or targetDate <= status['endDate'])

            # Calculate length of reign
            if status['isCurrent']:
                status['length'] = self.getAge(targetDate, status['startDate'])
            elif status['endDate']:
                status['length'] = self.getAge(status['endDate'], status['startDate'])

        return status

    def getTargetDateForPage(self, metadata):
        """
        Get the target date for a page from metadata.

        :param metadata: A dictionary containing metadata.
        :return: A normalized date.
        """

        # If metadata has a pageTargetDate, return the normalized date
        if metadata and 'pageTargetDate' in metadata:
            return self.normalizeDate(metadata['pageTargetDate'], False)

        # Otherwise, obtain and return the default target date
        # Replace 'getDefaultTargetDate()' with your method of getting the default date
        defaultTargetDate = self.getDefaultTargetDate() 
        return self.normalizeDate(defaultTargetDate, False)

    def getDefaultTargetDate(self):
        """
        Method to obtain the default date.
        """
        if self.overrideDate:
            return self.normalizeDate(self.overrideDate)
        else:
            with open(os.path.join(self.configPath, 'plugins', 'fantasy-calendar', 'data.json'), 'r', 2048, "utf-8") as f:
                data = json.load(f)
                current_data_string = str(data['calendars'][0]['current']['year']) + "-" + str(data['calendars'][0]['current']['month']+1) + "-" + str(data['calendars'][0]['current']['day'])
                return self.normalizeDate(current_data_string)


    def convertDate(self, value, from_format, to_format, return_string = False):
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
            year,month,day = self.normalizeDate(value, return_string=True).split('-')
            if int(month) < 3 or (int(month) == 3 and int(day) < 17):
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



    def displayDate(self, date, full = True, cr = "DR"):
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
