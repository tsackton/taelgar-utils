class DateManager:
    # Assuming DateManager methods are implemented similarly to those in your JavaScript code.
    @staticmethod
    def parse_date_to_events_date(date_str, flag):
        # Implement the logic of parsing the date string to event's date format
        pass

class WhereaboutsManager:
    def get_normalized_whereabout(self, w):
        def is_valid_loc_piece(l):
            return l and l != "unknown"

        end_date = DateManager.parse_date_to_events_date(w['end'], True) if 'end' in w else None
        start_date = DateManager.parse_date_to_events_date(w['start'], False) if 'start' in w else None
        if not start_date and 'date' in w:
            start_date = DateManager.parse_date_to_events_date(w['date'], False)

        date_min = DateManager.parse_date_to_events_date('0001-01-01', False)
        date_max = DateManager.parse_date_to_events_date('9999-01-01', True)

        w_type = w.get('type')
        if not w_type:
            if w.get('excursion') == True:
                w_type = "away"

        if w_type == "excursion":
            w_type = "away"
        if w_type == "origin":
            w_type = "home"

        if w_type == "away" and not start_date:
            print("Whereabouts not valid - type of away but no date")
            return None

        location = w.get('location')
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
        away_end = end_date if end_date else (date_max if w_type == "home" else DateManager.parse_date_to_events_date(w['start'], True))

        return {
            'start': start_date,
            'type': w_type,
            'end': end_date,
            'location': location,
            'logicalEnd': logical_end,
            'logicalStart': logical_start,
            'awayEnd': away_end
        }

    def get_distance_to_target(self, item, target):
        if item['logicalEnd'].sort < target.sort:
            return target.jsDate - item['logicalEnd'].jsDate
        else:
            return target.jsDate - item['logicalStart'].jsDate

    def filter_whereabouts(self, whereabouts_list, w_type, target, allow_past):
        candidate_set = [w for w in whereabouts_list if (not w_type or w['type'] == w_type) and (w['logicalStart'].sort <= target.sort)]
        candidate_set = [w for w in candidate_set if allow_past or target.sort <= w['logicalEnd'].sort]
        soonest_possible = min([self.get_distance_to_target(w, target) for w in candidate_set])
        return [w for w in candidate_set if self.get_distance_to_target(w, target) == soonest_possible]

    def get_whereabouts(self, metadata, target_date):
        whereabout_result = {'current': None, 'home': None, 'origin': None, 'lastKnown': None}

        if metadata and 'whereabouts' in metadata and metadata['whereabouts']:
            origin_date = DateManager.parse_date_to_events_date(metadata.get('born'), False) or DateManager.parse_date_to_events_date("0001-01-01", False)
            normalized = [self.get_normalized_whereabout(f) for f in metadata['whereabouts']]
            
            homes = self.filter_whereabouts(normalized, "home", target_date, False)
            origins = self.filter_whereabouts(normalized, "home", origin_date, False)
            
            whereabout_result['home'] = homes[-1] if homes else None
            whereabout_result['origin'] = origins[0] if origins else None

            if whereabout_result['origin'] and whereabout_result['origin']['startDate']:
                whereabout_result['origin'] = None

            current = self.filter_whereabouts(normalized, None, target_date, False)
            if current:
                current = current[-1]
                if target_date.sort <= current['awayEnd'].sort:
                    whereabout_result['current'] = current
                    whereabout_result['lastKnown'] = None
                else:
                    whereabout_result['current'] = None
                    whereabout_result['lastKnown'] = current

                return whereabout_result

            whereabout_result['lastKnown'] = self.filter_whereabouts(normalized, None, target_date, True)[-1] if self.filter_whereabouts(normalized, None, target_date, True) else None

        return whereabout_result
