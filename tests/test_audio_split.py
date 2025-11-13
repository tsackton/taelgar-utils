import math
import tempfile
import unittest
from pathlib import Path

try:
    from pydub import AudioSegment  # type: ignore
except ImportError:
    AudioSegment = None  # type: ignore

try:
    from session_pipeline.audio import chunk_audio_file  # type: ignore
except ImportError:
    chunk_audio_file = None  # type: ignore


class ChunkAudioFileTests(unittest.TestCase):
    def test_chunks_cover_full_audio_length(self) -> None:
        if AudioSegment is None or chunk_audio_file is None:
            self.skipTest("pydub is not installed, skipping audio regression test.")

        source = Path("test_data/audio-test.m4a").expanduser().resolve()
        if not source.exists():
            self.skipTest(f"Test audio not found at {source}")

        audio = AudioSegment.from_file(source)
        expected_length = len(audio)
        max_chunk_seconds = 300.0  # keep the test quick while forcing multiple splits
        max_chunk_ms = int(max_chunk_seconds * 1000)

        with tempfile.TemporaryDirectory() as tmpdir:
            chunks = chunk_audio_file(
                source,
                Path(tmpdir),
                max_chunk_seconds=max_chunk_seconds,
                min_silence_len=500,
                silence_thresh=-40,
            )

            chunk_files = [Path(entry["path"]) for entry in chunks]
            for chunk_path in chunk_files:
                self.assertTrue(chunk_path.exists(), f"Chunk file missing: {chunk_path}")

            file_lengths = [self._chunk_duration_ms(path) for path in chunk_files]

        self.assertGreater(len(chunks), 0, "Audio produced no chunks")
        self.assertEqual(chunks[0]["start_ms"], 0)
        self.assertEqual(chunks[-1]["end_ms"], expected_length)

        expected_chunk_count = math.ceil(expected_length / max_chunk_ms)
        self.assertEqual(
            len(chunks),
            expected_chunk_count,
            "Should produce the minimal number of chunks given max length.",
        )

        for previous, current in zip(chunks, chunks[1:]):
            self.assertEqual(
                previous["end_ms"],
                current["start_ms"],
                "Chunks must be contiguous with no gaps",
            )

        accumulated = 0
        for entry, file_len in zip(chunks, file_lengths):
            meta_length = entry["end_ms"] - entry["start_ms"]
            self.assertEqual(
                file_len,
                meta_length,
                f"Chunk metadata disagrees with exported audio: {entry['path']}",
            )
            self.assertLessEqual(meta_length, max_chunk_ms)
            accumulated += meta_length

        self.assertEqual(accumulated, expected_length)

        longest = max(file_lengths)
        shortest = min(file_lengths)
        allowed_delta = max(int(0.5 * max_chunk_ms), 5000)
        self.assertLessEqual(
            longest - shortest,
            allowed_delta,
            f"Chunk lengths vary too much: {file_lengths}",
        )


    @staticmethod
    def _chunk_duration_ms(path: Path) -> int:
        """Return the duration of ``path`` in milliseconds and ensure handles close."""

        fmt = path.suffix.lstrip(".") or None
        with path.open("rb") as handle:
            segment = AudioSegment.from_file(handle, format=fmt)
        return len(segment)


if __name__ == "__main__":
    unittest.main()
