import json
import plistlib
from pathlib import Path

import pytest

from rust.scripts import local_install_plan as install
from rust.scripts import local_release as release
from rust.scripts import local_rollback as rollback

COMMIT = "1" * 40


@pytest.fixture
def build(tmp_path):
    manifest = (release.ROOT / "extension/manifest.json").read_bytes()
    version = json.loads(manifest)["version"]
    for name, source in release.ARTIFACTS.items():
        path = tmp_path / source
        path.parent.mkdir(parents=True, exist_ok=True)
        if name.startswith("extension/"):
            browser = Path(name).name
            path.mkdir()
            (path / "manifest.json").write_bytes(manifest)
            (path / "build-info.json").write_text(
                json.dumps(
                    {
                        "browser": browser,
                        "native_host": f"com.automated_apply.{browser}",
                        "extension_id": release.STABLE_EXTENSION_ID,
                        "version": version,
                        "files": ["manifest.json"],
                    }
                )
            )
        elif name.endswith("/standalone"):
            (path / ".next/static").mkdir(parents=True)
            (path / "server.js").write_text("fixture server")
            (path / ".next/BUILD_ID").write_text("fixture-build-id")
            (path / "internal-link").symlink_to("server.js")
        else:
            path.write_text("fixture artifact")
            if name.startswith("bin/"):
                path.chmod(0o700)
    return tmp_path


def test_release_staging_verifies_copies_and_preserves_existing_release(build):
    tested = {"commit": COMMIT, **release.inventory(build)}
    releases = build / "private-releases"
    release.stage(build, releases, tested)
    installed = releases / ("rust-" + COMMIT)
    assert release.private_json(installed / "release-manifest.json") == tested
    assert (installed / "frontend/.next/standalone/internal-link").readlink() == Path(
        "server.js"
    )
    release.stage(build, releases, tested)
    (installed / "bin/automated-apply-agents").write_text("changed staged bytes")
    with pytest.raises(release.ReleaseError, match="existing_local_release_preserved"):
        release.stage(build, releases, tested)
    assert (
        installed / "bin/automated-apply-agents"
    ).read_text() == "changed staged bytes"


def test_release_stage_refuses_source_changed_after_combined_run(build):
    tested = {"commit": COMMIT, **release.inventory(build)}
    (build / "target/release/automated-apply-native").write_text("different build")
    releases = build / "private-releases"
    with pytest.raises(
        release.ReleaseError, match="build_output_changed_since_acceptance"
    ):
        release.stage(build, releases, tested)
    assert not (releases / ("rust-" + COMMIT)).exists()


def test_inventory_rejects_external_symlink_and_private_config(build):
    standalone = build / "frontend/.next/standalone"
    link = standalone / "external"
    link.symlink_to(build / "target/release/automated-apply-agents")
    with pytest.raises(release.ReleaseError, match="external_build_symlink"):
        release.inventory(build)
    link.unlink()
    (standalone / ".env.production.local").write_text("FICTIONAL=secret")
    with pytest.raises(
        release.ReleaseError, match="private_configuration_in_build_output"
    ):
        release.inventory(build)


def test_release_evidence_requires_every_stage_and_same_clean_commit(build):
    steps = [
        {"name": name, "status": "PASS", "exit_code": 0} for name, _ in release.STAGES
    ]
    stamp = {"commit": COMMIT, "clean": True}
    evidence = {
        "scope": "local_fixture_acceptance_not_live_platform_acceptance",
        "source_before": stamp,
        "source_after": stamp,
        "clean_commit_fixture_pass": True,
        "stages": steps,
    }
    artifacts = release.inventory(build)
    for filename, data in (
        ("results.json", evidence),
        ("release-artifacts.private.log", {"commit": COMMIT, "artifacts": artifacts}),
    ):
        path = build / filename
        path.write_text(json.dumps(data))
        path.chmod(0o600)
    assert release.tested_candidate(build) == {"commit": COMMIT, **artifacts}

    result = build / "results.json"
    result.write_text(json.dumps({**evidence, "stages": steps[1:]}))
    with pytest.raises(
        release.ReleaseError, match="clean_combined_release_evidence_required"
    ):
        release.tested_candidate(build)
    result.write_text(
        json.dumps({**evidence, "source_after": {**stamp, "clean": False}})
    )
    with pytest.raises(
        release.ReleaseError, match="clean_combined_release_evidence_required"
    ):
        release.tested_candidate(build)


