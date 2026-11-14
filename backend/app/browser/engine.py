"""Explicit installed-browser selection; never fall back to another browser."""

import sys
from pathlib import Path

from fastapi import HTTPException

BRAVE_EXECUTABLES = {
    "darwin": "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "linux": "/usr/bin/brave-browser",
}


def launch_options(channel):
    if channel == "brave":
        executable = BRAVE_EXECUTABLES.get(sys.platform)
        if not executable or not Path(executable).is_file():
            raise HTTPException(409, "Selected Brave browser is not installed")
        return {"executable_path": executable}
    if channel in {"msedge", "chrome", "chromium"}:
        return {"channel": channel}
    raise HTTPException(422, "Unsupported browser engine")
