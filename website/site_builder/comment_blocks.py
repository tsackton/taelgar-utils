from __future__ import annotations

import re
from bisect import bisect_right
from datetime import datetime

from taelgar_utils.vault.taelgar_date import TaelgarDate


STRUCTURED_MARKER_RE = re.compile(r"%%\^([^%\r\n]+)%%")
DATE_MARKER_RE = re.compile(
    r"^Date:\s*(?P<date>\d{1,4}(?:-\d{1,2})?(?:-\d{1,2})?)(?P<code>[A-Za-z]?)\s*$",
    re.IGNORECASE,
)
CAMPAIGN_MARKER_RE = re.compile(r"^Campaign:\s*(?P<campaign>.+?)\s*$", re.IGNORECASE)
METADATA_MARKER_RE = re.compile(r"^Metadata(?:\:[^%\r\n]+)?$", re.IGNORECASE)
POV_NOTES_MARKER_RE = re.compile(r"^povNotes(?:\:[^%\r\n]+)?$", re.IGNORECASE)
FENCE_OPEN_RE = re.compile(r"^(?P<indent> {0,3})(?P<fence>`{3,}|~{3,})(?P<rest>.*)$")


class CommentBlockError(ValueError):
    """A source comment or structured block cannot be safely exported."""

    def __init__(self, source: str, line: int, message: str) -> None:
        self.source = source
        self.line = line
        self.message = message
        super().__init__(f"{source}:{line}: {message}")


