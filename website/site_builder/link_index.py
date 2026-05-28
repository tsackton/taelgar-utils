from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .scanner import SourceEntry


@dataclass(frozen=True)
class LinkResolution:
    status: str
    entry: SourceEntry | None = None
    candidates: tuple[SourceEntry, ...] = ()


class LinkIndex:
    def __init__(self, entries: list[SourceEntry]) -> None:
        self.entries = entries
        self.by_id = {entry.id: entry for entry in entries}
        self.canonical_aliases: dict[str, set[str]] = defaultdict(set)
        self.explicit_aliases: dict[str, set[str]] = defaultdict(set)
        for entry in entries:
            for alias in canonical_aliases_for(entry):
                self.canonical_aliases[alias].add(entry.id)
            if entry.is_markdown and entry.note:
                for alias in explicit_aliases(entry.note.metadata.get("aliases")):
                    self.explicit_aliases[alias].add(entry.id)

    def resolve(self, link_target: str) -> LinkResolution:
        target = clean_target(link_target)
        if not target:
            return LinkResolution("empty")
        if target.startswith(("http://", "https://", "mailto:")):
            return LinkResolution("external")

        candidates = self._candidate_aliases(target)
        for alias in candidates:
            resolution = self._resolve_from(self.canonical_aliases, alias)
            if resolution is not None:
                return resolution
        for alias in candidates:
            resolution = self._resolve_from(self.explicit_aliases, alias)
            if resolution is not None:
                return resolution
        return LinkResolution("missing")

    def _resolve_from(self, aliases: dict[str, set[str]], alias: str) -> LinkResolution | None:
        ids = aliases.get(alias)
        if not ids:
            return None
        entries = tuple(self.by_id[item] for item in sorted(ids))
        if len(entries) == 1:
            return LinkResolution("found", entry=entries[0])
        return LinkResolution("ambiguous", candidates=entries)

    def ambiguous_aliases(self) -> dict[str, tuple[SourceEntry, ...]]:
        ambiguous: dict[str, tuple[SourceEntry, ...]] = {
            alias: tuple(self.by_id[item] for item in sorted(ids))
            for alias, ids in sorted(self.canonical_aliases.items())
            if len(ids) > 1
        }
        for alias, ids in sorted(self.explicit_aliases.items()):
            if alias in self.canonical_aliases:
                continue
            if not ids:
                continue
            if len(ids) > 1:
                ambiguous[alias] = tuple(self.by_id[item] for item in sorted(ids))
        return ambiguous

    def digest(self) -> str:
        payload = sorted((entry.relative_path.as_posix(), entry.target_path.as_posix()) for entry in self.entries)
        data = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        return hashlib.sha256(data.encode("utf-8")).hexdigest()

    @staticmethod
    def _candidate_aliases(target: str) -> list[str]:
        path = Path(target)
        aliases = [target, target.replace("\\", "/")]
        if path.suffix == ".md":
            aliases.append(target[: -len(".md")])
        if "/" in target:
            aliases.extend([path.name, path.stem])
            if path.suffix == "":
                aliases.append(target + ".md")
        else:
            aliases.append(target.lower())
            if not target.endswith(".md"):
                aliases.append(target + ".md")
        return dedupe(aliases)


def canonical_aliases_for(entry: SourceEntry) -> list[str]:
    rel = entry.relative_path.as_posix()
    target = entry.target_path.as_posix()
    aliases = [rel, target, entry.relative_path.name, entry.target_path.name]
    if entry.is_markdown:
        aliases.extend(
            [
                entry.relative_path.stem,
                entry.relative_path.stem.lower(),
                rel[: -len(".md")] if rel.endswith(".md") else rel,
                target[: -len(".md")] if target.endswith(".md") else target,
            ]
        )
    else:
        aliases.extend([entry.relative_path.name.lower()])
    return dedupe([alias for alias in aliases if alias])


def explicit_aliases(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        aliases = [value]
    elif isinstance(value, list):
        aliases = [str(item) for item in value if item]
    else:
        aliases = []
    output: list[str] = []
    for alias in aliases:
        output.extend([alias, alias.lower()])
    return output


def clean_target(target: str) -> str:
    return target.strip().strip("<>").replace("\\", "/")


def dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value not in seen:
            output.append(value)
            seen.add(value)
    return output
