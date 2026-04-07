from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "skills" / "session-summary" / "scripts"
SCRIPT_PATH = SCRIPT_DIR / "build_session_note_components.py"

sys.path.insert(0, str(SCRIPT_DIR))
from recap_markdown import SessionRecapParseError, parse_session_recap  # noqa: E402


class SessionNoteComponentsTest(unittest.TestCase):
    def make_workspace(self) -> Path:
        tmpdir = Path(tempfile.mkdtemp(prefix="session-note-components-test."))
        self.addCleanup(lambda: shutil.rmtree(tmpdir, ignore_errors=True))
        vault = tmpdir / "vault"
        (vault / ".obsidian").mkdir(parents=True)
        (vault / "_templates" / "session-notes").mkdir(parents=True)
        (vault / "People").mkdir(parents=True)
        (vault / "Places").mkdir(parents=True)
        (vault / "Items").mkdir(parents=True)
        (vault / "Organizations").mkdir(parents=True)
        (vault / "Campaigns" / "Test Campaign" / "Sessions").mkdir(parents=True)
        (vault / "_templates" / "session-notes" / "test-session.md").write_text(
            textwrap.dedent(
                """\
                # {session.title}

                *{session.tagline}*

                {session.summary}

                ## Timeline
                {timeline}

                ## Cast
                {cast}

                ## Narrative
                {narrative.short}
                """
            ),
            encoding="utf-8",
        )
        (vault / "session.yaml").write_text(
            textwrap.dedent(
                """\
                schemaVersion: "1.0"
                sourceType: transcript
                scope: session
                campaign: Test Campaign
                sessionNumber: 12
                realWorldDate: 2026-03-29
                drStart: 1730-01-25
                drEnd: 1730-01-25
                participants: []
                sourceInputPath: /tmp/source.cleaned.md
                sourceConfigPath: /tmp/config.yaml
                participantsPath: /tmp/participants.yaml
                preparedSourcePath: /tmp/prepared.md
                sessionNote:
                  templatePath: _templates/session-notes/test-session.md
                  generatedRoot: Campaigns/Test Campaign/_generated/session-notes
                  publishedNotePath: Campaigns/Test Campaign/Sessions/Test Session 12.md
                """
            ),
            encoding="utf-8",
        )
        (vault / "session-recap.md").write_text(self.reviewed_recap_text(), encoding="utf-8")
        (vault / "People" / "Kalima.md").write_text(
            textwrap.dedent(
                """\
                ---
                tags: [person]
                species: human
                gender: female
                pronunciation: kah-LEE-mah
                whereabouts: Frostbridge
                aliases: [Kalima of the Chasm]
                ---

                # Kalima
                """
            ),
            encoding="utf-8",
        )
        (vault / "Places" / "Zeyfa's Labyrinth.md").write_text(
            textwrap.dedent(
                """\
                ---
                tags: [place]
                typeOf: labyrinth
                whereabouts: Great Chasm
                ---

                # Zeyfa's Labyrinth
                """
            ),
            encoding="utf-8",
        )
        (vault / "Places" / "Great Chasm Encampment.md").write_text(
            textwrap.dedent(
                """\
                ---
                tags: [place]
                typeOf: encampment
                whereabouts: Great Chasm
                ---

                # Great Chasm Encampment
                """
            ),
            encoding="utf-8",
        )
        (vault / "Items" / "Romil's token.md").write_text(
            textwrap.dedent(
                """\
                ---
                tags: [object]
                typeOf: token
                owner: Kalima
                whereabouts: Frostbridge
                aliases: [Romil token]
                ---

                # Romil's token
                """
            ),
            encoding="utf-8",
        )
        (vault / "Organizations" / "Ashen Knives.md").write_text(
            textwrap.dedent(
                """\
                ---
                tags: [group]
                typeOf: raiders
                whereabouts: Great Chasm
                ---

                # Ashen Knives
                """
            ),
            encoding="utf-8",
        )
        return vault

    def reviewed_recap_text(self) -> str:
        return textwrap.dedent(
            """\
            # Session Recap

            ## Session Header

            - Title: Test Session 12: Into the Labyrinth
            - Tagline: in which the party descends
            - One-Sentence Summary: The party descends into Zeyfa's Labyrinth, fights Ashen Knives raiders, and escapes with Kalima and Romil's token.
            - Campaign: Test Campaign
            - Session Number: 12
            - DR Date: 1730-01-25
            - Real Date: 2026-03-29
            - DM: Maris
            - PCs: Ekko, Justas, Eolo

            ## Timeline

            ### Jan 25th, 1730 (afternoon)

            - Timeline Segment: timeline-001
            - Timeline Key: (DR:: 1730-01-25), afternoon
            - Resolution: part-of-day
            - Beat IDs: beat-001, beat-002
            - Locations: Zeyfa's Labyrinth
            - NPCs: Kalima
            - Organizations: Ashen Knives
            - Items: Romil's token
            - Combat Beats: beat-002

            #### Short
            The party enters Zeyfa's Labyrinth with Kalima and survives an ambush by Ashen Knives raiders.

            #### Long
            The party descends into Zeyfa's Labyrinth with Kalima as their guide, recovers Romil's token from the raiders, and breaks the Ashen Knives ambush before retreating back toward the surface.

            ### Jan 25th, 1730 (evening)

            - Timeline Segment: timeline-002
            - Timeline Key: (DR:: 1730-01-25), evening
            - Resolution: part-of-day
            - Beat IDs: beat-003
            - Locations: Great Chasm Encampment
            - NPCs: Kalima
            - Organizations: none
            - Items: Romil's token
            - Combat Beats: none

            #### Short
            At dusk the party returns to Great Chasm Encampment with Kalima and the recovered token.

            #### Long
            By evening the party is back at Great Chasm Encampment, where Kalima keeps close hold of Romil's token while the group shares the day's account and prepares for what comes next.

            ## Recap

            ### recap-001 | Into the Labyrinth

            - Kind: beat
            - Beat IDs: beat-001
            - Date: 1730-01-25
            - Time: afternoon
            - Source Range: u0001 -> u0100
            - Locations: Zeyfa's Labyrinth
            - NPCs: Kalima
            - Organizations: none
            - Items: none
            - Enemies: none

            #### Short
            The party descends into Zeyfa's Labyrinth with Kalima guiding them past the first frozen forks.

            #### Intermediate
            Kalima leads the party into Zeyfa's Labyrinth, where the first passages narrow under the ice and force the group to trust her memory of the maze.

            #### Long
            Kalima leads the party down the ice bridge and into Zeyfa's Labyrinth, where the frozen passages twist through old stone and leave the group dependent on her frightened but steady guidance.

            ### recap-002 | The Ashen Knives Ambush

            - Kind: combat
            - Beat IDs: beat-002
            - Date: 1730-01-25
            - Time: afternoon
            - Source Range: u0101 -> u0200
            - Locations: Zeyfa's Labyrinth
            - NPCs: Kalima
            - Organizations: Ashen Knives
            - Items: Romil's token
            - Enemies: Ashen Knives raiders

            #### Short
            Ashen Knives raiders spring an ambush in the maze, but the party drives them off and recovers Romil's token.

            #### Intermediate
            The Ashen Knives try to cut the party down in the frozen corridors, yet the ambush breaks apart when the raiders lose Romil's token and Kalima helps the party hold the line.

            #### Long
            Ashen Knives raiders crash into the party from a side passage and nearly split the group in the narrow corridor, but Kalima steadies the retreat long enough for the party to turn the fight, reclaim Romil's token, and force the survivors to flee deeper into the maze.

            ### recap-003 | Return to Camp

            - Kind: beat
            - Beat IDs: beat-003
            - Date: 1730-01-25
            - Time: evening
            - Source Range: u0201 -> u0280
            - Locations: Great Chasm Encampment
            - NPCs: Kalima
            - Organizations: none
            - Items: Romil's token
            - Enemies: none

            #### Short
            The party returns to Great Chasm Encampment with Kalima and the recovered token before night closes in.

            #### Intermediate
            By dusk the party is back in Great Chasm Encampment, where Kalima takes custody of Romil's token and the group recounts the Ashen Knives ambush to the camp.

            #### Long
            The party reaches Great Chasm Encampment by evening, hands Romil's token over to Kalima for safekeeping, and ends the day comparing the ambush to the older stories that first drew them into Zeyfa's Labyrinth.

            ## Cast

            ### NPCs

            - Kalima (companion): frightened guide
              - Zeyfa's Labyrinth, 1730-01-25
              - Great Chasm Encampment, 1730-01-25

            ## Locations

            - Zeyfa's Labyrinth: frozen maze beneath the Great Chasm
              - visited on 1730-01-25
            - Great Chasm Encampment: surface camp above the labyrinth
              - visited on 1730-01-25

            ## Organizations And Items

            ### Organizations

            - Ashen Knives (enemy): raiders contesting the labyrinth approaches
              - Zeyfa's Labyrinth, 1730-01-25

            ### Items

            - Romil's token (encountered): silver token recovered from the raiders
              - Zeyfa's Labyrinth, 1730-01-25
              - Great Chasm Encampment, 1730-01-25

            ## Combat

            ### recap-002 | The Ashen Knives Ambush

            - Beat IDs: beat-002
            - Enemies: Ashen Knives raiders
            - Context / Outcome: The party survives an Ashen Knives ambush in the labyrinth, routs the raiders, and recovers Romil's token.

            ## Source Files

            - Context JSON: /tmp/unused-context.json
            - Beats JSON: /tmp/unused-beats.json
            - Beat Facts JSON: /tmp/unused-beat-facts.json
            - Cleaned Source: /tmp/source.cleaned.md
            """
        )

    def run_builder(self, vault: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--session",
                str(vault / "session.yaml"),
                "--session-recap-md",
                str(vault / "session-recap.md"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_parser_extracts_reviewed_recap_sections(self) -> None:
        recap = parse_session_recap(self.reviewed_recap_text())

        self.assertEqual(recap["header"]["Title"], "Test Session 12: Into the Labyrinth")
        self.assertEqual(len(recap["timeline"]), 2)
        self.assertEqual(recap["timeline"][1]["locations"], ["Great Chasm Encampment"])
        self.assertEqual(recap["recap"][1]["kind"], "combat")
        self.assertEqual(recap["cast"][0]["name"], "Kalima")
        self.assertEqual(recap["items"][0]["history"][-1]["location"], "Great Chasm Encampment")
        self.assertEqual(recap["combat"][0]["title"], "The Ashen Knives Ambush")

    def test_parser_rejects_malformed_world_section(self) -> None:
        broken = self.reviewed_recap_text().replace("### NPCs", "### Allies")

        with self.assertRaises(SessionRecapParseError) as ctx:
            parse_session_recap(broken)

        self.assertTrue(any("Cast section is missing subsection ### NPCs." in error for error in ctx.exception.errors))

    def test_builder_writes_component_notes_with_required_frontmatter_and_slots(self) -> None:
        vault = self.make_workspace()
        result = self.run_builder(vault)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        component_dir = vault / "Campaigns" / "Test Campaign" / "_generated" / "session-notes" / "test-session-12"
        info_path = component_dir / "01-session-info.md"
        tech_path = component_dir / "02-technical-updates.md"
        narrative_path = component_dir / "03-narrative.md"
        self.assertTrue(info_path.exists())
        self.assertTrue(tech_path.exists())
        self.assertTrue(narrative_path.exists())

        info_text = info_path.read_text(encoding="utf-8")
        self.assertIn("tags: [status/check/ai]", info_text)
        self.assertIn('excludePublish: ["all"]', info_text)
        self.assertIn("<!-- SLOT: session.summary -->", info_text)
        self.assertIn("<!-- SLOT: timeline -->", info_text)

        tech_text = tech_path.read_text(encoding="utf-8")
        self.assertIn("<!-- SLOT: updates.whereabouts.party -->", tech_text)
        self.assertIn("<!-- SLOT: updates.review -->", tech_text)

        narrative_text = narrative_path.read_text(encoding="utf-8")
        self.assertIn("<!-- SLOT: narrative.short -->", narrative_text)
        self.assertIn("<!-- SLOT: narrative.long -->", narrative_text)

    def test_builder_uses_reviewed_recap_as_canonical_source(self) -> None:
        vault = self.make_workspace()
        recap_path = vault / "session-recap.md"
        recap_path.write_text(
            self.reviewed_recap_text().replace(
                "frightened guide",
                "battle-worn guide",
            ),
            encoding="utf-8",
        )

        result = self.run_builder(vault)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        info_text = (
            vault
            / "Campaigns"
            / "Test Campaign"
            / "_generated"
            / "session-notes"
            / "test-session-12"
            / "01-session-info.md"
        ).read_text(encoding="utf-8")
        self.assertIn("battle-worn guide", info_text)
        self.assertNotIn("frightened guide", info_text)

    def test_builder_enriches_from_notes_and_surfaces_location_conflicts(self) -> None:
        vault = self.make_workspace()
        result = self.run_builder(vault)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        component_dir = vault / "Campaigns" / "Test Campaign" / "_generated" / "session-notes" / "test-session-12"
        info_text = (component_dir / "01-session-info.md").read_text(encoding="utf-8")
        tech_text = (component_dir / "02-technical-updates.md").read_text(encoding="utf-8")

        self.assertIn("Existing note context: human; female; pronounced kah-LEE-mah.", info_text)
        self.assertIn("Existing note context: token; owned by Kalima; kept in Frostbridge.", info_text)
        self.assertIn(
            "note currently says whereabouts 'Frostbridge', but the reviewed recap ends them at 'Great Chasm Encampment'.",
            tech_text,
        )
        self.assertIn(
            "note currently says whereabouts 'Frostbridge', but the reviewed recap last places it at 'Great Chasm Encampment'.",
            tech_text,
        )

    def test_builder_resolves_frontmatter_aliases_without_obsidian_metadata(self) -> None:
        vault = self.make_workspace()
        recap_path = vault / "session-recap.md"
        recap_path.write_text(
            self.reviewed_recap_text().replace("Kalima", "Kalima of the Chasm"),
            encoding="utf-8",
        )

        result = self.run_builder(vault)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        info_text = (
            vault
            / "Campaigns"
            / "Test Campaign"
            / "_generated"
            / "session-notes"
            / "test-session-12"
            / "01-session-info.md"
        ).read_text(encoding="utf-8")
        self.assertIn("[[Kalima|Kalima of the Chasm]]", info_text)
        self.assertNotIn("metadata.json", result.stdout + result.stderr)

    def test_builder_emits_review_only_update_candidates(self) -> None:
        vault = self.make_workspace()
        result = self.run_builder(vault)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        tech_text = (
            vault
            / "Campaigns"
            / "Test Campaign"
            / "_generated"
            / "session-notes"
            / "test-session-12"
            / "02-technical-updates.md"
        ).read_text(encoding="utf-8")

        self.assertIn("Candidate party whereabouts: (DR:: 1730-01-25), evening: party ends at [[Great Chasm Encampment]].", tech_text)
        self.assertIn("[[Kalima]]: candidate whereabouts update from (DR:: 1730-01-25), evening -> [[Great Chasm Encampment]].", tech_text)
        self.assertIn("[[Romil's token]]: candidate item-location update from (DR:: 1730-01-25), evening -> [[Great Chasm Encampment]].", tech_text)


if __name__ == "__main__":
    unittest.main()
