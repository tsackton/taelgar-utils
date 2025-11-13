import json
import tempfile
import unittest
from pathlib import Path

from merge_session_vocab import merge_session_vocab


class MergeSessionVocabTests(unittest.TestCase):
    def test_merges_curated_session_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            dest_mistakes = tmp / "master_mistakes.json"
            dest_glossary = tmp / "master_glossary.txt"

            dest_mistakes.write_text(json.dumps({"Neverwinter": "Neverwinter"}, indent=2), encoding="utf-8")
            dest_glossary.write_text("Neverwinter\n", encoding="utf-8")

            session_mistakes = tmp / "session_known.json"
            session_mistakes.write_text(
                json.dumps({"Cailus": "Kaylus", "OldEntry": ""}, indent=2),
                encoding="utf-8",
            )
            session_glossary = tmp / "session_glossary.txt"
            session_glossary.write_text("Seasilk Docks\nNeverwinter\n", encoding="utf-8")

            result = merge_session_vocab(
                dest_mistakes=dest_mistakes,
                dest_glossary=dest_glossary,
                session_mistakes_paths=[session_mistakes],
                session_glossary_paths=[session_glossary],
            )

            merged_payload = json.loads(dest_mistakes.read_text(encoding="utf-8"))
            self.assertEqual(merged_payload["Cailus"], "Kaylus")
            self.assertIn("Neverwinter", merged_payload)

            glossary_entries = [line.strip() for line in dest_glossary.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertIn("Seasilk Docks", glossary_entries)
            self.assertEqual(len(glossary_entries), 2)

            self.assertEqual(result.merged_mistakes, 1)
            self.assertEqual(result.merged_glossary_terms, 1)


if __name__ == "__main__":
    unittest.main()
