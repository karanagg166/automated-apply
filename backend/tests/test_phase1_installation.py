"""Private launchd logs must not rely on the launched child's umask."""
import stat

import pytest

from backend.scripts.phase1.install_local import prepare_private_logs


def test_launchd_logs_are_private_and_preserve_existing_content(tmp_path):
    directory = tmp_path / "logs"
    directory.mkdir(mode=0o755)
    previous = directory / "telegram.err.log"
    previous.write_text("sanitized prior service diagnostic\n")
    previous.chmod(0o644)
    prepare_private_logs(directory)
    assert previous.read_text() == "sanitized prior service diagnostic\n"
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    for path in directory.iterdir():
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_launchd_log_symlink_does_not_modify_unrelated_file(tmp_path):
    unrelated = tmp_path / "unrelated"
    unrelated.write_text("preserve")
    unrelated.chmod(0o644)
    directory = tmp_path / "logs"
    directory.mkdir()
    (directory / "telegram.out.log").symlink_to(unrelated)
    with pytest.raises(SystemExit, match="unsafe_log_path_preserved"):
        prepare_private_logs(directory)
    assert unrelated.read_text() == "preserve"
    assert stat.S_IMODE(unrelated.stat().st_mode) == 0o644


def test_launchd_symlink_directory_is_preserved(tmp_path):
    target = tmp_path / "unrelated-logs"
    target.mkdir(mode=0o755)
    directory = tmp_path / "logs"
    directory.symlink_to(target, target_is_directory=True)
    with pytest.raises(SystemExit, match="existing_log_directory_preserved"):
        prepare_private_logs(directory)
    assert not list(target.iterdir())


def test_launchd_hardlink_does_not_change_unrelated_permissions(tmp_path):
    import os
    unrelated = tmp_path / "unrelated"
    unrelated.write_text("preserve")
    unrelated.chmod(0o644)
    directory = tmp_path / "logs"
    directory.mkdir()
    os.link(unrelated, directory / "telegram.out.log")
    with pytest.raises(SystemExit, match="unsafe_log_file_preserved"):
        prepare_private_logs(directory)
    assert stat.S_IMODE(unrelated.stat().st_mode) == 0o644
