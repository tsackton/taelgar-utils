from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Manifest:
    path: Path
    files: dict[str, dict[str, Any]] = field(default_factory=dict)
    generated: set[str] = field(default_factory=set)

    @classmethod
    def load(cls, path: Path) -> "Manifest":
        if not path.exists():
            return cls(path=path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            path=path,
            files=dict(payload.get("files", {})),
            generated=set(payload.get("generated", [])),
        )

    def save(self, files: dict[str, dict[str, Any]], generated: set[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "files": files,
            "generated": sorted(generated),
        }
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

