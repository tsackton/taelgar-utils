#!/usr/bin/env python3
from pathlib import Path
import sys


UTILS_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = UTILS_ROOT / "src"
for path in (UTILS_ROOT, SRC_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from website.site_builder.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
