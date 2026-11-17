"""Privately preserve installed macOS definitions and verify their rollback inputs."""

import argparse
import hashlib
import json
import os
import plistlib
import stat
import tempfile
from pathlib import Path

from rust.scripts.local_release import ROOT, ReleaseError, private_json

BACKUPS = ROOT / ".local/runtime-support/upgrade-backups"
SERVICES = ("api", "execution", "frontend", "telegram", "rust")
NATIVE = {
    "Google/Chrome": ("agent", "brave"),
    "BraveSoftware/Brave-Browser": ("brave",),
    "Microsoft Edge": ("edge",),
}


def definitions(home):
    library = home / "Library"
    for service in SERVICES:
        for suffix in ("", ".disabled"):
            yield library / f"LaunchAgents/com.automated-apply.{service}.plist{suffix}"
    for browser, hosts in NATIVE.items():
        for host in hosts:
            yield (
                library
                / f"Application Support/{browser}/NativeMessagingHosts/com.automated_apply.{host}.json"
            )


def path_stamp(path):
    if not path.exists() and not path.is_symlink():
        return {"kind": "absent"}
    target = path.resolve(strict=True)
    info = target.stat()
    record = {"path": str(target), "mode": info.st_mode & 0o777}
    if stat.S_ISDIR(info.st_mode):
        return {**record, "kind": "directory"}
    if not stat.S_ISREG(info.st_mode):
        raise ReleaseError("unsupported_rollback_reference_type")
    with target.open("rb") as file:
        checksum = hashlib.file_digest(file, "sha256").hexdigest()
    return {**record, "kind": "file", "sha256": checksum}


def snapshot(home, backup):
    files = backup / "definitions"
    files.mkdir(mode=0o700)
    saved = []
    inputs = set()
    for path in definitions(home):
        record = {"installed": str(path), "stamp": path_stamp(path)}
        saved.append(record)
        if record["stamp"]["kind"] == "absent":
            continue
        info = path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_size > 262144
        ):
            raise ReleaseError("unsupported_installed_definition")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != record["stamp"]["sha256"]:
            raise ReleaseError("installed_definition_changed_during_snapshot")
        local = files / f"{len(saved):02d}-{path.name}"
        with local.open("xb") as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(raw)
        record["backup"] = str(local.relative_to(backup))
        if path.suffix == ".json":
            document = json.loads(raw)
            if document["name"] != path.stem:
                raise ReleaseError("native_registration_name_mismatch")
            native = Path(document["path"])
            if not native.is_absolute():
                raise ReleaseError("invalid_native_rollback_reference")
            inputs.add(native)
            adjacent = native.with_name("automated-apply-native.private.env")
            if adjacent.exists():
                inputs.add(adjacent)
        else:
            document = plistlib.loads(raw)
            if document["Label"] != path.name.split(".plist")[0]:
                raise ReleaseError("launch_definition_label_mismatch")
            for value in (
                document.get("WorkingDirectory"),
                document.get("Program"),
                *document.get("ProgramArguments", ()),
            ):
                if isinstance(value, str) and value.startswith("/"):
                    inputs.add(Path(value))
    support = home / "Library/Application Support/Automated Apply"
    # The legacy Python dashboard reads this private file inside its launcher.
    if (support / "frontend.private.env").exists():
        inputs.add(support / "frontend.private.env")
    manifest = {
        "definitions": saved,
        "references": {str(path): path_stamp(path) for path in sorted(inputs)},
    }
    with (backup / "rollback-inventory.json").open("x") as file:
        os.fchmod(file.fileno(), 0o600)
        json.dump(manifest, file, indent=2)
        file.write("\n")
    return verify(backup, compare_installed=True)


def verify(backup, *, compare_installed):
    manifest = private_json(backup / "rollback-inventory.json")
    saved = 0
    for definition in manifest["definitions"]:
        expected = definition["stamp"]
        if compare_installed and path_stamp(Path(definition["installed"])) != expected:
            raise ReleaseError("installed_definition_changed_since_snapshot")
        if "backup" not in definition:
            continue
        local = backup / definition["backup"]
        copy = path_stamp(local)
        if (
            local.is_symlink()
            or not local.resolve().is_relative_to(backup.resolve())
            or copy["kind"] != "file"
            or copy["mode"] != 0o600
            or local.stat().st_uid != os.getuid()
            or copy["sha256"] != expected["sha256"]
        ):
            raise ReleaseError("rollback_definition_copy_mismatch")
        saved += 1
    missing = 0
    for original, expected in manifest["references"].items():
        if path_stamp(Path(original)) != expected:
            raise ReleaseError("rollback_reference_changed_since_snapshot")
        missing += expected["kind"] == "absent"
    return {
        "backup": backup.name,
        "definitions_saved": saved,
        "references_checked": len(manifest["references"]),
        "missing_references": missing,
        "installed_definitions_compared": compare_installed,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("snapshot", "verify"))
    parser.add_argument("backup", nargs="?")
    parser.add_argument("--compare-installed", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.action == "snapshot" and not args.backup:
            BACKUPS.mkdir(parents=True, exist_ok=True)
            backup = Path(tempfile.mkdtemp(prefix="rust-preinstall-", dir=BACKUPS))
            result = snapshot(Path.home(), backup)
        elif (
            args.action == "verify"
            and (args.backup or "").startswith("rust-preinstall-")
            and Path(args.backup).name == args.backup
        ):
            result = verify(
                BACKUPS / args.backup, compare_installed=args.compare_installed
            )
        else:
            raise ReleaseError("exact_rollback_snapshot_required")
        print(json.dumps(result))
    except ReleaseError as error:
        raise SystemExit(str(error)) from None
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        RuntimeError,
        plistlib.InvalidFileException,
    ):
        raise SystemExit("rollback_inventory_could_not_be_verified") from None


if __name__ == "__main__":
    main()
