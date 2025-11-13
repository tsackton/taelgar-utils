#!/usr/bin/env python3
import argparse
import concurrent.futures as cf
import dataclasses
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from dotenv import load_dotenv      
import openai as openai_lib
from openai import OpenAI, APIConnectionError, RateLimitError, APIStatusError
from pydantic import BaseModel

LINE_RE = re.compile(
    r"^\[(?P<start>[0-9:\.]+)\s*-\s*(?P<end>[0-9:\.]+)\]\s*(?P<speaker>[^:]+):\s*(?P<text>.*)$"
)

UNKNOWN_TOKENS_DEFAULT = {
    "unknown", "unknown speaker", "speaker_0", "speaker_1", "speaker_2",
    "speaker_3", "speaker", "unk", "??", "—"
}

@dataclasses.dataclass
class Utterance:
    idx: int
    start: str
    end: str
    speaker: str
    text: str
    def to_line(self) -> str:
        return f"[{self.start} - {self.end}] {self.speaker}: {self.text}"

def parse_transcript_lines(lines: List[str]) -> List[Utterance]:
    out = []
    for i, raw in enumerate(lines):
        raw = raw.rstrip("\n")
        m = LINE_RE.match(raw)
        if not m:
            out.append(Utterance(i, "00:00:00.00", "00:00:00.00", "Unknown", raw.strip()))
            continue
        d = m.groupdict()
        out.append(Utterance(i, d["start"], d["end"], d["speaker"].strip(), d["text"]))
    return out

def is_unknown(name: str, unknown_tokens: set) -> bool:
    norm = re.sub(r"\s+", " ", name.strip().lower())
    return norm in unknown_tokens

def chunk_utterances(utts: List[Utterance], max_lines: int = 300, unknown_tokens: Optional[set] = None) -> List[Tuple[int, int]]:
    if unknown_tokens is None:
        unknown_tokens = set(UNKNOWN_TOKENS_DEFAULT)
    chunks, n, i = [], len(utts), 0
    while i < n:
        j = min(i + max_lines, n)
        si = i
        while si < j and is_unknown(utts[si].speaker, unknown_tokens):
            si += 1
        if si >= j:
            extra = min(20, n - j)
            j += extra
            while si < j and is_unknown(utts[si].speaker, unknown_tokens):
                si += 1
            if si >= j:
                si = i
        ej = j - 1
        while ej >= si and is_unknown(utts[ej].speaker, unknown_tokens):
            ej -= 1
        if ej < si:
            extra = min(20, n - j)
            j += extra
            ej = j - 1
            while ej >= si and is_unknown(utts[ej].speaker, unknown_tokens):
                ej -= 1
            if ej < si:
                ej = j - 1
        j = ej + 1
        chunks.append((si, j))
        i = j
    return chunks

# ------------------ PROMPT (STRICT) ------------------

def build_cleaning_prompt(glossary_terms: List[str], fewshot_pairs: List[Dict[str, str]]) -> str:
    """
    Absolutely strict constraints: return exactly the same number of lines, same order,
    same timestamps, only permitted edits as listed. Emphasize transcription-error fixes.
    """
    rules = [
        "Return the SAME number of lines, in the SAME order, with the SAME timestamps (start/end) and idx mapping.",
        "For each line, you may ONLY change: (a) spelling/casing/punctuation, (b) obvious transcription errors, including homophones and multi-word mishearings (e.g., “isn’t gay” → “Isingue”), and (c) replace an Unknown speaker with a specific speaker ONLY if ≥0.8 confidence from context.",
        "Do NOT add, remove, merge, or split lines. Do NOT invent words or rephrase meaning.",
        "Preserve player real names exactly; do not alter them.",
        "Prefer canonical forms from the Glossary EXACTLY; do not introduce new canonical forms.",
        "If confidence to change is <0.8 AND the item is not in the Glossary or few-shot examples, leave it as-is.",
        "Keep in-world capitalization for spells, places, NPCs, items.",
    ]

    return (
        "You are a surgical D&D transcript cleaner.\n\n"
        "OBJECTIVE: Produce a minimally edited version strictly correcting only transcription/spelling/casing/punctuation and Unknown→speaker (if highly confident).\n\n"
        "HARD CONSTRAINTS:\n- " + "\n- ".join(rules) + "\n\n"
        "NOTES ON TRANSCRIPTION ERRORS:\n"
        "- Fix common ASR mistakes beyond simple typos: homophones, fused phrases, and phrase substitutions.\n"
        "- Examples include multi-token mishearings like “isn’t gay” → “Isingue” (a proper noun).\n"
        "- Only make such substitutions when context clearly supports the canonical term.\n\n"
        "GLOSSARY (always prefer these canonical spellings exactly):\n"
        f"{json.dumps(glossary_terms, ensure_ascii=False, indent=2)}\n\n"
        "FEW-SHOT WRONG→RIGHT PAIRS (examples of expected corrections):\n"
        f"{json.dumps(fewshot_pairs, ensure_ascii=False, indent=2)}\n\n"
        "Return JSON that strictly conforms to the provided schema."
    )

