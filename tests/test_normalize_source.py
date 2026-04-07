from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = REPO_ROOT / "cli" / "session.py"


class NormalizeSourceTest(unittest.TestCase):
    def make_workspace(self) -> Path:
        tmpdir = Path(tempfile.mkdtemp(prefix="normalize-source-test."))
        self.addCleanup(lambda: shutil.rmtree(tmpdir, ignore_errors=True))
        return tmpdir

    def run_normalizer(self, workspace: Path) -> subprocess.CompletedProcess[str]:
        output_dir = workspace / "cleaned"
        return subprocess.run(
            [
                sys.executable,
                str(CLI_PATH),
                "normalize-source",
                "--session",
                str(workspace / "session.yaml"),
                "--output-dir",
                str(output_dir),
                "--file-prefix",
                "sample-session",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_timeline_note_preserves_embedded_raw_notes_as_supplemental(self) -> None:
        workspace = self.make_workspace()
        source_path = workspace / "source.md"
        source_path.write_text(
            textwrap.dedent(
                """\
                ---
                title: Example
                ---
                ## Timeline

                - Day 1: The party reaches the tower.
                - Day 2: The party descends into the flooded crypt.

                ## Cast of Characters

                - Captain Sorrel

                ## Narrative

                The party spends the evening debating whether the tower is safe.

                %% RAW notes
                wake up at tower
                debate whether to enter
                descend to flooded crypt
                %%
                """
            ),
            encoding="utf-8",
        )
        session_path = workspace / "session.yaml"
        session_path.write_text(
            textwrap.dedent(
                f"""\
                schemaVersion: "1.0"
                sourceType: narrative
                scope: session
                campaign: Test Campaign
                sessionNumber: 12
                realWorldDate: 2026-03-31
                participants: []
                sourceInputPath: {source_path}
                sourceConfigPath: {workspace / "config.yaml"}
                participantsPath: {workspace / "participants.yaml"}
                preparedSourcePath: {workspace / "prepared.md"}
                """
            ),
            encoding="utf-8",
        )

        result = self.run_normalizer(workspace)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        cleaned_text = (workspace / "cleaned" / "sample-session-source-cleaned.md").read_text(encoding="utf-8")
        self.assertIn("The party reaches the tower.", cleaned_text)
        self.assertIn("The party descends into the flooded crypt.", cleaned_text)
        self.assertNotIn("Captain Sorrel", cleaned_text)

        structure_payload = json.loads(
            (workspace / "cleaned" / "normalization-artifacts" / "sample-session-source-structure.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(structure_payload["detectedShape"], "timeline-structured-note")
        self.assertGreaterEqual(len(structure_payload["supplementalSources"]), 2)

        supplemental_files = list((workspace / "cleaned" / "supplemental").glob("*.md"))
        self.assertTrue(any("embedded-raw-notes" in path.name for path in supplemental_files))
        self.assertTrue(any("derived" in path.name for path in supplemental_files))


if __name__ == "__main__":
    unittest.main()
