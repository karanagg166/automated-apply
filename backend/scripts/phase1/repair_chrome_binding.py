"""Rebind only this project's owned native host; preserve every credential byte."""
import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def main():
    from backend.app.operations.configuration import load_settings
    from backend.scripts.phase1.install_local import stable_extension_id
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    home = Path.home()
    config = args.env_file
    manifest = home / "Library/Application Support/Google/Chrome/NativeMessagingHosts/com.automated_apply.agent.json"
    wrapper = home / "Library/Application Support/Automated Apply/native-host"
    runtime = home / "Library/Application Support/Automated Apply/phase1-runtime"
    for path in (config, manifest, wrapper):
        if path.is_symlink() or path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
            raise SystemExit("owned_private_installation_required")
    settings = load_settings(str(config))
    document = json.loads(manifest.read_text())
    if (document.get("name") != "com.automated_apply.agent" or document.get("path") != str(wrapper)
            or document.get("type") != "stdio" or document.get("allowed_origins") != [f"chrome-extension://{settings.CHROME_EXTENSION_ID}/"]
            or str(runtime) not in wrapper.read_text() or str(config) not in wrapper.read_text()):
        raise SystemExit("existing_binding_ownership_or_origin_mismatch")
    identity = stable_extension_id(ROOT / "extension")
    if stable_extension_id(runtime / "extension") != identity:
        raise SystemExit("update_owned_runtime_checkout_before_rebinding")
    original = config.read_text()
    matches = re.findall(r"^CHROME_EXTENSION_ID=.*$", original, re.M)
    if len(matches) != 1:
        raise SystemExit("one_existing_extension_identity_required")
    revised = re.sub(r"^CHROME_EXTENSION_ID=.*$", "CHROME_EXTENSION_ID=" + identity, original, flags=re.M)
    changed = revised != original
    if args.apply and changed:
        # Backup contains secrets and remains alongside the private env, never in git.
        backup = config.with_name(config.name + ".before-stable-chrome")
        with backup.open("x") as file:
            backup.chmod(0o600)
            file.write(original)
        for path, content in ((config, revised), (manifest, json.dumps({**document,
                "allowed_origins": [f"chrome-extension://{identity}/"]}, indent=2) + "\n")):
            temporary = path.with_name(path.name + ".stable-tmp")
            with temporary.open("x") as file:
                temporary.chmod(0o600)
                file.write(content)
            temporary.replace(path)
    print(json.dumps({"stable_extension_id": identity, "changed": changed,
        "applied": args.apply and changed, "credentials_changed": False,
        "next_action": "Reload the unpacked extension from the stable runtime directory and restart this project's API."}))


if __name__ == "__main__":
    main()
