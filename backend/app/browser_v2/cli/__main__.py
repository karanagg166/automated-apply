"""`python -m backend.app.browser_v2.cli ...` entry point (launchd plist, .mcp.json, cutover_v2)."""

from __future__ import annotations

import sys

from backend.app.browser_v2.cli import main

if __name__ == "__main__":
    sys.exit(main())