def prepare_chunk_payload(chunk_utts: List[Utterance]) -> List[Dict[str, Any]]:
    return [{"idx": u.idx, "start": u.start, "end": u.end, "speaker": u.speaker, "text": u.text} for u in chunk_utts]

def write_raw_response(
    raw_dir: Path,
    chunk_id: int,
    attempt: int,
    resp_dump: Dict[str, Any],
    chunk_payload: List[Dict[str, Any]],
    system_prompt: str,
) -> Path:
    record = {
        "chunk_id": chunk_id,
        "attempt": attempt,
        "system_prompt": system_prompt,
        "payload": chunk_payload,
        "response": resp_dump,
    }
    timestamp = int(time.time() * 1000)
    path = raw_dir / f"chunk_{chunk_id:05d}_attempt_{attempt}_{timestamp}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def safe_model_dump(resp: Any) -> Any:
    if hasattr(resp, "model_dump_json"):
        try:
            return json.loads(resp.model_dump_json())
        except Exception:
            pass
    if hasattr(resp, "model_dump"):
        try:
            return resp.model_dump()
        except Exception:
            pass
    try:
        return json.loads(json.dumps(resp, default=str))
    except Exception:
        return str(resp)


def call_model_with_retries(
    client: OpenAI,
    model: str,
    system_prompt: str,
    chunk_payload: List[Dict[str, Any]],
    raw_log_dir: Path,
    chunk_id: int,
    max_retries: int,
    reasoning_effort: str,
    initial_backoff: float = 0.0,
) -> Dict[str, Any]:
    backoff = initial_backoff
    logger = logging.getLogger("cleaner")
    for attempt in range(max_retries):
        try:
            resp = client.responses.parse(
                model=model,
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "Clean this transcript chunk per constraints. Preserve idx and timestamps."},
                    {"role": "user", "content": json.dumps(chunk_payload, ensure_ascii=False)}
                ],
                reasoning={"effort": reasoning_effort},
                text_format=CleanedChunkModel,
            )
            resp_dump = safe_model_dump(resp)
            output_path = write_raw_response(raw_log_dir, chunk_id, attempt, resp_dump, chunk_payload, system_prompt)
            logger.debug("Wrote raw model output to %s", output_path)

            parsed_model = resp.output_parsed
            if not parsed_model:
                logger.error("No parsed output returned; see %s", output_path)
                raise ValueError("Missing parsed output from model.")

            parsed = parsed_model.model_dump()
            parsed["_raw_log_path"] = str(output_path)
            return parsed
        except (APIConnectionError, RateLimitError, APIStatusError) as exc:
            if isinstance(exc, APIStatusError):
                logger = logging.getLogger("cleaner")
                status = getattr(exc, "status_code", "?")
                body = ""
                if getattr(exc, "response", None) is not None:
                    try:
                        body = exc.response.text
                    except Exception:
                        body = str(exc.response)
                logger.error(
                    "OpenAI APIStatusError (status %s): %s", status, body or exc
                )
            if attempt == max_retries - 1:
                raise
            time.sleep(backoff); backoff *= 2.0
        except json.JSONDecodeError:
            if attempt == max_retries - 1:
                raise
            time.sleep(backoff); backoff *= 2.0
    raise RuntimeError("Exhausted retries without a valid response.")

