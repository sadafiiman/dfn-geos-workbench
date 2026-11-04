#!/usr/bin/env python3
"""Launch the dfn-GEOS Workbench management panel.

    python run_panel.py [--port 8765] [--home DIR]

No third-party packages are required — the panel runs on the Python standard
library only (Ubuntu, Windows, macOS).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from panel.webapp import serve  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--home", default=None,
                    help="directory for config.json, panel.db and cases/")
    args = ap.parse_args()
    serve(port=args.port,
          home=Path(args.home).resolve() if args.home else None)


if __name__ == "__main__":
    main()
