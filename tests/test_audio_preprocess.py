from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, List

try:
    from pydub import AudioSegment  # type: ignore
    from pydub.generators import Sine  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    AudioSegment = None  # type: ignore
    Sine = None  # type: ignore

try:
    from session_pipeline.audio import chunk_audio_file
except ImportError:  # pragma: no cover - optional dependency tree
    chunk_audio_file = None  # type: ignore

try:
    from session_pipeline.audio_processing import (
        AUDIO_PROFILES,
        AudioProfileConfig,
        prepare_clean_audio,
        preprocess_audio_file,
    )
except ImportError:  # pragma: no cover - optional dependency tree
    AUDIO_PROFILES = {}  # type: ignore
    AudioProfileConfig = None  # type: ignore
    prepare_clean_audio = None  # type: ignore
    preprocess_audio_file = None  # type: ignore


REPO_ROOT = Path(__file__).resolve().parents[1]


class AudioPreprocessingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if (
            AudioSegment is None
            or Sine is None
            or chunk_audio_file is None
            or preprocess_audio_file is None
            or prepare_clean_audio is None
        ):
            raise unittest.SkipTest(
                "Audio preprocessing dependencies are unavailable; skipping related tests."
            )
        try:
            Sine(440)
        except Exception as exc:  # pragma: no cover - defensive
            raise unittest.SkipTest(f"pydub.generators is unavailable: {exc}")

    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self._tempdir.name)
        self.sample_path = self.temp_path / "sample_input.wav"
        self._write_test_wave(self.sample_path)
        self.original_length_ms = len(_load_segment(self.sample_path))

    def tearDown(self) -> None:
        self._tempdir.cleanup()

    def test_preprocess_audio_profiles_emit_expected_format(self) -> None:
        outputs: List[Path] = []
        for profile in ["passthrough", "normalize-only", "zoom-audio", "voice-memo"]:
            with self.subTest(profile=profile):
                output_path = self.temp_path / f"{profile}.wav"
                context = _patch_voice_memo_without_rnnoise() if profile == "voice-memo" else _noop_context()
                with context:
                    preprocess_audio_file(
                        self.sample_path,
                        output_path,
                        profile=profile,
                        sample_rate=16_000,
                        channels=1,
                        output_format="wav",
                        overwrite=True,
                    )
                outputs.append(output_path)
                processed = _load_segment(output_path)
                self.assertTrue(output_path.exists())
                self.assertEqual(processed.frame_rate, 16_000)
                self.assertEqual(processed.channels, 1)
                self.assertEqual(processed.sample_width, 2)
                self.assertGreater(len(processed), 0)
        self.assertEqual(len(outputs), 4)

    def test_preprocess_cli_runs_successfully(self) -> None:
        cli_out_dir = self.temp_path / "cli"
        cli_out_dir.mkdir(parents=True, exist_ok=True)
        cmd = [
            sys.executable,
            str(REPO_ROOT / "preprocess_audio.py"),
            str(self.sample_path),
            "--audio-profile",
            "normalize-only",
            "--output-dir",
            str(cli_out_dir),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=str(REPO_ROOT))
        self.assertEqual(
            result.returncode,
            0,
            msg=f"CLI failed with stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}",
        )
        expected = cli_out_dir / f"{self.sample_path.stem}-clean.wav"
        self.assertTrue(expected.exists(), "Preprocess CLI did not produce expected output file.")

    def test_prepare_clean_audio_and_chunk_round_trip(self) -> None:
        clean_path: Path | None = None
        cleanup_path: Path | None = None
        try:
            clean_path, cleanup_path = prepare_clean_audio(
                self.sample_path,
                profile="normalize-only",
                discard=True,
                sample_rate=16_000,
                channels=1,
                output_format="wav",
            )
            self.assertIsNotNone(cleanup_path)
            self.assertTrue(clean_path.exists())

            chunk_dir = self.temp_path / "chunks"
            chunks = chunk_audio_file(
                clean_path,
                chunk_dir,
                max_chunk_seconds=0.6,
                min_silence_len=500,
                silence_thresh=-35,
            )

            self.assertGreaterEqual(len(chunks), 1)
            chunk_total = sum(entry["end_ms"] - entry["start_ms"] for entry in chunks)
            self.assertEqual(chunk_total, self.original_length_ms)
            for entry in chunks:
                exported = Path(entry["path"])
                self.assertTrue(exported.exists())
                segment = _load_segment(exported)
                self.assertEqual(segment.frame_rate, 16_000)
                self.assertEqual(segment.channels, 1)
                self.assertEqual(segment.sample_width, 2)
        finally:
            if cleanup_path and cleanup_path.exists():
                cleanup_path.unlink()

    def _write_test_wave(self, path: Path) -> None:
        tone = Sine(440).to_audio_segment(duration=400).apply_gain(-5)
        silence = AudioSegment.silent(duration=650)
        audio = (tone + silence + tone + AudioSegment.silent(duration=200)).set_frame_rate(44_100).set_channels(2)
        export_handle = audio.export(path, format="wav")
        export_handle.close()


@contextmanager
def _noop_context() -> Iterator[None]:
    yield


@contextmanager
def _patch_voice_memo_without_rnnoise() -> Iterator[None]:
    original = AUDIO_PROFILES["voice-memo"]
    patched = AudioProfileConfig(
        mode=original.mode,
        highpass=original.highpass,
        lowpass=original.lowpass,
        denoise=None,
        dynaudnorm=original.dynaudnorm,
        compressor=original.compressor,
        target_dbfs=original.target_dbfs,
        headroom_db=original.headroom_db,
    )
    AUDIO_PROFILES["voice-memo"] = patched
    try:
        yield
    finally:
        AUDIO_PROFILES["voice-memo"] = original


def _load_segment(path: Path) -> AudioSegment:
    with path.open("rb") as handle:
        segment = AudioSegment.from_file(handle)
    return segment
