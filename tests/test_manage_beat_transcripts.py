from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "skills" / "beat-transcript-polisher" / "scripts" / "manage_beat_transcripts.py"
SPEC = importlib.util.spec_from_file_location("manage_beat_transcripts", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Could not import {SCRIPT_PATH}")
manager = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = manager
SPEC.loader.exec_module(manager)


class ManageBeatTranscriptsTest(unittest.TestCase):
    def make_workspace(self) -> Path:
        tmpdir = Path(tempfile.mkdtemp(prefix="manage-beat-transcripts-test."))
        self.addCleanup(lambda: shutil.rmtree(tmpdir, ignore_errors=True))
        return tmpdir

    def test_read_recap_blocks_uses_recap_markdown_metadata(self) -> None:
        workspace = self.make_workspace()
        recap_path = workspace / "session-recap.md"
        recap_path.write_text(
            "# Session Recap\n\n"
            "## Recap\n\n"
            "### recap-001 | Campfire Tales\n\n"
            "- Kind: beat\n"
            "- Beat IDs: B01, B02\n"
            "- Source Range: u0001 -> u0698\n"
            "- Polished Transcript: old/path.md\n\n"
            "#### Short\n"
            "The party camps in the woods.\n\n"
            "#### Long\n"
            "- Source Range: u9999 -> u9999\n\n"
            "### recap-003 | The Journey\n\n"
            "- Kind: beat\n"
            "- Beat IDs: B03\n"
            "- Source Range: u0699 -> u1415\n\n"
            "## Cast\n",
            encoding="utf-8",
        )

        blocks = manager.read_recap_blocks(recap_path)

        self.assertEqual([block["blockId"] for block in blocks], ["recap-001", "recap-003"])
        self.assertEqual(blocks[0]["title"], "Campfire Tales")
        self.assertEqual(blocks[0]["beatIds"], ["B01", "B02"])
        self.assertEqual(blocks[0]["startUid"], "u0001")
        self.assertEqual(blocks[0]["endUid"], "u0698")
        self.assertEqual(blocks[1]["beatIds"], ["B03"])
        self.assertEqual(blocks[1]["sourceEntries"][0]["title"], "The Journey")

    def test_main_ignores_missing_context_json(self) -> None:
        workspace = self.make_workspace()
        transcript_path = workspace / "source-cleaned.md"
        recap_path = workspace / "session-recap.md"
        output_dir = workspace / "beat-transcripts"
        transcript_path.write_text(
            "[u0001 | 00:00:00.000-00:00:01.000 | DM] The door opens.\n"
            "[u0002 | 00:00:01.000-00:00:02.000 | Kaito] What could go wrong?\n"
            "[u0003 | 00:00:02.000-00:00:03.000 | DM] Everything.\n",
            encoding="utf-8",
        )
        recap_path.write_text(
            "# Session Recap\n\n"
            "## Recap\n\n"
            "### recap-001 | Opening the Door\n\n"
            "- Kind: beat\n"
            "- Beat IDs: B01\n"
            "- Source Range: u0001 -> u0003\n\n"
            "#### Short\n"
            "The door opens.\n",
            encoding="utf-8",
        )

        old_argv = sys.argv
        try:
            sys.argv = [
                "manage_beat_transcripts.py",
                "--transcript",
                str(transcript_path),
                "--context-json",
                str(workspace / "missing-context.json"),
                "--session-recap-md",
                str(recap_path),
                "--output-dir",
                str(output_dir),
                "--file-prefix",
                "test-session-001",
            ]
            result = manager.main()
        finally:
            sys.argv = old_argv

        self.assertEqual(result, 0)
        transcript_file = output_dir / "test-session-001-recap-001-transcript.md"
        self.assertTrue(transcript_file.exists())
        self.assertIn("- Polished Transcript: beat-transcripts/test-session-001-recap-001-transcript.md", recap_path.read_text(encoding="utf-8"))
        self.assertIn("%% u0001 %%", transcript_file.read_text(encoding="utf-8"))

    def test_sync_recap_review_media_from_highlights_summary(self) -> None:
        workspace = self.make_workspace()
        recap_path = workspace / "session-recap.md"
        summary_path = workspace / "beat-transcripts" / "test-transcript-highlights.md"
        summary_path.parent.mkdir(parents=True)
        recap_path.write_text(
            "# Session Recap\n\n"
            "## Source Files\n\n"
            "- Cleaned Source: source.md\n",
            encoding="utf-8",
        )
        summary_path.write_text(
            "# Transcript Highlights\n\n"
            "## Pull Quotes\n\n"
            "### beat-001 | Arrival\n\n"
            "- Recap Block: recap-001\n"
            "- Transcript: test-recap-001-transcript.md\n"
            "- Source Range: u0001 -> u0010\n"
            "- Pull Quotes:\n"
            "  - ID: quote-beat-001-001\n"
            "    - Quote: \"The maze remembers.\"\n"
            "    - Speaker: Kalima\n"
            "    - Source Lines: u0004-u0006\n\n"
            "## Audio Monologue Candidates\n\n"
            "- ID: audio-001\n"
            "  - Source Lines: u0020-u0040\n"
            "  - Speaker: DM\n"
            "  - Summary: Holda tells his story.\n"
            "  - Why Called Out: Central exposition.\n",
            encoding="utf-8",
        )

        manager.sync_recap_review_media(recap_path, summary_path)

        recap_text = recap_path.read_text(encoding="utf-8")
        self.assertIn("## Pull Quotes", recap_text)
        self.assertIn("- ID: quote-beat-001-001", recap_text)
        self.assertIn("  - Quote: \"The maze remembers.\"", recap_text)
        self.assertIn("## Audio Highlights", recap_text)
        self.assertIn("- ID: audio-001", recap_text)
        self.assertIn("  - Title: Holda tells his story.", recap_text)
        self.assertIn("  - Output: audio-001.m4a", recap_text)
        self.assertIn("## Source Files", recap_text)


if __name__ == "__main__":
    unittest.main()
