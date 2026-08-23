from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from taelgar_utils.session.prepare_source import (  # noqa: E402
    SOURCE_TYPE_NARRATIVE,
    SOURCE_TYPE_TRANSCRIPT,
    infer_source_audio_path,
    resolve_source_audio_path,
)


class PrepareSourceTest(unittest.TestCase):
    def make_workspace(self) -> Path:
        tmpdir = Path(tempfile.mkdtemp(prefix="prepare-source-test."))
        self.addCleanup(lambda: shutil.rmtree(tmpdir, ignore_errors=True))
        return tmpdir

    def test_infers_source_audio_path_from_transcript_suffix(self) -> None:
        workspace = self.make_workspace()
        transcript_path = workspace / "GMT20260603-004350_Recording.transcript.vtt"
        audio_path = workspace / "GMT20260603-004350_Recording.m4a"
        transcript_path.write_text("WEBVTT\n", encoding="utf-8")
        audio_path.write_bytes(b"audio")

        self.assertEqual(infer_source_audio_path(transcript_path), audio_path.resolve())

    def test_infers_source_audio_path_from_matching_stem(self) -> None:
        workspace = self.make_workspace()
        transcript_path = workspace / "session-source.vtt"
        audio_path = workspace / "session-source.mp3"
        transcript_path.write_text("WEBVTT\n", encoding="utf-8")
        audio_path.write_bytes(b"audio")

        self.assertEqual(infer_source_audio_path(transcript_path), audio_path.resolve())

    def test_resolve_source_audio_path_uses_explicit_config_path(self) -> None:
        workspace = self.make_workspace()
        transcript_path = workspace / "session-source.vtt"
        audio_path = workspace / "recordings" / "session-audio.wav"
        audio_path.parent.mkdir()
        transcript_path.write_text("WEBVTT\n", encoding="utf-8")
        audio_path.write_bytes(b"audio")

        self.assertEqual(
            resolve_source_audio_path(
                source_path=transcript_path,
                configured_path=str(audio_path),
                source_type=SOURCE_TYPE_TRANSCRIPT,
            ),
            audio_path.resolve(),
        )

    def test_resolve_source_audio_path_skips_inference_for_non_transcripts(self) -> None:
        workspace = self.make_workspace()
        source_path = workspace / "session-notes.md"
        audio_path = workspace / "session-notes.m4a"
        source_path.write_text("Notes.\n", encoding="utf-8")
        audio_path.write_bytes(b"audio")

        self.assertIsNone(
            resolve_source_audio_path(
                source_path=source_path,
                configured_path=None,
                source_type=SOURCE_TYPE_NARRATIVE,
            )
        )


if __name__ == "__main__":
    unittest.main()
