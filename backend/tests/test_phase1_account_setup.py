"""Account/profile pinning is separate from database credentials and DDL approval."""
import json

import pytest

from backend.scripts.phase1.activate_online_database import (
    APPROVED_BUNDLE,
    check_approval,
    save_private_configuration,
)
from backend.scripts.phase1.inspect_online_database import validate_target
from backend.scripts.phase1.supabase_account import (
    PROFILE,
    PROJECT,
    prepare_profile,
    require_project,
)


def test_exact_management_project_required():
    assert require_project([{"id": PROJECT}], PROJECT)["id"] == PROJECT
    for projects, confirmation in [([], PROJECT), ([{"id": "wrong"}], PROJECT), ([{"id": PROJECT}], "wrong"), ([{"id": PROJECT}, {"id": PROJECT}], PROJECT)]:
        with pytest.raises(ValueError):
            require_project(projects, confirmation)


def test_separate_profile_does_not_touch_default_account(tmp_path):
    old = tmp_path / "supabase-default"
    old.mkdir()
    (old / "profile").write_text("supabase")
    (old / "access-token").write_text("fictional-prior-token")
    before = [(p.name, p.read_bytes()) for p in old.iterdir()]
    path = prepare_profile(tmp_path / "automated-apply")
    assert json.loads(path.read_text()) == PROFILE
    assert path.stat().st_mode & 0o077 == 0
    assert prepare_profile(path.parent) == path
    assert before == [(p.name, p.read_bytes()) for p in old.iterdir()]


def test_unreviewed_profile_and_symlink_preserved(tmp_path):
    base = tmp_path / "separate"
    path = prepare_profile(base)
    path.write_text(json.dumps({**PROFILE, "api_url": "https://attacker.example"}))
    before = path.read_bytes()
    with pytest.raises(ValueError, match="preserved"):
        prepare_profile(base)
    assert path.read_bytes() == before
    link = tmp_path / "link"
    link.symlink_to(base, target_is_directory=True)
    with pytest.raises(ValueError):
        prepare_profile(link)


@pytest.mark.parametrize("host,user", [
    (f"db.{PROJECT}.supabase.co", "postgres"),
    ("aws-1-ap-south-1.pooler.supabase.com", f"postgres.{PROJECT}"),
])
def test_inventory_pins_online_database(host, user):
    validate_target(host, user)


@pytest.mark.parametrize("host,user", [
    ("db.wrong.supabase.co", "postgres"), ("127.0.0.1", "postgres"),
    ("aws-1-ap-south-1.pooler.supabase.com", "postgres.wrong"),
    ("aws-1-ap-south-1.pooler.supabase.com.attacker.example", f"postgres.{PROJECT}"),
])
def test_inventory_rejects_wrong_project_and_host(host, user):
    with pytest.raises(ValueError):
        validate_target(host, user)


def test_activation_requires_exact_owner_approval_and_checksum():
    from pathlib import Path
    content = (Path(__file__).resolve().parents[2] / "supabase/fresh_public/001_phase1_public.sql").read_bytes()
    check_approval(True, PROJECT, APPROVED_BUNDLE, content)
    for approval, project, checksum, data in [(False, PROJECT, APPROVED_BUNDLE, content),
            (True, "wrong", APPROVED_BUNDLE, content), (True, PROJECT, "wrong", content),
            (True, PROJECT, APPROVED_BUNDLE, content + b"\n")]:
        with pytest.raises(ValueError):
            check_approval(approval, project, checksum, data)


def test_runtime_config_update_preserves_existing_credentials(tmp_path):
    from dotenv import dotenv_values
    path = tmp_path / "private.env"
    path.write_text('EXISTING_KEY="fictional-preserved-secret"\nGMAIL_SENDING_ENABLED="false"\nDATABASE_URL="old-fictional-uri"\n')
    path.chmod(0o600)
    save_private_configuration(path, {"DATABASE_URL": "new-fictional-runtime-uri"})
    values = dotenv_values(path)
    assert values["EXISTING_KEY"] == "fictional-preserved-secret"
    assert values["GMAIL_SENDING_ENABLED"] == "false"
    assert values["DATABASE_URL"] == "new-fictional-runtime-uri"
    assert path.stat().st_mode & 0o077 == 0
    link = tmp_path / "link.env"
    link.symlink_to(path)
    with pytest.raises(ValueError):
        save_private_configuration(link, {"EXISTING_KEY": "must-not-write"})
    assert dotenv_values(path)["EXISTING_KEY"] == "fictional-preserved-secret"
