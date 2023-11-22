import json
import os
from datetime import datetime, date
import re

class DateManager:
    """
    Class for managing dates
    """

    def __init__(self, config_path, override_date = None):
        self.config_path = config_path        # Path to Obsidian config, used for getting default date
        if (override_date):
            self.default_date = self.normalize_date(override_date)   # Override date from command line
        else:
            self.default_date = self._get_default_target_date() # Default date from Obsidian config

    def _get_default_target_date(self):
        """
        Retrieves the default target date from the Obsidian config.

        :return: Default target date as a string.
        """
        with open(os.path.join(self.config_path, 'plugins', 'fantasy-calendar', 'data.json'), 'r', 2048, "utf-8") as f:
            data = json.load(f)
            current_data_string = str(data['calendars'][0]['current']['year']) + "-" + str(data['calendars'][0]['current']['month']+1) + "-" + str(data['calendars'][0]['current']['day'])
            return self.normalize_date(current_data_string)
 
 
    def get_target_date_for_page(self, metadata):
        """
        Retrieves the target date for the page based on the provided metadata.

        :param metadata: Metadata containing information about the page.
        :return: Target date for the page as a string.
        """

        # If metadata has a pageTargetDate, return the normalized date
        if metadata and 'pageTargetDate' in metadata and metadata['pageTargetDate']:
            return self.normalize_date(metadata['pageTargetDate'], False)

        # Otherwise, return the default target date
        return self.normalize_date(self.default_date, False)
    
    def get_page_dates(self, metadata, target_date=None):
        """
        Retrieves page date information based on the provided metadata.

        :param metadata: The metadata containing date information.
        :param target_date: The target date for the page, if already known.
        :return: A dictionary with status information including start and end dates.
        """
        if not target_date:
            target_date = self.get_target_date_for_page(metadata)

        status = {
            'startDate': None,
            'endDate': None,
            'isCreated': None,
            'isAlive': None,
            'age': None
        }

        if 'born' in metadata:
            status['startDate'] = self.normalize_date(metadata['born'], False)
        elif 'created' in metadata:
            status['startDate'] = self.normalize_date(metadata['created'], False)
        elif 'DR' in metadata:
            status['startDate'] = self.normalize_date(metadata['DR'], False)

        if 'died' in metadata:
            status['endDate'] = self.normalize_date(metadata['died'], True)
        elif 'destroyed' in metadata:
            status['endDate'] = self.normalize_date(metadata['destroyed'], True)
        elif 'DR_end' in metadata:
            if metadata['DR_end']:
                status['endDate'] = self.normalize_date(metadata['DR_end'], True)
        elif 'DR' in metadata:
            status['endDate'] = self.normalize_date(metadata['DR'], True)

        status = self.set_page_date_properties(status, target_date)

        return status
    
    def set_page_date_properties(self, page_dates, target_date):
        """
        Updates the page date properties based on the target date.

        :param page_dates: A dictionary containing start and end date information.
        :param target_date: The target date for comparison.
        """
        if 'startDate' in page_dates and page_dates['startDate']:
            page_dates['isCreated'] = page_dates['startDate'] <= target_date
        else:
            page_dates['isCreated'] = True

        if 'endDate' in page_dates and page_dates['endDate']:
            page_dates['isAlive'] = page_dates['endDate'] >= target_date
        else:
            page_dates['isAlive'] = page_dates.get('isCreated', True)

        if 'startDate' in page_dates and page_dates['startDate']:
            if page_dates.get('isAlive'):
                page_dates['age'] = self._get_age(target_date, page_dates['startDate'])
            elif 'endDate' in page_dates and page_dates['endDate']:
                page_dates['age'] = self._get_age(page_dates['endDate'], page_dates['startDate'])
        
        return page_dates

    # Private method
    def _get_age(self, age1, age2):
        """
        Calculates the age between two dates.

        :param end_date: The end date.
        :param start_date: The start date.
        :return: The age as a calculated difference between the dates.
        """

        age1 = self.normalize_date(age1)
        age2 = self.normalize_date(age2)

        if age1 is None or age2 is None:
            return None

        if age1 > age2:
            younger = age1
            older = age2
        elif age2 > age1:
            younger = age2
            older = age1
        else:
            return 0

        return younger.year - older.year - ((younger.month, younger.day) < (older.month, older.day))


    def normalize_date(self, value, end=False, debug=False, return_string=False):
        """
        Normalizes various date formats into a Python date object or a string representation.

        :param value: The input date in different formats (datetime, date, int, str).
        :param end: If True, returns the end of the period for incomplete dates.
        :param debug: If True, prints debug information.
        :param return_string: If True, returns a string representation of the date.
        :return: A normalized date as a date object or a string.
        """
        def sanitize(input_string):
            return re.sub(r'\D', '', input_string)

        if debug:
            print(value, type(value))

        # Early return for None or empty value
        if not value:
            return None

        # Handle datetime and date types
        if isinstance(value, datetime):
            clean_date = date(value.year, value.month, value.day)
        elif isinstance(value, date):
            clean_date = value
        elif isinstance(value, int):
            # Validate and handle integer year
            if value < 1:
                raise ValueError("Input year cannot be negative.")
            month_day = (12, 31) if end else (1, 1)
            clean_date = date(value, *month_day)
        elif isinstance(value, str):
            # Validate and process string format
            if value.startswith("-"):
                raise ValueError("Input year cannot be negative.")
            
            parts = [int(sanitize(part)) for part in value.split('-')]
            if len(parts) == 1:
                month_day = (12, 31) if end else (1, 1)
                clean_date = date(parts[0], *month_day)
            elif len(parts) == 2:
                day = 31 if end else 1
                clean_date = date(parts[0], parts[1], day)
            elif len(parts) == 3:
                clean_date = date(*parts)
            else:
                raise ValueError("Invalid date format.")
        else:
            raise ValueError("Unsupported date type.")

        return clean_date.strftime("%Y-%m-%d") if return_string else clean_date

    def convert_date(self, value, from_format, to_format, return_string=False):
        """
        Converts dates between DR and CY calendar systems.

        :param value: The input date.
        :param from_format: The current format of the date ('DR' or 'CY').
        :param to_format: The target format of the date ('DR' or 'CY').
        :param return_string: If True, returns a string representation of the date.
        :return: The converted date.
        """
        def dr_to_cy(dr_date):
            """
            Converts a DR date to CY format.
            """
            year, month, day = [int(part) for part in self.normalize_date(dr_date, return_string=True).split('-')]
            dr_start = date(1, 3, 17)
            cy_start_year = 4134

            # Calculate days since DR start
            days_since_dr_start = (date(year, month, day) - dr_start).days

            # Convert to CY date
            cy_year = cy_start_year + days_since_dr_start // 365
            cy_day_of_year = days_since_dr_start % 365
            cy_date = datetime.strptime(f"{cy_year}-{cy_day_of_year + 1:03d}", "%Y-%j").date()

            return cy_date

        def cy_to_dr(cy_date):
            """
            Converts a CY date to DR format.
            """
            cy_year, cy_month, cy_day = [int(part) for part in self.normalize_date(cy_date, return_string=True).split('-')]
            cy_start = date(4134, 1, 1)
            dr_start_year = 1

            # Calculate days since CY start
            days_since_cy_start = (date(cy_year, cy_month, cy_day) - cy_start).days

            # Convert to DR date
            dr_year = dr_start_year + days_since_cy_start // 365
            dr_day_of_year = days_since_cy_start % 365
            dr_date = datetime.strptime(f"{dr_year}-{dr_day_of_year + 1:03d}", "%Y-%j").date()

            return dr_date

        # Process conversion
        if from_format == "DR" and to_format == "CY" and value is not None:
            converted_date = dr_to_cy(value)
        elif from_format == "CY" and to_format == "DR" and value is not None:
            converted_date = cy_to_dr(value)
        else:
            raise ValueError("From format and to format must be 'DR' or 'CY'.")

        return converted_date.strftime("%Y-%m-%d") if return_string else converted_date



