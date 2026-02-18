import json
import logging
from typing import Any, Dict, Iterable, List, Optional


def transcribe_audio_chunks(
    client: Any,
    chunks: Iterable[Dict[str, Any]],
    *,
    model: str = "whisper-1",
    response_format: str = "vtt",
    timestamp_granularities: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Submit each audio chunk to the transcription endpoint and yield the raw responses.
    """

    logger = logging.getLogger(__name__)
    results: List[Dict[str, Any]] = []

    for chunk in chunks:
        logger.info(
            "Transcribing chunk %s (%s-%s ms)",
            chunk["index"],
            chunk["start_ms"],
            chunk["end_ms"],
        )

        with open(chunk["path"], "rb") as audio_file:
            payload: Dict[str, Any] = {
                "model": model,
                "file": audio_file,
                "response_format": response_format,
            }
            if timestamp_granularities:
                payload["timestamp_granularities"] = timestamp_granularities

            response = client.audio.transcriptions.create(**payload)

        transcript = _normalise_response(response, response_format)
        results.append({"chunk": chunk, "transcript": transcript})

    return results


def _normalise_response(response: Any, response_format: str) -> Any:
    """
    Coerce the API response into either text or dict form based on ``response_format``.
    """

    if response_format == "vtt":
        return _ensure_text(response)
    return _ensure_dict(response)


def _ensure_text(response: Any) -> str:
    """Return ``response`` as UTF-8 text, serialising when necessary."""

    if isinstance(response, (bytes, bytearray)):
        return response.decode("utf-8")
    if isinstance(response, str):
        return response
    text_attr = getattr(response, "text", None)
    if isinstance(text_attr, str):
        return text_attr
    if hasattr(response, "to_dict"):
        try:
            return response.to_dict().get("text", "")  # type: ignore[attr-defined]
        except Exception:
            return json.dumps(response.to_dict())  # type: ignore[attr-defined]
    if isinstance(response, dict):
        text_value = response.get("text")
        if isinstance(text_value, str):
            return text_value
        return json.dumps(response)
    return str(response)


def _ensure_dict(response: Any) -> Dict[str, Any]:
    """Return ``response`` as a JSON-serialisable dictionary."""

    if isinstance(response, dict):
        return response
    if hasattr(response, "to_dict"):
        return response.to_dict()  # type: ignore[attr-defined]
    if hasattr(response, "model_dump"):
        return response.model_dump()  # type: ignore[attr-defined]
    if isinstance(response, (bytes, bytearray)):
        response = response.decode("utf-8")
    if isinstance(response, str):
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            return {"raw": response}
    return json.loads(json.dumps(response, default=str))
