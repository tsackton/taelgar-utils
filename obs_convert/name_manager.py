from pathlib import Path

class NameManager:

    LowerCase = "lower"
    TitleCase = "title"
    PreserveCase = "preserve"
    CreateLink = "always"
    NoLink = "never"
    LinkIfValid = "exists"

    def __init__(self, core_meta, vault_files, cached_metadata):
        """
        Initialize the NameManager with core metadata.

        :param core_meta: The core metadata dictionary.
        """
        self.core_meta = core_meta
        self.vault_files = vault_files
        self.cached_metadata = cached_metadata
    
    def get_name(self, target, linkType = None, casing=None):
        """
        wrapper for getFilteredName
        linkType = "never" | "always" | "exists"
        casing = "title" | "lower" | "preserve"
        """
        if linkType is None:
            linkType = self.LinkIfValid
        if casing is None:
            casing = self.PreserveCase

        return self.get_filtered_name(target, None, linkType, casing)

    def get_filtered_name(self, target, filter_func, linkType=None, casing=None):
        """
        Retrieve and format a name based on file existence, filter matching, and metadata.

        :param target: The target name to search for.
        :param filter_func: The filter function to apply.
        :param linkType: The type of link to apply (LinkIfValid, CreateLink).
        :param casing: The casing rule to apply (PreserveCase, etc.).
        :return: A formatted name based on the given conditions.
        """
        if not target or target == "Untitled":
            return ""

        if linkType is None:
            linkType = self.LinkIfValid
        if casing is None:
            casing = self.PreserveCase

        # Adjust linkType based on certain conditions
        if linkType == self.CreateLink:
            fragmentsThatDontAlwaysLink = self.core_meta.get("fragmentsThatDontAutoLink")
            if fragmentsThatDontAlwaysLink:
                for word in target.split(' '):
                    if word.lower() in fragmentsThatDontAlwaysLink:
                        linkType = self.LinkIfValid
                        break

        fileData = self.get_file_for_target(target, filter_func)

        if not fileData:
            if filter_func:
                return ""
            return self.process_descriptive_name(target, None, "", linkType, casing)

        frontmatter = fileData['frontmatter']
        selectedDescriptiveName = target if fileData['isAlias'] else fileData['filename']
        article = ""

        if not fileData['isAlias']:
            if frontmatter.get('title') and frontmatter.get('name'):
                selectedDescriptiveName = frontmatter['title'] + " " + frontmatter['name']
            elif frontmatter.get('name'):
                selectedDescriptiveName = frontmatter['name']
            elif frontmatter.get('campaign') and frontmatter.get('sessionNumber') is not None:
                selectedDescriptiveName = frontmatter['campaign'] + " " + str(frontmatter['sessionNumber'])


            displayData = self.get_display_data(frontmatter)

            # Add definitive article
            if 'definitiveArticle' in displayData:
                if displayData['definitiveArticle']:
                    article = displayData['definitiveArticle']
            elif len(selectedDescriptiveName.split(' ')) > 1:
                article = "the"

        return self.process_descriptive_name(selectedDescriptiveName, fileData['filename'], article, linkType, casing)
    
    def process_descriptive_name(self, descriptiveName, targetLink, article, linkType="exists", casing="default"):
        """
        Process a descriptive name by adjusting its casing and optionally creating a link.

        This method formats a descriptive name based on provided casing rules (title case, lower case, or default)
        and conditionally formats it as a link. It trims the descriptive name and article, then concatenates them,
        applying the specified casing. If link creation is specified, it formats the name as a wiki-style link.

        :param descriptiveName: The name to be processed.
        :param targetLink: The target URL or identifier for link creation.
        :param article: An article to prepend to the name (e.g., "The", "An").
        :param linkType: Specifies the type of link to create ("exists", "CreateLink", "LinkIfValid").
        :param casing: Specifies the casing to apply ("TitleCase", "LowerCase", "default").
        :return: A processed string with the formatted name, optionally as a link.
        """
        def buildName(pre, main):
            return (pre + " " + main).strip()

        if not article:
            article = ""
        if not descriptiveName:
            return ""

        # if path, get filename
        if isinstance(descriptiveName, Path):
            descriptiveName = descriptiveName.stem

        if isinstance(targetLink, Path):
            targetLink = targetLink.stem    

        descriptiveName = descriptiveName.strip()

        # Apply casing
        if casing == self.TitleCase:
            descriptiveName = self.to_title(descriptiveName)
            article = article[0].upper() + article[1:]
        elif casing == self.LowerCase:
            descriptiveName = descriptiveName.lower()
            article = article.lower()

        descriptiveName = descriptiveName.strip()
        article = article.strip()

        # Determine if a link should be created
        link = linkType == self.CreateLink or (linkType == self.LinkIfValid and targetLink)

        # Build the final string based on the conditions
        if link:
            if descriptiveName == targetLink or not targetLink:
                return (article + " " + "[[" + descriptiveName + "]]").strip()
            else:
                return "[[" + targetLink + "|" + buildName(article, descriptiveName) + "]]"

        return buildName(article, descriptiveName)   

 
    def to_title(self, string):
        """
        Convert a string to title case, keeping certain words in lower case.

        :param string: The string to be converted.
        :return: The title-cased string.
        """
        lowers = ['a', 'an', 'the', 'and', 'but', 'or', 'for', 'nor', 'as', 'at', 'by', 'for', 'from', 'in', 'into', 'near', 'of', 'on', 'onto', 'to', 'with']
        
        # Split the string into words, process each word and then join them back together
        return ' '.join([
            word if (word.lower() in lowers and index > 0) or len(word) == 0 
            else word[0].upper() + word[1:].lower() 
            for index, word in enumerate(string.split(' '))
        ])


    def get_display_data(self, target):
        """
        Retrieves and merges display data for a given target.

        :param target: The target for which display data is required.
        :return: A dictionary containing merged display data.
        """
        def merge_options(obj1, obj2):
            """
            Merges two dictionaries, with values from the second dictionary overwriting those of the first.

            :param obj1: The first dictionary.
            :param obj2: The second dictionary.
            :return: The merged dictionary.
            """
            merged = obj1.copy()
            merged.update(obj2)
            return merged

        metadata = target

        if isinstance(target, str):
            file = self.get_file_for_target(target)  ##CHECK THIS
            metadata = file["frontmatter"] if file else {} ##CHECK THIS

        display_default_data = self.core_meta.get("displayDefaults")
        default_for_this_item = display_default_data.get(self._get_page_type(metadata)) if display_default_data else None
        if not default_for_this_item:
            default_for_this_item = self.core_meta.get("displayDefaults").get('default', {}) if display_default_data else {}

        required = {
            'startStatus': "", 
            'endStatus': "", 
            'whereaboutsOrigin': "<loc>", 
            'whereaboutsHome': "<loc>", 
            'whereaboutsPastHome': "<loc>",
            'whereaboutsCurrent': "Current location (as of <target>): <loc>",
            'whereaboutsPast': "<end> in <loc>",
            'whereaboutsLastKnown': "Last known location: (as of <endDate>): <loc>",
            'whereaboutsUnknown': "Current location: Unknown",
            'whereaboutsParty': "<met> by <person> on <target> in <loc>",
            'pageCurrent': "<start> <startDate>",
            'pagePastWithStart': "<start> <startDate> - <end> <endDate>",
            'pagePast': "<end> <endDate>",
            'boxName': "Information",
            'partOf': "<loc>",
            'defaultTypeOfForDisplay': "",
            'affiliationTypeOf': []
        }

        base = merge_options(required, default_for_this_item)
        return merge_options(base, metadata.get('displayDefaults', {}))

    def _get_page_type(self, metadata):
        """
        Determines the type of a page based on its metadata.

        :param metadata: The metadata dictionary of the page.
        :return: A string representing the page type.
        """
        if not metadata:
            return "unknown"

        tags = metadata.get('tags', [])

        if any(key in metadata for key in ['DR', 'DR_end', 'CY', 'CY_end']):
            return "event"
        elif any(tag.startswith("person") for tag in tags):
            return "person"
        elif 'location' in metadata or any(tag.startswith("place") for tag in tags):
            return "place"
        elif any(tag.startswith("organization") for tag in tags):
            return "organization"
        elif any(tag.startswith("item") for tag in tags):
            return "item"

        return "unknown"

    def get_description_of_date_information(self, metadata, date_info, override_display_info=None):
        """
        Formats date information based on metadata and optional override display information.

        :param metadata: The metadata dictionary of the page.
        :param date_info: A dictionary containing date-related information.
        :param override_display_info: Optional dictionary to override display settings.
        :return: A string representing formatted date information.
        """
        if not date_info.get('isCreated', False):
            return "**(page is future dated)**"

        page_display_data = override_display_info if override_display_info is not None else self.get_display_data(metadata)
        format_str = ""

        if date_info.get('isAlive'):
            format_str = page_display_data.get('pageCurrent', "")
        elif date_info.get('age') is not None:
            format_str = page_display_data.get('pagePastWithStart', "")
        elif date_info.get('endDate'):
            format_str = page_display_data.get('pagePast', "")
        else:
            return ""

        return format_str.replace("<length>", str(date_info.get('age', ''))) \
                         .replace("<start>", page_display_data.get('startStatus', '')) \
                         .replace("<end>", page_display_data.get('endStatus', '')) \
                         .replace("<startDate>", str(self.display_date(date_info.get('startDate', {})))) \
                         .replace("<endDate>", str(self.display_date(date_info.get('endDate', {}))))

    def get_file_for_target(self, target, filter_func=None):
        """
        Searches for a file corresponding to the target, considering various criteria including aliases and custom maps.

        :param target: The target to search for.
        :param filter_func: An optional filter function to apply to the file's frontmatter.
        :return: Information about the found file or None if not found.
        """
        if target in self.vault_files:
            # Assuming the existence of a method equivalent to window.app.metadataCache.getFileCache(tfile)?.frontmatter
            fm = self.cached_metadata.get(target, {})
            if filter_func and not filter_func(fm):
                return None
            return {'filename': target, 'isAlias': False, 'frontmatter': fm}

        # Assuming the existence of a method to get all markdown files equivalent to window.app.vault.getMarkdownFiles()
        for file in self.vault_files:
            aliases = []
            cached_fm = self.cached_metadata.get(file, {})  # Equivalent to window.app.metadataCache.getFileCache(file)
            if cached_fm:
                aliases = cached_fm.get('aliases', [])

            possible_return = None

            if aliases:
                if isinstance(aliases, str):
                    if aliases.lower() == target.lower():
                        possible_return = {'filename': file, 'isAlias': True, 'frontmatter': cached_fm}
                else:
                    for alias in aliases:
                        if alias.lower() == target.lower():
                            possible_return =  {'filename': file, 'isAlias': True, 'frontmatter': cached_fm}

            if possible_return:
                if not filter_func or filter_func(possible_return['frontmatter']):
                    return possible_return

        # Custom map logic
        # Assuming the existence of a method equivalent to this.#getElementFromMetadata("linkmap")
        link_map = self.core_meta.get("linkmap", {})
        map_entry = next((m for m in link_map if m.get('from', '').lower() == target.lower()), None)
        if map_entry:
            mapped_tfile = self.vault_files.get(map_entry.get('to'))
            if mapped_tfile:
                fm = self.cached_metadata.get(mapped_tfile) or {}
                if filter_func and not filter_func(fm):
                    return None
                return {'filename': mapped_tfile, 'isAlias': map_entry.get('isAlias', False), 'frontmatter': fm}

        return None

    def display_date(self, date, full=True, cr="DR"):
        """
        Formats a date object into a string.

        :param date: The date object to format.
        :param full: If True, returns the date in long format (Mon DD, YYYY). If False, returns short format (DR YYYY).
        :param cr: The calendar representation prefix for the short format. Defaults to "DR".
        :return: A formatted date string.
        """
        if not date:
            return ""

        if full:
            return date.strftime("%b %d, %Y")
        else:
            return f"{cr} {date.strftime('%Y')}"