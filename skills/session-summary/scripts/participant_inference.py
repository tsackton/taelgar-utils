#!/usr/bin/env python3

"""Shared participant inference for session recap scaffolds and validation."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


def infer_session_header_participants(session_payload: Dict[str, Any]) -> Dict[str, Any]:
    participants = extract_participants(session_payload)
    dm_name = extract_dm_name(participants)

    transcript_pcs = infer_pcs_from_speaker_stats(session_payload, participants)
    if transcript_pcs:
        return {
            "dmName": dm_name,
            "pcs": transcript_pcs,
            "mode": "speaker-stats",
            "strictValidation": True,
            "warnings": [],
            "allowedFallbackPcs": transcript_pcs,
        }

    source_type = normalize_optional_string(session_payload.get("sourceType"))
    if source_type != "transcript":
        source_players = infer_pcs_from_source_frontmatter(session_payload)
        if source_players:
            return {
                "dmName": dm_name,
                "pcs": source_players,
                "mode": "source-frontmatter",
                "strictValidation": True,
                "warnings": [],
                "allowedFallbackPcs": source_players,
            }

    session_pcs = infer_pcs_from_session_payload(session_payload)
    if session_pcs:
        return {
            "dmName": dm_name,
            "pcs": session_pcs,
            "mode": "session-pcs",
            "strictValidation": True,
            "warnings": [],
            "allowedFallbackPcs": session_pcs,
        }

    fallback_pcs = build_fallback_pc_labels(participants)
    warnings: List[str] = []
    if fallback_pcs:
        warnings.append(
            "PC inference fell back to all non-DM session participants; remove non-participants from the recap header if needed."
        )
    return {
        "dmName": dm_name,
        "pcs": fallback_pcs,
        "mode": "participants-fallback",
        "strictValidation": False,
        "warnings": warnings,
        "allowedFallbackPcs": fallback_pcs,
    }


def extract_participants(session_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    value = session_payload.get("participants")
    if not isinstance(value, list):
        return []

    participants: List[Dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        participants.append(
            {
                "name": normalize_optional_string(item.get("name")),
                "gameRole": normalize_optional_string(item.get("gameRole")),
            }
        )
    return participants


def extract_dm_name(participants: List[Dict[str, Any]]) -> Optional[str]:
    for participant in participants:
        if participant.get("gameRole") == "DM":
            return participant.get("name") or participant.get("gameRole")
    return None


def infer_pcs_from_speaker_stats(
    session_payload: Dict[str, Any],
    participants: List[Dict[str, Any]],
) -> List[str]:
    speaker_stats_path = normalize_optional_string(session_payload.get("speakerStatsPath"))
    if speaker_stats_path is None:
        return []

    path = Path(speaker_stats_path).expanduser().resolve()
    if not path.exists():
        return []

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    speakers = payload.get("speakers")
    if not isinstance(speakers, list):
        return []

    active_roles: List[str] = []
    seen_roles: set[str] = set()
    for raw in speakers:
        if not isinstance(raw, dict):
            continue
        role = normalize_optional_string(raw.get("gameRole"))
        if role in {None, "DM", "Unknown"}:
            continue
        segment_count = raw.get("segmentCount", 0)
        duration_seconds = raw.get("durationSeconds", 0)
        word_count = raw.get("wordCount", 0)
        if not has_positive_signal(segment_count, duration_seconds, word_count):
            continue
        key = role.casefold()
        if key not in seen_roles:
            seen_roles.add(key)
            active_roles.append(role)

    if not active_roles:
        return []

    ordered_roles: List[str] = []
    remaining = {role.casefold(): role for role in active_roles}
    for participant in participants:
        role = participant.get("gameRole")
        if role is None or role == "DM":
            continue
        key = role.casefold()
        if key in remaining:
            ordered_roles.append(role)
            remaining.pop(key, None)
    for role in active_roles:
        if role.casefold() in remaining:
            ordered_roles.append(role)
            remaining.pop(role.casefold(), None)
    return ordered_roles


def has_positive_signal(segment_count: Any, duration_seconds: Any, word_count: Any) -> bool:
    try:
        if int(segment_count) > 0:
            return True
    except (TypeError, ValueError):
        pass
    try:
        if float(duration_seconds) > 0:
            return True
    except (TypeError, ValueError):
        pass
    try:
        if int(word_count) > 0:
            return True
    except (TypeError, ValueError):
        pass
    return False


def infer_pcs_from_source_frontmatter(session_payload: Dict[str, Any]) -> List[str]:
    source_input_path = normalize_optional_string(session_payload.get("sourceInputPath"))
    if source_input_path is None:
        return []
    path = Path(source_input_path).expanduser().resolve()
    if not path.exists() or path.suffix.lower() not in {".md", ".markdown"}:
        return []

    frontmatter = read_markdown_frontmatter(path)
    if not isinstance(frontmatter, dict):
        return []
    return normalize_name_listish(frontmatter.get("players"))


def infer_pcs_from_session_payload(session_payload: Dict[str, Any]) -> List[str]:
    for key in ("pcs", "PCs", "players", "playerCharacters", "characters"):
        values = normalize_name_listish(session_payload.get(key))
        if values:
            return values
    return []


def build_fallback_pc_labels(participants: List[Dict[str, Any]]) -> List[str]:
    labels: List[str] = []
    seen: set[str] = set()
    for participant in participants:
        role = participant.get("gameRole")
        if role == "DM":
            continue
        label = role or participant.get("name")
        if label is None:
            continue
        key = label.casefold()
        if key not in seen:
            seen.add(key)
            labels.append(label)
    return labels


def read_markdown_frontmatter(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\s*\n(.*?)\n---(?:\s*\n|$)", text, re.DOTALL)
    if not match:
        return {}
    payload = yaml.safe_load(match.group(1)) or {}
    return payload if isinstance(payload, dict) else {}


def normalize_name_listish(value: Any) -> List[str]:
    if value is None:
        return []
    raw_values: List[str]
    if isinstance(value, list):
        raw_values = [str(item).strip() for item in value if str(item).strip()]
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        raw_values = [part.strip() for part in text.split(",") if part.strip()]
    else:
        return []

    normalized: List[str] = []
    seen: set[str] = set()
    for item in raw_values:
        key = item.casefold()
        if key not in seen:
            seen.add(key)
            normalized.append(item)
    return normalized


def normalize_optional_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
