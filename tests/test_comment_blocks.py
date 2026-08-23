import unittest
from pathlib import Path
import sys


UTILS_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = UTILS_ROOT / "src"
for path in (UTILS_ROOT, SRC_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from website.site_builder.comment_blocks import CommentBlockError, filter_comment_blocks


class CommentBlockParserTests(unittest.TestCase):
    def test_plain_date_is_visible_on_and_after_cutoff(self) -> None:
        text = "before\n%%^Date:1740-10-07%%new state%%^End%%\nafter\n"

        self.assertNotIn("new state", filter_comment_blocks(text, export_date="1740-10-06"))
        self.assertIn("new state", filter_comment_blocks(text, export_date="1740-10-07"))
        self.assertIn("new state", filter_comment_blocks(text, export_date="1740-10-08"))

    def test_b_date_is_visible_strictly_before_cutoff(self) -> None:
        text = "%%^Date:1740-10-07b%%old state%%^End%%"

        self.assertIn("old state", filter_comment_blocks(text, export_date="1740-10-06"))
        self.assertNotIn("old state", filter_comment_blocks(text, export_date="1740-10-07"))
        self.assertNotIn("old state", filter_comment_blocks(text, export_date="1740-10-08"))

    def test_partial_dates_use_start_of_period(self) -> None:
        after = "%%^Date:1740%%current%%^End%%"
        before = "%%^Date:1740b%%old%%^End%%"

        self.assertIn("current", filter_comment_blocks(after, export_date="1740-01-01"))
        self.assertNotIn("old", filter_comment_blocks(before, export_date="1740-01-01"))
        self.assertIn("old", filter_comment_blocks(before, export_date="1739-12-31"))

    def test_inline_date_blocks_are_supported(self) -> None:
        text = "Durable. %%^Date:1749%%Later.%%^End%% Done."

        self.assertEqual(filter_comment_blocks(text, export_date="1748"), "Durable.  Done.")
        self.assertEqual(filter_comment_blocks(text, export_date="1749"), "Durable. Later. Done.")

    def test_a_date_is_rejected(self) -> None:
        with self.assertRaisesRegex(CommentBlockError, "unsupported date block suffix 'a'"):
            filter_comment_blocks("%%^Date:1740a%%old%%^End%%", export_date="1740", source="A.md")

    def test_date_block_requires_export_date(self) -> None:
        with self.assertRaisesRegex(CommentBlockError, "requires a configured export_date"):
            filter_comment_blocks("%%^Date:1740%%later%%^End%%", source="A.md")

    def test_campaign_none_is_always_removed(self) -> None:
        text = "public%%^Campaign: None%%private%%^End%%after"

        self.assertEqual(filter_comment_blocks(text), "publicafter")
        self.assertEqual(filter_comment_blocks(text, campaigns=("none",)), "publicafter")

    def test_unselected_campaigns_are_removed_when_selection_is_empty(self) -> None:
        text = "%%^Campaign:dufr%%dufr%%^End%%general"

        self.assertEqual(filter_comment_blocks(text), "general")
        self.assertEqual(filter_comment_blocks(text, campaigns=("DUFR",)), "dufrgeneral")

    def test_all_nonpublic_comment_forms_are_removed(self) -> None:
        text = (
            "visible\n"
            "%% ordinary comment %%\n"
            "%%SECRET local secret %%\n"
            "%%^Metadata%%unversioned metadata body%%^End%%\n"
            "%%^Metadata:names:v1%%metadata body%%^End%%\n"
            "%%^Metadata:map:v1%%map body%%^End%%\n"
            "%%^povNotes%%unversioned pov body%%^End%%\n"
            "%%^povNotes:v1%%pov body%%^End%%\n"
            "%%^Lint%%lint body%%^End%%\n"
            "after\n"
        )

        result = filter_comment_blocks(text)

        self.assertIn("visible", result)
        self.assertIn("after", result)
        for private_text in (
            "ordinary comment",
            "local secret",
            "unversioned metadata body",
            "metadata body",
            "map body",
            "unversioned pov body",
            "pov body",
            "lint body",
        ):
            self.assertNotIn(private_text, result)

    def test_malformed_comment_structures_are_rejected(self) -> None:
        cases = {
            "ordinary": "visible %% comment",
            "unknown": "%%^Campagin:none%%private%%^End%%",
            "unterminated": "%%^Lint%%private",
            "stray": "visible%%^End%%",
            "nested": "%%^Campaign:dufr%%outer%%^Date:1740%%inner%%^End%%%%^End%%",
            "discarded_block_with_bad_comment": "%%^Lint%%private %% comment%%^End%%",
            "bad_date": "%%^Date:1740-10-07^%%later%%^End%%",
        }
        for label, text in cases.items():
            with self.subTest(label=label):
                with self.assertRaises(CommentBlockError):
                    filter_comment_blocks(text, campaigns=("dufr",), export_date="1740")

    def test_errors_report_source_and_line_without_body_content(self) -> None:
        with self.assertRaises(CommentBlockError) as raised:
            filter_comment_blocks("visible\n%%^Lint%%PRIVATE BODY", source="Secret.md")

        message = str(raised.exception)
        self.assertIn("Secret.md:2", message)
        self.assertIn("unterminated structured block 'Lint'", message)
        self.assertNotIn("PRIVATE BODY", message)


if __name__ == "__main__":
    unittest.main()