def test_rollback_copies_definitions_and_detects_changed_runtime_input(tmp_path):
    home = tmp_path / "home"
    backup = tmp_path / "backup"
    backup.mkdir()
    launcher = home / "Library/LaunchAgents/com.automated-apply.api.plist"
    launcher.parent.mkdir(parents=True)
    runtime = home / "runtime"
    runtime.write_text("saved runtime bytes")
    launcher.write_bytes(
        plistlib.dumps(
            {
                "Label": "com.automated-apply.api",
                "ProgramArguments": [str(runtime)],
                "WorkingDirectory": str(home),
            }
        )
    )
    result = rollback.snapshot(home, backup)
    assert result["definitions_saved"] == 1
    assert result["references_checked"] == 2
    assert result["missing_references"] == 0
    manifest = release.private_json(backup / "rollback-inventory.json")
    row = next(row for row in manifest["definitions"] if row.get("backup"))
    copy = backup / row["backup"]
    assert copy.read_bytes() == launcher.read_bytes()

    runtime.write_text("different runtime bytes")
    with pytest.raises(
        release.ReleaseError, match="rollback_reference_changed_since_snapshot"
    ):
        rollback.verify(backup, compare_installed=False)
    runtime.write_text("saved runtime bytes")
    launcher.write_text("different definition")
    assert rollback.verify(backup, compare_installed=False)["definitions_saved"] == 1
    with pytest.raises(
        release.ReleaseError, match="installed_definition_changed_since_snapshot"
    ):
        rollback.verify(backup, compare_installed=True)
    copy.write_text("different backup bytes")
    with pytest.raises(release.ReleaseError, match="rollback_definition_copy_mismatch"):
        rollback.verify(backup, compare_installed=False)


def test_cutover_plan_keeps_runtime_and_configuration_pinned(tmp_path, monkeypatch):
    node = tmp_path / "node"
    runtime = tmp_path / "runtime.env"
    frontend = tmp_path / "frontend.env"
    release_dir = tmp_path / "candidate"
    plan = tmp_path / "plan"
    plan.mkdir()
    logs = tmp_path / "logs"
    calls = []

    def check(arguments):
        calls.append(arguments)
        if arguments[-1] == "--check-config":
            return b""
        (plan / install.NATIVE_CONFIG).write_text("fictional companion config")
        return json.dumps(
            {
                "extension_id": release.STABLE_EXTENSION_ID,
                "fixture": False,
                "telegram_enabled": False,
            }
        ).encode()

    monkeypatch.setattr(install, "local_check", check)
    install.render(release_dir, plan, (runtime, frontend), node, 3000, logs=logs)
    assert calls[0][0] == node
    daemon = release_dir / "bin/automated-apply-agents"
    assert calls[1][:4] == (daemon, "prepare-native-config", "--config", runtime)
    with (plan / "com.automated-apply.rust.plist").open("rb") as file:
        definition = plistlib.load(file)
    assert definition["ProgramArguments"] == [
        str(daemon),
        "serve",
        "--config",
        str(runtime),
    ]
    assert definition["StandardOutPath"] == str(logs / "rust.out.log")
    assert definition["StandardErrorPath"] == str(logs / "rust.err.log")
    with (plan / "com.automated-apply.frontend.plist").open("rb") as file:
        dashboard = plistlib.load(file)
    assert dashboard["ProgramArguments"][0] == str(node)
    assert dashboard["ProgramArguments"][2:6] == [
        "--frontend-config",
        str(frontend),
        "--runtime-config",
        str(runtime),
    ]
    assert dashboard["StandardOutPath"] == str(logs / "frontend.out.log")
    assert dashboard["StandardErrorPath"] == str(logs / "frontend.err.log")
    for filename in ("rust.out.log", "rust.err.log", "frontend.out.log", "frontend.err.log"):
        log_path = logs / filename
        assert log_path.is_file()
        assert log_path.stat().st_mode & 0o777 == 0o600
        assert install.prepare_private_log(logs, filename) == log_path
    symlink_log = logs / "symlink.out.log"
    symlink_log.symlink_to(logs / "rust.out.log")
    with pytest.raises(release.ReleaseError, match="private_log_path_unavailable"):
        install.prepare_private_log(logs, "symlink.out.log")
    for browser in ("brave", "edge"):
        manifest = json.loads(
            (plan / f"com.automated_apply.{browser}.json").read_text()
        )
        assert manifest["allowed_origins"] == [
            f"chrome-extension://{release.STABLE_EXTENSION_ID}/"
        ]
        assert manifest["path"] == str(release_dir / "bin/automated-apply-native")


