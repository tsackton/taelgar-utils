import re
import unicodedata


def slugify(value: str) -> str:
    """Return a stable ASCII slug for MkDocs paths."""
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^A-Za-z0-9]+", "-", ascii_value).strip("-").lower()
    return slug or "untitled"


def normalized_alias(value: str) -> str:
    """Normalize an Obsidian link target for loose matching."""
    return re.sub(r"[\s\-_]", "", value).lower().replace(".md", "")