def clean_chunk_worker(
    client: OpenAI,
    model: str,
    chunk_id: int,
    utts: List[Utterance],
    glossary_terms: List[str],
    fewshot_pairs: List[Dict[str, str]],
    chunk_dir: Path,
    logger: logging.Logger,
    raw_log_dir: Path,
    max_retries: int,
    reasoning_effort: str,
) -> Path:
    system_prompt = build_cleaning_prompt(glossary_terms, fewshot_pairs)
    payload = prepare_chunk_payload(utts)
    logger.info(f"[chunk {chunk_id}] sending {len(utts)} lines")

    result = call_model_with_retries(
        client,
        model,
        system_prompt,
        payload,
        raw_log_dir,
        chunk_id,
        max_retries=max(1, min(max_retries, 5)),
        reasoning_effort=reasoning_effort,
    )
    cleaned_items = result["cleaned"]

    cleaned_by_idx = {item["idx"]: item for item in cleaned_items}
    for u in utts:
        if u.idx not in cleaned_by_idx:
            raise ValueError(f"[chunk {chunk_id}] Missing idx {u.idx} in model output")

    out_path = chunk_dir / f"chunk_{chunk_id:05d}.txt"
    with out_path.open("w", encoding="utf-8") as f:
        for u in utts:
            c = cleaned_by_idx[u.idx]
            f.write(f"[{c['start']} - {c['end']}] {c['speaker']}: {c['text']}\n")
    raw_log = result.pop("_raw_log_path", None)
    if raw_log:
        logger.debug(f"[chunk {chunk_id}] raw response log: {raw_log}")
    logger.info(f"[chunk {chunk_id}] wrote {out_path.name}")
    return out_path

