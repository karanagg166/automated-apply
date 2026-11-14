"""Read macOS foreground/window order without Apple Events to a browser or activation."""

import argparse
import ctypes
import json
import os
import plistlib
import subprocess
import sys
from pathlib import Path


def capture():
    if sys.platform != "darwin":
        raise ValueError("macos_required")
    core = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    graphics = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
    graphics.CGWindowListCopyWindowInfo.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
    graphics.CGWindowListCopyWindowInfo.restype = ctypes.c_void_p
    core.CFPropertyListCreateData.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                             ctypes.c_long, ctypes.c_ulong, ctypes.c_void_p]
    core.CFPropertyListCreateData.restype = ctypes.c_void_p
    core.CFDataGetLength.argtypes = [ctypes.c_void_p]
    core.CFDataGetLength.restype = ctypes.c_long
    core.CFDataGetBytePtr.argtypes = [ctypes.c_void_p]
    core.CFDataGetBytePtr.restype = ctypes.c_void_p
    core.CFRelease.argtypes = [ctypes.c_void_p]
    array = graphics.CGWindowListCopyWindowInfo(1, 0)
    if not array:
        raise ValueError("window_snapshot_unavailable")
    data = None
    try:
        data = core.CFPropertyListCreateData(None, array, 100, 0, None)
        if not data:
            raise ValueError("window_snapshot_unavailable")
        size = core.CFDataGetLength(data)
        if not 0 < size <= 4 * 1024 * 1024:
            raise ValueError("window_snapshot_too_large")
        windows = plistlib.loads(ctypes.string_at(core.CFDataGetBytePtr(data), size))
    finally:
        if data:
            core.CFRelease(data)
        core.CFRelease(array)
    # AppKit reads only; no browser Apple Events, AX, GUI scripting or activation.
    front = subprocess.run(["/usr/bin/osascript", "-l", "JavaScript", "-e",
        'ObjC.import("AppKit"); Number($.NSWorkspace.sharedWorkspace.frontmostApplication.processIdentifier);'],
        capture_output=True, text=True, timeout=10, check=False)
    if front.returncode or not front.stdout.strip().isdigit():
        raise ValueError("foreground_snapshot_unavailable")
    return {"foreground_pid": int(front.stdout), "windows": [
        {"id": w["kCGWindowNumber"], "pid": w["kCGWindowOwnerPID"]}
        for w in windows if w.get("kCGWindowLayer") == 0
    ]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--compare", type=Path)
    args = parser.parse_args()
    try:
        value = capture()
        if args.output:
            descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, "w") as handle:
                json.dump(value, handle)
            print(json.dumps({"snapshot_saved": True, "window_count": len(value["windows"])}))
        elif args.compare:
            before = json.loads(args.compare.read_text())
            same = value == before
            print(json.dumps({"status": "PASS" if same else "FAIL",
                              "foreground_unchanged": value["foreground_pid"] == before["foreground_pid"],
                              "window_order_unchanged": value["windows"] == before["windows"],
                              "active_browser_tabs_checked": False}))
            if not same:
                raise SystemExit(1)
        else:
            print(json.dumps({"window_count": len(value["windows"]), "snapshot_available": True}))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        print(json.dumps({"status": "snapshot_unavailable"}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
