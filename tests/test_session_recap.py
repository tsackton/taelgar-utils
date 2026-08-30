from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "tests" / "data" / "session_summary"
CONTEXT_BUILDER_PATH = REPO_ROOT / "skills" / "session-summary" / "scripts" / "build_session_summary_context.py"
RECAP_BUILDER_PATH = REPO_ROOT / "skills" / "session-summary" / "scripts" / "build_session_recap.py"
RECAP_VALIDATOR_PATH = REPO_ROOT / "skills" / "session-summary" / "scripts" / "manage_session_recap.py"
RECAP_SCENES_VALIDATOR_PATH = REPO_ROOT / "skills" / "session-summary" / "scripts" / "manage_recap_scenes.py"


class SessionRecapBase(unittest.TestCase):
    def make_workspace(self) -> Path:
        tmpdir = Path(tempfile.mkdtemp(prefix="session-recap-test."))
        self.addCleanup(lambda: shutil.rmtree(tmpdir, ignore_errors=True))
        shutil.copytree(FIXTURE_DIR, tmpdir / "fixture")
        return tmpdir / "fixture"

    def load_json(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def write_json(self, path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def load_yaml(self, path: Path) -> dict:
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    def write_yaml(self, path: Path, payload: dict) -> None:
        path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    def run_context_builder(
        self,
        workspace: Path,
        recap_scenes_path: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        output_dir = workspace / "out"
        command = [
            sys.executable,
            str(CONTEXT_BUILDER_PATH),
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
        ]
        if recap_scenes_path is not None:
            command.extend(["--recap-scenes-json", str(recap_scenes_path)])
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )

    def run_recap_scenes_validator(
        self,
        workspace: Path,
        recap_scenes_path: Path,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(RECAP_SCENES_VALIDATOR_PATH),
                "--beats-json",
                str(workspace / "beats.json"),
                "--beat-facts-json",
                str(workspace / "beat-facts.json"),
                "--recap-scenes-json",
                str(recap_scenes_path),
                "--output-dir",
                str(workspace / "out"),
                "--file-prefix",
                "test-session-007",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def write_recap_scenes(self, workspace: Path, scenes: list[dict]) -> Path:
        path = workspace / "recap-scenes.json"
        self.write_json(path, {"schemaVersion": "1.0", "scenes": scenes})
        return path

    def run_recap_builder(self, workspace: Path) -> subprocess.CompletedProcess[str]:
        output_dir = workspace / "recap"
        return subprocess.run(
            [
                sys.executable,
                str(RECAP_BUILDER_PATH),
                "--context-json",
                str(workspace / "out" / "test-session-007-session-summary-context.json"),
                "--output-dir",
                str(output_dir),
                "--file-prefix",
                "test-session-007",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def run_recap_validator(self, workspace: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(RECAP_VALIDATOR_PATH),
                "--context-json",
                str(workspace / "out" / "test-session-007-session-summary-context.json"),
                "--session-recap-md",
                str(workspace / "recap" / "test-session-007-session-recap.md"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )


class BuildSessionSummaryContextTest(SessionRecapBase):
    def test_same_afternoon_collapses_to_one_timeline_block(self) -> None:
        workspace = self.make_workspace()
        result = self.run_context_builder(workspace)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = self.load_json(workspace / "out" / "test-session-007-session-summary-context.json")
        self.assertEqual(len(payload["timelineBlocks"]), 1)
        self.assertEqual(payload["timelineBlocks"][0]["beatIds"], ["beat-001", "beat-002", "beat-003"])

    def test_multi_day_input_splits_timeline_blocks(self) -> None:
        workspace = self.make_workspace()
        beats = self.load_json(workspace / "beats.json")
        facts = self.load_json(workspace / "beat-facts.json")
        beats["beats"][2]["dateStart"] = "1730-01-26"
        facts["facts"][2]["dateStart"] = "1730-01-26"
        self.write_json(workspace / "beats.json", beats)
        self.write_json(workspace / "beat-facts.json", facts)

        result = self.run_context_builder(workspace)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = self.load_json(workspace / "out" / "test-session-007-session-summary-context.json")
        self.assertEqual(len(payload["timelineBlocks"]), 2)

    def test_adjacent_combat_beats_collapse_into_one_recap_block(self) -> None:
        workspace = self.make_workspace()
        beats = self.load_json(workspace / "beats.json")
        facts = self.load_json(workspace / "beat-facts.json")
        for index in (0, 1):
            beats["beats"][index]["containsCombat"] = True
            facts["facts"][index]["combat"] = {
                "isCombat": True,
                "phase": "middle" if index else "start",
                "mainEnemies": [{"name": "Ice wraiths", "role": "encountered"}],
            }
        self.write_json(workspace / "beats.json", beats)
        self.write_json(workspace / "beat-facts.json", facts)

        result = self.run_context_builder(workspace)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = self.load_json(workspace / "out" / "test-session-007-session-summary-context.json")
        self.assertEqual(payload["recapBlocks"][0]["kind"], "combat")
        self.assertEqual(payload["recapBlocks"][0]["beatIds"], ["beat-001", "beat-002"])

    def test_adjacent_full_combat_beats_stay_separate_recap_blocks(self) -> None:
        workspace = self.make_workspace()
        beats = self.load_json(workspace / "beats.json")
        facts = self.load_json(workspace / "beat-facts.json")
        for index in (0, 1):
            beats["beats"][index]["containsCombat"] = True
            facts["facts"][index]["combat"] = {
                "isCombat": True,
                "phase": "full",
                "mainEnemies": [{"name": "Ice wraiths", "role": "encountered"}],
            }
        self.write_json(workspace / "beats.json", beats)
        self.write_json(workspace / "beat-facts.json", facts)

        result = self.run_context_builder(workspace)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = self.load_json(workspace / "out" / "test-session-007-session-summary-context.json")
        self.assertEqual(payload["recapBlocks"][0]["kind"], "combat")
        self.assertEqual(payload["recapBlocks"][0]["beatIds"], ["beat-001"])
        self.assertEqual(payload["recapBlocks"][1]["kind"], "combat")
        self.assertEqual(payload["recapBlocks"][1]["beatIds"], ["beat-002"])


    def test_recap_refs_exclude_mentioned_entities(self) -> None:
        workspace = self.make_workspace()
        facts = self.load_json(workspace / "beat-facts.json")
        facts["facts"][0]["npcs"].append({"name": "Zeyfa", "role": "mentioned", "context": "ancient figure tied to the maze"})
        self.write_json(workspace / "beat-facts.json", facts)

        result = self.run_context_builder(workspace)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = self.load_json(workspace / "out" / "test-session-007-session-summary-context.json")
        self.assertEqual(payload["recapBlocks"][0]["npcRefs"], ["Kalima"])
        self.assertEqual(payload["worldCandidates"]["mentioned"]["npcs"][0]["name"], "Zeyfa")

    def test_approved_scene_groups_control_recap_blocks(self) -> None:
        workspace = self.make_workspace()
        recap_scenes_path = self.write_recap_scenes(
            workspace,
            [
                {
                    "sceneId": "scene-001",
                    "title": "Entering the Labyrinth",
                    "beatIds": ["beat-001", "beat-002"],
                    "rationale": "The descent and fissure discovery form one continuous exploration scene.",
                },
                {
                    "sceneId": "scene-002",
                    "title": "Across the Fissure",
                    "beatIds": ["beat-003"],
                    "rationale": "The dangerous crossing is the next distinct situation.",
                },
            ],
        )

        result = self.run_context_builder(workspace, recap_scenes_path)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = self.load_json(workspace / "out" / "test-session-007-session-summary-context.json")
        self.assertEqual(payload["recapScenesPath"], str(recap_scenes_path.resolve()))
        self.assertEqual([block["beatIds"] for block in payload["recapBlocks"]], [["beat-001", "beat-002"], ["beat-003"]])
        self.assertEqual([block["title"] for block in payload["recapBlocks"]], ["Entering the Labyrinth", "Across the Fissure"])

    def test_scene_group_can_include_setup_and_combat(self) -> None:
        workspace = self.make_workspace()
        beats = self.load_json(workspace / "beats.json")
        facts = self.load_json(workspace / "beat-facts.json")
        beats["beats"][1]["containsCombat"] = True
        facts["facts"][1]["combat"] = {
            "isCombat": True,
            "phase": "full",
            "mainEnemies": [{"name": "Ice wraiths", "role": "enemy"}],
        }
        self.write_json(workspace / "beats.json", beats)
        self.write_json(workspace / "beat-facts.json", facts)
        recap_scenes_path = self.write_recap_scenes(
            workspace,
            [
                {
                    "sceneId": "scene-001",
                    "title": "Discovery and Attack",
                    "beatIds": ["beat-001", "beat-002"],
                    "rationale": "The setup runs directly into the combat without a scene break.",
                },
                {
                    "sceneId": "scene-002",
                    "title": "Deeper In",
                    "beatIds": ["beat-003"],
                    "rationale": "The party moves into the next situation after the fight.",
                },
            ],
        )

        result = self.run_context_builder(workspace, recap_scenes_path)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = self.load_json(workspace / "out" / "test-session-007-session-summary-context.json")
        self.assertEqual(payload["recapBlocks"][0]["kind"], "combat")
        self.assertEqual(payload["recapBlocks"][0]["beatIds"], ["beat-001", "beat-002"])
        self.assertEqual(payload["recapBlocks"][0]["combatEnemyRefs"], ["Ice wraiths"])
        self.assertEqual(payload["recapExtrasCandidates"]["combats"][0]["blockId"], "recap-001")


class ManageRecapScenesTest(SessionRecapBase):
    def test_valid_scene_map_writes_preview(self) -> None:
        workspace = self.make_workspace()
        recap_scenes_path = self.write_recap_scenes(
            workspace,
            [
                {
                    "sceneId": "scene-001",
                    "title": "The Descent",
                    "beatIds": ["beat-001", "beat-002"],
                    "rationale": "The party remains in one continuous exploratory situation.",
                },
                {
                    "sceneId": "scene-002",
                    "title": "The Crossing",
                    "beatIds": ["beat-003"],
                    "rationale": "The fissure crossing creates a distinct scene goal.",
                },
            ],
        )

        result = self.run_recap_scenes_validator(workspace, recap_scenes_path)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        preview = (workspace / "out" / "test-session-007-recap-scenes-preview.md").read_text(encoding="utf-8")
        self.assertIn("- Scene Count: 2", preview)
        self.assertIn("- Beat Coverage: 3/3", preview)
        self.assertIn("## scene-001 | The Descent", preview)
        self.assertIn("beat-001 | Into the Labyrinth", preview)

    def test_scene_map_rejects_missing_or_reordered_beats(self) -> None:
        workspace = self.make_workspace()
        recap_scenes_path = self.write_recap_scenes(
            workspace,
            [
                {
                    "sceneId": "scene-001",
                    "title": "Out of Order",
                    "beatIds": ["beat-002", "beat-001"],
                    "rationale": "Invalid test grouping.",
                }
            ],
        )

        result = self.run_recap_scenes_validator(workspace, recap_scenes_path)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cover every beat exactly once in original order", result.stdout)


class BuildSessionRecapTest(SessionRecapBase):
    def test_builds_structured_markdown_scaffold(self) -> None:
        workspace = self.make_workspace()
        result = self.run_context_builder(workspace)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        result = self.run_recap_builder(workspace)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        recap_text = (workspace / "recap" / "test-session-007-session-recap.md").read_text(encoding="utf-8")
        self.assertTrue(recap_text.startswith("# Session Recap\n"))
        self.assertIn("## Session Header", recap_text)
        self.assertIn("- Title: TODO", recap_text)
        self.assertIn("- Desc Title: TODO", recap_text)
        self.assertIn("- Tagline: TODO", recap_text)
        self.assertIn("- One-Sentence Summary: TODO", recap_text)
        self.assertIn("- Arc: none", recap_text)
        self.assertIn("- DM: Maris", recap_text)
        self.assertIn("- PCs: Ekko, Justas, Eolo", recap_text)
        self.assertIn("- Table Notes: none", recap_text)
        self.assertIn("## Timeline", recap_text)
        self.assertIn("### Jan 25th, 1730 (afternoon)", recap_text)
        self.assertIn("- Timeline Segment: timeline-001", recap_text)
        self.assertIn("- Timeline Key: (DR:: 1730-01-25), afternoon", recap_text)
        self.assertIn("#### Short", recap_text)
        timeline_text = recap_text.split("## Timeline", 1)[1].split("## Recap", 1)[0]
        self.assertNotIn("#### Long", timeline_text)
        self.assertIn("## Recap", recap_text)
        self.assertIn("### recap-001 | Into the Labyrinth", recap_text)
        self.assertIn(
            "- Image:\n"
            "- Image Placement:\n"
            "- Image Render:\n"
            "- Image Caption:",
            recap_text,
        )
        self.assertIn("#### Intermediate", recap_text)
        self.assertIn("## Source Files", recap_text)
        self.assertIn("source.cleaned.md", recap_text)

    def test_multi_day_beat_expands_to_daily_timeline_blocks(self) -> None:
        workspace = self.make_workspace()
        beats = self.load_json(workspace / "beats.json")
        beats["beats"][2]["dateEnd"] = "1730-01-27"
        beats["beats"][2]["timeWindow"] = None
        self.write_json(workspace / "beats.json", beats)

        result = self.run_context_builder(workspace)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        context_path = workspace / "out" / "test-session-007-session-summary-context.json"
        context = self.load_json(context_path)
        daily_blocks = context["timelineBlocks"][-3:]
        self.assertEqual([block["dateStart"] for block in daily_blocks], ["1730-01-25", "1730-01-26", "1730-01-27"])
        self.assertTrue(all(block["dateEnd"] is None for block in daily_blocks))
        self.assertTrue(all(block["beatIds"] == ["beat-003"] for block in daily_blocks))
        self.assertEqual(
            [block["sourceEntries"][0]["sourceDateSpan"]["dayPosition"] for block in daily_blocks],
            ["start", "middle", "end"],
        )

        result = self.run_recap_builder(workspace)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        recap_path = workspace / "recap" / "test-session-007-session-recap.md"
        recap_text = recap_path.read_text(encoding="utf-8")
        timeline_text = recap_text.split("## Timeline", 1)[1].split("## Recap", 1)[0]
        self.assertIn("- Timeline Key: (DR:: 1730-01-25)", timeline_text)
        self.assertIn("- Timeline Key: (DR:: 1730-01-26)", timeline_text)
        self.assertIn("- Timeline Key: (DR:: 1730-01-27)", timeline_text)
        self.assertNotIn("DR_end", timeline_text)
        self.assertNotIn("#### Long", timeline_text)

        recap_text = recap_text.replace("TODO", "Drafted text.")
        recap_text = recap_text.replace("- Tagline: Drafted text.", "- Tagline: in which the party descends.")
        recap_path.write_text(recap_text, encoding="utf-8")

        result = self.run_recap_validator(workspace)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_undated_blocks_render_cleanly(self) -> None:
        workspace = self.make_workspace()
        beats = self.load_json(workspace / "beats.json")
        facts = self.load_json(workspace / "beat-facts.json")
        beats["beats"][0]["dateStart"] = None
        beats["beats"][0]["dateEnd"] = None
        beats["beats"][0]["timeWindow"] = None
        beats["beats"][0]["dateResolution"] = "unknown"
        beats["beats"][0]["dateEvidence"] = []
        facts["facts"][0]["location"] = {
            "kind": "unknown",
            "context": "The source does not pin down the exact chamber.",
        }
        self.write_json(workspace / "beats.json", beats)
        self.write_json(workspace / "beat-facts.json", facts)

        result = self.run_context_builder(workspace)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        result = self.run_recap_builder(workspace)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        recap_text = (workspace / "recap" / "test-session-007-session-recap.md").read_text(encoding="utf-8")
        self.assertIn("### Undated (ordered)", recap_text)
        self.assertIn("- Timeline Key: undated", recap_text)
        self.assertIn("- Source Range: u0001 -> u0100", recap_text)

    def test_scaffold_keeps_world_entries_compact(self) -> None:
        workspace = self.make_workspace()
        result = self.run_context_builder(workspace)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        result = self.run_recap_builder(workspace)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        recap_text = (workspace / "recap" / "test-session-007-session-recap.md").read_text(encoding="utf-8")
        self.assertIn("- Kalima (companion): frightened guide", recap_text)
        self.assertIn("  - Zeyfa's Labyrinth, 1730-01-25", recap_text)
        self.assertIn("- Zeyfa's Labyrinth", recap_text)
        self.assertIn("  - Summary: TODO", recap_text)
        self.assertIn(
            "  - Sublocations: descending from the ice bridge and probing the first forked passages within the labyrinth",
            recap_text,
        )
        self.assertIn("  - Date Visited: 1730-01-25", recap_text)

    def test_scaffold_combat_section_is_structured(self) -> None:
        workspace = self.make_workspace()
        beats = self.load_json(workspace / "beats.json")
        facts = self.load_json(workspace / "beat-facts.json")
        for index in (1, 2):
            beats["beats"][index]["containsCombat"] = True
            facts["facts"][index]["combat"] = {
                "isCombat": True,
                "phase": "middle" if index == 2 else "start",
                "mainEnemies": [{"name": "Ice wraiths", "role": "enemy"}],
            }
        self.write_json(workspace / "beats.json", beats)
        self.write_json(workspace / "beat-facts.json", facts)

        result = self.run_context_builder(workspace)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        result = self.run_recap_builder(workspace)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        recap_text = (workspace / "recap" / "test-session-007-session-recap.md").read_text(encoding="utf-8")
        self.assertIn("## Combat", recap_text)
        self.assertIn("### recap-002 | TODO", recap_text)
        self.assertIn("- Enemies: Ice wraiths", recap_text)
        self.assertIn("- Context / Outcome: TODO", recap_text)

    def test_non_transcript_source_frontmatter_players_override_session_pcs(self) -> None:
        workspace = self.make_workspace()
        session_path = workspace / "session.yaml"
        session_payload = self.load_yaml(session_path)
        source_note = workspace / "source-note.md"
        source_note.write_text(
            "---\nplayers:\n  - Ryu\n  - Wazir\n  - Trok\n---\n\n# Source\n\nBody.\n",
            encoding="utf-8",
        )
        session_payload["sourceType"] = "narrative"
        session_payload["sourceInputPath"] = str(source_note)
        session_payload["pcs"] = ["Wrong", "Values"]
        self.write_yaml(session_path, session_payload)

        result = self.run_context_builder(workspace)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        result = self.run_recap_builder(workspace)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        recap_text = (workspace / "recap" / "test-session-007-session-recap.md").read_text(encoding="utf-8")
        self.assertIn("- PCs: Ryu, Wazir, Trok", recap_text)

    def test_transcript_speaker_stats_infer_only_active_pc_roles(self) -> None:
        workspace = self.make_workspace()
        session_path = workspace / "session.yaml"
        session_payload = self.load_yaml(session_path)
        session_payload["sourceType"] = "transcript"
        session_payload.pop("pcs", None)
        session_payload["participants"] = [
            {"name": "David Kong", "gameRole": "Ryu"},
            {"name": "Mike Sackton", "gameRole": "Wazir"},
            {"name": "Eric Rosenbaum", "gameRole": "Trok"},
            {"name": "Tim Sackton", "gameRole": "DM"},
        ]
        speaker_stats_path = workspace / "speaker-stats.json"
        speaker_stats_path.write_text(
            json.dumps(
                {
                    "speakers": [
                        {"gameRole": "Ryu", "segmentCount": 12, "durationSeconds": 100, "wordCount": 500},
                        {"gameRole": "Trok", "segmentCount": 8, "durationSeconds": 70, "wordCount": 300},
                        {"gameRole": "DM", "segmentCount": 40, "durationSeconds": 250, "wordCount": 2000},
                        {"gameRole": "Unknown", "segmentCount": 3, "durationSeconds": 10, "wordCount": 20},
                    ]
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        session_payload["speakerStatsPath"] = str(speaker_stats_path)
        self.write_yaml(session_path, session_payload)

        result = self.run_context_builder(workspace)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        result = self.run_recap_builder(workspace)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        recap_text = (workspace / "recap" / "test-session-007-session-recap.md").read_text(encoding="utf-8")
        self.assertIn("- PCs: Ryu, Trok", recap_text)
        self.assertNotIn("- PCs: David Kong", recap_text)


class ManageSessionRecapTest(SessionRecapBase):
    def test_valid_recap_passes_validation(self) -> None:
        workspace = self.make_workspace()
        result = self.run_context_builder(workspace)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        result = self.run_recap_builder(workspace)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        recap_path = workspace / "recap" / "test-session-007-session-recap.md"
        recap_text = recap_path.read_text(encoding="utf-8").replace("TODO", "Drafted text.")
        recap_text = recap_text.replace("- Tagline: Drafted text.", "- Tagline: in which the party descends.")
        recap_path.write_text(recap_text, encoding="utf-8")

        result = self.run_recap_validator(workspace)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Validated", result.stdout)

    def test_locations_without_sublocations_fail_agent_validation(self) -> None:
        workspace = self.make_workspace()
        result = self.run_context_builder(workspace)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        result = self.run_recap_builder(workspace)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        recap_path = workspace / "recap" / "test-session-007-session-recap.md"
        recap_lines = recap_path.read_text(encoding="utf-8").replace("TODO", "Drafted text.").splitlines()
        recap_text = "\n".join(line for line in recap_lines if not line.startswith("  - Sublocations:")) + "\n"
        recap_text = recap_text.replace("- Tagline: Drafted text.", "- Tagline: in which the party descends.")
        recap_path.write_text(recap_text, encoding="utf-8")

        result = self.run_recap_validator(workspace)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("is missing Sublocations.", result.stdout)

    def test_missing_recap_subsection_fails_validation(self) -> None:
        workspace = self.make_workspace()
        result = self.run_context_builder(workspace)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        result = self.run_recap_builder(workspace)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        recap_path = workspace / "recap" / "test-session-007-session-recap.md"
        recap_text = recap_path.read_text(encoding="utf-8").replace("TODO", "Drafted text.")
        recap_text = recap_text.replace("- Tagline: Drafted text.", "- Tagline: in which the party descends.")
        recap_text = recap_text.replace("#### Intermediate\nDrafted text.\n", "")
        recap_path.write_text(recap_text, encoding="utf-8")

        result = self.run_recap_validator(workspace)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("recap recap-001 is missing subsection #### Intermediate.", result.stdout)

    def test_validator_allows_human_omitted_context_blocks(self) -> None:
        workspace = self.make_workspace()
        beats = self.load_json(workspace / "beats.json")
        facts = self.load_json(workspace / "beat-facts.json")
        beats["beats"][2]["dateStart"] = "1730-01-26"
        facts["facts"][2]["dateStart"] = "1730-01-26"
        self.write_json(workspace / "beats.json", beats)
        self.write_json(workspace / "beat-facts.json", facts)

        result = self.run_context_builder(workspace)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        result = self.run_recap_builder(workspace)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        recap_path = workspace / "recap" / "test-session-007-session-recap.md"
        recap_text = recap_path.read_text(encoding="utf-8").replace("TODO", "Drafted text.")
        recap_text = recap_text.replace("- Tagline: Drafted text.", "- Tagline: in which the party descends.")
        recap_text = recap_text.replace(
            "\n### Jan 26th, 1730\n"
            "\n"
            "- Timeline Segment: timeline-002\n"
            "- Timeline Key: (DR:: 1730-01-26)\n"
            "- Resolution: day\n"
            "- Beat IDs: beat-003\n"
            "- Locations: Zeyfa's Labyrinth\n"
            "- NPCs: Kalima\n"
            "- Organizations: none\n"
            "- Items: none\n"
            "- Combat Beats: none\n"
            "\n"
            "#### Short\n"
            "Drafted text: Jan 26th, 1730: one short event-log line.\n"
            "\n",
            "",
        )
        recap_text = recap_text.replace(
            "\n### recap-002 | The Warm Fissure\n"
            "\n"
            "- Kind: beat\n"
            "- Beat IDs: beat-002\n"
            "- Date: 1730-01-25\n"
            "- Time: afternoon\n"
            "- Source Range: u0101 -> u0200\n"
            "- Locations: Zeyfa's Labyrinth\n"
            "- NPCs: Kalima\n"
            "- Organizations: none\n"
            "- Items: heating rune\n"
            "- Enemies: none\n"
            "- Image:\n"
            "- Image Placement:\n"
            "- Image Render:\n"
            "- Image Caption:\n"
            "\n"
            "#### Short\n"
            "Drafted text.\n"
            "\n"
            "#### Intermediate\n"
            "Drafted text.\n"
            "\n"
            "#### Long\n"
            "Drafted text.\n",
            "",
        )
        recap_path.write_text(recap_text, encoding="utf-8")

        result = self.run_recap_validator(workspace)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unknown_recap_block_fails_validation(self) -> None:
        workspace = self.make_workspace()
        result = self.run_context_builder(workspace)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        result = self.run_recap_builder(workspace)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        recap_path = workspace / "recap" / "test-session-007-session-recap.md"
        recap_text = recap_path.read_text(encoding="utf-8").replace("TODO", "Drafted text.")
        recap_text = recap_text.replace("- Tagline: Drafted text.", "- Tagline: in which the party descends.")
        recap_text = recap_text.replace("### recap-001 | Into the Labyrinth", "### recap-999 | Into the Labyrinth")
        recap_path.write_text(recap_text, encoding="utf-8")

        result = self.run_recap_validator(workspace)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Recap block recap-999 is not present in context.", result.stdout)

    def test_unfilled_title_fails_validation(self) -> None:
        workspace = self.make_workspace()
        result = self.run_context_builder(workspace)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        result = self.run_recap_builder(workspace)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        recap_path = workspace / "recap" / "test-session-007-session-recap.md"
        recap_text = recap_path.read_text(encoding="utf-8").replace("TODO", "Drafted text.")
        recap_text = recap_text.replace("- Title: Drafted text.", "- Title: TODO")
        recap_text = recap_text.replace("- Tagline: Drafted text.", "- Tagline: in which the party descends.")
        recap_path.write_text(recap_text, encoding="utf-8")

        result = self.run_recap_validator(workspace)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("session-recap.md still contains TODO placeholders.", result.stdout)

    def test_unfilled_todo_placeholders_fail_validation(self) -> None:
        workspace = self.make_workspace()
        result = self.run_context_builder(workspace)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        result = self.run_recap_builder(workspace)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        result = self.run_recap_validator(workspace)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("session-recap.md still contains TODO placeholders.", result.stdout)

    def test_analytical_recap_opener_fails_validation(self) -> None:
        workspace = self.make_workspace()
        result = self.run_context_builder(workspace)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        result = self.run_recap_builder(workspace)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        recap_path = workspace / "recap" / "test-session-007-session-recap.md"
        recap_text = recap_path.read_text(encoding="utf-8").replace("TODO", "Drafted text.")
        recap_text = recap_text.replace("- Tagline: Drafted text.", "- Tagline: in which the party descends.")
        recap_text = recap_text.replace(
            "### recap-001 | Into the Labyrinth\n"
            "\n"
            "- Kind: beat\n"
            "- Beat IDs: beat-001\n"
            "- Date: 1730-01-25\n"
            "- Time: afternoon\n"
            "- Source Range: u0001 -> u0100\n"
            "- Locations: Zeyfa's Labyrinth\n"
            "- NPCs: Kalima\n"
            "- Organizations: none\n"
            "- Items: Romil's token\n"
            "- Enemies: none\n"
            "- Image:\n"
            "- Image Placement:\n"
            "- Image Render:\n"
            "- Image Caption:\n"
            "\n"
            "#### Short\n"
            "Drafted text.\n"
            "\n"
            "#### Intermediate\n"
            "Drafted text.\n"
            "\n"
            "#### Long\n"
            "Drafted text.\n",
            "### recap-001 | Into the Labyrinth\n"
            "\n"
            "- Kind: beat\n"
            "- Beat IDs: beat-001\n"
            "- Date: 1730-01-25\n"
            "- Time: afternoon\n"
            "- Source Range: u0001 -> u0100\n"
            "- Locations: Zeyfa's Labyrinth\n"
            "- NPCs: Kalima\n"
            "- Organizations: none\n"
            "- Items: Romil's token\n"
            "- Enemies: none\n"
            "- Image:\n"
            "- Image Placement:\n"
            "- Image Render:\n"
            "- Image Caption:\n"
            "\n"
            "#### Short\n"
            "Drafted text.\n"
            "\n"
            "#### Intermediate\n"
            "Drafted text.\n"
            "\n"
            "#### Long\n"
            "The opening establishes the Great Chasm as a gathering point for fear.\n",
            1,
        )
        recap_path.write_text(recap_text, encoding="utf-8")

        result = self.run_recap_validator(workspace)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "recap recap-001 #### Long starts with analytical framing instead of direct recap prose.",
            result.stdout,
        )

    def test_fallback_pc_validation_allows_subset_of_participant_roster(self) -> None:
        workspace = self.make_workspace()
        session_path = workspace / "session.yaml"
        session_payload = self.load_yaml(session_path)
        session_payload.pop("pcs", None)
        session_payload["participants"] = [
            {"name": "David Kong", "gameRole": "Ryu"},
            {"name": "Mike Sackton", "gameRole": "Wazir"},
            {"name": "Eric Rosenbaum", "gameRole": "Trok"},
            {"name": "John Leeker", "gameRole": "Kaleho"},
            {"name": "Tim Sackton", "gameRole": "DM"},
        ]
        self.write_yaml(session_path, session_payload)

        result = self.run_context_builder(workspace)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        result = self.run_recap_builder(workspace)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        recap_path = workspace / "recap" / "test-session-007-session-recap.md"
        recap_text = recap_path.read_text(encoding="utf-8").replace("TODO", "Drafted text.")
        recap_text = recap_text.replace("- Tagline: Drafted text.", "- Tagline: in which the party descends.")
        recap_text = recap_text.replace("- PCs: Ryu, Wazir, Trok, Kaleho", "- PCs: Ryu, Wazir, Trok")
        recap_path.write_text(recap_text, encoding="utf-8")

        result = self.run_recap_validator(workspace)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