def load_glossary_terms(path: Path) -> List[str]:
    terms: List[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        terms.append(stripped)
    return terms


REPO_ROOT = Path(__file__).resolve().parent

class CleanedEntry(BaseModel):
    idx: int
    start: str
    end: str
    speaker: str
    text: str


class CleanedChunkModel(BaseModel):
    cleaned: List[CleanedEntry]


def load_mistakes(path: Optional[Path]) -> Dict[str, Dict[str, str]]:
    base: Dict[str, Dict[str, str]] = {"text": {}, "speakers": {}}
    if not path:
        return base
    logger = logging.getLogger("cleaner")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.warning("Mistakes file %s not found; continuing without replacements.", path)
        return base
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse mistakes file %s: %s", path, exc)
        return base

    if isinstance(data, dict) and ("text" in data or "speakers" in data):
        text_map = data.get("text") or {}
        speaker_map = data.get("speakers") or {}
        if isinstance(text_map, dict):
            base["text"].update({str(k): str(v) for k, v in text_map.items()})
        if isinstance(speaker_map, dict):
            base["speakers"].update({str(k): str(v) for k, v in speaker_map.items()})
    elif isinstance(data, dict):
        base["text"].update({str(k): str(v) for k, v in data.items()})
    else:
        logger.warning("Unexpected mistakes format in %s; expected dict.", path)
    return base


def apply_mistakes(
    entries: List[Utterance],
    mistakes: Dict[str, Dict[str, str]],
    logger: logging.Logger,
) -> List[str]:
    text_map = mistakes.get("text", {})
    speaker_map = mistakes.get("speakers", {})
    if not text_map and not speaker_map:
        logger.warning("--no-llm enabled but no replacements supplied; output will match input.")

    cleaned_lines: List[str] = []
    for entry in entries:
        speaker = speaker_map.get(entry.speaker, entry.speaker)
        text = entry.text
        for wrong, right in text_map.items():
            if wrong:
                text = text.replace(wrong, right)
        cleaned_lines.append(f"[{entry.start} - {entry.end}] {speaker}: {text}")
    return cleaned_lines


def main():
    ap = argparse.ArgumentParser(description="Clean D&D transcripts with OpenAI")
    ap.add_argument("input", type=Path, help="Path to input transcript .txt")
    ap.add_argument("--model", default="gpt-5-mini", help="OpenAI model (default: gpt-5-mini)")
    ap.add_argument("--glossary", type=Path, help="Plain-text canonical terms (one per line)")
    ap.add_argument("--fewshot", type=Path, help='JSON list of {"wrong": "...", "right": "..."} pairs')
    ap.add_argument("--mistakes", type=Path, help="JSON mapping for deterministic replacements (see README)")
    ap.add_argument("--max-lines", type=int, default=300, help="Max lines per chunk (default: 300)")
    ap.add_argument("--max-retries", type=int, default=3, help="Retries for model calls (default: 3)")
    ap.add_argument("--reasoning-effort", choices=["low", "medium", "high"], default="low", help="OpenAI reasoning effort hint (default: low)")
    ap.add_argument(
        "--first-chunk-only",
        action="store_true",
        help="Run only the first chunk (useful when iterating on prompts/glossaries).",
    )
    ap.add_argument(
        "--no-llm",
        action="store_true",
        help="Skip GPT cleaning and only apply replacements from --mistakes.",
    )
    ap.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    args = ap.parse_args()

    # Load environment (.env) and key  ------------------  NEW
    load_dotenv(REPO_ROOT / ".env")
    # OpenAI SDK will read OPENAI_API_KEY from the environment after load_dotenv()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger = logging.getLogger("cleaner")
    logger.info("OpenAI Python package version: %s", getattr(openai_lib, "__version__", "unknown"))

    if not args.input.exists():
        logger.error("Input file not found"); sys.exit(1)

    raw_text = args.input.read_text(encoding="utf-8").splitlines(True)
    original_lines = [l.rstrip("\n") for l in raw_text]
    utts = parse_transcript_lines(original_lines)
    logger.info(f"Loaded {len(utts)} lines")

    glossary_terms: List[str] = []
    if args.glossary and args.glossary.exists():
        glossary_terms = load_glossary_terms(args.glossary)

    fewshot_pairs = []
    if args.fewshot and args.fewshot.exists():
        fewshot_pairs = json.loads(args.fewshot.read_text(encoding="utf-8"))

    mistakes_map = load_mistakes(args.mistakes)

    base = args.input.with_suffix("")
    cleaned_lines: List[str]

    if args.no_llm:
        cleaned_lines = apply_mistakes(utts, mistakes_map, logger)
    else:
        api_key = os.getenv("OPENAI_API_KEY") or os.getenv("OPEN_API_TAELGAR")
        if not api_key:
            logger.error("Missing OpenAI API key (set OPENAI_API_KEY or OPEN_API_TAELGAR).")
            sys.exit(1)
        client = OpenAI(api_key=api_key)
        if not hasattr(client, "responses"):
            logger.error(
                "Installed openai package does not expose the Responses API. Upgrade with 'pip install --upgrade openai'."
            )
            sys.exit(1)

        chunks = chunk_utterances(utts, max_lines=args.max_lines)
        logger.info(f"Chunked into {len(chunks)} chunks")
        if args.first_chunk_only and chunks:
            logger.info("First-chunk-only mode enabled; processing only chunk 0.")
            chunks = [chunks[0]]

        chunk_dir = base.parent / "transcript-chunks" / base.name
        chunk_dir.mkdir(parents=True, exist_ok=True)
        for stale in chunk_dir.glob("chunk_*.txt"):
            stale.unlink()
        raw_log_dir = base.parent / "transcript-chunks" / f"{base.name}-raw-{int(time.time())}"
        raw_log_dir.mkdir(parents=True, exist_ok=True)

        worker_target = min(8, os.cpu_count() or 4)
        num_workers = max(1, min(worker_target, max(1, len(chunks))))
        futures = []
        written_paths: List[Path] = []
        with cf.ThreadPoolExecutor(max_workers=num_workers) as ex:
            for cid, (a, b) in enumerate(chunks):
                    futures.append(
                        ex.submit(
                            clean_chunk_worker,
                            client,
                            args.model,
                            cid,
                            utts[a:b],
                            glossary_terms,
                            fewshot_pairs,
                            chunk_dir,
                            logger,
                            raw_log_dir,
                            max(1, min(args.max_retries, 5)),
                            args.reasoning_effort,
                        )
                    )
            for fut in cf.as_completed(futures):
                try:
                    written_paths.append(fut.result())
                except Exception:
                    logger.exception("Chunk failed")
                    sys.exit(2)

        written_paths.sort()
        cleaned_lines = []
        for p in written_paths:
            cleaned_lines.extend(p.read_text(encoding="utf-8").splitlines())

    out_path = base.parent / f"{base.name}-cleaned-transcript.txt"
    with out_path.open("w", encoding="utf-8") as f:
        for line in cleaned_lines:
            f.write(line + "\n")
    logger.info(f"Wrote cleaned transcript: {out_path}")


if __name__ == "__main__":
    main()
