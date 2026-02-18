#!/usr/bin/env python3
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from website.site_builder.cli import main


if __name__ == "__main__":
    args = sys.argv[1:] or ["export"]
    raise SystemExit(main(args))
