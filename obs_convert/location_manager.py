import re

class LocationManager:

    def __init__(self, date_manager, name_manager):
        """
        Initialize LocationManager with DateManager and NameManager instances.

        :param date_manager: An instance of the DateManager class.
        :param name_manager: An instance of the NameManager class.
        """
        self.date_manager = date_manager
        self.name_manager = name_manager

    def build_formatted_location_string(self, format_str, whereabout, target_date, end_status, met_status, person):
        """
        Builds a formatted location string based on the provided parameters.

        :param format_str: The format string to use for formatting.
        :param whereabout: The whereabout information.
        :param target_date: The target date.
        :param end_status: The end status.
        :param met_status: The met status.
        :param person: The person involved.
        :return: A formatted location string.
        """
        if target_date:
            target_date = self.date_manager.normalize_date(target_date)

        # use a regex to split <loc:1l> into <loc>, 1, l, where 1 is any number and l is any letter
        group = re.match(r"<loc(:([0-9]*)([a-z]{0,1}))?>", format_str)
        location = ""
        if group and whereabout:
            format_str = format_str.replace(group[0], "<loc>")

            casing = self.name_manager.PreserveCase
            if group[3] == "l":
                casing = self.name_manager.LowerCase
            elif group[3] == "t":
                casing = self.name_manager.TitleCase

            location = self.get_current_location_name(whereabout['location'], target_date, casing, int(group[2]), self.name_manager.CreateLink)
        elif whereabout:
            location = self.get_current_location_name(whereabout['location'], target_date)
        else:
            location = ""

        end_replace = self.name_manager.display_date(whereabout['awayEnd']) if whereabout and "awayEnd" in whereabout else ""
        start_replace = self.name_manager.display_date(whereabout['awayStart']) if whereabout and "awayStart" in whereabout else ""
        person = "" if person is None else person
        met_status = "" if met_status is None else met_status

        formatted = format_str.replace("<loc>", location) \
                              .replace("<end>", end_replace) \
                              .replace("<start>", start_replace) \
                              .replace("<end>", end_status) \
                              .replace("<person>", person) \
                              .replace("<met>", met_status) \
                              .replace("<target>", self.name_manager.display_date(target_date) if target_date else "")

        return (formatted[0].upper() + formatted[1:]).strip() if formatted else ""

    def get_current_location_name(self, location, target_date, casing="default", max_pieces=3, link_type="always"):
        """
        Gets the current location name formatted based on specified parameters.

        :param location: The location string.
        :param target_date: The target date for the location.
        :param casing: The casing style for the location name.
        :param max_pieces: The maximum number of location parts to include.
        :param link_type: The type of linking to apply.
        :return: A formatted location string.
        """
        def trim_trailing_comma(in_str):
            out_str = in_str.rstrip(',')
            return out_str.strip()

        if max_pieces is None or not isinstance(max_pieces, int):
            max_pieces = 3

        if not location:
            return "Unknown"

        if "," not in location:
            # Placeholder for #getLocationFromPartOfs method
            return trim_trailing_comma(self.get_location_from_part_ofs(location, target_date, 0, max_pieces, link_type, casing))
        else:
            return ", ".join(self.name_manager.get_name(part.strip(), link_type, casing) for part in location.split(','))

    def is_in_location(self, starting_location, target_location):
        """
        Checks if a starting location is part of a target location.

        :param starting_location: The starting location string.
        :param target_location: The target location string.
        :return: True if the starting location is part of the target location, False otherwise.
        """
        starting_location = starting_location.strip()
        target_location = target_location.strip()

        if starting_location == target_location:
            return True

        if starting_location == "":
            return False

        if "," not in starting_location:
            # Single location string
            file = self.name_manager.get_file_for_target(starting_location)
            if file:
                next_lvl = file["frontmatter"].get('partOf')
                if next_lvl:
                    return self.is_in_location(next_lvl, target_location)
                return False
            else:
                print(f"Unable to retrieve file for {starting_location}")
                return False
        else:
            # Check if target_location is a part of the starting_location string
            return target_location in starting_location

    def get_location_name(self, location, casing="default", max_pieces=3, link_type="always"):
        """
        Gets a location string formatted based on specified parameters.

        :param location: The location string.
        :param casing: The casing style for the location name.
        :param max_pieces: The maximum number of location parts to include.
        :param link_type: The type of linking to apply.
        :return: A formatted location string.
        """
        return self.get_current_location_name(location, None, casing, max_pieces, link_type)

    def get_location_from_part_ofs(self, location_piece, target_date, this_depth, max_depth, link_type, casing):
        """
        Recursively processes location parts to build a formatted location string.

        :param location_piece: The current piece of the location being processed.
        :param target_date: The target date for the location.
        :param this_depth: The current depth of recursion.
        :param max_depth: The maximum depth to recurse to.
        :param link_type: The type of linking to apply.
        :param casing: The casing style for the location name.
        :return: A formatted location string.
        """
        if this_depth == max_depth or not location_piece or location_piece == "Taelgar":
            return ""

        name_section = self.name_manager.get_name(location_piece, link_type, casing)
        file = self.name_manager.get_file_for_target(location_piece)

        if not file:
            return name_section
        else:
            next_level = file['frontmatter'].get('partOf')
            if not next_level and file['frontmatter'].get('whereabouts'):
                current = self.whereabouts_manager.get_whereabouts(file['frontmatter'], target_date).get('current')
                if current:
                    next_level = current['location']

            if next_level:
                return name_section + ", " + self.get_location_from_part_ofs(next_level, target_date, this_depth + 1, max_depth, link_type, casing)

            return name_section


