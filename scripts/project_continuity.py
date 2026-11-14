"""Private, account-independent Codex project snapshots. Never edits Codex state."""

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_TRANSCRIPT = 512 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024


def private_directory(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise ValueError("unsafe_snapshot_directory")
    path.chmod(0o700)


def private_write(path, raw):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def snapshot(project=ROOT, codex=None, destination=None):
    project = Path(project).resolve()
    codex = Path(codex or os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).resolve()
    destination = Path(destination or project / ".local/codex-history")
    # Check every existing component before resolving: do not follow an output symlink.
    for component in [destination, *destination.parents]:
        if component.is_symlink():
            raise ValueError("unsafe_snapshot_directory")
    private_directory(destination)
    objects = destination / "objects"
    manifests = destination / "snapshots"
    private_directory(objects)
    private_directory(manifests)
    lock = os.open(destination / "snapshot.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(lock)
        return {"status": "already_running"}
    try:
        database = codex / "state_5.sqlite"
        if not database.is_file() or database.is_symlink():
            raise ValueError("codex_index_unavailable")
        connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=5)
        try:
            connection.row_factory = sqlite3.Row
            # Metadata can be private. It stays in the ignored, owner-only snapshot.
            rows = [dict(row) for row in connection.execute(
                "SELECT id,rollout_path,cwd,title,git_sha,git_branch,created_at,updated_at,archived "
                "FROM threads WHERE cwd=? ORDER BY id", (str(project),)
            )]
        finally:
            connection.close()
        for row in rows:
            source = Path(row["rollout_path"])
            row["transcript_status"] = "missing"
            # Only transcripts in the known Codex transcript roots can be copied.
            if (not source.is_absolute() or source != source.resolve()
                    or not any(source.is_relative_to(codex / folder) for folder in ("sessions", "archived_sessions"))):
                row["transcript_status"] = "outside_transcript_root"
                continue
            try:
                if any(part.is_symlink() for part in [source, *source.parents] if part != codex.parent):
                    raise ValueError("unsafe_transcript")
                descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(descriptor, "rb") as handle:
                    info = os.fstat(handle.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_size > MAX_TRANSCRIPT:
                        raise ValueError("unsafe_transcript")
                    # Capture a bounded prefix while Codex may still be appending.
                    raw = handle.read(info.st_size)
                end = raw.rfind(b"\n") + 1
                raw = raw[:end]
                first = json.loads(raw.split(b"\n", 1)[0])
                metadata = first.get("payload", {})
                if (first.get("type") != "session_meta" or metadata.get("id") != row["id"]
                        or metadata.get("cwd") != str(project)):
                    raise ValueError("transcript_identity_mismatch")
                chunks = []
                for offset in range(0, len(raw), CHUNK_BYTES):
                    chunk = raw[offset:offset + CHUNK_BYTES]
                    digest = hashlib.sha256(chunk).hexdigest()
                    target = objects / (digest + ".chunk")
                    if target.exists():
                        if target.is_symlink() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                            raise ValueError("snapshot_integrity_failed")
                    else:
                        private_write(target, chunk)
                    chunks.append(digest)
                row.update(transcript_status="saved", chunks=chunks, bytes=len(raw),
                           sha256=hashlib.sha256(raw).hexdigest())
            except FileNotFoundError:
                continue
            except (ValueError, OSError, json.JSONDecodeError):
                row["transcript_status"] = "unreadable_or_unsafe"
        content = {"schema_version": 1, "project": str(project), "threads": rows}
        encoded = json.dumps(content, ensure_ascii=False, sort_keys=True, indent=2).encode() + b"\n"
        digest = hashlib.sha256(encoded).hexdigest()
        manifest = manifests / (digest + ".json")
        if not manifest.exists():
            private_write(manifest, encoded)
        elif manifest.is_symlink() or manifest.read_bytes() != encoded:
            raise ValueError("snapshot_integrity_failed")
        return {"status": "saved", "indexed_threads": len(rows),
                "saved_transcripts": sum(row["transcript_status"] == "saved" for row in rows),
                "missing_transcripts": sum(row["transcript_status"] == "missing" for row in rows),
                "unreadable_transcripts": sum(row["transcript_status"] not in ("saved", "missing") for row in rows),
                "snapshot": digest}
    finally:
        os.close(lock)


def verify(destination):
    destination = Path(destination)
    if any(part.is_symlink() for part in [destination, *destination.parents]):
        raise ValueError("unsafe_snapshot_directory")
    for directory in (destination, destination / "objects", destination / "snapshots"):
        if not directory.is_dir() or directory.is_symlink():
            raise ValueError("snapshot_store_unavailable")
    verified = 0
    for manifest in (destination / "snapshots").glob("*.json"):
        raw = manifest.read_bytes()
        if hashlib.sha256(raw).hexdigest() != manifest.stem:
            raise ValueError("snapshot_manifest_corrupt")
        for row in json.loads(raw)["threads"]:
            if row.get("transcript_status") != "saved":
                continue
            full = hashlib.sha256()
            size = 0
            for digest in row["chunks"]:
                if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                    raise ValueError("snapshot_object_invalid")
                target = destination / "objects" / (digest + ".chunk")
                if target.is_symlink():
                    raise ValueError("snapshot_object_corrupt")
                raw = target.read_bytes()
                if hashlib.sha256(raw).hexdigest() != digest:
                    raise ValueError("snapshot_object_corrupt")
                size += len(raw)
                full.update(raw)
            if full.hexdigest() != row["sha256"] or size != row["bytes"]:
                raise ValueError("snapshot_transcript_corrupt")
            verified += 1
    return {"status": "verified", "transcript_references": verified}


def recover(destination, thread_id):
    """Export the most complete retained transcript without editing app account state."""
    destination = Path(destination)
    verify(destination)
    candidates = []
    for manifest in (destination / "snapshots").glob("*.json"):
        for row in json.loads(manifest.read_bytes())["threads"]:
            if row["id"] == thread_id and row.get("transcript_status") == "saved":
                candidates.append(row)
    if not candidates:
        raise ValueError("no_retained_transcript_for_thread")
    row = max(candidates, key=lambda value: value["bytes"])
    directory = destination / "recovered"
    private_directory(directory)
    target = directory / (row["sha256"] + ".jsonl")
    raw = b"".join((destination / "objects" / (digest + ".chunk")).read_bytes()
                   for digest in row["chunks"])
    if not target.exists():
        private_write(target, raw)
    elif target.is_symlink() or target.read_bytes() != raw:
        raise ValueError("recovered_transcript_conflict")
    return {"status": "recovered_private_export", "path": str(target), "bytes": len(raw),
            "codex_database_modified": False}


def install_backup(project=ROOT):
    """Install only the backup job; no app, browser or production service restart."""
    import plistlib

    if sys.platform != "darwin":
        raise ValueError("macos_required")
    uv = shutil.which("uv")
    if not uv:
        raise ValueError("uv_required")
    project = Path(project).resolve()
    snapshot(project)
    label = "com.automated-apply.codex-history"
    target = Path.home() / "Library/LaunchAgents" / (label + ".plist")
    content = plistlib.dumps({"Label": label, "ProgramArguments": [uv, "run", "--no-project",
        "--python", sys.executable, "python", str(project / "scripts/project_continuity.py"),
        "snapshot", "--project", str(project)], "WorkingDirectory": str(project),
        "StartInterval": 300, "RunAtLoad": True, "ProcessType": "Background", "LowPriorityIO": True,
        "Nice": 10, "Umask": 0o077})
    if target.exists():
        if target.is_symlink() or target.read_bytes() != content:
            raise ValueError("existing_backup_job_differs")
    else:
        private_write(target, content)
    result = subprocess.run(["/bin/launchctl", "bootstrap", f"gui/{os.getuid()}", str(target)],
                            capture_output=True, check=False)
    if result.returncode and subprocess.run(["/bin/launchctl", "print", f"gui/{os.getuid()}/{label}"],
                                            capture_output=True, check=False).returncode:
        raise ValueError("backup_job_bootstrap_failed")
    return {"status": "installed", "interval_seconds": 300, "label": label}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("snapshot", "verify", "recover", "resume", "install-backup"))
    parser.add_argument("--project", type=Path, default=ROOT)
    parser.add_argument("--thread-id")
    arguments = parser.parse_args()
    try:
        if arguments.command == "resume":
            print((arguments.project / "docs/project-state.md").read_text())
            return
        if arguments.command == "snapshot":
            result = snapshot(arguments.project)
        elif arguments.command == "verify":
            result = verify(arguments.project / ".local/codex-history")
        elif arguments.command == "recover":
            if not arguments.thread_id:
                raise ValueError("thread_id_required")
            result = recover(arguments.project / ".local/codex-history", arguments.thread_id)
        else:
            result = install_backup(arguments.project)
        print(json.dumps({**result, "at": dt.datetime.now(dt.timezone.utc).isoformat()}))
    except (ValueError, OSError, sqlite3.Error) as error:
        # Never emit raw SQLite rows, transcripts, credentials or environment values.
        code = str(error) if type(error) is ValueError else "continuity_operation_failed"
        print(json.dumps({"status": "failed", "code": code}), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
