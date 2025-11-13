#!/usr/bin/env python3
import argparse
import concurrent.futures as cf
import dataclasses
import difflib
import json
import logging
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from dotenv import load_dotenv              # NEW
from openai import OpenAI, APIConnectionError, RateLimitError, APIStatusError

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

def build_cleaning_prompt(glossary: Dict[str, str], fewshot_pairs: List[Dict[str, str]]) -> str:
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
        "GLOSSARY (variants→canonical; always prefer canonical exactly):\n"
        f"{json.dumps(glossary, ensure_ascii=False, indent=2)}\n\n"
        "FEW-SHOT WRONG→RIGHT PAIRS (examples of expected corrections):\n"
        f"{json.dumps(fewshot_pairs, ensure_ascii=False, indent=2)}\n\n"
        "Return JSON that strictly conforms to the provided schema."
    )

def schema_for_chunk() -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "cleaned": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "idx": {"type": "integer"},
                        "start": {"type": "string"},
                        "end": {"type": "string"},
                        "speaker": {"type": "string"},
                        "text": {"type": "string"}
                    },
                    "required": ["idx", "start", "end", "speaker", "text"]
                }
            }
        },
        "required": ["cleaned"],
        "additionalProperties": False
    }

def prepare_chunk_payload(chunk_utts: List[Utterance]) -> List[Dict[str, Any]]:
    return [{"idx": u.idx, "start": u.start, "end": u.end, "speaker": u.speaker, "text": u.text} for u in chunk_utts]

def call_model_with_retries(client: OpenAI, model: str, system_prompt: str, chunk_payload: List[Dict[str, Any]], schema: Dict[str, Any], max_retries: int = 6, initial_backoff: float = 1.0) -> Dict[str, Any]:
    backoff = initial_backoff
    for attempt in range(max_retries):
        try:
            resp = client.responses.create(
                model=model,
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "Clean this transcript chunk per constraints. Preserve idx and timestamps."},
                    {"role": "user", "content": json.dumps(chunk_payload, ensure_ascii=False)}
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "cleaned_chunk", "schema": schema, "strict": True}
                }
            )
            txt = None
            content_items = getattr(resp, "output", None) or getattr(resp, "choices", None)
            if content_items:
                try:
                    txt = content_items[0].content[0].text  # new SDK
                except Exception:
                    try:
                        txt = content_items[0].message.content  # legacy shape
                    except Exception:
                        pass
            if not txt:
                raise ValueError("Could not extract text content from model response.")
            return json.loads(txt)
        except (APIConnectionError, RateLimitError, APIStatusError):
            if attempt == max_retries - 1:
                raise
            time.sleep(backoff); backoff *= 2.0
        except json.JSONDecodeError:
            if attempt == max_retries - 1:
                raise
            time.sleep(backoff); backoff *= 2.0
    raise RuntimeError("Exhausted retries without a valid response.")

def clean_chunk_worker(client: OpenAI, model: str, chunk_id: int, utts: List[Utterance], glossary: Dict[str, str], fewshot_pairs: List[Dict[str, str]], tmp_dir: Path, logger: logging.Logger) -> Path:
    system_prompt = build_cleaning_prompt(glossary, fewshot_pairs)
    payload = prepare_chunk_payload(utts)
    schema = schema_for_chunk()
    logger.info(f"[chunk {chunk_id}] sending {len(utts)} lines")

    result = call_model_with_retries(client, model, system_prompt, payload, schema)
    cleaned_items = result["cleaned"]

    cleaned_by_idx = {item["idx"]: item for item in cleaned_items}
    for u in utts:
        if u.idx not in cleaned_by_idx:
            raise ValueError(f"[chunk {chunk_id}] Missing idx {u.idx} in model output")

    out_path = tmp_dir / f"chunk_{chunk_id:05d}.txt"
    with out_path.open("w", encoding="utf-8") as f:
        for u in utts:
            c = cleaned_by_idx[u.idx]
            f.write(f"[{c['start']} - {c['end']}] {c['speaker']}: {c['text']}\n")
    logger.info(f"[chunk {chunk_id}] wrote {out_path.name}")
    return out_path

def unified_diff_text(original: List[str], cleaned: List[str], fromfile: str, tofile: str) -> str:
    return "".join(difflib.unified_diff(original, cleaned, fromfile=fromfile, tofile=tofile, lineterm=""))

def main():
    ap = argparse.ArgumentParser(description="Clean D&D transcripts with OpenAI")
    ap.add_argument("input", type=Path, help="Path to input transcript .txt")
    ap.add_argument("--model", default="gpt-5-mini", help="OpenAI model (default: gpt-5-mini)")
    ap.add_argument("--glossary", type=Path, help="JSON file mapping variants->canonical")
    ap.add_argument("--fewshot", type=Path, help='JSON list of {"wrong": "...", "right": "..."} pairs')
    ap.add_argument("--max-lines", type=int, default=300, help="Max lines per chunk (default: 300)")
    ap.add_argument("--write-diff", action="store_true", help="Also write a unified diff file")
    ap.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    args = ap.parse_args()

    # Load environment (.env) and key  ------------------  NEW
    load_dotenv()
    # OpenAI SDK will read OPENAI_API_KEY from the environment after load_dotenv()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger = logging.getLogger("cleaner")

    if not args.input.exists():
        logger.error("Input file not found"); sys.exit(1)

    raw_text = args.input.read_text(encoding="utf-8").splitlines(True)
    original_lines = [l.rstrip("\n") for l in raw_text]
    utts = parse_transcript_lines(original_lines)
    logger.info(f"Loaded {len(utts)} lines")

    glossary = {}
    if args.glossary and args.glossary.exists():
        glossary = json.loads(args.glossary.read_text(encoding="utf-8"))

    fewshot_pairs = []
    if args.fewshot and args.fewshot.exists():
        fewshot_pairs = json.loads(args.fewshot.read_text(encoding="utf-8"))

    chunks = chunk_utterances(utts, max_lines=args.max_lines)
    logger.info(f"Chunked into {len(chunks)} chunks")

    client = OpenAI()

    with tempfile.TemporaryDirectory(prefix="clean-chunks-") as td:
        tmp_dir = Path(td)
        futures = []
        written_paths = []
        with cf.ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 4)) as ex:
            for cid, (a, b) in enumerate(chunks):
                futures.append(ex.submit(clean_chunk_worker, client, args.model, cid, utts[a:b], glossary, fewshot_pairs, tmp_dir, logger))
            for fut in cf.as_completed(futures):
                try:
                    written_paths.append(fut.result())
                except Exception:
                    logger.exception("Chunk failed"); sys.exit(2)

        written_paths.sort()
        cleaned_lines: List[str] = []
        for p in written_paths:
            cleaned_lines.extend(p.read_text(encoding="utf-8").splitlines())

    base = args.input.with_suffix("")
    out_path = base.parent / f"{base.name}-cleaned-transcript.txt"
    with out_path.open("w", encoding="utf-8") as f:
        for line in cleaned_lines:
            f.write(line + "\n")
    logger.info(f"Wrote cleaned transcript: {out_path}")

    if args.write_diff:
        diff_txt = unified_diff_text([u.to_line() for u in utts], cleaned_lines, fromfile=str(args.input.name), tofile=str(out_path.name))
        diff_path = base.parent / f"{base.name}-cleaned.diff"
        diff_path.write_text(diff_txt, encoding="utf-8")
        logger.info(f"Wrote diff: {diff_path}")

if __name__ == "__main__":
    main()
