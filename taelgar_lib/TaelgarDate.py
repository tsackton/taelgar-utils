from datetime import datetime

class TaelgarDate:

    DR_MONTHS = {
        1: 'Jan',
        2: 'Feb',
        3: 'Mar',
        4: 'Apr',
        5: 'May',
        6: 'Jun',
        7: 'Jul',
        8: 'Aug',
        9: 'Sep',
        10: 'Oct',
        11: 'Nov',
        12: 'Dec'
    }

    @staticmethod    
    def parse_date_string(date_str):
        """
        Tries to parse the date string in various formats and returns a datetime object.
        """

        if date_str is None:
            return None
        
        # Split the date string into parts
        parts = date_str.split('-')
        
        # Pad the year part with zeros if necessary
        parts[0] = parts[0].zfill(4)
        
        # Rejoin the parts into a date string
        padded_date_str = '-'.join(parts)

        for fmt in ['%Y', '%Y-%m', '%Y-%m-%d']:
            try:
                return datetime.strptime(padded_date_str, fmt)
            except ValueError:
                continue
        raise ValueError(f"Date '{date_str}' is not in a recognized format")

    @staticmethod
    def get_dr_date_string(date_string, dr=True):
        if isinstance(date_string, datetime.date):
            date_string = date_string.strftime("%Y-%m-%d")
        
        if dr:
            end_string = " DR"
        else:
            end_string = ""
        parts = date_string.split("-")
        if len(parts) > 1:
            parts[1] = TaelgarDate.DR_MONTHS[int(parts[1])]
        if len(parts) == 3:
            return(f'{parts[1]} {parts[2]}, {parts[0]}{end_string}')
        if len(parts) == 2:
            return(f'{parts[1]} {parts[0]}{end_string}')
        if len(parts) == 1:
            return(f'{parts[0]}{end_string}')