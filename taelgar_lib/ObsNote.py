import yaml
import re
from pathlib import Path
from .TaelgarDate import TaelgarDate

class ObsNote:

    WIKILINK_RE_OLD = r"""\[\[(.*?)(\#.*?)?(?:\|([\D][^\|\]]+[\d]*))?(?:\|(\d+)(?:x(\d+))?)?\]\]"""
    WIKILINK_RE = r"""\[\[([^\|\]\#]+)(\#.*?)?(?:\|([^\|\]]*))?(?:\|([^\|\]]*))?\]\]"""

    def __init__(self, path, config={}, is_markdown=True):
        # Variables
        self.config = config
        self.original_path = Path(path)
        self.target_path = self.original_path
        self.filename = self.original_path.stem
        self.campaign = self._parse_campaign(config.get('campaign', ''))
        self.target_date = TaelgarDate.parse_date_string(config.get('target_date', None))
        self.is_markdown = is_markdown

        if is_markdown:
            self.metadata, self.raw_text = self._parse_markdown_file()
            self._clean_text() #sets self.clean_text
            self._page_title() #set self.page_title
            self.is_stub = self.count_relevant_lines(self.clean_text) < 1
            self.is_unnamed = self.page_title.startswith("~") or self.filename.startswith("~")
            self.is_future_dated = self.metadata.get("activeYear", None) and self.target_date and TaelgarDate.parse_date_string(self.metadata.get("activeYear", None)) > self.target_date
            self.outlinks = [match[0] for match in re.findall(self.WIKILINK_RE, self.raw_text) if match[0] is not None]
        else:
            self.raw_text = None
            self.clean_text = None
            self.metadata = {}
            self.page_title = self.filename
            self.is_stub = False
            self.is_unnamed = False
            self.is_future_dated = False
            self.outlinks = []

    def _parse_campaign(self, value):
        if isinstance(value, str):
            return value.split(',')
        elif isinstance(value, list):
            return value
        else:
            return []
        
    @staticmethod
    def title_case(text, exclusions=None, always_upper=None):
        if exclusions is None:
            exclusions = ['A', 'An', 'The', 'And', 'But', 'Or', 'For', 'Nor', 'As', 'At', 'By', 'For', 'From', 'In', 'Into', 'Near', 'Of', 'On', 'Onto', 'To', 'With', 'De', 'About']

        if always_upper is None:
            always_upper = ['DR']

        # Convert exclusions to lowercase for case-insensitive comparison
        exclusions = [word.lower() for word in exclusions]
        # Keep always_upper as it is for exact matching

        words = text.split()
        title_cased_words = []

        for i, word in enumerate(words):
            # Remove punctuation for comparison, but retain original for replacement
            word_stripped = re.sub(r'\W+', '', word)

            # Check if the stripped word (case-insensitive) is in always_upper
            if any(word_stripped.lower() == au.lower() for au in always_upper):
                # Preserve original non-word characters, capitalize the rest
                title_cased_words.append(word.upper())
            elif i == 0 or word_stripped.lower() not in exclusions:
                # Capitalize the first unicode character that is a letter
                title_cased_words.append(re.sub(r'(\b\w)', lambda x: x.groups()[0].upper(), word, 1))
            else:
                # If in exclusions, keep the word as it is
                title_cased_words.append(word.lower())

        return ' '.join(title_cased_words)

    @staticmethod
    def count_relevant_lines(text):
        """
        Counts the number of lines in a string that are not empty, do not start with a header (^#),
        and do not contain only the word "stub" or "(stub)".
        
        Args:
        text (str): A multi-line string representing the text file content.

        Returns:
        int: The number of relevant lines.
        """
        # Split the text into lines
        lines = text.split('\n')

        # Define the criteria for a line to be excluded
        def is_excluded(line):
            return (line.strip() == '' or            # Check for empty lines
                    line.strip() in ['stub', '(stub)'] or  # Check for lines containing only 'stub' or '(stub)'
                    line.lstrip().startswith('#'))  # Check for lines starting with '#', ignoring leading whitespace

        # Count the lines that are not excluded
        relevant_lines = [line for line in lines if not is_excluded(line)]
        return len(relevant_lines)

    @staticmethod
    def strip_comments(text):
        """
        Takes a string as input, and strips all text between closest pairs of %% markers, or between a %% and EOF if there is an unmatched %%.
        Additionally, it handles cases where there is an unmatched %% by removing everything from that %% to the end of the file.
        """
        return re.sub(r'%%.*?%%|%%.*', '', text, flags=re.DOTALL)

    def _parse_markdown_file(self):
        """
        Reads a markdown file and returns its frontmatter as a dictionary and the rest of the text as a string.
        :param file_path: Path to the markdown file.
        :return: A tuple containing a dictionary of the frontmatter and a string of the markdown text.
        """
        file_path = self.original_path

        with open(file_path, 'r', encoding='utf-8') as file:
            lines = file.readlines()

        # Check if the file starts with frontmatter (triple dashes)
        if lines and lines[0].strip() == '---':
            # Try to find the second set of triple dashes
            try:
                end_frontmatter_idx = lines[1:].index('---\n') + 1
            except ValueError:
                # Handle the case where the closing triple dashes are not found
                frontmatter = {}
                markdown_text = ''.join(lines)
            else:
                frontmatter = yaml.safe_load(''.join(lines[1:end_frontmatter_idx]))
                markdown_text = ''.join(lines[end_frontmatter_idx + 1:])
        else:
            frontmatter = {}
            markdown_text = ''.join(lines)
        return frontmatter, markdown_text

    def _clean_text(self):
        """
        Cleans the text of a markdown file.
        :param text: A string of the markdown text.
        :return: A string of the cleaned markdown text.
        Understands the following configuration options:
        - strip_comments: If True, strips all text between %% markers, or between a %% and EOF if there is an unmatched %%.
        - strip_campaigns: If not None, removes text between %%^Campaign:text%% and %%^End%% if the campaign text does not match the target campaign.
        - strip_dates: If not Nonte, removes text between %%^Date:YYYY-MM-DD%% and %%^End%% if the date in the comment is before the target date.
        - clean_inline_tags: If True, converts inline tags to human-readable strings.
        """

        text = self.raw_text

        if self.target_date:
            text = self._strip_date_content(text)
        if self.campaign:
            text = self._strip_campaign_content(text)
        if self.config.get("strip_comments", True):
            text = self.strip_comments(text)
        if self.config.get("clean_inline_tags", True):
            text = self._clean_inline_tags(text)
        
        self.clean_text = text

    def _strip_campaign_content(self, text):
        """
        Given a string s, it finds strings of the format:
        %%^Campaign:text%%
        some text here
        %%^End%%
        It keeps all text between %%^Campaign:text%% and %%^End%% if the argument text matches the text in the %% line, 
        and removes it otherwise.
        """
        # This function will be used to determine whether to keep or remove the matched text
        def keep_or_remove(match):
            campaign_text = match.group(1)
            content = match.group(2)
            return content if campaign_text.lower() in [i.lower() for i in self.campaign] else ""

        pattern = r'%%\^Campaign:(.*?)%%(.*?)%%\^End%%'
        return re.sub(pattern, keep_or_remove, text, flags=re.DOTALL | re.IGNORECASE)

    def _strip_date_content(self, text):
        """
        Removes text between %%^Date:YYYY-MM-DD%% and %%^End%% if the input_date is before the date in the %% comment.
        The date in the comment and the input date can be in the formats YYYY, YYYY-MM, or YYYY-MM-DD.
        """

        def replace_func(match):
            # Extract the date from the comment
            comment_date_str = match.group(1)
            # Check if the date ends with a letter
            parse_code = "b"
            if comment_date_str[-1].isalpha():
                parse_code = comment_date_str[-1].lower()
                # Remove the letter
                comment_date_str = comment_date_str[:-1]
            # Parse the comment date
            comment_date = TaelgarDate.parse_date_string(comment_date_str)

            # Compare the dates
            if parse_code == "a":
                if self.target_date <= comment_date:
                    return ""  # Remove the text if input_date is before comment_date
                else:
                    return match.group(0)  # Keep the text otherwise
            elif parse_code == "b":
                if self.target_date >= comment_date:
                    return ""
                else:
                    return match.group(0)  # Keep the text otherwise
            else:
                raise ValueError(f"Invalid parse code '{parse_code}' in comment '{match.group(0)}'")

        # Define the regular expression pattern
        pattern = r'%%\^Date:(.*?)%%(.*?)%%\^End%%'
        # Replace matching sections
        return re.sub(pattern, replace_func, text, flags=re.DOTALL)

    def _clean_inline_tags(self, text):
        def date_to_string(match):
            inline_tag = match.group(1)
            tag_value = match.group(2)
            if inline_tag == "DR" or inline_tag == "DR_end":
                parts = tag_value.split("-")
                if len(parts) > 1:
                    parts[1] = TaelgarDate.DR_MONTHS[int(parts[1])]
                if len(parts) == 3:
                    return(f'{parts[1]} {parts[2]}, {parts[0]} DR')
                if len(parts) == 2:
                    return(f'{parts[1]} {parts[0]} DR')
                if len(parts) == 1:
                    return(f'{parts[0]} DR')
            return inline_tag + " " + tag_value
        
        pattern = r'\((\w+)::\s*([^\s\)]+)\s*\)\)?'
        return re.sub(pattern, date_to_string, text, flags=re.DOTALL)

    def _page_title(self):
        """
        Check frontmatter, if name exists, use that, with title prepended if it exists.
        Otherwise, use the filename, changed to title case, with title prepended if it exists.
        """      
        if self.metadata.get("name"):
            page_name = self.title_case(self.metadata.get("name"))
        else:
            page_name = self.title_case(self.filename.replace("-", " "))
        
        if self.metadata.get("title"):
            page_title = self.title_case(self.metadata.get("title"))
        else:
            page_title = ""
        
        self.page_title = " ".join([page_title, page_name]).strip()
