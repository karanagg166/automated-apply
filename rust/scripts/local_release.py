"""Inventory and stage one verified local build without activating it."""

import argparse
import base64
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

from scripts.run_acceptance import STAGES

ROOT = Path(__file__).resolve().parents[2]
RELEASES = ROOT / ".local/runtime-support/releases"
ARTIFACTS = {
    "bin/automated-apply-agents": "target/release/automated-apply-agents",
    "bin/automated-apply-native": "target/release/automated-apply-native",
    "bin/automated-apply-documents": "target/release/automated-apply-documents",
    "bin/automated-apply-tools": "target/release/automated-apply-tools",
    "frontend/.next/standalone": "frontend/.next/standalone",
    "frontend/run-local-rust.mjs": "frontend/run-local-rust.mjs",
    "extension/brave": "extension/dist",
    "extension/edge": "extension/dist-edge",
    "schema/001_rust_agent_runtime.review.sql": (
        "supabase/runtime/001_rust_agent_runtime.review.sql"
    ),
}
STABLE_EXTENSION_ID = "gdjbmkffcpicbpiikcohlmokkmcpipgp"


class ReleaseError(Exception):
    pass


def private_json(path):
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_mode & 0o077
        or info.st_size > 262144
    ):
        raise ReleaseError("private_release_evidence_required")
    return json.loads(path.read_bytes())


def content_digest(path, *, tree=False):
    base = path.resolve(strict=True)
    digest = hashlib.sha256()
    files = 0
    size = 0

    def visit(entry):
        nonlocal files, size
        relative = entry.relative_to(path).as_posix()
        info = entry.lstat()
        if (
            entry.name == ".env"
            or entry.name.startswith(".env.")
            or entry.name.endswith(".private.env")
        ):
            raise ReleaseError("private_configuration_in_build_output")
        if stat.S_ISLNK(info.st_mode):
            target = entry.readlink()
            if target.is_absolute() or not entry.resolve(strict=True).is_relative_to(
                base
            ):
                raise ReleaseError("external_build_symlink")
            marker = ("link", str(target))
        elif stat.S_ISDIR(info.st_mode):
            marker = ("directory",)
        elif stat.S_ISREG(info.st_mode):
            with entry.open("rb") as handle:
                file_digest = hashlib.file_digest(handle, "sha256").hexdigest()
            files += 1
            size += info.st_size
            marker = ("file", info.st_size, info.st_mode & 0o111, file_digest)
        else:
            raise ReleaseError("unsupported_build_entry")
        digest.update(json.dumps((relative, *marker), separators=(",", ":")).encode())
        digest.update(b"\n")
        if stat.S_ISDIR(info.st_mode):
            for child in sorted(entry.iterdir()):
                visit(child)

    info = path.lstat()
    if not (stat.S_ISDIR if tree else stat.S_ISREG)(info.st_mode):
        raise ReleaseError("release_artifact_type_mismatch")
    visit(path)
    return {"sha256": digest.hexdigest(), "files": files, "bytes": size}


def extension_identity(bundle, browser):
    info = json.loads((bundle / "build-info.json").read_bytes())
    manifest = json.loads((bundle / "manifest.json").read_bytes())
    key = base64.b64decode(manifest["key"], validate=True)
    prefix = hashlib.sha256(key).hexdigest()[:32]
    extension_id = "".join(chr(97 + int(letter, 16)) for letter in prefix)
    names = info["files"]
    if (
        extension_id != STABLE_EXTENSION_ID
        or info["extension_id"] != extension_id
        or info["native_host"] != f"com.automated_apply.{browser}"
        or info["browser"] != browser
        or info["version"] != manifest["version"]
        or not isinstance(names, list)
        or any(not isinstance(name, str) or Path(name).name != name for name in names)
        or set(names) | {"build-info.json"} != {p.name for p in bundle.iterdir()}
        or any(not stat.S_ISREG(p.lstat().st_mode) for p in bundle.iterdir())
    ):
        raise ReleaseError("extension_bundle_identity_mismatch")
    return {"extension_id": extension_id, "version": info["version"]}


