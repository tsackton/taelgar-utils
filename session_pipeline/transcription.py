"""
Utilities for interacting with OpenAI transcription models.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Dict, Iterable, List, Mapping, Optional, Protocol

from .audio import AudioChunk


class OpenAIClient(Protocol):
    """
    Minimal protocol describing the OpenAI client needed for transcription.

    The official ``openai`` package's ``OpenAI`` client satisfies this
    interface. Keeping it as a protocol allows us to unit test without the real
    dependency.
    """

    class AudioNamespace(Protocol):
        class TranscriptionsNamespace(Protocol):
            def create(self, **kwargs: Any) -> Any: ...

        @property
        def transcriptions(self) -> "OpenAIClient.AudioNamespace.TranscriptionsNamespace": ...

    @property
    def audio(self) -> "OpenAIClient.AudioNamespace": ...


@dataclass(frozen=True)
class ChunkTranscription:
    """
    Captures the model response for a single audio chunk.

    Attributes:
        chunk: The originating audio chunk metadata.
        response: Raw response payload returned by the OpenAI API.
    """

    chunk: AudioChunk
    response: Mapping[str, Any]


def transcribe_audio_chunks(
    client: OpenAIClient,
    chunks: Iterable[AudioChunk],
    *,
    model: str = "gpt-4o-transcribe-diarize",
    request_options: Optional[Mapping[str, Any]] = None,
) -> List[ChunkTranscription]:
    """
    Call the speech-to-text model on each chunk in order.

    Returns:
        All chunk responses in matching sequence order.
    """

    logger = logging.getLogger(__name__)
    options = dict(request_options or {})

    results: List[ChunkTranscription] = []
    for chunk in chunks:
        logger.info(
            "Transcribing chunk %s (%s-%s ms)",
            chunk.index,
            chunk.start_ms,
            chunk.end_ms,
        )

        with open(chunk.path, "rb") as audio_file:
            response = client.audio.transcriptions.create(
                model=model,
                file=audio_file,
                **options,
            )

        if hasattr(response, "to_dict"):
            response_mapping = response.to_dict()  # type: ignore[assignment]
        elif isinstance(response, Mapping):
            response_mapping = dict(response)
        else:
            raise TypeError(
                "Unexpected response type from OpenAI client: "
                f"{type(response)!r}"
            )

        results.append(ChunkTranscription(chunk=chunk, response=response_mapping))

    return results


def combine_chunk_transcripts(
    chunk_results: Iterable[ChunkTranscription],
) -> Dict[str, Any]:
    """
    Produce a consolidated transcript from chunk-level responses.

    Returns:
        A dictionary with at least ``text`` and ``segments`` keys when
        available in the raw responses.
    """

    chunk_list = list(chunk_results)
    combined_text_parts: List[str] = []
    combined_segments: List[Dict[str, Any]] = []

    chunk_payloads: List[Dict[str, Any]] = []

    for chunk_transcript in chunk_list:
        response = dict(chunk_transcript.response)
        chunk_payloads.append(
            {
                "index": chunk_transcript.chunk.index,
                "start_ms": chunk_transcript.chunk.start_ms,
                "end_ms": chunk_transcript.chunk.end_ms,
                "response": response,
            }
        )

        text = response.get("text")
        if isinstance(text, str) and text.strip():
            combined_text_parts.append(text.strip())

        segments = response.get("segments")
        if isinstance(segments, list):
            offset_seconds = chunk_transcript.chunk.start_ms / 1000.0
            for segment in segments:
                if not isinstance(segment, Mapping):
                    continue
                segment_copy = dict(segment)
                for key in ("start", "end"):
                    value = segment_copy.get(key)
                    if isinstance(value, (int, float)):
                        segment_copy[key] = value + offset_seconds
                combined_segments.append(segment_copy)

    result: Dict[str, Any] = {
        "text": " ".join(combined_text_parts).strip(),
        "chunks": chunk_payloads,
    }
    if combined_segments:
        result["segments"] = combined_segments

    return result
