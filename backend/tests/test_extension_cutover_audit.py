"""Fixture directories/Chrome preferences; the auditor never edits them."""

import json

import pytest

from backend.scripts import verify_extension_cutover as verifier

SHA = "98965f7607a4714371599fef0143d5e1f8eed25b"


@pytest.mark.parametrize("change", ["clean", "old_path", "missing", "modified", "extra", "symlink"])
def test_exact_artifact_and_saved_profile_path_are_independent(tmp_path, change):
    files, identity = verifier.expected(SHA)
    directory = tmp_path / "extension"
    directory.mkdir()
    for name, data in files.items():
        (directory / name).write_bytes(data)
    profile = tmp_path / "Profile 8"
    profile.mkdir()
    preferences = profile / "Secure Preferences"
    saved_path = tmp_path / "historical" if change == "old_path" else directory
    preferences.write_text(json.dumps({"extensions": {"settings": {identity: {"path": str(saved_path)}}},
                                       "private_fixture": "must not be printed"}))
    original = preferences.read_bytes()
    if change == "missing":
        (directory / "background.js").unlink()
    elif change == "modified":
        (directory / "background.js").write_text("historical code")
    elif change == "extra":
        (directory / "unexpected.js").write_text("unexpected")
    elif change == "symlink":
        target = tmp_path / "mutable.js"
        target.write_bytes(files["background.js"])
        (directory / "background.js").unlink()
        (directory / "background.js").symlink_to(target)
    result = verifier.audit(SHA, directory, profile)
    assert result["disk_matches_sha"] == (change in {"clean", "old_path"})
    assert result["persisted_path_matches_directory"] == (change != "old_path")
    assert result["writes_performed"] == 0 and not result["runtime_reload_verified"]
    assert preferences.read_bytes() == original
    assert "must not be printed" not in json.dumps(result)
    assert str(tmp_path) not in json.dumps(result)


def test_ref_names_are_not_exact_sha_installation_evidence():
    with pytest.raises(ValueError, match="exact_40"):
        verifier.expected("main")