class CommentBlockParser:
    def __init__(
        self,
        text: str,
        *,
        campaigns: tuple[str, ...] = (),
        export_date: str | datetime | None = None,
        source: str = "<text>",
        line_offset: int = 0,
    ) -> None:
        self.text = text
        self.campaigns = {
            campaign.strip().casefold()
            for campaign in campaigns
            if campaign.strip()
        }
        self.source = source
        self.line_offset = line_offset
        self.protected_ranges = self._markdown_code_ranges(text)
        self.protected_range_starts = tuple(start for start, _ in self.protected_ranges)
        self.export_date = self._parse_export_date(export_date)

    def parse(self) -> str:
        return self._parse_segment(self.text, 0)

    def _parse_segment(self, text: str, base_offset: int) -> str:
        output: list[str] = []
        cursor = 0
        while cursor < len(text):
            marker_start = self._find_unprotected(text, "%%", cursor, base_offset)
            if marker_start < 0:
                output.append(text[cursor:])
                break

            output.append(text[cursor:marker_start])
            absolute_start = base_offset + marker_start

            if text.startswith("%%^", marker_start):
                marker_match = STRUCTURED_MARKER_RE.match(text, marker_start)
                if marker_match is None:
                    self._error(absolute_start, "malformed structured block marker")
                marker = marker_match.group(1).strip()
                if marker.casefold() == "end":
                    self._error(absolute_start, "stray structured block terminator")

                body_start = marker_match.end()
                end_match = self._find_block_end(
                    text,
                    body_start,
                    base_offset,
                    marker,
                    absolute_start,
                )
                body = text[body_start : end_match.start()]
                parsed_body = self._parse_segment(body, base_offset + body_start)
                if self._keep_block(marker, absolute_start):
                    output.append(parsed_body)
                cursor = end_match.end()
                continue

            comment_end = self._find_unprotected(text, "%%", marker_start + 2, base_offset)
            if comment_end < 0:
                self._error(absolute_start, "unterminated Obsidian comment")
            cursor = comment_end + 2

        return "".join(output)

    def _find_block_end(
        self,
        text: str,
        body_start: int,
        base_offset: int,
        opener: str,
        opener_offset: int,
    ) -> re.Match[str]:
        search_at = body_start
        while True:
            marker_start = self._find_unprotected(text, "%%^", search_at, base_offset)
            if marker_start < 0:
                self._error(opener_offset, f"unterminated structured block '{self._marker_kind(opener)}'")
            marker_match = STRUCTURED_MARKER_RE.match(text, marker_start)
            if marker_match is None:
                self._error(base_offset + marker_start, "malformed structured block marker")
            marker = marker_match.group(1).strip()
            if marker.casefold() == "end":
                return marker_match
            self._error(
                base_offset + marker_start,
                f"nested structured block '{self._marker_kind(marker)}' inside '{self._marker_kind(opener)}'",
            )

    def _keep_block(self, marker: str, marker_offset: int) -> bool:
        if (
            marker.casefold() == "lint"
            or METADATA_MARKER_RE.fullmatch(marker)
            or POV_NOTES_MARKER_RE.fullmatch(marker)
        ):
            return False

        campaign_match = CAMPAIGN_MARKER_RE.fullmatch(marker)
        if campaign_match:
            campaign = campaign_match.group("campaign").strip().casefold()
            if not campaign:
                self._error(marker_offset, "campaign block is missing a campaign identifier")
            if campaign == "none":
                return False
            return campaign in self.campaigns

        date_match = DATE_MARKER_RE.fullmatch(marker)
        if date_match:
            if self.export_date is None:
                self._error(marker_offset, "date block requires a configured export_date")
            code = date_match.group("code").casefold()
            if code == "a":
                self._error(
                    marker_offset,
                    "unsupported date block suffix 'a'; use 'b' for before-state content",
                )
            if code not in {"", "b"}:
                self._error(marker_offset, f"unsupported date block suffix '{code}'")
            try:
                block_date = TaelgarDate.parse_date_string(date_match.group("date"))
            except ValueError:
                self._error(marker_offset, "date block contains an invalid date")
            if code == "b":
                return self.export_date < block_date
            return self.export_date >= block_date

        self._error(marker_offset, f"unknown structured block marker '{self._marker_kind(marker)}'")

    def _parse_export_date(self, export_date: str | datetime | None) -> datetime | None:
        if export_date is None or export_date == "":
            return None
        if isinstance(export_date, datetime):
            return export_date
        try:
            return TaelgarDate.parse_date_string(str(export_date))
        except ValueError:
            self._error(0, "configured export_date is invalid")

    def _line(self, offset: int) -> int:
        return self.text.count("\n", 0, offset) + 1 + self.line_offset

    def _error(self, offset: int, message: str):
        raise CommentBlockError(self.source, self._line(offset), message)

    @staticmethod
    def _marker_kind(marker: str) -> str:
        return marker.split(":", 1)[0].strip()[:80] or "unknown"

    def _find_unprotected(
        self,
        text: str,
        token: str,
        start: int,
        base_offset: int,
    ) -> int:
        search_at = start
        while True:
            found = text.find(token, search_at)
            if found < 0:
                return -1
            protected_range = self._protected_range_containing(base_offset + found)
            if protected_range is None:
                return found
            search_at = max(found + len(token), protected_range[1] - base_offset)

    def _protected_range_containing(self, offset: int) -> tuple[int, int] | None:
        index = bisect_right(self.protected_range_starts, offset) - 1
        if index < 0:
            return None
        protected_range = self.protected_ranges[index]
        return protected_range if offset < protected_range[1] else None

    @classmethod
    def _markdown_code_ranges(cls, text: str) -> tuple[tuple[int, int], ...]:
        fenced_ranges = cls._fenced_code_ranges(text)
        inline_ranges = cls._inline_code_ranges(text, fenced_ranges)
        return tuple(sorted((*fenced_ranges, *inline_ranges)))

    @staticmethod
    def _fenced_code_ranges(text: str) -> tuple[tuple[int, int], ...]:
        ranges: list[tuple[int, int]] = []
        active_fence: tuple[str, int, int] | None = None
        offset = 0

        for line in text.splitlines(keepends=True):
            content = line.rstrip("\r\n")
            if active_fence is None:
                opener = FENCE_OPEN_RE.fullmatch(content)
                if opener is not None:
                    fence = opener.group("fence")
                    if fence[0] == "`" and "`" in opener.group("rest"):
                        offset += len(line)
                        continue
                    active_fence = (fence[0], len(fence), offset)
            else:
                fence_char, fence_length, range_start = active_fence
                stripped = content.lstrip(" ")
                indent = len(content) - len(stripped)
                fence_run = len(stripped) - len(stripped.lstrip(fence_char))
                if indent <= 3 and fence_run >= fence_length and not stripped[fence_run:].strip():
                    ranges.append((range_start, offset + len(line)))
                    active_fence = None
            offset += len(line)

        if active_fence is not None:
            ranges.append((active_fence[2], len(text)))
        return tuple(ranges)

    @staticmethod
    def _inline_code_ranges(
        text: str,
        fenced_ranges: tuple[tuple[int, int], ...],
    ) -> tuple[tuple[int, int], ...]:
        ranges: list[tuple[int, int]] = []
        fence_index = 0
        cursor = 0

        while cursor < len(text):
            while fence_index < len(fenced_ranges) and fenced_ranges[fence_index][1] <= cursor:
                fence_index += 1
            if fence_index < len(fenced_ranges):
                fence_start, fence_end = fenced_ranges[fence_index]
                if fence_start <= cursor < fence_end:
                    cursor = fence_end
                    continue

            opener = text.find("`", cursor)
            if opener < 0:
                break
            if fence_index < len(fenced_ranges) and opener >= fenced_ranges[fence_index][0]:
                cursor = fenced_ranges[fence_index][1]
                continue

            opener_end = opener + 1
            while opener_end < len(text) and text[opener_end] == "`":
                opener_end += 1
            if CommentBlockParser._is_escaped(text, opener):
                cursor = opener_end
                continue
            delimiter_length = opener_end - opener
            line_end = text.find("\n", opener_end)
            if line_end < 0:
                line_end = len(text)
            search_at = opener_end
            closer_end: int | None = None

            while search_at < line_end:
                candidate = text.find("`", search_at, line_end)
                if candidate < 0:
                    break
                candidate_fence = next(
                    (
                        protected_range
                        for protected_range in fenced_ranges
                        if protected_range[0] <= candidate < protected_range[1]
                    ),
                    None,
                )
                if candidate_fence is not None:
                    search_at = candidate_fence[1]
                    continue
                candidate_end = candidate + 1
                while candidate_end < len(text) and text[candidate_end] == "`":
                    candidate_end += 1
                if CommentBlockParser._is_escaped(text, candidate):
                    search_at = candidate_end
                    continue
                if candidate_end - candidate == delimiter_length:
                    closer_end = candidate_end
                    break
                search_at = candidate_end

            if closer_end is None:
                cursor = opener_end
                continue
            ranges.append((opener, closer_end))
            cursor = closer_end

        return tuple(ranges)

    @staticmethod
    def _is_escaped(text: str, offset: int) -> bool:
        backslashes = 0
        cursor = offset - 1
        while cursor >= 0 and text[cursor] == "\\":
            backslashes += 1
            cursor -= 1
        return backslashes % 2 == 1


def filter_comment_blocks(
    text: str,
    *,
    campaigns: tuple[str, ...] = (),
    export_date: str | datetime | None = None,
    source: str = "<text>",
    line_offset: int = 0,
) -> str:
    """Return publishable text or raise when comment syntax cannot be handled safely."""

    return CommentBlockParser(
        text,
        campaigns=campaigns,
        export_date=export_date,
        source=source,
        line_offset=line_offset,
    ).parse()
