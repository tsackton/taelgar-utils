import os
import json

class NameManager:
    """
    Class for managing page names
    """

    LowerCase = "lower"
    TitleCase = "title"
    PreserveCase = "preserve"
    CreateLink = "always"
    NoLink = "never"
    LinkIfValid = "exists"

    def __init__(self, configPath):
        self.configPath = configPath
        self.coreMeta = self.loadCoreMetadata()
    
    def loadCoreMetadata(self):
         """
         Loads the core metadata from the metadata.json file
         """
         with open(os.path.join(self.configPath, 'metadata.json'), 'r', 2048, "utf-8") as f:
            data = json.load(f)
            return data

    def getElementFromMetadata(self, elem):
        """
        Returns the value of the element from the core metadata
        """
        if (self.coreMeta):
            if (elem in self.coreMeta):
                return self.coreMeta[elem]
        return None

    def getPageType(self, metadata):
        """
        Determine the type of a page based on its metadata.

        :param metadata: A dictionary containing metadata.
        :return: A string representing the page type.
        """

        # Return 'default' if metadata is not provided
        if not metadata:
            return "default"

        # Use an empty list if metadata doesn't have 'tags'
        tags = metadata.get('tags', [])

        # Check for various conditions to determine the page type
        if any(key in metadata for key in ['DR', 'DR_end', 'CY', 'CY_end']):
            return "event"
        elif any(tag.startswith("person") for tag in tags):
            return "person"
        elif any(tag.startswith("place") for tag in tags):
            return "place"
        elif any(tag.startswith("organization") for tag in tags):
            return "organization"
        elif any(tag.startswith("item") for tag in tags):
            return "item"

        return "default"

    def toTitle(self, string):
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

    def processDescriptiveName(self, descriptiveName, targetLink, article, linkType="exists", casing="default"):
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
            return None

        descriptiveName = descriptiveName.strip()

        # Apply casing
        if casing == self.TitleCase:
            descriptiveName = self.toTitle(descriptiveName)
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
    
    def getName(self, target, linkType = None, casing=None):
        """
        wrapper for getFilteredName
        linkType = "never" | "always" | "exists"
        casing = "title" | "lower" | "preserve"
        """
        if linkType is None:
            linkType = self.LinkIfValid
        if casing is None:
            casing = self.PreserveCase

        return self.getFilteredName(target, None, linkType, casing)

    def mergeOptions(self, obj1, obj2):
        """
        Merge two dictionaries, with values from the second dictionary overriding those from the first.

        :param obj1: The first dictionary.
        :param obj2: The second dictionary.
        :return: A merged dictionary.
        """
        merged = dict(obj1)  # Create a copy of obj1
        merged.update(obj2)  # Update with values from obj2
        return merged

    def getDisplayData(self, target):
        """
        Process and merge metadata from various sources to form display data.

        :param target: The target object or string to process.
        :return: A dictionary containing the display data.
        """
        metadata = target

        # Check if target is a string and process accordingly
        if isinstance(target, str):
            file = self.getFileForTarget(target)
            metadata = file.get("frontmatter", {})

        displayDefaultData = self.getElementFromMetadata("displayDefaults")
        defaultForThisItem = displayDefaultData.get(self.getPageType(metadata)) if displayDefaultData else None
        if not defaultForThisItem:
            defaultForThisItem = self.getElementFromMetadata("displayDefaults").get('default', {}) if displayDefaultData else {}

        required = {
            'startStatus': "", 
            'endStatus': "", 
            'whereaboutsOrigin': "<loc>", 
            'whereaboutsHome': "<loc>", 
            'whereaboutsPastHome': "<loc>",
            'pageCurrent': "<start> <startDate>",
            'pagePastWithStart': "<start> <startDate> - <end> <endDate>",
            'pagePast': "<end> <endDate>"
        }

        base = self.mergeOptions(required, defaultForThisItem)
        return self.mergeOptions(base, metadata.get('displayDefaults', {}))

    def getFilteredName(self, target, filter_func, linkType=None, casing=None):
        """
        Retrieve and format a name based on file existence, filter matching, and metadata.

        :param target: The target name to search for.
        :param filter_func: The filter function to apply.
        :param linkType: The type of link to apply (LinkIfValid, CreateLink).
        :param casing: The casing rule to apply (PreserveCase, etc.).
        :return: A formatted name based on the given conditions.
        """
        if not target or target == "Untitled":
            return None

        if linkType is None:
            linkType = self.LinkIfValid
        if casing is None:
            casing = self.PreserveCase

        # Adjust linkType based on certain conditions
        if linkType == self.CreateLink:
            fragmentsThatDontAlwaysLink = self.getElementFromMetadata("fragmentsThatDontAutoLink")
            if fragmentsThatDontAlwaysLink:
                for word in target.split(' '):
                    if word.lower() in fragmentsThatDontAlwaysLink:
                        linkType = self.LinkIfValid
                        break

        fileData = self.getFileForTarget(target, filter_func)

        if not fileData:
            if filter_func:
                return None
            return self.processDescriptiveName(target, None, "", linkType, casing)

        frontmatter = fileData['frontmatter']
        selectedDescriptiveName = target if fileData['isAlias'] else fileData['filename']
        article = ""

        if not fileData['isAlias']:
            if 'title' in frontmatter and 'name' in frontmatter:
                selectedDescriptiveName = frontmatter['title'] + " " + frontmatter['name']
            elif 'name' in frontmatter:
                selectedDescriptiveName = frontmatter['name']
            elif 'campaign' in frontmatter and 'sessionNumber' in frontmatter:
                selectedDescriptiveName = frontmatter['campaign'] + " " + str(frontmatter['sessionNumber'])

            displayData = self.getDisplayData(frontmatter)

            # Add definitive article
            if 'definitiveArticle' in displayData:
                if displayData['definitiveArticle']:
                    article = displayData['definitiveArticle']
            elif len(selectedDescriptiveName.split(' ')) > 1:
                article = "the"

        return self.processDescriptiveName(selectedDescriptiveName, fileData['filename'], article, linkType, casing)
    
    
    def getDescriptionOfDateInformation(self, metadata, dateInfo, overrideDisplayInfo=None):
        """
        Format a date-related description based on metadata and date information.

        :param metadata: Metadata dictionary.
        :param dateInfo: Dictionary containing date-related information.
        :param overrideDisplayInfo: Optional dictionary to override display settings.
        :return: A formatted date-related description string.
        """
        isExist = dateInfo.get('isCreated') or dateInfo.get('isStarted')
        if not isExist:
            return dateInfo.get('notExistenceError', "")

        isActive = dateInfo.get('isAlive') or dateInfo.get('isCurrent')
        length = dateInfo.get('age', dateInfo.get('length', None))

        pageDisplayData = overrideDisplayInfo if overrideDisplayInfo is not None else self.getDisplayData(metadata)

        if isActive:
            formatStr = pageDisplayData.get('pageCurrent')
        elif length:
            formatStr = pageDisplayData.get('pagePastWithStart')
        else:
            formatStr = pageDisplayData.get('pagePast')

        # Using Python string formatting to replace placeholders
        return formatStr.replace("<length>", str(length)) \
                        .replace("<start>", pageDisplayData.get('startStatus', '')) \
                        .replace("<end>", pageDisplayData.get('endStatus', '')) \
                        .replace("<startDate>", dateInfo.get('startDate', {}).get('display', '')) \
                        .replace("<endDate>", dateInfo.get('endDate', {}).get('display', ''))

    #######################
    ### NOT IMPLEMENTED ###
    #######################

    def getFileForTarget(self, target, filter_func=None):
        """
        Search through files and retrieve metadata based on a target string.

        :param target: The target string to search for.
        :param filter_func: An optional filter function to apply to the metadata.
        :return: A dictionary with file information and metadata, or None if not found.
        """

        # Implement logic to search through files
        # This is a placeholder implementation and needs to be adapted to your specific context

        # Search in primary location
        primary_file = self.searchPrimaryLocation(target)
        if primary_file:
            metadata = self.getMetadata(primary_file)
            if filter_func and not filter_func(metadata):
                return None
            return {'filename': primary_file.basename, 'isAlias': False, 'frontmatter': metadata}

        # Search in secondary locations (e.g., aliases)
        secondary_file = self.searchSecondaryLocations(target, filter_func)
        if secondary_file:
            return secondary_file

        # Search in custom map
        mapped_file = self.searchCustomMap(target, filter_func)
        if mapped_file:
            return mapped_file

        return None

    def searchPrimaryLocation(self, target):
        # Implement search logic for primary location
        pass

    def searchSecondaryLocations(self, target, filter_func):
        # Implement search logic for secondary locations (aliases)
        pass

    def searchCustomMap(self, target, filter_func):
        # Implement search logic for custom mapping
        pass

    def getMetadata(self, file):
        # Implement logic to retrieve metadata from a file
        pass

    

