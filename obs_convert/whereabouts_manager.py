from datetime import datetime, date

class WhereaboutsManager:
    
    def __init__(self, date_manager, name_manager, location_manager):
        """
        Initialize WhereaboutsManager with DateManager, NameManager, and LocationManager instances.

        :param date_manager: An instance of the DateManager class.
        :param name_manager: An instance of the NameManager class.
        :param location_manager: An instance of the LocationManager class.
        """
        self.date_manager = date_manager
        self.name_manager = name_manager
        self.location_manager = location_manager

    def _get_normalized_whereabout(self, w):
        """
        Normalizes the whereabouts data.

        :param w: The whereabouts information as a dictionary.
        :return: A dictionary with normalized whereabouts information.
        """
        def is_valid_loc_piece(l):
            return l and l != "unknown"

        end_date = self.date_manager.normalize_date(w.get('end', ''), True)
        start_date = self.date_manager.normalize_date(w.get('start', ''), False)
        if not start_date:
            start_date = self.date_manager.normalize_date(w.get('date', ''), False)

        date_min = self.date_manager.normalize_date('0001', False)
        date_max = self.date_manager.normalize_date('9999', True)

        type = w.get('type', '')
        if not type:
            if w.get('excursion', False) == True:
                type = "away"

        type = "away" if type == "excursion" else type
        type = "home" if type == "origin" else type

        location = w.get('location', '')
        if not location:
            has_place = is_valid_loc_piece(w.get('place'))
            has_region = is_valid_loc_piece(w.get('region'))

            if has_place and has_region:
                location = f"{w['place']}, {w['region']}"
            elif has_place:
                location = w['place']
            elif has_region:
                location = w['region']

        logical_end = end_date if end_date else date_max
        logical_start = start_date if start_date else date_min
        away_end = end_date if end_date else (date_max if type == "home" else self.date_manager.normalize_date(w.get('start', ''), True) or date_max)

        return {
            'start': start_date,
            'type': type,
            'end': end_date,
            'location': location,
            'logicalEnd': logical_end,
            'logicalStart': logical_start,
            'awayEnd': away_end
        }


    def _get_distance_to_target(self, item, target):
        """
        Calculates the distance (in days) to the target date from the given item.

        :param item: The item containing whereabouts information.
        :param target: The target datetime object.
        :return: The number of days as an integer.
        """
        target_date = self.date_manager.normalize_date(target)
        logical_end = self.date_manager.normalize_date(item.get('logicalEnd'))
        logical_start = self.date_manager.normalize_date(item.get('logicalStart'))

        if logical_end and logical_end < target_date:
            return (target_date - logical_end).days
        elif logical_start:
            return (target_date - logical_start).days
        else:
            return float('inf')  # Return a large number if dates are not available
    
    def filter_whereabouts(self, whereabouts_list, type, target, allow_past):
        """
        Filters a list of whereabouts based on type, target date, and whether past locations are allowed.

        :param whereabouts_list: The list of whereabouts to be filtered.
        :param type: The type of whereabouts to filter for (e.g., 'home', 'away').
        :param target: The target date for filtering.
        :param allow_past: Boolean indicating whether past whereabouts are allowed.
        :return: A filtered list of whereabouts.
        """

        target = self.date_manager.normalize_date(target)
        candidate_set = [w for w in whereabouts_list if (not type or w['type'] == type) and (w['logicalStart'] <= target)]

        if not allow_past:
            candidate_set = [w for w in candidate_set if target <= w['logicalEnd']]

        if not candidate_set:
            return []

        # Calculate the closest distance to the target date for each whereabout
        soonest_possible = min(self._get_distance_to_target(w, target) for w in candidate_set)

        # Return the whereabouts that are closest to the target date
        return [w for w in candidate_set if self._get_distance_to_target(w, target) == soonest_possible]

    def get_party_meeting(self, metadata, campaign):
        """
        Retrieves party meeting information based on metadata and a specific campaign.

        :param metadata: The metadata containing party meeting information.
        :param campaign: The specific campaign to filter the party meetings.
        :return: A list of dictionaries, each containing information about a party meeting.
        """
        results = []

        if 'campaignInfo' in metadata:
            for element in metadata['campaignInfo']:
                if 'campaign' in element and 'date' in element:
                    display_date = self.date_manager.normalize_date(element['date'])
                    loc_for_this_date = self.get_whereabouts(metadata, element['date']).get('current')

                    if loc_for_this_date and (element['campaign'] == campaign or not campaign):
                        party_name = self.name_manager.get_name(element['campaign'], self.name_manager.CreateLink, self.name_manager.PreserveCase)
                        
                        if party_name:
                            type = element.get('type', "seen")
                            format_str = self.location_manager.build_formatted_location_string(
                                self.name_manager.get_display_data(metadata).get('whereaboutsParty', ''),
                                loc_for_this_date, display_date, None, type, party_name
                            )
                            text = format_str[0].upper() + format_str[1:].strip()

                            result = {
                                'text': text,
                                'campaign': element['campaign'],
                                'date': display_date,
                                'location': loc_for_this_date.get('location')
                            }
                            results.append(result)

        return results


    def get_whereabouts(self, metadata, target_date):
        """
        Gets the current whereabouts based on metadata and a target date.

        :param metadata: The metadata containing whereabouts information.
        :param target_date: The target date for which whereabouts information is needed.
        :return: A dictionary containing whereabouts information.
        """
        target_date = self.date_manager.normalize_date(target_date)
        if not target_date:
            target_date = self.date_manager.get_target_date_for_page(metadata)

        whereabout_result = {'current': None, 'home': None, 'origin': None, 'lastKnown': None}

        origin_input = metadata["born"] if "born" in metadata and metadata["born"] else "0001-01-01"
        origin_date = self.date_manager.normalize_date(origin_input, False)
        normalized = self.get_whereabouts_list(metadata)

        homes = self.filter_whereabouts(normalized, "home", target_date, False)
        origins = self.filter_whereabouts(normalized, "home", origin_date, False)

        whereabout_result['home'] = homes[-1] if homes else None
        whereabout_result['origin'] = origins[0] if origins else None

        if whereabout_result['origin'] and whereabout_result['origin'].get('startDate'):
            whereabout_result['origin'] = None

        current = self.filter_whereabouts(normalized, None, target_date, False)
        current = current[-1] if current else None

        if current:
            if target_date <= current['awayEnd']:
                # This away is truly valid
                whereabout_result['current'] = current
                whereabout_result['lastKnown'] = None
            else:
                # This away is our best guess as to location, but we are not still there
                whereabout_result['current'] = None
                whereabout_result['lastKnown'] = current
        else:
            # We don't have a current whereabout - everything is in the past
            past_whereabouts = self.filter_whereabouts(normalized, None, target_date, True)
            whereabout_result['lastKnown'] = past_whereabouts[-1] if past_whereabouts else None

        return whereabout_result

    def get_whereabouts_list(self, metadata):
        """
        Get whereabouts list based on metadata.
        """
        if metadata and metadata.get('whereabouts') and len(metadata.get('whereabouts')) > 0:
            wb = metadata.get('whereabouts')
            if isinstance(wb, str):
                wb = [{'type': 'home', 'location': wb}]

            return [self._get_normalized_whereabout(f) for f in wb]

        return []