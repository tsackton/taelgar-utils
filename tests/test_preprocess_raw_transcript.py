import tempfile
import unittest
from pathlib import Path

from preprocess_raw_transcript import preprocess_transcript


FIXTURES = Path("tests/data/preprocess")


class PreprocessRawTranscriptTests(unittest.TestCase):
    def test_generates_report_and_session_artifacts(self) -> None:
        known = FIXTURES / "known_mistakes.json"
        glossary = FIXTURES / "glossary.txt"

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            bundle_dir = tmpdir_path / "sample_bundle"
            bundle_dir.mkdir()
            bundle_transcript = bundle_dir / f"{bundle_dir.name}.transcript.txt"
            bundle_transcript.write_text((FIXTURES / "sample_transcript.txt").read_text(encoding="utf-8"), encoding="utf-8")
            report_path = tmpdir_path / "sample.preprocess.md"
            session_mistakes = tmpdir_path / "sample.session-known-mistakes.json"
            session_glossary = tmpdir_path / "sample.session-glossary.txt"

            result = preprocess_transcript(
                method_bundle_path=bundle_dir,
                known_mistakes_path=known,
                glossary_path=glossary,
                report_path=report_path,
                session_mistakes_path=session_mistakes,
                session_glossary_path=session_glossary,
                min_proper_count=1,
                proper_zipf_threshold=5.0,
            )

            self.assertTrue(report_path.exists(), "Report Markdown should be created")
            self.assertTrue(session_mistakes.exists(), "Session mistakes JSON should be created")
            self.assertTrue(session_glossary.exists(), "Session glossary text should be created")

            self.assertEqual(result.report["metadata"]["total_lines"], 6)
            self.assertIn("Cailus", result.report["proper_noun_candidates"])
            self.assertIn("examples", result.report["proper_noun_candidates"]["Cailus"])
            self.assertIn("# Transcript QC Report", result.report_markdown)
            file_text = report_path.read_text(encoding="utf-8")
            self.assertEqual(file_text, result.report_markdown)
            self.assertIn("Quality Overview", file_text)

            text_entries = result.session_mistakes
            self.assertEqual(text_entries["glaces"], "glances")
            self.assertIn("Cailus", text_entries)
            self.assertEqual(text_entries["Cailus"], "")

            glossary_terms = session_glossary.read_text(encoding="utf-8").strip().splitlines()
            self.assertListEqual(glossary_terms, ["Neverwinter", "Seasilk Docks"])

            report_payload = result.report
            self.assertIn("quality", report_payload)
            self.assertIn(report_payload["quality"]["grade"], {"rough", "needs_review", "mostly_clean", "insufficient_sample"})
            self.assertIn("score", report_payload["quality"])
            self.assertIn("sample_word_count", report_payload["quality"])
            self.assertIn("transcription_errors", report_payload)


if __name__ == "__main__":
    unittest.main()
