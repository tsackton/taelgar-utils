#!/usr/bin/env python3

"""Sample speaker-balanced clips from diarized sessions."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, MutableMapping, Optional, Sequence, Tuple

import yaml

from session_pipeline.audio_processing import (
    AUDIO_PROFILES,
    prepare_clean_audio,
)


DEFAULT_MIN_CLIP_SECONDS = 3.0
DEFAULT_SESSION_MINUTES = 4.0
DEFAULT_TARGET_HOURS = 3.0  # 3 hours per speaker
DIARIZATION_NUMBER_PATTERN = re.compile(r"(\d+)")
PLAYER_SUFFIX_PATTERN = re.compile(r"\s*\([^)]*\)\s*$")
SPACE_PATTERN = re.compile(r"\s+")
VERBOSE = False


@dataclass
class CorpusConfig:
    sessions_dir: Path
    recordings_dir: Path
    clips_dir: Path
    diarization_glob: str
    speaker_mapping_glob: str
    player_allowlist: List[str]
    min_clip_seconds: float = DEFAULT_MIN_CLIP_SECONDS
    max_session_minutes_per_speaker: float = DEFAULT_SESSION_MINUTES
    target_minutes_per_speaker: float = DEFAULT_TARGET_HOURS * 60.0
    audio_profile: str = "zoom-audio"
    recording_subdir_pattern: Optional[str] = "Session ({number})"
    clip_format: str = "wav"
    sample_rate: int = 16_000
    channels: int = 1
    max_clips_per_session: Optional[int] = None
    min_gap_ms: int = 100
    manifest_filename: str = "manifest.jsonl"
    stats_filename: str = "manifest_stats.json"

    def target_seconds(self) -> float:
        return max(0.0, self.target_minutes_per_speaker) * 60.0

    def per_session_cap_seconds(self) -> float:
        return (
            max(0.0, self.max_session_minutes_per_speaker) * 60.0
            if self.max_session_minutes_per_speaker
            else float("inf")
        )


@dataclass
class SessionResources:
    session_id: str
    diarization_path: Path
    speaker_mapping_path: Path
    recording_path: Path
    session_number: Optional[int] = None


@dataclass
class ClipCandidate:
    session_id: str
    speaker: str
    start: float
    end: float
    duration: float
    diarization_path: Path
    segment_index: int
    source_audio: Path


class PlayerRegistry:
    """Normalize canonical player names and enforce an allowlist."""

    def __init__(self, allowed_names: Sequence[str]):
        normalized: Dict[str, str] = {}
        for raw in allowed_names:
            cleaned = sanitize_player_label(str(raw))
            if not cleaned:
                continue
            key = normalize_player_key(cleaned)
            if key in normalized:
                raise ValueError(f"Duplicate player entry after normalization: '{raw}' conflicts with '{normalized[key]}'")
            normalized[key] = cleaned
        if not normalized:
            raise ValueError("player_allowlist is empty after normalization.")
        self._normalized = normalized

    def resolve(self, name: str) -> Optional[str]:
        cleaned = sanitize_player_label(name)
        if not cleaned:
            return None
        return self._normalized.get(normalize_player_key(cleaned))

    @property
    def canonical(self) -> List[str]:
        return sorted(self._normalized.values())


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate per-speaker clip corpus from diarized Zoom sessions.")
    parser.add_argument("--config", type=Path, required=True, help="Path to corpus config YAML.")
    parser.add_argument(
        "--session",
        dest="session_filter",
        action="append",
        help="Restrict processing to specific session IDs (may be repeated).",
    )
    parser.add_argument(
        "--limit-sessions",
        type=int,
        default=None,
        help="Process at most N sessions (after filtering).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan selections without writing clips or manifests.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite clips if they already exist.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print additional debug logging.",
    )
    return parser.parse_args(argv)


def load_config(path: Path) -> CorpusConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, MutableMapping):
        raise SystemExit("Config must be a mapping.")

    missing = [field for field in ("sessions_dir", "recordings_dir", "clips_dir", "diarization_glob", "speaker_mapping_glob", "player_allowlist") if field not in raw]
    if missing:
        raise SystemExit(f"Config is missing required fields: {', '.join(missing)}")

    sessions_dir = Path(raw["sessions_dir"]).expanduser().resolve()
    recordings_dir = Path(raw["recordings_dir"]).expanduser().resolve()
    clips_dir = Path(raw["clips_dir"]).expanduser().resolve()
    player_allowlist = raw["player_allowlist"]
    if not isinstance(player_allowlist, Sequence) or isinstance(player_allowlist, (str, bytes)):
        raise SystemExit("player_allowlist must be a sequence of names.")

    cfg = CorpusConfig(
        sessions_dir=sessions_dir,
        recordings_dir=recordings_dir,
        clips_dir=clips_dir,
        diarization_glob=str(raw["diarization_glob"]),
        speaker_mapping_glob=str(raw["speaker_mapping_glob"]),
        player_allowlist=[str(item) for item in player_allowlist],
        min_clip_seconds=float(raw.get("min_clip_seconds", DEFAULT_MIN_CLIP_SECONDS)),
        max_session_minutes_per_speaker=float(
            raw.get("max_session_minutes_per_speaker", DEFAULT_SESSION_MINUTES)
        ),
        target_minutes_per_speaker=float(raw.get("target_minutes_per_speaker", DEFAULT_TARGET_HOURS * 60.0)),
        audio_profile=str(raw.get("audio_profile", "zoom-audio")),
        recording_subdir_pattern=raw.get("recording_subdir_pattern", "Session ({number})"),
        clip_format=str(raw.get("clip_format", "wav")),
        sample_rate=int(raw.get("sample_rate", 16_000)),
        channels=int(raw.get("channels", 1)),
        max_clips_per_session=raw.get("max_clips_per_session"),
        min_gap_ms=int(raw.get("min_gap_ms", 100)),
        manifest_filename=str(raw.get("manifest_filename", "manifest.jsonl")),
        stats_filename=str(raw.get("stats_filename", "manifest_stats.json")),
    )

    if cfg.audio_profile not in AUDIO_PROFILES:
        raise SystemExit(f"Unknown audio profile '{cfg.audio_profile}'. Valid options: {', '.join(sorted(AUDIO_PROFILES))}")
    if cfg.sample_rate <= 0:
        raise SystemExit("sample_rate must be positive.")
    if cfg.channels not in (1, 2):
        raise SystemExit("channels must be 1 (mono) or 2 (stereo).")
    if cfg.clip_format not in {"wav"}:
        raise SystemExit("Currently only WAV clip output is supported.")

    if not sessions_dir.exists():
        raise SystemExit(f"sessions_dir not found: {sessions_dir}")
    if not recordings_dir.exists():
        raise SystemExit(f"recordings_dir not found: {recordings_dir}")
    cfg.clips_dir.mkdir(parents=True, exist_ok=True)

    max_clips = cfg.max_clips_per_session
    if max_clips is not None:
        cfg.max_clips_per_session = int(max_clips)

    return cfg


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    global VERBOSE
    VERBOSE = bool(args.verbose)

    config_path = args.config.expanduser().resolve()
    log_info(f"Loading config from {config_path}")
    config = load_config(config_path)
    log_debug(f"Config: sessions_dir={config.sessions_dir} recordings_dir={config.recordings_dir} clips_dir={config.clips_dir}")
    registry = PlayerRegistry(config.player_allowlist)
    session_filter = set(args.session_filter or [])
    sessions = discover_sessions(config, session_filter=session_filter, limit=args.limit_sessions)
    if not sessions:
        print("No sessions matched the provided filters.", file=sys.stderr)
        return 1

    print(f"Loaded {len(sessions)} session(s) from {config.sessions_dir}")
    print(f"Target duration per speaker: {config.target_minutes_per_speaker:.1f} minutes (~{config.target_seconds()/3600:.2f} hours)")

    global_totals: Dict[str, float] = {name: 0.0 for name in registry.canonical}
    candidates_by_speaker: Dict[str, Dict[str, List[ClipCandidate]]] = defaultdict(lambda: defaultdict(list))
    for session in sessions:
        log_info(f"Processing session {session.session_id} ({session.diarization_path})")
        log_debug(f"  -> recording: {session.recording_path}")
        segments = load_session_segments(
            session,
            registry,
            config.min_clip_seconds,
            config.min_gap_ms,
        )
        if not segments:
            log_info(f"  No eligible segments for {session.session_id}; skipping.")
            continue
        selected = sample_session_segments(
            session.session_id,
            segments,
            global_totals,
            config,
        )
        if not selected:
            continue
        for speaker, segs in selected.items():
            for seg in segs:
                candidate = ClipCandidate(
                    session_id=session.session_id,
                    speaker=speaker,
                    start=seg["start"],
                    end=seg["end"],
                    duration=seg["duration"],
                    diarization_path=session.diarization_path,
                    segment_index=seg["index"],
                    source_audio=session.recording_path,
                )
                candidates_by_speaker[speaker][session.session_id].append(candidate)

    if not any(candidates_by_speaker.values()):
        print("No eligible clips were selected. Check config thresholds and allowlist.", file=sys.stderr)
        return 1

    clip_candidates = balance_clips_by_session(candidates_by_speaker, config.target_seconds())

    clip_candidates.sort(key=lambda item: (item.speaker, item.session_id, item.start))

    print(
        f"Selected {len(clip_candidates)} clip(s) covering "
        f"{sum(entry.duration for entry in clip_candidates)/60:.1f} minutes."
    )
    if args.dry_run:
        for speaker, total in global_totals.items():
            print(f" - {speaker}: {total/60:.2f} min selected")
        print("Dry run complete; no audio written.")
        return 0

    manifest_entries = export_clips(
        clip_candidates,
        config,
        overwrite=args.overwrite,
    )
    write_manifest_outputs(manifest_entries, config)
    print(f"Wrote {len(manifest_entries)} clip(s) to {config.clips_dir}")
    return 0


def discover_sessions(
    config: CorpusConfig,
    *,
    session_filter: Optional[set[str]] = None,
    limit: Optional[int] = None,
) -> List[SessionResources]:
    diarization_map = group_by_session(config.sessions_dir, config.diarization_glob)
    mapping_map = group_by_session(config.sessions_dir, config.speaker_mapping_glob)
    discovered: List[SessionResources] = []

    for session_id in sorted(diarization_map):
        if session_filter and session_id not in session_filter:
            continue
        diar_paths = sorted(diarization_map[session_id])
        speaker_paths = sorted(mapping_map.get(session_id, []))
        diar_path = diar_paths[0]
        session_number, session_number_raw = extract_session_number(diar_path)

        mapping_path = resolve_mapping_path(diar_path, speaker_paths)
        if not mapping_path:
            print(f"[skip] {session_id}: no speaker mapping matched {diar_path}", file=sys.stderr)
            continue

        recording_path = resolve_recording_path(session_id, session_number, session_number_raw, config)
        if not recording_path:
            print(f"[skip] {session_id}: recording file not found under {config.recordings_dir}", file=sys.stderr)
            continue

        log_debug(
            f"Matched session {session_id}: diarization={diar_path}, speaker_mapping={mapping_path}, recording={recording_path}"
        )

        discovered.append(
            SessionResources(
                session_id=session_id,
                diarization_path=diar_path,
                speaker_mapping_path=mapping_path,
                recording_path=recording_path,
                session_number=session_number,
            )
        )
        if limit and len(discovered) >= limit:
            break
    return discovered


def group_by_session(base_dir: Path, pattern: str) -> Dict[str, List[Path]]:
    mapping: Dict[str, List[Path]] = defaultdict(list)
    for path in base_dir.glob(pattern):
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(base_dir)
        except ValueError:
            continue
        session_id = rel.parts[0]
        mapping[session_id].append(path)
    return mapping


def resolve_mapping_path(diarization_path: Path, candidates: Sequence[Path]) -> Optional[Path]:
    if not candidates:
        return None
    parent = diarization_path.parent
    for candidate in candidates:
        if candidate.parent == parent:
            return candidate
    return candidates[0]


def extract_session_number(path: Path) -> Tuple[Optional[int], Optional[str]]:
    match = DIARIZATION_NUMBER_PATTERN.search(path.stem)
    if not match:
        return None, None
    digits = match.group(1)
    try:
        return int(digits), digits
    except ValueError:
        return None, None


def resolve_recording_path(
    session_id: str,
    session_number: Optional[int],
    session_number_raw: Optional[str],
    config: CorpusConfig,
) -> Optional[Path]:
    candidates: List[Path] = []
    if config.recording_subdir_pattern:
        subdir_name = render_recording_subdir(
            session_id,
            config.recording_subdir_pattern,
            session_number,
            session_number_raw,
        )
        if subdir_name:
            candidates.append(config.recordings_dir / subdir_name)
    candidates.append(config.recordings_dir / session_id)

    for directory in candidates:
        if not directory.exists():
            continue
        log_debug(f"    Looking for recordings in {directory}")
        recording = select_best_recording(directory)
        if recording:
            return recording
    return None


def render_recording_subdir(
    session_id: str,
    pattern: str,
    session_number: Optional[int],
    session_number_raw: Optional[str],
) -> Optional[str]:
    context = {"session_id": session_id}
    number = session_number
    number_raw = session_number_raw
    if number is None:
        match = re.search(r"(\d+)", session_id)
        if match:
            number_raw = match.group(1)
            try:
                number = int(number_raw)
            except ValueError:
                number = None
    if number is not None:
        context["number"] = number
        context["number_raw"] = number_raw or str(number)
        context["number_padded2"] = f"{number:02d}"
        context["number_padded3"] = f"{number:03d}"
        context["number_padded4"] = f"{number:04d}"
    try:
        return pattern.format_map(Default(dict(context)))
    except KeyError:
        return None


class Default(dict):
    """Formatter helper that returns blank strings for missing keys."""

    def __missing__(self, key: str) -> str:
        return ""


def select_best_recording(directory: Path) -> Optional[Path]:
    m4a = _gather_audio_files(directory, ".m4a")
    if m4a:
        chosen = pick_largest_file(m4a)
        log_debug(f"      selected {chosen} (m4a)")
        return chosen
    mp4 = _gather_audio_files(directory, ".mp4")
    if mp4:
        chosen = pick_largest_file(mp4)
        log_debug(f"      selected {chosen} (mp4)")
        return chosen
    return None


def _gather_audio_files(directory: Path, extension: str) -> List[Path]:
    return sorted(child for child in directory.iterdir() if child.is_file() and child.suffix.lower() == extension)


def pick_largest_file(paths: Sequence[Path]) -> Path:
    return max(paths, key=lambda path: (path.stat().st_size, str(path)))


def load_session_segments(
    session: SessionResources,
    registry: PlayerRegistry,
    min_clip_seconds: float,
    min_gap_ms: int,
) -> Dict[str, List[Dict[str, float]]]:
    speaker_mapping = load_speaker_mapping(session.speaker_mapping_path)
    diar_segments = load_diarization_segments(session.diarization_path)
    segments: Dict[str, List[Dict[str, float]]] = defaultdict(list)

    ordered_segments = sorted(diar_segments, key=lambda item: float(item.get("start", 0.0)))

    for index, seg in enumerate(ordered_segments):
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", start))
        duration = max(0.0, end - start)
        if duration < min_clip_seconds:
            continue
        if not has_min_gap(ordered_segments, index, min_gap_ms):
            continue
        speaker_id = str(seg.get("speaker") or seg.get("speaker_id") or "")
        canonical = speaker_mapping.get(speaker_id, speaker_id)
        player_name = registry.resolve(canonical)
        if not player_name:
            continue
        segments[player_name].append(
            {
                "index": index,
                "start": start,
                "end": end,
                "duration": duration,
            }
        )
    if segments:
        total_segments = sum(len(items) for items in segments.values())
        speaker_summaries = ", ".join(
            f"{speaker}={sum(seg['duration'] for seg in segs) / 60:.2f}m"
            for speaker, segs in segments.items()
        )
        log_info(
            f"{session.session_id}: found {total_segments} eligible segments covering {speaker_summaries}"
        )
    return segments


def load_speaker_mapping(path: Path) -> Dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"Speaker mapping must be a dict: {path}")
    mapping: Dict[str, str] = {}
    for key, value in data.items():
        if value:
            mapping[str(key)] = sanitize_player_label(str(value))
    return mapping


def load_diarization_segments(path: Path) -> List[Dict[str, float]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        if "segments" in data:
            data = data["segments"]
        else:
            data = []
    if not isinstance(data, list):
        raise SystemExit(f"Unexpected diarization structure in {path}")
    return data


def has_min_gap(
    segments: Sequence[Dict[str, float]],
    index: int,
    min_gap_ms: int,
) -> bool:
    if min_gap_ms <= 0:
        return True
    current_start = float(segments[index].get("start", 0.0))
    current_end = float(segments[index].get("end", current_start))
    min_gap_seconds = min_gap_ms / 1000.0

    if index > 0:
        prev_end = float(segments[index - 1].get("end", segments[index - 1].get("start", 0.0)))
        if current_start - prev_end < min_gap_seconds:
            return False

    if index + 1 < len(segments):
        next_start = float(segments[index + 1].get("start", segments[index + 1].get("end", 0.0)))
        if next_start - current_end < min_gap_seconds:
            return False

    return True


def sample_session_segments(
    session_id: str,
    segments: Dict[str, List[Dict[str, float]]],
    global_totals: Dict[str, float],
    config: CorpusConfig,
) -> Dict[str, List[Dict[str, float]]]:
    selections: Dict[str, List[Dict[str, float]]] = defaultdict(list)
    per_session_cap = config.per_session_cap_seconds()
    target_seconds = config.target_seconds()

    for speaker in sorted(segments):
        speaker_segments = sorted(segments[speaker], key=lambda item: (item["start"], item["end"]))
        session_accum = 0.0
        clip_count = 0
        for seg in speaker_segments:
            if per_session_cap != float("inf") and session_accum >= per_session_cap and clip_count > 0:
                break
            selections[speaker].append(seg)
            session_accum += seg["duration"]
            global_totals[speaker] = global_totals.get(speaker, 0.0) + seg["duration"]
            clip_count += 1
            if config.max_clips_per_session and clip_count >= config.max_clips_per_session:
                break
        if selections.get(speaker):
            log_info(
                f"  {session_id}: {speaker} -> {len(selections[speaker])} clip(s) "
                f"({sum(seg['duration'] for seg in selections[speaker])/60:.2f} min; "
                f"total {global_totals[speaker]/60:.2f} / {target_seconds/60:.2f} min)"
            )
    return selections


def balance_clips_by_session(
    candidates_by_speaker: Dict[str, Dict[str, List[ClipCandidate]]],
    target_seconds: float,
) -> List[ClipCandidate]:
    balanced: List[ClipCandidate] = []
    for speaker in sorted(candidates_by_speaker):
        sessions = candidates_by_speaker[speaker]
        if not sessions:
            continue
        session_ids = sorted(sessions.keys())
        session_queues: Dict[str, deque[ClipCandidate]] = {
            session_id: deque(sorted(clips, key=lambda clip: clip.start))
            for session_id, clips in sessions.items()
        }
        total_duration = sum(clip.duration for clips in sessions.values() for clip in clips)
        if target_seconds <= 0 or total_duration <= target_seconds:
            for session_id in session_ids:
                balanced.extend(session_queues[session_id])
            continue

        selected_duration = 0.0
        active_sessions = [session_id for session_id in session_ids if session_queues[session_id]]
        index = 0
        while active_sessions and selected_duration < target_seconds:
            session_id = active_sessions[index]
            queue = session_queues[session_id]
            clip = queue.popleft()
            balanced.append(clip)
            selected_duration += clip.duration
            if not queue:
                active_sessions.pop(index)
                if not active_sessions:
                    break
                index %= len(active_sessions)
            else:
                index = (index + 1) % len(active_sessions)
    balanced.sort(key=lambda clip: (clip.speaker, clip.session_id, clip.start))
    return balanced


def export_clips(
    clips: Sequence[ClipCandidate],
    config: CorpusConfig,
    *,
    overwrite: bool,
) -> List[Dict[str, object]]:
    entries: List[Dict[str, object]] = []
    clips_by_source: Dict[Path, List[ClipCandidate]] = defaultdict(list)
    for clip in clips:
        clips_by_source[clip.source_audio].append(clip)

    for source_audio in sorted(clips_by_source.keys(), key=lambda path: str(path)):
        source_clips = sorted(clips_by_source[source_audio], key=lambda c: (c.start, c.end))
        log_info(f"Preparing normalized audio for {source_audio} ({len(source_clips)} clip(s))")
        clean_path, cleanup_path = prepare_clean_audio(
            source_audio,
            profile=config.audio_profile,
            discard=True,
            sample_rate=config.sample_rate,
            channels=config.channels,
            output_format=config.clip_format,
            log_fn=log_debug if VERBOSE else None,
        )
        try:
            for clip in source_clips:
                speaker_slug = slugify(clip.speaker)
                session_slug = slugify(clip.session_id)
                start_ms = int(round(clip.start * 1000))
                end_ms = int(round(clip.end * 1000))
                filename = f"{session_slug}_{start_ms:010d}_{end_ms:010d}.wav"
                clip_dir = config.clips_dir / speaker_slug / session_slug
                clip_dir.mkdir(parents=True, exist_ok=True)
                destination = clip_dir / filename

                if destination.exists() and not overwrite:
                    print(f"[skip] clip exists: {destination}")
                    continue
                log_info(
                    f"Writing clip {destination} ({clip.session_id} {clip.speaker} {clip.start:.2f}-{clip.end:.2f}s)"
                )
                extract_clean_clip(
                    clean_path,
                    clip.start,
                    clip.end,
                    destination,
                )

                entries.append(
                    {
                        "speaker": clip.speaker,
                        "speaker_slug": speaker_slug,
                        "session_id": clip.session_id,
                        "start": clip.start,
                        "end": clip.end,
                        "duration": clip.duration,
                        "segment_index": clip.segment_index,
                        "source_audio": str(clip.source_audio),
                        "diarization": str(clip.diarization_path),
                        "clip_path": str(destination),
                    }
                )
        finally:
            if cleanup_path and cleanup_path.exists():
                try:
                    cleanup_path.unlink()
                except OSError:
                    pass
    return entries


def extract_clean_clip(
    clean_audio: Path,
    start: float,
    end: float,
    destination: Path,
) -> None:
    duration = max(0.0, end - start)
    if duration <= 0:
        raise ValueError("Clip duration must be positive.")
    extract_cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-ss",
        f"{start:.3f}",
        "-t",
        f"{duration:.3f}",
        "-i",
        str(clean_audio),
        "-c",
        "copy",
        str(destination),
    ]
    log_debug(f"      ffmpeg command: {' '.join(extract_cmd)}")
    result = subprocess.run(extract_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffmpeg clip extraction failed")


def write_manifest_outputs(entries: Sequence[Dict[str, object]], config: CorpusConfig) -> None:
    manifest_path = config.clips_dir / config.manifest_filename
    with manifest_path.open("w", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(json.dumps(entry))
            fh.write("\n")

    stats_by_speaker: Dict[str, Dict[str, float]] = defaultdict(lambda: {"clips": 0, "seconds": 0.0})
    for entry in entries:
        stats = stats_by_speaker[entry["speaker"]]
        stats["clips"] += 1
        stats["seconds"] += float(entry["duration"])

    stats_path = config.clips_dir / config.stats_filename
    with stats_path.open("w", encoding="utf-8") as fh:
        json.dump(
            {
                "target_minutes_per_speaker": config.target_minutes_per_speaker,
                "per_session_minutes_cap": config.max_session_minutes_per_speaker,
                "clip_format": config.clip_format,
                "speakers": {
                    speaker: {
                        "clips": values["clips"],
                        "minutes": values["seconds"] / 60.0,
                    }
                    for speaker, values in sorted(stats_by_speaker.items())
                },
            },
            fh,
            indent=2,
            ensure_ascii=False,
        )
        fh.write("\n")


def sanitize_player_label(label: str) -> str:
    label = PLAYER_SUFFIX_PATTERN.sub("", label).strip()
    label = SPACE_PATTERN.sub(" ", label)
    return label


def normalize_player_key(label: str) -> str:
    return sanitize_player_label(label).lower()


def slugify(value: str) -> str:
    cleaned = re.sub(r"[^\w]+", "-", value.lower()).strip("-")
    return cleaned or "speaker"


def log_info(message: str) -> None:
    print(message, flush=True)


def log_debug(message: str) -> None:
    if VERBOSE:
        print(f"[debug] {message}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
