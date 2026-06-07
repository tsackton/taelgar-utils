import json
import html
import io
import re
import tempfile
import unittest
from contextlib import contextmanager, redirect_stdout
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
from website.site_builder.session_zoom import TRANSCRIPT_COLLAPSE_LIMIT, SourceLine, collapse_transcript_lines


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

    def test_callouts_without_titles_hide_material_default_title(self) -> None:
        with fixture_site() as site:
            write_note(
                site.source / "Callouts.md",
                "---\nname: Callouts\n---\n"
                ">[!info] Custom title\n"
                "> Body.\n\n"
                "> [!quote]\n"
                "> Quote body.\n\n"
                "> [!image]\n"
                "> ![[pic.png]]\n",
            )
            (site.source / "pic.png").write_bytes(b"fake image bytes")

            export_site(site.config)
            text = (site.docs / "callouts.md").read_text(encoding="utf-8")

            self.assertIn('!!! info "Custom title"', text)
            self.assertIn('!!! quote " "', text)
            self.assertIn('!!! image " "', text)
            self.assertNotIn("[!quote]", text)
            self.assertNotIn("[!image]", text)

    def test_asset_selection_and_stale_cleanup(self) -> None:
        with fixture_site() as site:
            write_note(site.source / "A.md", "---\nname: A\n---\n![[pic.png]]\n![Audio](/assets/audio/song.mp3)\n![[assets/audio/clip.m4a]]\n")
            (site.source / "pic.png").write_bytes(b"fake image bytes")
            (site.source / "assets" / "audio").mkdir(parents=True)
            (site.source / "assets" / "audio" / "song.mp3").write_bytes(b"audio")
            (site.source / "assets" / "audio" / "clip.m4a").write_bytes(b"m4a")
            (site.source / "unused.png").write_bytes(b"unused")
            export_site(site.config)
            self.assertTrue((site.docs / "pic.png").exists())
            self.assertTrue((site.docs / "assets" / "audio" / "song.mp3").exists())
            self.assertTrue((site.docs / "assets" / "audio" / "clip.m4a").exists())
            text = (site.docs / "a.md").read_text(encoding="utf-8")
            self.assertIn("<audio controls>", text)
            self.assertIn('<source src="/assets/audio/song.mp3" type="audio/mpeg">', text)
            self.assertIn('<source src="/assets/audio/clip.m4a" type="audio/mp4">', text)
            self.assertNotIn("![Audio]", text)
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

    def test_export_prints_phase_status_updates(self) -> None:
        with fixture_site() as site:
            write_note(site.source / "A.md", "---\nname: A\n---\nbody\n")

            output = io.StringIO()
            with redirect_stdout(output):
                export_site(site.config)
            text = output.getvalue()

            self.assertIn("Manifest:", text)
            self.assertIn("Index: 1 markdown note(s), 0 asset(s)", text)
            self.assertIn("Notes: transforming 1 markdown note(s)", text)
            self.assertIn("Notes: processed 1 markdown note(s)", text)
            self.assertIn("Assets: resolving 0 linked/always-include asset(s), 0 tile request(s)", text)
            self.assertIn("Reports: writing manifest, warning report, and asset report", text)

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

    def test_search_exclude_tags_add_material_search_exclusion(self) -> None:
        with fixture_site() as site:
            write_note(site.source / "Timeline.md", "---\nname: Timeline\ntags: [search/exclude]\n---\nrollup\n")
            update_config(site.config_path, {"search_exclude_tags": ["search/exclude"]})
            config = load_config(site.config_path)

            export_site(config)
            text = (site.docs / "timeline.md").read_text(encoding="utf-8")

            self.assertIn("search:", text)
            self.assertIn("exclude: true", text)

    def test_config_accepts_session_artifact_roots(self) -> None:
        with fixture_site() as site:
            update_config(site.config_path, {"session_artifact_roots": ["sessions"]})
            config = load_config(site.config_path)

            self.assertEqual(config.session_artifact_roots, ((site.root / "sessions").resolve(),))

    def test_zoomable_session_replaces_narrative_and_writes_lazy_transcript(self) -> None:
        with fixture_site() as site:
            write_note(site.source / "Alden.md", "---\nname: Alden\n---\ncontact\n")
            write_note(site.source / "Glass Key.md", "---\nname: Glass Key\n---\nitem\n")
            write_note(
                site.source / "Zoom.md",
                "---\n"
                "name: Zoom\n"
                "sessionKey: test-campaign-session-7\n"
                "websiteSessionView: zoomable\n"
                "---\n"
                "# Zoom\n\n"
                "## Narrative\n\n"
                "The long narrative links [[Alden]] and the [[Glass Key|key]].\n\n"
                "## Cast\n\n"
                "- Alden\n\n"
                "## Narrative\n\n"
                "A later duplicate heading remains untouched.\n",
            )
            (site.source / "opening-door.png").write_bytes(b"opening image")
            (site.source / "closing-door.png").write_bytes(b"closing image")
            write_zoom_session_artifacts(site.root / "sessions")
            update_config(site.config_path, {"session_artifact_roots": ["sessions"]})
            config = load_config(site.config_path)

            export_site(config)
            text = (site.docs / "zoom.md").read_text(encoding="utf-8")
            transcript_path = site.docs / "assets" / "session-zoom" / "test-campaign-session-7.json"
            transcript = json.loads(transcript_path.read_text(encoding="utf-8"))

            self.assertIn("taelgar-session-zoom", text)
            self.assertIn("### Opening the Door", text)
            self.assertNotIn("B01", text)
            self.assertNotIn("taelgar-session-zoom__nav", text)
            self.assertNotIn("taelgar-session-zoom__beat-id", text)
            self.assertNotIn("taelgar-session-zoom__cycle", text)
            self.assertNotIn("Next: Intermediate", text)
            self.assertIn('<a href="/alden/">Alden</a>', text)
            self.assertIn('<a href="/glass-key/">key</a>', text)
            self.assertIn("taelgar-session-zoom__image--right", text)
            self.assertIn("taelgar-session-zoom__image--left", text)
            self.assertIn('style="width: 400px; max-width: 100%;"', text)
            self.assertIn('<img src="/opening-door.png" alt="Alden turns the key" width="400">', text)
            self.assertIn(
                '<figcaption><a href="/alden/">Alden</a> turns the <a href="/glass-key/">key</a></figcaption>',
                text,
            )
            self.assertIn('<img src="/closing-door.png" alt="Mira waits with Alden" width="240">', text)
            self.assertIn('<figcaption>Mira waits with <a href="/alden/">Alden</a></figcaption>', text)
            self.assertIn('<p><a href="/alden/">Alden</a> turns the <a href="/glass-key/">key</a>.</p>', text)
            self.assertIn('<p><a href="/alden/">Alden</a> turns the <a href="/glass-key/">key</a> while Mira waits.</p>', text)
            self.assertEqual(text.count('<img src="/opening-door.png"'), 1)
            self.assertEqual(text.count('<img src="/closing-door.png"'), 1)
            self.assertIn("turns the", text)
            self.assertNotIn("DM first line", text)
            self.assertNotIn("The long narrative links", text)
            self.assertIn("A later duplicate heading remains untouched.", text)
            self.assertTrue(transcript_path.exists())
            self.assertTrue((site.docs / "opening-door.png").exists())
            self.assertTrue((site.docs / "closing-door.png").exists())
            self.assertLess(
                text.index('<figure class="taelgar-session-zoom__image taelgar-session-zoom__image--right"'),
                text.index('<p><a href="/alden/">Alden</a> turns the <a href="/glass-key/">key</a> and opens the door while Mira waits.</p>'),
            )
            mira_paragraph = text.index('<p>Mira steps through the doorway while <a href="/alden/">Alden</a> watches from the hall.</p>')
            self.assertGreater(
                text.index('<figure class="taelgar-session-zoom__image taelgar-session-zoom__image--left"', mira_paragraph),
                mira_paragraph,
            )
            self.assertEqual(
                transcript["blocks"][0]["lines"],
                [
                    {"speaker": "DM", "text": "DM first line. DM second line."},
                    {"speaker": "Mira", "text": "Mira replies. Mira continues."},
                ],
            )
            self.assertNotIn("u0001", transcript_path.read_text(encoding="utf-8"))

            write_note(
                site.source / "Zoom.md",
                "---\n"
                "name: Zoom\n"
                "sessionKey: test-campaign-session-7\n"
                "---\n"
                "# Zoom\n\n"
                "## Narrative\n\n"
                "The long narrative links [[Alden]] and the [[Glass Key|key]].\n",
            )
            export_site(config)

            self.assertFalse(transcript_path.exists())

    def test_zoomable_transcript_collapse_respects_cap(self) -> None:
        collapsed = collapse_transcript_lines(
            [
                SourceLine("u0001", "DM", "a" * (TRANSCRIPT_COLLAPSE_LIMIT - 2)),
                SourceLine("u0002", "DM", "b"),
            ]
        )
        split = collapse_transcript_lines(
            [
                SourceLine("u0001", "DM", "a" * TRANSCRIPT_COLLAPSE_LIMIT),
                SourceLine("u0002", "DM", "b"),
            ]
        )

        self.assertEqual(len(collapsed), 1)
        self.assertEqual(len(collapsed[0]["text"]), TRANSCRIPT_COLLAPSE_LIMIT)
        self.assertEqual(len(split), 2)

    def test_zoomable_session_missing_artifacts_preserves_original_narrative(self) -> None:
        with fixture_site() as site:
            write_note(
                site.source / "Zoom.md",
                "---\n"
                "name: Zoom\n"
                "sessionKey: missing-session-key\n"
                "websiteSessionView: zoomable\n"
                "---\n"
                "# Zoom\n\n"
                "## Narrative\n\n"
                "Keep this narrative.\n",
            )
            update_config(site.config_path, {"session_artifact_roots": ["sessions"]})
            config = load_config(site.config_path)

            stats = export_site(config)
            text = (site.docs / "zoom.md").read_text(encoding="utf-8")

            self.assertIn("Keep this narrative.", text)
            self.assertNotIn("taelgar-session-zoom", text)
            self.assertTrue(any(warning.kind == "zoomable session view" for warning in stats.content_warnings))

    def test_asset_report_lists_linked_and_unlinked_assets(self) -> None:
        with fixture_site() as site:
            write_note(site.source / "A.md", "---\nname: A\n---\n![[linked.png]]\n")
            (site.source / "linked.png").write_bytes(b"linked")
            (site.source / "unused.png").write_bytes(b"unused")

            stats = export_site(site.config)
            report = site.root / ".website-build" / "asset-report.md"
            text = report.read_text(encoding="utf-8")

            self.assertEqual(stats.asset_warnings, [])
            self.assertIn("Linked assets: 1", text)
            self.assertIn("`linked.png` -> `linked.png`", text)
            self.assertIn("`unused.png` -> `unused.png`", text)
            self.assertIn("copied", text)
            self.assertIn("unlinked", text)

    def test_export_converts_eligible_images_to_webp_and_rewrites_links(self) -> None:
        with fixture_site() as site:
            write_note(site.source / "A.md", "---\nname: A\n---\n![[portrait.png]]\n")
            write_rgb_png(site.source / "portrait.png", (24, 16), "red")
            update_config(site.config_path, {"resize_images": True, "optimize_images": True})
            config = load_config(site.config_path)

            export_site(config)
            text = (site.docs / "a.md").read_text(encoding="utf-8")

            self.assertIn("](/portrait.webp)", text)
            self.assertTrue((site.docs / "portrait.webp").exists())
            self.assertFalse((site.docs / "portrait.png").exists())

    def test_leaflet_tile_map_generates_tiles_without_copying_full_image(self) -> None:
        with fixture_site() as site:
            write_note(
                site.source / "Map.md",
                "---\nname: Map\n---\n"
                "```leaflet\n"
                "id: test-map\n"
                "image: [[assets/map.png]]\n"
                "bounds:\n"
                "- [0, 0]\n"
                "- [12, 20]\n"
                "height: 400px\n"
                "lat: 6\n"
                "long: 10\n"
                "minZoom: -1\n"
                "maxZoom: 2\n"
                "defaultZoom: 0\n"
                "```\n",
            )
            write_rgb_png(site.source / "assets" / "map.png", (20, 12), "blue")
            update_config(
                site.config_path,
                {
                    "clean_code_blocks": True,
                    "codeblock_template_dir": str(UTILS_ROOT / "website" / "templates"),
                    "tile_map_assets": ["assets/map.png"],
                    "map_tile_size": 8,
                },
            )
            config = load_config(site.config_path)

            stats = export_site(config)
            text = (site.docs / "map.md").read_text(encoding="utf-8")
            map_config = extract_leaflet_config(text)

            self.assertIn("taelgar-leaflet-map", text)
            self.assertEqual(map_config["tile"]["baseUrl"], "/assets/tiles/map")
            self.assertRegex(map_config["tile"]["cacheKey"], r"^[0-9a-f]{10}$")
            self.assertEqual(map_config["tile"]["maxNativeZoom"], 0)
            self.assertNotIn("imageOverlay", text)
            self.assertTrue((site.docs / "assets" / "tiles" / "map" / "0" / "0" / "0.webp").exists())
            self.assertTrue((site.docs / "assets" / "tiles" / "map" / "0" / "2" / "1.webp").exists())
            self.assertFalse((site.docs / "assets" / "map.png").exists())
            self.assertEqual(stats.map_tiles_written, 6)

    def test_direct_tile_map_image_renders_leaflet_tiles(self) -> None:
        with fixture_site() as site:
            write_note(site.source / "Guide.md", "---\nname: Guide\n---\n![[assets/player-map.png]]\n")
            write_rgb_png(site.source / "assets" / "player-map.png", (20, 12), "green")
            update_config(
                site.config_path,
                {
                    "tile_map_assets": ["assets/player-map.png"],
                    "map_tile_size": 8,
                },
            )
            config = load_config(site.config_path)

            stats = export_site(config)
            text = (site.docs / "guide.md").read_text(encoding="utf-8")
            map_config = extract_leaflet_config(text)

            self.assertIn("taelgar-leaflet-map", text)
            self.assertEqual(map_config["tile"]["baseUrl"], "/assets/tiles/player-map")
            self.assertEqual(map_config["tile"]["maxNativeZoom"], 0)
            self.assertNotIn("](assets/player-map.png)", text)
            self.assertTrue((site.docs / "assets" / "tiles" / "player-map" / "0" / "2" / "1.webp").exists())
            self.assertFalse((site.docs / "assets" / "player-map.png").exists())
            self.assertEqual(stats.map_tiles_written, 6)

    def test_tile_map_preserves_higher_source_resolution(self) -> None:
        with fixture_site() as site:
            write_note(
                site.source / "Map.md",
                "---\nname: Map\n---\n"
                "```leaflet\n"
                "id: test-map\n"
                "image: [[assets/map.png]]\n"
                "bounds:\n"
                "- [0, 0]\n"
                "- [12, 20]\n"
                "height: 400px\n"
                "lat: 6\n"
                "long: 10\n"
                "minZoom: -1\n"
                "maxZoom: 2\n"
                "defaultZoom: 0\n"
                "```\n",
            )
            write_rgb_png(site.source / "assets" / "map.png", (40, 24), "blue")
            update_config(
                site.config_path,
                {
                    "clean_code_blocks": True,
                    "codeblock_template_dir": str(UTILS_ROOT / "website" / "templates"),
                    "tile_map_assets": ["assets/map.png"],
                    "map_tile_size": 8,
                },
            )
            config = load_config(site.config_path)

            stats = export_site(config)
            text = (site.docs / "map.md").read_text(encoding="utf-8")
            map_config = extract_leaflet_config(text)

            self.assertEqual(map_config["tile"]["maxNativeZoom"], 1)
            self.assertTrue((site.docs / "assets" / "tiles" / "map" / "1" / "4" / "2.webp").exists())
            self.assertEqual(stats.map_tiles_written, 21)

    def test_tile_map_pads_top_edge_for_simple_crs_alignment(self) -> None:
        with fixture_site() as site:
            write_note(
                site.source / "Map.md",
                "---\nname: Map\n---\n"
                "```leaflet\n"
                "id: test-map\n"
                "image: [[assets/map.png]]\n"
                "bounds:\n"
                "- [0, 0]\n"
                "- [12, 20]\n"
                "height: 400px\n"
                "lat: 6\n"
                "long: 10\n"
                "```\n",
            )
            write_top_band_png(site.source / "assets" / "map.png", (20, 12))
            update_config(
                site.config_path,
                {
                    "clean_code_blocks": True,
                    "codeblock_template_dir": str(UTILS_ROOT / "website" / "templates"),
                    "tile_map_assets": ["assets/map.png"],
                    "map_tile_format": "png",
                    "map_tile_size": 8,
                },
            )
            config = load_config(site.config_path)

            export_site(config)

            try:
                from PIL import Image
            except ModuleNotFoundError as error:
                raise unittest.SkipTest("Pillow is required for image export tests") from error
            with Image.open(site.docs / "assets" / "tiles" / "map" / "0" / "0" / "0.png") as tile:
                self.assertEqual(tile.getpixel((0, 0)), (255, 255, 255))
                self.assertEqual(tile.getpixel((0, 3)), (255, 255, 255))
                self.assertEqual(tile.getpixel((0, 4)), (255, 0, 0))

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
        "optimize_images": False,
        "webp_quality": 82,
        "resize_exclude_assets": [],
        "max_image_width": 1600,
        "max_image_height": 1600,
        "tile_map_assets": [],
        "map_tile_size": 512,
        "map_tile_format": "webp",
        "map_tile_quality": 82,
        "delete_unlinked_assets": True,
        "base_path": "/",
        "clean_code_blocks": False,
        "hide_toc_tags": [],
        "hide_nav_tags": [],
        "hide_backlinks_tags": [],
        "exclude_tags": [],
        "search_exclude_tags": [],
        "unnamed_files": "unlist",
        "stub_files": "skip",
        "skip_future_dated": True,
        "always_include_assets": [],
        "manifest_path": ".website-build/export-manifest.json",
        "warning_report_path": ".website-build/export-warnings.md",
        "asset_report_path": ".website-build/asset-report.md",
        "asset_report_top_n": 30,
        "asset_warning_size_bytes": 5000000,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_note(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def update_config(path: Path, updates: dict) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.update(updates)
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_zoom_session_artifacts(root: Path) -> None:
    cleaned = root / "test-campaign-007" / "cleaned"
    cleaned.mkdir(parents=True)
    (cleaned / "test-campaign-007-session.yaml").write_text(
        "campaign: Test Campaign\n"
        "scope: session\n"
        "sessionNumber: 7\n",
        encoding="utf-8",
    )
    (cleaned / "test-campaign-007-beats.json").write_text(
        json.dumps(
            {
                "schemaVersion": "1.0",
                "sourceTranscriptPath": str(cleaned / "test-campaign-007-source-cleaned.md"),
                "sessionPath": str(cleaned / "test-campaign-007-session.yaml"),
                "beats": [],
            }
        ),
        encoding="utf-8",
    )
    (cleaned / "test-campaign-007-session-recap.md").write_text(
        "# Session Recap\n\n"
        "## Recap\n\n"
        "### recap-001 | Opening the Door\n\n"
        "- Kind: beat\n"
        "- Beat IDs: beat-001\n"
        "- Source Range: u0001 -> u0004\n\n"
        "- Image: opening-door.png\n"
        "- Image Placement: start\n"
        "- Image Render: right|400\n"
        "- Image Caption: Alden turns the [[Glass Key|key]]\n\n"
        "#### Short\n"
        "Alden turns the key.\n\n"
        "#### Intermediate\n"
        "Alden turns the key while Mira waits.\n\n"
        "#### Long\n"
        "Alden turns the key and opens the door while Mira waits.\n\n"
        "### recap-002 | Crossing the Threshold\n\n"
        "- Kind: beat\n"
        "- Beat IDs: beat-002\n"
        "- Source Range: u0005 -> u0006\n"
        "- Image: closing-door.png\n"
        "- Image Placement: end\n"
        "- Image Render: left|240\n"
        "- Image Caption: Mira waits with [[Alden]]\n\n"
        "#### Short\n"
        "Mira steps through.\n\n"
        "#### Intermediate\n"
        "Mira steps through while Alden watches.\n\n"
        "#### Long\n"
        "Mira steps through the doorway while Alden watches from the hall.\n",
        encoding="utf-8",
    )
    (cleaned / "test-campaign-007-source-cleaned.md").write_text(
        "[u0001 | 00:00:00-00:00:01 | DM] DM first line.\n"
        "[u0002 | 00:00:01-00:00:02 | DM] DM second line.\n"
        "[u0003 | 00:00:02-00:00:03 | Mira] Mira replies.\n"
        "[u0004 | 00:00:03-00:00:04 | Mira] Mira continues.\n"
        "[u0005 | 00:00:04-00:00:05 | Mira] Mira crosses.\n"
        "[u0006 | 00:00:05-00:00:06 | DM] Alden watches.\n",
        encoding="utf-8",
    )


def extract_leaflet_config(text: str) -> dict:
    match = re.search(r'data-taelgar-leaflet="([^"]+)"', text)
    if not match:
        raise AssertionError("Missing leaflet data config")
    return json.loads(html.unescape(match.group(1)))


def write_rgb_png(path: Path, size: tuple[int, int], color: str) -> None:
    try:
        from PIL import Image
    except ModuleNotFoundError as error:
        raise unittest.SkipTest("Pillow is required for image export tests") from error

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)


def write_top_band_png(path: Path, size: tuple[int, int]) -> None:
    try:
        from PIL import Image
    except ModuleNotFoundError as error:
        raise unittest.SkipTest("Pillow is required for image export tests") from error

    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", size, "blue")
    for x in range(size[0]):
        img.putpixel((x, 0), (255, 0, 0))
    img.save(path)


if __name__ == "__main__":
    unittest.main()
