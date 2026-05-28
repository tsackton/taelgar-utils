#!/usr/bin/env python3
from pathlib import Path
import sys


UTILS_ROOT = Path(__file__).resolve().parents[1]
if str(UTILS_ROOT) not in sys.path:
    sys.path.insert(0, str(UTILS_ROOT))

from website.site_builder.cli import main


if __name__ == "__main__":
    raise SystemExit(main())

