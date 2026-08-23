#!/usr/bin/env python3

"""Prepare a step-0 session source bundle."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import textwrap
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import yaml

from taelgar_utils.common.io import write_json
from taelgar_utils.common.time import parse_timecode


SOURCE_TYPE_TRANSCRIPT = "transcript"
SOURCE_TYPE_NARRATIVE = "narrative"
SOURCE_TYPE_RAW_NOTES = "raw_notes"
SOURCE_TYPE_CHOICES = [
    SOURCE_TYPE_TRANSCRIPT,
    SOURCE_TYPE_NARRATIVE,
    SOURCE_TYPE_RAW_NOTES,
]

SCOPE_SESSION = "session"
SCOPE_ARC = "arc"
SCOPE_CHOICES = [SCOPE_SESSION, SCOPE_ARC]

TRANSCRIPT_FORMAT_AUTO = "auto"
TRANSCRIPT_FORMAT_LINES = "speaker_lines"
TRANSCRIPT_FORMAT_VTT = "vtt"
TRANSCRIPT_FORMAT_CHOICES = [
    TRANSCRIPT_FORMAT_AUTO,
    TRANSCRIPT_FORMAT_LINES,
    TRANSCRIPT_FORMAT_VTT,
]
SOURCE_AUDIO_EXTENSIONS = [
    ".m4a",
    ".mp3",
    ".wav",
    ".aac",
    ".flac",
    ".mp4",
    ".mov",
    ".m4v",
]
TRANSCRIPT_STEM_SUFFIXES = [".transcript", "-transcript", "_transcript"]

NARRATIVE_UNIT_SENTENCE = "sentence"
NARRATIVE_UNIT_PARAGRAPH = "paragraph"
NARRATIVE_UNIT_CHOICES = [
    NARRATIVE_UNIT_SENTENCE,
    NARRATIVE_UNIT_PARAGRAPH,
]

SPEAKER_LINE_RE = re.compile(
    r"^\[(?P<start>[0-9:\.]+)\s*-\s*(?P<end>[0-9:\.]+)\]\s*(?P<speaker>[^:]+):\s*(?P<text>.*)$"
)
VOICE_TAG_RE = re.compile(r"^<v\s+([^>]+)>(.*)$", re.IGNORECASE)
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
LEGACY_ROLE_SUFFIX_RE = re.compile(r"^(?P<name>.+?)\s*\((?P<game_role>[^()]+)\)$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare a session source bundle for step 0.")
    parser.add_argument("--config", type=Path, required=True, help="YAML config file for source preparation.")
    parser.add_argument(
        "--speaker-mappings",
        type=Path,
        help="JSON mapping of gameRole -> transcript identifier for this session.",
    )
    parser.add_argument(
        "--interactive-speakers",
        action="store_true",
        help="Prompt for unresolved transcript speakers using participant game roles.",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite existing outputs.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = args.config.expanduser().resolve()
    config = load_yaml_mapping(config_path)
    options = validate_config(config)

    source_path = Path(options["sourcePath"]).expanduser().resolve()
    if not source_path.exists():
        raise SystemExit(f"Source file not found: {source_path}")
    source_audio_path = resolve_source_audio_path(
        source_path=source_path,
        configured_path=options.get("sourceAudioPath"),
        source_type=options["sourceType"],
    )

    participants_path = Path(options["participantsPath"]).expanduser().resolve()
    speaker_mappings_path = args.speaker_mappings.expanduser().resolve() if args.speaker_mappings else None
    known_mistakes_path = (
        Path(options["knownMistakes"]).expanduser().resolve()
        if options.get("knownMistakes")
        else None
    )

    bundle_stem = build_bundle_stem(
        options["campaign"],
        options.get("sessionNumber"),
        scope=options["scope"],
        source_path=source_path,
    )
    output_parent_dir = Path(options["outputDir"]).expanduser().resolve()
    output_dir = output_parent_dir / bundle_stem
    sources_dir = output_dir / "sources"
    cleaned_dir = output_dir / "cleaned"
    output_dir.mkdir(parents=True, exist_ok=True)
    sources_dir.mkdir(parents=True, exist_ok=True)
    cleaned_dir.mkdir(parents=True, exist_ok=True)

    session_path = cleaned_dir / f"{bundle_stem}-session.yaml"
    prepared_path = cleaned_dir / f"{bundle_stem}-source-prepared.md"
    speaker_stats_path = cleaned_dir / f"{bundle_stem}-speaker-stats.json"

    archived_source_path = sources_dir / source_path.name
    archived_config_path = sources_dir / config_path.name
    archived_participants_path = sources_dir / participants_path.name
    archived_speaker_mappings_path = sources_dir / speaker_mappings_path.name if speaker_mappings_path else None
    archived_known_mistakes_path = (
        sources_dir / known_mistakes_path.name if known_mistakes_path else None
    )
    archived_supplemental_sources = archive_supplemental_sources(
        options.get("supplementalSources", []),
        sources_dir=sources_dir,
    )

    if options["sourceType"] == SOURCE_TYPE_TRANSCRIPT:
        if args.speaker_mappings is None and not args.interactive_speakers:
            raise SystemExit(
                "Transcript preparation requires either --speaker-mappings or --interactive-speakers."
            )
        if args.speaker_mappings is not None and args.interactive_speakers:
            raise SystemExit(
                "Choose exactly one transcript speaker resolution mode: --speaker-mappings or --interactive-speakers."
            )
    else:
        if args.speaker_mappings is not None or args.interactive_speakers:
            raise SystemExit(
                "Speaker resolution flags are only valid when sourceType=transcript."
            )

    output_paths = [session_path, prepared_path]
    if options["sourceType"] == SOURCE_TYPE_TRANSCRIPT:
        output_paths.append(speaker_stats_path)
    source_archive_paths = [
        archived_source_path,
        archived_config_path,
        archived_participants_path,
    ]
    if archived_speaker_mappings_path is not None:
        source_archive_paths.append(archived_speaker_mappings_path)
    if archived_known_mistakes_path is not None:
        source_archive_paths.append(archived_known_mistakes_path)
    for supplemental in archived_supplemental_sources:
        archived_path = supplemental.get("archivedPath")
        if archived_path is not None:
            source_archive_paths.append(Path(archived_path))

    for path in [*output_paths, *source_archive_paths]:
        if path.exists() and not args.force:
            raise SystemExit(f"Refusing to overwrite existing file without --force: {path}")

    participants = load_participants(participants_path)
    participant_index = build_participant_index(participants)
    known_mistakes = load_json_object(known_mistakes_path) if known_mistakes_path else {}
    speaker_mappings = (
        load_speaker_mappings(speaker_mappings_path, participant_index=participant_index)
        if speaker_mappings_path
        else {}
    )

    speaker_stats_payload: Optional[Dict[str, Any]] = None
    if options["sourceType"] == SOURCE_TYPE_TRANSCRIPT:
        transcript_format = resolve_transcript_format(source_path, options["transcriptFormat"])
        prepared_lines, participants, speaker_stats_payload = prepare_transcript(
            source_path=source_path,
            transcript_format=transcript_format,
            participants=participants,
            participant_index=participant_index,
            speaker_mappings=speaker_mappings,
            interactive_speakers=args.interactive_speakers,
            min_speaker_fraction=options["minSpeakerFraction"],
            known_mistakes=known_mistakes,
        )
    elif options["sourceType"] == SOURCE_TYPE_NARRATIVE:
        prepared_lines = prepare_narrative(
            source_path=source_path,
            unit_mode=options["narrativeUnit"],
            known_mistakes=known_mistakes,
        )
    else:
        prepared_lines = prepare_raw_notes(source_path=source_path, known_mistakes=known_mistakes)

    manifest = build_session_manifest(
        options=options,
        source_path=archived_source_path,
        config_path=archived_config_path,
        participants_path=archived_participants_path,
        speaker_mappings_path=archived_speaker_mappings_path,
        known_mistakes_path=archived_known_mistakes_path,
        prepared_path=prepared_path,
        speaker_stats_path=speaker_stats_path if speaker_stats_payload is not None else None,
        participants=participants,
        supplemental_sources=archived_supplemental_sources,
        source_audio_path=source_audio_path,
    )

    copy_file(source_path, archived_source_path)
    copy_file(config_path, archived_config_path)
    copy_file(participants_path, archived_participants_path)
    if speaker_mappings_path is not None and archived_speaker_mappings_path is not None:
        copy_file(speaker_mappings_path, archived_speaker_mappings_path)
    if known_mistakes_path is not None and archived_known_mistakes_path is not None:
        copy_file(known_mistakes_path, archived_known_mistakes_path)
    for supplemental in archived_supplemental_sources:
        source_value = supplemental.get("sourcePath")
        archived_path = supplemental.get("archivedPath")
        if source_value is None or archived_path is None:
            continue
        copy_file(Path(source_value), Path(archived_path))

    session_path.write_text(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    prepared_path.write_text("\n".join(prepared_lines) + "\n", encoding="utf-8")
    if speaker_stats_payload is not None:
        write_json(speaker_stats_path, speaker_stats_payload)

    print(f"Wrote {session_path}")
    print(f"Wrote {prepared_path} ({len(prepared_lines)} units)")
    if speaker_stats_payload is not None:
        print(f"Wrote {speaker_stats_path}")
    return 0


def load_yaml_mapping(path: Path) -> Dict[str, Any]:
    payload = yaml.safe_load(path.expanduser().resolve().read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise SystemExit(f"Expected a YAML mapping in {path}")
    return payload


def validate_config(config: Dict[str, Any]) -> Dict[str, Any]:
    options = {
        "sourcePath": config.get("sourcePath"),
        "sourceAudioPath": config.get("sourceAudioPath"),
        "sourceType": config.get("sourceType"),
        "scope": config.get("scope") or SCOPE_SESSION,
        "outputDir": config.get("outputDir"),
        "campaign": config.get("campaign"),
        "sessionNumber": config.get("sessionNumber"),
        "realWorldDate": config.get("realWorldDate"),
        "drStart": config.get("drStart"),
        "drEnd": config.get("drEnd"),
        "drStartTime": config.get("drStartTime"),
        "drEndTime": config.get("drEndTime"),
        "participantsPath": config.get("participantsPath"),
        "transcriptFormat": config.get("transcriptFormat") or TRANSCRIPT_FORMAT_AUTO,
        "narrativeUnit": config.get("narrativeUnit") or NARRATIVE_UNIT_SENTENCE,
        "minSpeakerFraction": config.get("minSpeakerFraction", 0.01),
        "knownMistakes": config.get("knownMistakes"),
        "supplementalSources": normalize_supplemental_sources(config.get("supplementalSources")),
        "sessionNote": normalize_session_note_config(config.get("sessionNote")),
    }

    required = [
        "sourcePath",
        "sourceType",
        "outputDir",
        "campaign",
        "participantsPath",
    ]
    if options["scope"] == SCOPE_SESSION:
        required.extend(["sessionNumber", "realWorldDate"])
    missing = [key for key in required if not options.get(key)]
    if missing:
        raise SystemExit("Missing required config fields: " + ", ".join(missing))
    if options["sourceType"] not in SOURCE_TYPE_CHOICES:
        raise SystemExit(f"Unsupported sourceType: {options['sourceType']}")
    if options["scope"] not in SCOPE_CHOICES:
        raise SystemExit(f"Unsupported scope: {options['scope']}")
    if options["transcriptFormat"] not in TRANSCRIPT_FORMAT_CHOICES:
        raise SystemExit(f"Unsupported transcriptFormat: {options['transcriptFormat']}")
    if options["narrativeUnit"] not in NARRATIVE_UNIT_CHOICES:
        raise SystemExit(f"Unsupported narrativeUnit: {options['narrativeUnit']}")
    return options


def normalize_session_note_config(value: Any) -> Optional[Dict[str, str]]:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise SystemExit("sessionNote must be a mapping when provided.")
    normalized = {
        "templatePath": str(value.get("templatePath", "")).strip(),
        "generatedRoot": str(value.get("generatedRoot", "")).strip(),
    }
    missing = [key for key, item in normalized.items() if not item]
    if missing:
        raise SystemExit("sessionNote is missing required fields: " + ", ".join(missing))
    return normalized


def load_participants(path: Path) -> List[Dict[str, Any]]:
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        raise SystemExit(f"Participants file not found: {resolved}")

    if resolved.suffix.lower() == ".json":
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    else:
        payload = yaml.safe_load(resolved.read_text(encoding="utf-8"))

    if not isinstance(payload, dict) or "participants" not in payload:
        raise SystemExit(f"Expected a mapping with a 'participants' list in {resolved}")
    payload = payload["participants"]
    if not isinstance(payload, list):
        raise SystemExit(f"Expected 'participants' to be a list in {resolved}")

    participants = [parse_participant(item) for item in payload]
    ensure_unique_participants(participants)
    return participants


def parse_participant(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise SystemExit(f"Invalid participant {raw!r}; expected a mapping.")

    name = str(raw.get("name", "")).strip()
    game_role = str(raw.get("gameRole", "")).strip()
    transcript_identifiers = raw.get("transcriptIdentifiers", [])
    if isinstance(transcript_identifiers, str):
        transcript_identifiers = [transcript_identifiers]
    if not isinstance(transcript_identifiers, list):
        raise SystemExit(
            f"Invalid participant {raw!r}; transcriptIdentifiers must be a list."
        )

    if not name or not game_role:
        raise SystemExit(
            f"Invalid participant {raw!r}; expected non-empty name and gameRole."
        )

    return {
        "name": name,
        "gameRole": game_role,
        "transcriptIdentifiers": sorted(
            {str(item).strip() for item in transcript_identifiers if str(item).strip()}
        ),
    }


def ensure_unique_participants(participants: Sequence[Dict[str, Any]]) -> None:
    seen_names: set[str] = set()
    seen_roles: set[str] = set()
    seen_transcript_ids: set[str] = set()

    for participant in participants:
        if participant["name"] in seen_names:
            raise SystemExit(f"Duplicate participant name: {participant['name']}")
        if participant["gameRole"] in seen_roles:
            raise SystemExit(f"Duplicate participant gameRole: {participant['gameRole']}")
        seen_names.add(participant["name"])
        seen_roles.add(participant["gameRole"])
        for transcript_identifier in participant["transcriptIdentifiers"]:
            if transcript_identifier in seen_transcript_ids:
                raise SystemExit(f"Duplicate transcript identifier: {transcript_identifier}")
            seen_transcript_ids.add(transcript_identifier)


def build_participant_index(participants: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    by_name: Dict[str, Dict[str, Any]] = {}
    by_game_role: Dict[str, Dict[str, Any]] = {}
    by_transcript_identifier: Dict[str, Dict[str, Any]] = {}

    for participant in participants:
        stored = dict(participant)
        by_name[participant["name"]] = stored
        by_game_role[participant["gameRole"]] = stored
        for transcript_identifier in participant["transcriptIdentifiers"]:
            by_transcript_identifier[transcript_identifier] = stored

    return {
        "byName": by_name,
        "byGameRole": by_game_role,
        "byTranscriptIdentifier": by_transcript_identifier,
    }


def load_json_object(path: Path) -> Dict[str, str]:
    payload = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"Expected a JSON object in {path}")
    return {str(key): str(value) for key, value in payload.items()}


def load_speaker_mappings(
    path: Path,
    *,
    participant_index: Dict[str, Dict[str, Dict[str, Any]]],
) -> Dict[str, List[str]]:
    payload = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"Expected a JSON object in {path}")

    mappings: Dict[str, List[str]] = {}
    for raw_key, raw_value in payload.items():
        for game_role, transcript_identifier in normalize_speaker_mapping_entry(
            raw_key,
            raw_value,
            participant_index=participant_index,
        ):
            mappings.setdefault(game_role, [])
            if transcript_identifier not in mappings[game_role]:
                mappings[game_role].append(transcript_identifier)
    return mappings


def normalize_speaker_mapping_entry(
    raw_key: str,
    raw_value: Any,
    *,
    participant_index: Dict[str, Dict[str, Dict[str, Any]]],
) -> List[Tuple[str, str]]:
    key = str(raw_key).strip()
    if not key:
        return []

    if isinstance(raw_value, list):
        normalized_pairs: List[Tuple[str, str]] = []
        for item in raw_value:
            normalized_pairs.extend(
                normalize_speaker_mapping_entry(
                    raw_key,
                    item,
                    participant_index=participant_index,
                )
            )
        return normalized_pairs

    value = str(raw_value).strip()
    if not value:
        return []

    if key in participant_index["byGameRole"]:
        return [(key, value)]

    if value in participant_index["byGameRole"]:
        return [(value, key)]

    participant = participant_index["byName"].get(value)
    if participant is not None:
        return [(participant["gameRole"], key)]

    legacy_match = LEGACY_ROLE_SUFFIX_RE.match(value)
    if legacy_match:
        legacy_game_role = legacy_match.group("game_role").strip()
        if legacy_game_role in participant_index["byGameRole"]:
            return [(legacy_game_role, key)]
        legacy_name = legacy_match.group("name").strip()
        participant = participant_index["byName"].get(legacy_name)
        if participant is not None:
            return [(participant["gameRole"], key)]

    if value.lower() == "unknown_speaker" or key.lower() == "unknown_speaker":
        warnings.warn(
            f"Skipping legacy unknown speaker mapping {raw_key!r}: {raw_value!r}.",
            stacklevel=2,
        )
        return []

    raise SystemExit(
        f"Could not normalize speaker mapping entry {raw_key!r}: {raw_value!r}. "
        "Expected 'gameRole -> transcriptIdentifier', 'transcriptIdentifier -> gameRole', "
        "or a legacy value like 'Real Name (GameRole)'."
    )


def resolve_transcript_format(source_path: Path, requested: str) -> str:
    if requested != TRANSCRIPT_FORMAT_AUTO:
        return requested
    if source_path.suffix.lower() == ".vtt":
        return TRANSCRIPT_FORMAT_VTT
    return TRANSCRIPT_FORMAT_LINES


def resolve_source_audio_path(
    *,
    source_path: Path,
    configured_path: Any,
    source_type: str,
) -> Optional[Path]:
    configured_text = str(configured_path or "").strip()
    if configured_text:
        audio_path = Path(configured_text).expanduser().resolve()
        if not audio_path.exists():
            raise SystemExit(f"sourceAudioPath file not found: {audio_path}")
        if not audio_path.is_file():
            raise SystemExit(f"sourceAudioPath is not a file: {audio_path}")
        return audio_path
    if source_type != SOURCE_TYPE_TRANSCRIPT:
        return None
    return infer_source_audio_path(source_path)


def infer_source_audio_path(source_path: Path) -> Optional[Path]:
    source_stem = source_path.with_suffix("").name
    candidate_stems: List[str] = []

    def add_candidate_stem(stem: str) -> None:
        if stem and stem not in candidate_stems:
            candidate_stems.append(stem)

    add_candidate_stem(source_stem)
    lower_source_stem = source_stem.lower()
    for suffix in TRANSCRIPT_STEM_SUFFIXES:
        if lower_source_stem.endswith(suffix):
            add_candidate_stem(source_stem[: -len(suffix)])

    for stem in candidate_stems:
        for extension in SOURCE_AUDIO_EXTENSIONS:
            candidate = source_path.parent / f"{stem}{extension}"
            if candidate.is_file():
                return candidate.resolve()

    candidate_stem_lowers = {stem.lower() for stem in candidate_stems}
    matches = [
        candidate
        for candidate in source_path.parent.iterdir()
        if candidate.is_file()
        and candidate.suffix.lower() in SOURCE_AUDIO_EXTENSIONS
        and candidate.with_suffix("").name.lower() in candidate_stem_lowers
    ]
    matches.sort(
        key=lambda candidate: (
            SOURCE_AUDIO_EXTENSIONS.index(candidate.suffix.lower()),
            candidate.name.lower(),
        )
    )
    return matches[0].resolve() if matches else None


def build_bundle_stem(
    campaign: Any,
    session_number: Any,
    *,
    scope: str,
    source_path: Path,
) -> str:
    campaign_slug = slugify_text(str(campaign))
    if not campaign_slug:
        raise SystemExit("Campaign must contain at least one alphanumeric character.")
    if scope == SCOPE_ARC and session_number in (None, ""):
        source_slug = slugify_text(source_path.stem) or "arc"
        return f"{campaign_slug}-{source_slug}"
    try:
        session_number_int = int(session_number)
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"sessionNumber must be an integer, got {session_number!r}") from exc
    return f"{campaign_slug}-{session_number_int:03d}"


def slugify_text(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return re.sub(r"-{2,}", "-", slug)


def copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def build_session_manifest(
    *,
    options: Dict[str, Any],
    source_path: Path,
    config_path: Path,
    participants_path: Path,
    speaker_mappings_path: Optional[Path],
    known_mistakes_path: Optional[Path],
    prepared_path: Path,
    speaker_stats_path: Optional[Path],
    participants: Sequence[Dict[str, Any]],
    supplemental_sources: Sequence[Dict[str, str]],
    source_audio_path: Optional[Path],
) -> Dict[str, Any]:
    manifest: Dict[str, Any] = {
        "schemaVersion": "1.0",
        "sourceType": options["sourceType"],
        "scope": options["scope"],
        "campaign": options["campaign"],
        "sessionNumber": options["sessionNumber"],
        "realWorldDate": options["realWorldDate"],
        "drStart": options.get("drStart"),
        "drEnd": options.get("drEnd") or options.get("drStart"),
        "drStartTime": options.get("drStartTime"),
        "drEndTime": options.get("drEndTime"),
        "participants": list(participants),
        "sourceInputPath": str(source_path),
    }
    if source_audio_path is not None:
        manifest["sourceAudioPath"] = str(source_audio_path)
    manifest["sourceConfigPath"] = str(config_path)
    manifest["participantsPath"] = str(participants_path)
    manifest["preparedSourcePath"] = str(prepared_path)
    if supplemental_sources:
        manifest["supplementalSources"] = list(supplemental_sources)
    if speaker_mappings_path is not None:
        manifest["speakerMappingsPath"] = str(speaker_mappings_path)
    if known_mistakes_path is not None:
        manifest["knownMistakesPath"] = str(known_mistakes_path)
    if options["sourceType"] == SOURCE_TYPE_TRANSCRIPT:
        manifest["transcriptFormat"] = resolve_transcript_format(source_path, options["transcriptFormat"])
        if speaker_stats_path is not None:
            manifest["speakerStatsPath"] = str(speaker_stats_path)
    if options["sourceType"] == SOURCE_TYPE_NARRATIVE:
        manifest["narrativeUnit"] = options["narrativeUnit"]
    if options.get("sessionNote") is not None:
        manifest["sessionNote"] = dict(options["sessionNote"])
    return manifest


def prepare_transcript(
    *,
    source_path: Path,
    transcript_format: str,
    participants: Sequence[Dict[str, Any]],
    participant_index: Dict[str, Dict[str, Dict[str, Any]]],
    speaker_mappings: Dict[str, List[str]],
    interactive_speakers: bool,
    min_speaker_fraction: float,
    known_mistakes: Dict[str, str],
) -> Tuple[List[str], List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    if transcript_format == TRANSCRIPT_FORMAT_VTT:
        entries = parse_vtt_entries(source_path)
    elif transcript_format == TRANSCRIPT_FORMAT_LINES:
        entries = parse_speaker_lines(source_path)
    else:  # pragma: no cover - guarded by config validation
        raise SystemExit(f"Unsupported transcript format: {transcript_format}")

    segments = transcript_entries_to_segments(entries)
    speaker_resolution = resolve_transcript_speakers(
        segments=segments,
        participant_index=participant_index,
        speaker_mappings=speaker_mappings,
        interactive_speakers=interactive_speakers,
        min_speaker_fraction=min_speaker_fraction,
    )

    finalized_resolution = {
        transcript_identifier: resolution
        for transcript_identifier, resolution in speaker_resolution.items()
        if resolution is not None
    }

    updated_participants = merge_transcript_identifiers(participants, finalized_resolution)
    prepared_lines: List[str] = []
    unknown_role_count = 0
    for index, (start, end, speaker, text) in enumerate(entries, start=1):
        resolved = finalized_resolution.get(speaker)
        game_role = resolved["gameRole"] if resolved is not None else speaker
        if resolved is None:
            unknown_role_count += 1
        cleaned_text = apply_known_mistakes(normalize_whitespace(text), known_mistakes)
        prepared_lines.append(f"[u{index:04d} | {start}-{end} | {game_role}] {cleaned_text}")

    warn_on_unknown_game_roles(total_units=len(prepared_lines), unknown_units=unknown_role_count)

    speaker_stats_payload = None
    if transcript_format == TRANSCRIPT_FORMAT_VTT:
        speaker_stats_payload = build_speaker_stats_payload(segments, finalized_resolution)

    return prepared_lines, updated_participants, speaker_stats_payload


def resolve_transcript_speakers(
    *,
    segments: Sequence[Dict[str, Any]],
    participant_index: Dict[str, Dict[str, Dict[str, Any]]],
    speaker_mappings: Dict[str, List[str]],
    interactive_speakers: bool,
    min_speaker_fraction: float,
) -> Dict[str, Optional[Dict[str, Any]]]:
    transcript_identifiers = sorted(
        {str(segment.get("speaker") or "Unknown").strip() or "Unknown" for segment in segments}
    )

    resolution: Dict[str, Optional[Dict[str, Any]]] = {}
    for transcript_identifier in transcript_identifiers:
        resolution[transcript_identifier] = resolve_participant_for_identifier(
            transcript_identifier,
            participant_index,
        )

    if speaker_mappings:
        for game_role, transcript_identifiers in speaker_mappings.items():
            participant = participant_index["byGameRole"].get(game_role)
            if participant is None:
                raise SystemExit(
                    f"Speaker mappings file references unknown gameRole: {game_role}"
                )
            for transcript_identifier in transcript_identifiers:
                resolution[transcript_identifier] = dict(participant)

    unresolved = [identifier for identifier, value in resolution.items() if value is None]
    if not unresolved or not interactive_speakers:
        return resolution

    if not sys.stdin.isatty():
        raise SystemExit(
            "Interactive speaker mapping was requested, but no interactive terminal is attached. "
            "Run prepare-source in a real terminal session."
        )

    speaker_stats = compute_transcript_speaker_stats(segments)
    resolution.update(
        prompt_for_game_roles(
            segments=segments,
            unresolved=unresolved,
            speaker_stats=speaker_stats,
            participants=participant_index["byGameRole"],
            min_speaker_fraction=min_speaker_fraction,
        )
    )
    return resolution


def resolve_participant_for_identifier(
    transcript_identifier: str,
    participant_index: Dict[str, Dict[str, Dict[str, Any]]],
) -> Optional[Dict[str, Any]]:
    if transcript_identifier in participant_index["byTranscriptIdentifier"]:
        return dict(participant_index["byTranscriptIdentifier"][transcript_identifier])
    if transcript_identifier in participant_index["byName"]:
        return dict(participant_index["byName"][transcript_identifier])
    if transcript_identifier in participant_index["byGameRole"]:
        return dict(participant_index["byGameRole"][transcript_identifier])
    return None


def merge_transcript_identifiers(
    participants: Sequence[Dict[str, Any]],
    resolution: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    by_game_role = {participant["gameRole"]: dict(participant) for participant in participants}
    for participant in by_game_role.values():
        participant["transcriptIdentifiers"] = list(participant["transcriptIdentifiers"])

    for transcript_identifier, participant in resolution.items():
        updated = by_game_role[participant["gameRole"]]
        if transcript_identifier not in updated["transcriptIdentifiers"]:
            updated["transcriptIdentifiers"].append(transcript_identifier)

    merged = []
    for participant in participants:
        updated = by_game_role[participant["gameRole"]]
        updated["transcriptIdentifiers"] = sorted(set(updated["transcriptIdentifiers"]))
        merged.append(updated)
    return merged


def compute_transcript_speaker_stats(segments: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    stats: Dict[str, Dict[str, Any]] = {}
    for segment in segments:
        transcript_identifier = str(segment.get("speaker") or "Unknown").strip() or "Unknown"
        start = float(segment.get("start", 0.0))
        end = float(segment.get("end", start))
        duration = max(0.0, end - start)
        text = str(segment.get("text") or "").strip()
        entry = stats.setdefault(
            transcript_identifier,
            {"durationSeconds": 0.0, "segmentCount": 0, "wordCount": 0},
        )
        entry["durationSeconds"] += duration
        entry["segmentCount"] += 1
        entry["wordCount"] += len(text.split()) if text else 0
    return stats


def prompt_for_game_roles(
    *,
    segments: Sequence[Dict[str, Any]],
    unresolved: Sequence[str],
    speaker_stats: Dict[str, Dict[str, Any]],
    participants: Dict[str, Dict[str, Any]],
    min_speaker_fraction: float,
) -> Dict[str, Dict[str, Any]]:
    total_duration = sum(item["durationSeconds"] for item in speaker_stats.values()) or 1.0
    segments_by_speaker: Dict[str, List[Dict[str, Any]]] = {}
    for segment in segments:
        segments_by_speaker.setdefault(segment["speaker"], []).append(segment)

    candidates = [
        transcript_identifier
        for transcript_identifier in unresolved
        if (speaker_stats.get(transcript_identifier, {}).get("durationSeconds", 0.0) / total_duration) >= min_speaker_fraction
    ]

    print(
        f"Interactive speaker assignment queued for {len(candidates)} speakers "
        f"(> {min_speaker_fraction:.2%} duration)."
    )
    print("Available game roles:")
    for game_role in sorted(participants):
        participant = participants[game_role]
        print(f"  - {participant['gameRole']} ({participant['name']})")
    print()

    mapping: Dict[str, Dict[str, Any]] = {}
    for transcript_identifier in candidates:
        excerpt = build_speaker_excerpt(segments_by_speaker.get(transcript_identifier, []))
        fraction = speaker_stats[transcript_identifier]["durationSeconds"] / total_duration if total_duration else 0.0
        print("-----")
        print(f"Transcript speaker {transcript_identifier} ({fraction:.2%} of speaking time)")
        if excerpt:
            for paragraph in excerpt:
                print(textwrap.fill(paragraph, width=100))
                print()
        else:
            print("(No sample text available)\n")

        while True:
            choice = input("Map to which gameRole? (leave blank to skip): ").strip()
            if not choice:
                break
            participant = participants.get(choice)
            if participant is None:
                print("Unknown gameRole. Choose one of the listed game roles.")
                continue
            mapping[transcript_identifier] = dict(participant)
            break
        print()
    return mapping


def build_speaker_excerpt(
    segments: Sequence[Dict[str, Any]],
    *,
    target_words: int = 160,
    max_words: int = 220,
) -> List[str]:
    ranked = sorted(
        segments,
        key=lambda segment: len(str(segment.get("text") or "").split()),
        reverse=True,
    )

    excerpts: List[str] = []
    word_total = 0
    for segment in ranked:
        text = str(segment.get("text") or "").strip()
        if not text:
            continue
        excerpts.append(text)
        word_total += len(text.split())
        if word_total >= target_words:
            break

    trimmed: List[str] = []
    consumed = 0
    for excerpt in excerpts:
        words = excerpt.split()
        if consumed + len(words) <= max_words:
            trimmed.append(excerpt)
            consumed += len(words)
            continue
        remaining = max_words - consumed
        if remaining > 0:
            trimmed.append(" ".join(words[:remaining]))
        break
    return trimmed


def build_speaker_stats_payload(
    segments: Sequence[Dict[str, Any]],
    resolution: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    speaker_stats = compute_transcript_speaker_stats(segments)
    total_duration = sum(entry["durationSeconds"] for entry in speaker_stats.values()) or 1.0

    speakers = []
    for transcript_identifier in sorted(speaker_stats):
        entry = speaker_stats[transcript_identifier]
        participant = resolution.get(transcript_identifier)
        speakers.append(
            {
                "transcriptIdentifier": transcript_identifier,
                "name": participant["name"] if participant is not None else None,
                "gameRole": participant["gameRole"] if participant is not None else transcript_identifier,
                "segmentCount": int(entry["segmentCount"]),
                "durationSeconds": round(float(entry["durationSeconds"]), 3),
                "fraction": round(float(entry["durationSeconds"]) / total_duration, 4),
                "wordCount": int(entry["wordCount"]),
            }
        )

    return {
        "totalDurationSeconds": round(total_duration, 3),
        "speakers": speakers,
    }


def warn_on_unknown_game_roles(*, total_units: int, unknown_units: int) -> None:
    if total_units <= 0 or unknown_units <= 0:
        return
    fraction = unknown_units / total_units
    if fraction <= 0.01:
        return
    warnings.warn(
        (
            f"{unknown_units} of {total_units} prepared transcript units ({fraction:.2%}) use an unknown game role. "
            "This usually means some transcript identifiers were not mapped or were skipped during interactive mapping."
        ),
        stacklevel=2,
    )


def parse_speaker_lines(source_path: Path) -> List[Tuple[str, str, str, str]]:
    entries: List[Tuple[str, str, str, str]] = []
    for raw in source_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        match = SPEAKER_LINE_RE.match(line)
        if match:
            entries.append(
                (
                    match.group("start"),
                    match.group("end"),
                    match.group("speaker").strip(),
                    match.group("text").strip(),
                )
            )
        else:
            entries.append(("00:00:00.00", "00:00:00.00", "Unknown", line))
    return entries


def parse_vtt_entries(source_path: Path) -> List[Tuple[str, str, str, str]]:
    try:
        from webvtt import WebVTT
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise SystemExit(
            "VTT input requires webvtt-py. Install the project requirements first."
        ) from exc

    entries: List[Tuple[str, str, str, str]] = []
    for caption in WebVTT().read(str(source_path)):
        voice = normalize_whitespace(getattr(caption, "voice", "") or "")
        text = normalize_whitespace(" ".join((caption.text or "").splitlines()))
        if voice:
            speaker = voice
        else:
            speaker, text = split_speaker_text(text)
        entries.append((caption.start, caption.end, speaker, text))
    return entries


def transcript_entries_to_segments(entries: Sequence[Tuple[str, str, str, str]]) -> List[Dict[str, Any]]:
    segments: List[Dict[str, Any]] = []
    for index, (start, end, speaker, text) in enumerate(entries):
        start_seconds = safe_parse_timecode(start)
        end_seconds = safe_parse_timecode(end)
        segments.append(
            {
                "id": f"seg_{index:06d}",
                "start": start_seconds,
                "end": max(end_seconds, start_seconds),
                "speaker": speaker.strip() or "Unknown",
                "text": text.strip(),
            }
        )
    return segments


def split_speaker_text(text: str) -> Tuple[str, str]:
    if not text:
        return "Unknown", ""
    voice_match = VOICE_TAG_RE.match(text)
    if voice_match:
        return (
            normalize_whitespace(voice_match.group(1)) or "Unknown",
            normalize_whitespace(voice_match.group(2)),
        )
    if ":" in text:
        speaker, remainder = text.split(":", 1)
        return normalize_whitespace(speaker) or "Unknown", normalize_whitespace(remainder)
    return "Unknown", normalize_whitespace(text)


def prepare_narrative(
    *,
    source_path: Path,
    unit_mode: str,
    known_mistakes: Dict[str, str],
) -> List[str]:
    raw_text = source_path.read_text(encoding="utf-8")
    paragraphs = [normalize_whitespace(block) for block in re.split(r"\n\s*\n", raw_text) if block.strip()]

    units: List[str] = []
    if unit_mode == NARRATIVE_UNIT_PARAGRAPH:
        units = paragraphs
    else:
        for paragraph in paragraphs:
            sentences = [
                normalize_whitespace(sentence)
                for sentence in SENTENCE_SPLIT_RE.split(paragraph)
                if sentence.strip()
            ]
            units.extend(sentences or [paragraph])

    return [
        f"[u{index:04d}] {apply_known_mistakes(text, known_mistakes)}"
        for index, text in enumerate(units, start=1)
    ]


def prepare_raw_notes(*, source_path: Path, known_mistakes: Dict[str, str]) -> List[str]:
    units = []
    for raw in source_path.read_text(encoding="utf-8").splitlines():
        stripped = strip_note_prefix(raw)
        if stripped:
            units.append(apply_known_mistakes(normalize_whitespace(stripped), known_mistakes))
    return [f"[u{index:04d}] {text}" for index, text in enumerate(units, start=1)]


def normalize_supplemental_sources(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if not isinstance(value, list):
        raise SystemExit("supplementalSources must be a list of file paths or URLs.")
    normalized: List[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            normalized.append(text)
    return normalized


def archive_supplemental_sources(
    supplemental_sources: Sequence[str],
    *,
    sources_dir: Path,
) -> List[Dict[str, str]]:
    archived: List[Dict[str, str]] = []
    supplemental_dir = sources_dir / "supplemental"
    for index, entry in enumerate(supplemental_sources, start=1):
        if re.match(r"^https?://", entry, re.IGNORECASE):
            archived.append({"original": entry, "archivedPath": entry})
            continue
        source_path = Path(entry).expanduser().resolve()
        if not source_path.exists():
            raise SystemExit(f"Supplemental source file not found: {source_path}")
        destination = supplemental_dir / f"{index:02d}-{source_path.name}"
        archived.append(
            {
                "original": entry,
                "sourcePath": str(source_path),
                "archivedPath": str(destination),
            }
        )
    return archived


def strip_note_prefix(line: str) -> str:
    stripped = line.strip()
    if not stripped:
        return ""
    return re.sub(r"^[-*+]\s+", "", stripped)


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def safe_parse_timecode(value: str) -> float:
    try:
        return parse_timecode(value)
    except ValueError:
        return 0.0


def apply_known_mistakes(text: str, replacements: Dict[str, str]) -> str:
    if not text or not replacements:
        return text
    cleaned = text
    for wrong, right in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
        if wrong:
            cleaned = cleaned.replace(wrong, right)
    return cleaned


if __name__ == "__main__":
    raise SystemExit(main())
