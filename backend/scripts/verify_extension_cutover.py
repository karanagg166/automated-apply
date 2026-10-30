"""Read-only exact-SHA extension audit. Never writes Chrome preferences or files.

Only extension file names/digests and path-equality booleans are emitted. Disk
evidence is explicitly distinct from an owner-observed runtime reload.
"""

import argparse
import base64
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def blob(sha, path):
    return subprocess.run(
        ["git", "show", sha + ":" + path], cwd=ROOT,
        check=True, capture_output=True,
    ).stdout


def expected(sha):
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("exact_40_character_sha_required")
    build = blob(sha, "extension/build.mjs").decode()
    match = re.search(r"for \(const file of \[(.*?)\]\)", build, re.S)
    if not match:
        raise ValueError("extension_build_inventory_unrecognized")
    names = re.findall(r'"([a-zA-Z0-9_.-]+)"', match[1])
    if not names or "manifest.json" not in names or len(names) != len(set(names)):
        raise ValueError("extension_build_inventory_invalid")
    files = {name: blob(sha, "extension/" + name) for name in names}
    manifest = json.loads(files["manifest.json"])
    key_hash = hashlib.sha256(base64.b64decode(manifest["key"], validate=True)).hexdigest()[:32]
    identity = "".join(chr(97 + int(c, 16)) for c in key_hash)
    return files, identity


def audit(sha, directory, profile_directory=None):
    files, identity = expected(sha)
    directory = Path(directory)
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    mismatched = [name for name, data in files.items()
                  if (directory / name).is_symlink() or not (directory / name).is_file()
                  or (directory / name).read_bytes() != data]
    extras = len({str(p.relative_to(directory)) for p in directory.rglob("*") if p.is_file()} - files.keys())
    paths = []
    if profile_directory:
        for name in ("Preferences", "Secure Preferences"):
            path = Path(profile_directory) / name
            if path.is_file():
                record = json.loads(path.read_text()).get("extensions", {}).get("settings", {}).get(identity, {})
                if isinstance(record.get("path"), str):
                    # Unpacked installation uses an absolute directory. Never
                    # infer another profile or modify Chrome's protected state.
                    paths.append(Path(record["path"]))
    path_match = bool(paths) and all(p.is_absolute() and p.resolve() == directory.resolve() for p in paths)
    return {
        "source_sha": sha, "extension_id": identity, "expected_file_count": len(files),
        "matching_file_count": len(files) - len(mismatched), "mismatched_files": sorted(mismatched),
        "extra_file_count": extras, "expected_sha256": hashes,
        "disk_matches_sha": not mismatched and extras == 0,
        "profile_checked": profile_directory is not None,
        "persisted_extension_record_found": bool(paths),
        "persisted_path_matches_directory": path_match,
        "runtime_reload_verified": False, "writes_performed": 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--extension-dir", required=True, type=Path)
    parser.add_argument("--profile-dir", type=Path)
    args = parser.parse_args()
    try:
        result = audit(args.sha, args.extension_dir, args.profile_dir)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError):
        print(json.dumps({"error": "extension_audit_failed", "writes_performed": 0}))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["disk_matches_sha"] and (
        not args.profile_dir or result["persisted_path_matches_directory"]
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
