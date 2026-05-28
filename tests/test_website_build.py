import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
import sys


UTILS_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = UTILS_ROOT / "src"
for path in (UTILS_ROOT, SRC_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from website.site_builder.config import ConfigError, load_config
from website.site_builder.assets import is_resize_excluded
from website.site_builder.exporter import export_site
from website.site_builder.link_index import LinkIndex
from website.site_builder.nav import MkDocsNavigationGenerator
from website.site_builder.scanner import scan_source


class WebsiteBuildTests(unittest.TestCase):
    def test_config_rejects_old_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = root / "website.json"
            config.write_text(json.dumps({"source": "taelgar", "docs_dir": "docs"}), encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(config)

    def test_export_filters_future_notes_and_cleans_campaign_blocks(self) -> None:
        with fixture_site() as site:
            write_note(
                site.source / "Current.md",
                "---\nname: Current\n---\n%%^Campaign:dufr%%keep%%^End%%\n%%^Campaign:other%%drop%%^End%%\n",
            )
            write_note(site.source / "Future.md", "---\nname: Future\nactiveYear: 1751\n---\nfuture\n")
            export_site(site.config)
            current = site.docs / "current.md"
            self.assertTrue(current.exists())
            text = current.read_text(encoding="utf-8")
            self.assertIn("keep", text)
            self.assertNotIn("drop", text)
            self.assertFalse((site.docs / "future.md").exists())

    def test_wikilinks_use_single_index(self) -> None:
        with fixture_site() as site:
            write_note(site.source / "A.md", "---\nname: A\n---\nSee [[B|bee]].\n")
            write_note(site.source / "B.md", "---\nname: B\n---\nbody\n")
            export_site(site.config)
            text = (site.docs / "a.md").read_text(encoding="utf-8")
            self.assertIn("[bee](<b.md>)", text)

    def test_asset_selection_and_stale_cleanup(self) -> None:
        with fixture_site() as site:
            write_note(site.source / "A.md", "---\nname: A\n---\n![[pic.png]]\n![Audio](/assets/audio/song.mp3)\n")
            (site.source / "pic.png").write_bytes(b"fake image bytes")
            (site.source / "assets" / "audio").mkdir(parents=True)
            (site.source / "assets" / "audio" / "song.mp3").write_bytes(b"audio")
            (site.source / "unused.png").write_bytes(b"unused")
            export_site(site.config)
            self.assertTrue((site.docs / "pic.png").exists())
            self.assertTrue((site.docs / "assets" / "audio" / "song.mp3").exists())
            self.assertIn("](/assets/audio/song.mp3)", (site.docs / "a.md").read_text(encoding="utf-8"))
            self.assertFalse((site.docs / "unused.png").exists())

            write_note(site.source / "A.md", "---\nname: A\n---\nNo asset now.\n")
            export_site(site.config)
            self.assertFalse((site.docs / "pic.png").exists())

    def test_nav_generation_omits_empty_directories(self) -> None:
        with fixture_site() as site:
            pages = site.source / "Pages"
            pages.mkdir()
            write_note(pages / "One.md", "---\nname: One\n---\none\n")
            template = site.root / "nav.md"
            template.write_text("- {glob: pages}\n", encoding="utf-8")
            config = load_config(site.config_path)
            scan = scan_source(config)
            nav = MkDocsNavigationGenerator(template, scan.entries, config).process_template()
            self.assertIn("- [One](pages/one.md)", nav.lines)

    def test_duplicate_aliases_are_reported(self) -> None:
        with fixture_site() as site:
            write_note(site.source / "Places" / "Fairgate.md", "---\nname: Fairgate\n---\none\n")
            write_note(site.source / "Wards" / "Fairgate.md", "---\nname: Fairgate\n---\ntwo\n")
            index = LinkIndex(scan_source(site.config).entries)
            self.assertIn("Fairgate", index.ambiguous_aliases())

    def test_display_metadata_is_not_a_link_alias(self) -> None:
        with fixture_site() as site:
            write_note(site.source / "Azar.md", "---\nname: Azar\naliases: [Warrior]\n---\ngod\n")
            write_note(site.source / "Azar the Lost.md", "---\nname: Azar\naliases: [Azar the Lost]\n---\nperson\n")
            write_note(site.source / "Drankorian Empire.md", "---\nname: Drankorian Empire\naliases: [Azar]\n---\nempire\n")
            index = LinkIndex(scan_source(site.config).entries)

            azar = index.resolve("Azar")
            azar_lost = index.resolve("Azar the Lost")
            warrior = index.resolve("Warrior")

            self.assertEqual(azar.status, "found")
            self.assertEqual(azar.entry.relative_path.as_posix(), "Azar.md")
            self.assertEqual(azar_lost.status, "found")
            self.assertEqual(azar_lost.entry.relative_path.as_posix(), "Azar the Lost.md")
            self.assertEqual(warrior.status, "found")
            self.assertNotIn("Azar", index.ambiguous_aliases())

    def test_resize_excludes_map_assets(self) -> None:
        with fixture_site() as site:
            write_note(site.source / "A.md", "---\nname: A\n---\n![[assets/taelgar-world-map.png]]\n![[assets/portrait.png]]\n")
            assets = site.source / "assets"
            assets.mkdir()
            (assets / "taelgar-world-map.png").write_bytes(b"map")
            (assets / "portrait.png").write_bytes(b"portrait")
            update_config(site.config_path, {"resize_images": True, "resize_exclude_assets": ["assets/*map*.png"]})
            config = load_config(site.config_path)
            entries = {entry.relative_path.as_posix(): entry for entry in scan_source(config).entries}

            self.assertTrue(is_resize_excluded(entries["assets/taelgar-world-map.png"], config))
            self.assertFalse(is_resize_excluded(entries["assets/portrait.png"], config))

    def test_exclude_tags_skip_source_notes(self) -> None:
        with fixture_site() as site:
            write_note(site.source / "Drawing.md", "---\ntags: [excalidraw]\n---\n# Excalidraw Data\n")
            write_note(site.source / "Public.md", "---\nname: Public\n---\nvisible\n")
            update_config(site.config_path, {"exclude_tags": ["excalidraw"]})
            config = load_config(site.config_path)

            entries = {entry.relative_path.as_posix(): entry for entry in scan_source(config).entries}
            self.assertNotIn("Drawing.md", entries)
            self.assertIn("Public.md", entries)

            export_site(config)
            self.assertFalse((site.docs / "drawing.md").exists())
            self.assertTrue((site.docs / "public.md").exists())

    def test_export_writes_content_warning_report_after_campaign_filtering(self) -> None:
        with fixture_site() as site:
            write_note(
                site.source / "Warning.md",
                "---\nname: Warning\n---\nVisible TODO\n%%^Campaign:none%%\n# (XXX) Species Details\n%%^End%%\n",
            )

            stats = export_site(site.config)
            report = site.root / ".website-build" / "export-warnings.md"
            text = report.read_text(encoding="utf-8")

            self.assertEqual(len(stats.content_warnings), 1)
            self.assertIn("Warning.md:1", text)
            self.assertIn("TODO marker", text)
            self.assertNotIn("(XXX)", text)

    def test_ignore_file_omits_metadata_files(self) -> None:
        with fixture_site() as site:
            (site.source / "Thumbs.db").write_bytes(b"metadata")
            ignore_file = site.root / "ignore.txt"
            ignore_file.write_text("Thumbs.db\n", encoding="utf-8")
            update_config(site.config_path, {"ignore_file": "ignore.txt"})
            config = load_config(site.config_path)

            entries = {entry.relative_path.as_posix(): entry for entry in scan_source(config).entries}
            self.assertNotIn("Thumbs.db", entries)

    def test_exported_nav_file_is_excluded_from_search(self) -> None:
        with fixture_site() as site:
            write_note(site.source / "One.md", "---\nname: One\n---\none\n")
            nav_template = site.root / "nav.md"
            nav_template.write_text("- {glob: .}\n", encoding="utf-8")
            update_config(site.config_path, {"nav_source": "nav.md"})
            config = load_config(site.config_path)

            export_site(config)
            text = (site.docs / "toc.md").read_text(encoding="utf-8")

            self.assertTrue(text.startswith("---\ntitle: Toc\nsearch:\n  exclude: true\n---\n"))
            self.assertIn("- [One](one.md)", text)

    def test_export_normalizes_paragraph_adjacent_lists(self) -> None:
        with fixture_site() as site:
            write_note(
                site.source / "Lists.md",
                "---\nname: Lists\n---\n"
                "Intro:\n"
                "- first\n"
                "- second\n\n"
                "Steps:\n"
                "1. one\n"
                "2. two\n\n"
                "Already valid:\n\n"
                "- valid\n\n"
                "```text\n"
                "Code:\n"
                "- not a list\n"
                "```\n",
            )

            export_site(site.config)
            text = (site.docs / "lists.md").read_text(encoding="utf-8")

            self.assertIn("Intro:\n\n- first\n- second", text)
            self.assertIn("Steps:\n\n1. one\n2. two", text)
            self.assertIn("Already valid:\n\n- valid", text)
            self.assertNotIn("Already valid:\n\n\n- valid", text)
            self.assertIn("```text\nCode:\n- not a list\n```", text)

    def test_campaign_nav_template_owns_pc_navigation(self) -> None:
        with fixture_site() as site:
            for path in [
                "Campaigns/Campaigns.md",
                "Campaigns/Current Games.md",
                "Campaigns/Campaign Archive.md",
                "Campaigns/Addermarch Campaign/Addermarch Campaign.md",
                "Campaigns/Great Library Campaign/Great Library Campaign.md",
                "People/PCs/Addermarch/Addermarch Mercenaries.md",
                "People/PCs/Addermarch/Drou.md",
                "People/PCs/Silver Tempests/Silver Tempests.md",
                "People/PCs/Silver Tempests/Adrik.md",
            ]:
                write_note(site.source / path, f"---\nname: {Path(path).stem}\n---\nbody\n")

            config = load_config(site.config_path)
            scan = scan_source(config)
            nav = MkDocsNavigationGenerator(
                UTILS_ROOT / "website" / "templates" / "toc.md",
                scan.entries,
                config,
            ).process_template()
            top_level = [line for line in nav.lines if line.startswith("- ")]
            text = "\n".join(nav.lines)
            people_section = text.split("- [People](people/people.md)", 1)[1].split(
                "- [Gazetteer](gazetteer/geography-of-taelgar.md)",
                1,
            )[0]

            self.assertEqual(top_level.count("- [Campaigns](campaigns/campaigns.md)"), 1)
            self.assertNotIn("- [Current Campaigns](people/pcs/pcs.md)", top_level)
            self.assertNotIn("- Finished Campaigns", top_level)
            self.assertIn("- [Current Games](campaigns/current-games.md)", text)
            self.assertIn("- [Campaign Archive](campaigns/campaign-archive.md)", text)
            self.assertIn(
                "- [Player Characters](people/pcs/addermarch/addermarch-mercenaries.md)",
                text,
            )
            self.assertIn("- [Drou](people/pcs/addermarch/drou.md)", text)
            self.assertIn(
                "- [Player Characters](people/pcs/silver-tempests/silver-tempests.md)",
                text,
            )
            self.assertIn("- [Adrik](people/pcs/silver-tempests/adrik.md)", text)
            self.assertNotIn("people/pcs", people_section)
            self.assertNotIn("people/pcs/cleenseau", text)


class FixtureSite:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.source = root / "taelgar-static"
        self.docs = root / "docs"
        self.config_path = root / "website.json"
        self.config = None

    def setup(self) -> "FixtureSite":
        self.source.mkdir()
        write_config(self.config_path)
        self.config = load_config(self.config_path)
        return self


@contextmanager
def fixture_site() -> FixtureSite:
    with tempfile.TemporaryDirectory() as tmpdir:
        yield FixtureSite(Path(tmpdir)).setup()


def write_config(path: Path) -> None:
    payload = {
        "source_dir": "taelgar-static",
        "docs_dir": "docs",
        "slugify": True,
        "clean_docs": False,
        "campaigns": ["dufr"],
        "export_date": "1750-01-01",
        "strip_comments": True,
        "strip_campaign_blocks": True,
        "strip_date_blocks": True,
        "clean_inline_tags": True,
        "home_dest": "index.md",
        "nav_dest": "toc.md",
        "asset_dir": "assets",
        "resize_images": False,
        "resize_exclude_assets": [],
        "max_image_width": 1600,
        "max_image_height": 1600,
        "delete_unlinked_assets": True,
        "base_path": "/",
        "clean_code_blocks": False,
        "hide_toc_tags": [],
        "hide_nav_tags": [],
        "hide_backlinks_tags": [],
        "exclude_tags": [],
        "unnamed_files": "unlist",
        "stub_files": "skip",
        "skip_future_dated": True,
        "always_include_assets": [],
        "manifest_path": ".website-build/export-manifest.json",
        "warning_report_path": ".website-build/export-warnings.md",
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_note(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def update_config(path: Path, updates: dict) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.update(updates)
    path.write_text(json.dumps(payload), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