def test_cutover_plan_rejects_telegram_by_default(tmp_path, monkeypatch):
    node = tmp_path / "node"
    runtime = tmp_path / "runtime.env"
    frontend = tmp_path / "frontend.env"
    release_dir = tmp_path / "candidate"
    plan = tmp_path / "plan"
    plan.mkdir()
    logs = tmp_path / "logs"

    def check(arguments):
        if arguments[-1] == "--check-config":
            return b""
        (plan / install.NATIVE_CONFIG).write_text("fictional companion config")
        return json.dumps(
            {
                "extension_id": release.STABLE_EXTENSION_ID,
                "fixture": False,
                "telegram_enabled": True,
            }
        ).encode()

    monkeypatch.setattr(install, "local_check", check)
    with pytest.raises(
        release.ReleaseError, match="production_native_configuration_required"
    ):
        install.render(release_dir, plan, (runtime, frontend), node, 3000, logs=logs)


def test_cutover_plan_allows_telegram_when_legacy_plist_absent(tmp_path, monkeypatch):
    node = tmp_path / "node"
    runtime = tmp_path / "runtime.env"
    frontend = tmp_path / "frontend.env"
    release_dir = tmp_path / "candidate"
    plan = tmp_path / "plan"
    plan.mkdir()
    logs = tmp_path / "logs"
    launch_agents = tmp_path / "LaunchAgents"
    launch_agents.mkdir()
    (launch_agents / "com.automated-apply.telegram.plist.disabled").write_text("disabled")

    def check(arguments):
        if arguments[-1] == "--check-config":
            return b""
        (plan / install.NATIVE_CONFIG).write_text("fictional companion config")
        return json.dumps(
            {
                "extension_id": release.STABLE_EXTENSION_ID,
                "fixture": False,
                "telegram_enabled": True,
            }
        ).encode()

    monkeypatch.setattr(install, "local_check", check)
    assert (
        install.render(
            release_dir,
            plan,
            (runtime, frontend),
            node,
            3000,
            logs=logs,
            allow_telegram=True,
            launch_agents_dir=launch_agents,
        )
        is True
    )


def test_cutover_plan_rejects_telegram_when_legacy_plist_active(tmp_path, monkeypatch):
    node = tmp_path / "node"
    runtime = tmp_path / "runtime.env"
    frontend = tmp_path / "frontend.env"
    release_dir = tmp_path / "candidate"
    plan = tmp_path / "plan"
    plan.mkdir()
    logs = tmp_path / "logs"
    launch_agents = tmp_path / "LaunchAgents"
    launch_agents.mkdir()
    (launch_agents / "com.automated-apply.telegram.plist").write_text("active")

    def check(arguments):
        if arguments[-1] == "--check-config":
            return b""
        (plan / install.NATIVE_CONFIG).write_text("fictional companion config")
        return json.dumps(
            {
                "extension_id": release.STABLE_EXTENSION_ID,
                "fixture": False,
                "telegram_enabled": True,
            }
        ).encode()

    monkeypatch.setattr(install, "local_check", check)
    with pytest.raises(release.ReleaseError, match="legacy_telegram_service_active"):
        install.render(
            release_dir,
            plan,
            (runtime, frontend),
            node,
            3000,
            logs=logs,
            allow_telegram=True,
            launch_agents_dir=launch_agents,
        )
