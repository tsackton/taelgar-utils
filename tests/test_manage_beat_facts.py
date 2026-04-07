from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "tests" / "data" / "beat_facts"
SCRIPT_PATH = REPO_ROOT / "skills" / "beat-annotator" / "scripts" / "manage_beat_facts.py"


class ManageBeatFactsTest(unittest.TestCase):
    def make_workspace(self) -> Path:
        tmpdir = Path(tempfile.mkdtemp(prefix="beat-facts-test."))
        self.addCleanup(lambda: shutil.rmtree(tmpdir, ignore_errors=True))
        shutil.copytree(FIXTURE_DIR, tmpdir / "fixture")
        return tmpdir / "fixture"

    def load_json(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def write_json(self, path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def run_validator(self, workspace: Path) -> subprocess.CompletedProcess[str]:
        output_dir = workspace / "out"
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--session",
                str(workspace / "session.yaml"),
                "--beats-json",
                str(workspace / "beats.json"),
                "--beat-facts-json",
                str(workspace / "beat-facts.json"),
                "--output-dir",
                str(output_dir),
                "--file-prefix",
                "test-session-007",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_valid_input_writes_outputs_and_normalizes_dates(self) -> None:
        workspace = self.make_workspace()
        result = self.run_validator(workspace)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        output_json = self.load_json(workspace / "out" / "test-session-007-beat-facts.json")
        self.assertEqual(output_json["facts"][0]["dateStart"], "1372-05-14")
        self.assertIsNone(output_json["facts"][0]["dateEnd"])
        self.assertEqual(output_json["facts"][0]["timeWindow"], "evening")
        self.assertEqual(output_json["facts"][1]["dateStart"], "1372-05-15")
        preview_text = (workspace / "out" / "test-session-007-beat-facts-preview.md").read_text(encoding="utf-8")
        self.assertIn("# Beat Facts Preview", preview_text)
        self.assertIn("## Arrival at the Shrine", preview_text)
        self.assertIn("*b01*", preview_text)
        self.assertIn("**NPCs**:", preview_text)
        self.assertIn("- Caretaker Nella (encountered): host. She greets the party at the shrine.", preview_text)

    def test_missing_beat_fails(self) -> None:
        workspace = self.make_workspace()
        payload = self.load_json(workspace / "beat-facts.json")
        payload["facts"] = payload["facts"][:1]
        self.write_json(workspace / "beat-facts.json", payload)

        result = self.run_validator(workspace)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing beat fact for b02", result.stdout)

    def test_duplicate_beat_fails(self) -> None:
        workspace = self.make_workspace()
        payload = self.load_json(workspace / "beat-facts.json")
        payload["facts"][1]["beatId"] = "b01"
        self.write_json(workspace / "beat-facts.json", payload)

        result = self.run_validator(workspace)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Duplicate beatId in beat-facts: b01", result.stdout)

    def test_unknown_beat_fails(self) -> None:
        workspace = self.make_workspace()
        payload = self.load_json(workspace / "beat-facts.json")
        payload["facts"][1]["beatId"] = "b99"
        self.write_json(workspace / "beat-facts.json", payload)

        result = self.run_validator(workspace)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unknown beatId in beat-facts: b99", result.stdout)

    def test_out_of_order_fails(self) -> None:
        workspace = self.make_workspace()
        payload = self.load_json(workspace / "beat-facts.json")
        payload["facts"] = [payload["facts"][1], payload["facts"][0]]
        self.write_json(workspace / "beat-facts.json", payload)

        result = self.run_validator(workspace)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Beat facts are out of order relative to beats.json.", result.stdout)

    def test_participant_tagged_as_npc_warns(self) -> None:
        workspace = self.make_workspace()
        payload = self.load_json(workspace / "beat-facts.json")
        payload["facts"][0]["npcs"][0]["name"] = "Mira"
        self.write_json(workspace / "beat-facts.json", payload)

        result = self.run_validator(workspace)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("b01 tags participant/game role as NPC: Mira", result.stdout)

    def test_combat_mismatch_warns(self) -> None:
        workspace = self.make_workspace()
        payload = self.load_json(workspace / "beat-facts.json")
        payload["facts"][1]["combat"] = {"isCombat": False}
        self.write_json(workspace / "beat-facts.json", payload)

        result = self.run_validator(workspace)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("b02 combat mismatch", result.stdout)

    def test_missing_location_defaults_to_unknown_with_warning(self) -> None:
        workspace = self.make_workspace()
        payload = self.load_json(workspace / "beat-facts.json")
        del payload["facts"][0]["location"]
        self.write_json(workspace / "beat-facts.json", payload)

        result = self.run_validator(workspace)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("b01 is missing location; defaulting to unknown.", result.stdout)
        output_json = self.load_json(workspace / "out" / "test-session-007-beat-facts.json")
        self.assertEqual(output_json["facts"][0]["location"]["kind"], "unknown")

    def test_main_enemies_do_not_require_role_and_legacy_role_is_dropped(self) -> None:
        workspace = self.make_workspace()
        payload = self.load_json(workspace / "beat-facts.json")
        payload["facts"][1]["combat"]["mainEnemies"][0]["role"] = "enemy"
        self.write_json(workspace / "beat-facts.json", payload)

        result = self.run_validator(workspace)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        output_json = self.load_json(workspace / "out" / "test-session-007-beat-facts.json")
        main_enemy = output_json["facts"][1]["combat"]["mainEnemies"][0]
        self.assertEqual(main_enemy["name"], "Ashen Knives raiders")
        self.assertEqual(main_enemy["notes"], "Primary attackers.")
        self.assertNotIn("role", main_enemy)


if __name__ == "__main__":
    unittest.main()
