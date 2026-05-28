#!/usr/bin/env python3
from pathlib import Path
import sys


UTILS_ROOT = Path(__file__).resolve().parent
if str(UTILS_ROOT) not in sys.path:
    sys.path.insert(0, str(UTILS_ROOT))

from website.site_builder.cli import main


if __name__ == "__main__":
    args = sys.argv[1:] or ["export"]
    raise SystemExit(main(args))

