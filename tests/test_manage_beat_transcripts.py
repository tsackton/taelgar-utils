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
