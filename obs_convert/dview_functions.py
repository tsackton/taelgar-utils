def get_PageDatedValue(metadata, dm, nm, lm, wm):
    """
    Retrieves and returns a description of date information for a given page.

    :param metadata: The metadata of the page.
    :param dm: An instance of the DateManager class.
    :param nm: An instance of the NameManager class.
    :return: Description of the date information.
    """
    page_existence_data = dm.get_page_dates(metadata)

    return nm.get_description_of_date_information(metadata, page_existence_data)

# def get_RegnalValue(metadata, dm, nm, lm, wm):
    """
    Retrieves and returns a regnal value based on metadata, handling the grouping and formatting of leader information.

    :param metadata: The metadata containing leader and date information.
    :param dm: An instance of the DateManager class.
    :param lm: An instance of the LocationManager class.
    :param nm: An instance of the NameManager class.
    :return: A string representation of regnal value.
    """

    def group_by(list_to_group, key_getter):
        """
        Groups elements of a list into a dictionary based on a key getter function.

        :param list_to_group: The list to be grouped.
        :param key_getter: Function to determine the key for grouping.
        :return: A dictionary with grouped elements.
        """
        grouped = {}
        for item in list_to_group:
            key = key_getter(item)
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(item)
        return grouped

    target_date = dm.get_target_date_for_page(metadata)
    page_dates = dm.get_page_dates(metadata, target_date)

    lines = []
    grouped = group_by(metadata['leaderOf'], lambda f: f"{f['title']}_{f['start']}_{f['end']}")

    for leader_of in grouped.values():
        display_override = {
            "pagePast": "<title> of <loclist> (reigned until <endDate>)",
            "pageCurrent": "<title> of <loclist> (since <startDate>, <length> years ago)",
            "pagePastWithStart": "<title> of <loclist> <startDate> - <endDate> (<length> years)"
        }

        first = leader_of[0]
        start = dm.normalize_date(first.get('start', None)) or dm.normalize_date(metadata.get('reignStart', None))
        end = dm.normalize_date(first.get('end', None)) or dm.normalize_date(metadata.get('reignEnd', None)) or page_dates['endDate']
        title = first.get('title', metadata.get('title', "Leader"))

        date_info = {
            "startDate": start,
            "endDate": end,
            "isCreated": True,
            "isAlive": None,
            "age": None
        }

        dm.set_page_date_properties(date_info, target_date)

        places = [lm.get_location_name(item['place'], "title", 1, "always") for item in leader_of if 'place' in item]
        last_place = places.pop() if places else None

        if last_place:
            remaining = ", ".join(places)
            loc_string = f"{remaining} and {last_place}" if remaining else last_place

            for key in display_override:
                display_override[key] = display_override[key].replace("<title>", title).replace("<loclist>", loc_string)

            description = nm.get_description_of_date_information(metadata, date_info, display_override)

            if description:
                lines.append(description)

    return "\n".join(lines)

def get_Whereabouts(metadata, dm, nm, lm, wm):
    """
    Retrieves and formats whereabouts information based on the provided metadata.

    :param metadata: Metadata containing information about whereabouts.
    :param dm: Instance of the DateManager class.
    :param nm: Instance of the NameManager class.
    :param lm: Instance of the LocationManager class.
    :param wm: Instance of the WhereaboutsManager class.
    :return: Formatted whereabouts information as a string.
    """

    display_defaults = nm.get_display_data(metadata)

    page_data = dm.get_page_dates(metadata)
    page_year = dm.get_target_date_for_page(metadata)
    end_status = display_defaults['endStatus']
    unknown_str = display_defaults['whereaboutsUnknown']

    if not page_data['isCreated']:
        return ""

    is_page_alive = page_data['isAlive']
    if not is_page_alive:
        page_year = page_data['endDate']

    whereabouts = wm.get_whereabouts(metadata, page_year)
    show_origin = whereabouts['origin'] and whereabouts['origin']['location'] and (not whereabouts['home'] or whereabouts['origin']['location'] != whereabouts['home']['location'])

    display_string = ""

    if show_origin:
        display_string = lm.build_formatted_location_string(display_defaults['whereaboutsOrigin'], whereabouts['origin'], page_year, end_status, None, None)

    if whereabouts['home'] and whereabouts['home']['location']:
        format_str = display_defaults['whereaboutsHome'] if is_page_alive else display_defaults['whereaboutsPastHome']

        if display_string:
            display_string += "\n"
        display_string += lm.build_formatted_location_string(format_str, whereabouts['home'], page_year, end_status, "", "")

        if whereabouts['current'] and whereabouts['home']['location'] == whereabouts['current']['location']:
            return display_string

    if (whereabouts['current'] and not whereabouts['current']['location']) or (whereabouts['lastKnown'] and not whereabouts['lastKnown']['location']):
        if is_page_alive:
            if display_string:
                display_string += "\n"
            display_string += lm.build_formatted_location_string(unknown_str, None, page_year, end_status, "", "")

        return display_string

    if whereabouts['current'] and whereabouts['current']['location']:
        if display_string:
            display_string += "\n"

        format_str = display_defaults['whereaboutsCurrent'] if is_page_alive else display_defaults['whereaboutsPast']
        display_string += lm.build_formatted_location_string(format_str, whereabouts['current'], page_year, end_status, "", "")

        return display_string

    if whereabouts['lastKnown'] and whereabouts['lastKnown']['location']:
        if display_string:
            display_string += "\n"

        display_string += lm.build_formatted_location_string(display_defaults['whereaboutsLastKnown'], whereabouts["lastKnown"], page_year, end_status, "", "")
        if is_page_alive:
            display_string += "\n" + lm.build_formatted_location_string(unknown_str, None, page_year, end_status, "", "")

        return display_string

    return display_string

