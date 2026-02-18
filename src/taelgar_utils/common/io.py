"""Miscellaneous file IO helpers for the session pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_json(path: Path, payload: Any) -> None:
    """
    Write ``payload`` to ``path`` as UTF-8 JSON, ensuring parent directories exist.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


__all__ = ["write_json"]