def inventory(root, *, packaged=False):
    paths = {
        dest: root / (dest if packaged else src) for dest, src in ARTIFACTS.items()
    }
    for name, path in paths.items():
        if name.startswith("bin/") and not path.lstat().st_mode & stat.S_IXUSR:
            raise ReleaseError("release_binary_not_executable")
    frontend = paths["frontend/.next/standalone"]
    if (
        not all((frontend / name).is_file() for name in ["server.js", ".next/BUILD_ID"])
        or not (frontend / ".next/static").is_dir()
    ):
        raise ReleaseError("prepared_dashboard_bundle_required")
    return {
        "contents": {
            name: content_digest(
                path, tree=name.startswith("extension/") or name.endswith("/standalone")
            )
            for name, path in paths.items()
        },
        "extensions": {
            browser: extension_identity(paths[f"extension/{browser}"], browser)
            for browser in ("brave", "edge")
        },
    }


def tested_candidate(directory):
    report = private_json(directory / "results.json")
    record = private_json(directory / "release-artifacts.private.log")
    steps = report["stages"]
    commit = record["commit"]
    expected = {"commit": commit, "clean": True}
    if (
        not re.fullmatch(r"[0-9a-f]{40}", commit)
        or report["scope"] != "local_fixture_acceptance_not_live_platform_acceptance"
        or report["clean_commit_fixture_pass"] is not True
        or report["source_before"] != expected
        or report["source_after"] != expected
        or any(s.get("status") != "PASS" or s.get("exit_code") != 0 for s in steps)
        or [s["name"] for s in steps] != [name for name, _ in STAGES]
    ):
        raise ReleaseError("clean_combined_release_evidence_required")
    return {**record["artifacts"], "commit": commit}


def acceptance_candidate(label):
    if not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{32}", label or ""):
        raise ReleaseError("exact_local_acceptance_run_required")
    return tested_candidate(ROOT / ".local/acceptance" / label)


def verify_staged(destination, tested):
    if (
        destination.is_symlink()
        or private_json(destination / "release-manifest.json") != tested
        or inventory(destination, packaged=True)
        != {key: value for key, value in tested.items() if key != "commit"}
    ):
        raise ReleaseError("existing_local_release_preserved")


def stage(root, releases, tested):
    commit = tested["commit"]
    expected = dict(tested)
    del expected["commit"]
    destination = releases / f"rust-{commit}"
    releases.mkdir(parents=True, exist_ok=True)
    with (releases / ".rust-release.lock").open("a") as lease:
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if destination.exists() or destination.is_symlink():
            verify_staged(destination, tested)
            return
        if inventory(root) != expected:
            raise ReleaseError("build_output_changed_since_acceptance")
        staging = Path(tempfile.mkdtemp(prefix=".rust-release-", dir=releases))
        for dest, src in ARTIFACTS.items():
            path = root / src
            target = staging / dest
            target.parent.mkdir(parents=True, exist_ok=True)
            if path.is_dir():
                shutil.copytree(path, target, symlinks=True)
            else:
                shutil.copy2(path, target, follow_symlinks=False)
        if inventory(staging, packaged=True) != expected:
            raise ReleaseError("staged_release_verification_failed")
        with (staging / "release-manifest.json").open("x") as manifest:
            json.dump(tested, manifest, indent=2)
            manifest.write("\n")
            os.fchmod(manifest.fileno(), 0o600)
        staging.rename(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("inventory", "stage"))
    parser.add_argument("--acceptance-run")
    arguments = parser.parse_args()
    os.umask(0o077)
    try:
        if arguments.action == "inventory" and arguments.acceptance_run is None:
            commit = subprocess.check_output(
                ["git", "rev-parse", "--verify", "HEAD"],
                cwd=ROOT,
                text=True,
                timeout=10,
            ).strip()
            print(json.dumps({"commit": commit, "artifacts": inventory(ROOT)}))
            return
        if arguments.action != "stage":
            raise ReleaseError("exact_local_acceptance_run_required")
        tested = acceptance_candidate(arguments.acceptance_run)
        stage(ROOT, RELEASES, tested)
        print(json.dumps({"staged_commit": tested["commit"], "installed": False}))
    except ReleaseError as error:
        raise SystemExit(str(error)) from None
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        RuntimeError,
        subprocess.SubprocessError,
    ):
        raise SystemExit("local_release_evidence_or_artifact_unavailable") from None


if __name__ == "__main__":
    main()
