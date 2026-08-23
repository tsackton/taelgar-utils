from __future__ import annotations

import re
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
    ) -> None:
        self.text = text
        self.campaigns = {
            campaign.strip().casefold()
            for campaign in campaigns
            if campaign.strip()
        }
        self.source = source
        self.export_date = self._parse_export_date(export_date)

    def parse(self) -> str:
        return self._parse_segment(self.text, 0)

    def _parse_segment(self, text: str, base_offset: int) -> str:
        output: list[str] = []
        cursor = 0
        while cursor < len(text):
            marker_start = text.find("%%", cursor)
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

            comment_end = text.find("%%", marker_start + 2)
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
            marker_start = text.find("%%^", search_at)
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
        return self.text.count("\n", 0, offset) + 1

    def _error(self, offset: int, message: str):
        raise CommentBlockError(self.source, self._line(offset), message)

    @staticmethod
    def _marker_kind(marker: str) -> str:
        return marker.split(":", 1)[0].strip()[:80] or "unknown"


def filter_comment_blocks(
    text: str,
    *,
    campaigns: tuple[str, ...] = (),
    export_date: str | datetime | None = None,
    source: str = "<text>",
) -> str:
    """Return publishable text or raise when comment syntax cannot be handled safely."""

    return CommentBlockParser(
        text,
        campaigns=campaigns,
        export_date=export_date,
        source=source,
    ).parse()
