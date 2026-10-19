"""Catalog presence is not historical migration evidence; drift always remains visible."""

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from backend.app.operations.migrations import MANIFEST, compare_catalog, file_inventory


def manifest():
    return json.loads(MANIFEST.read_text())


def test_manifest_pins_all_nine_migrations():
    expected = manifest()
    assert file_inventory() == expected["migrations"]
    report = compare_catalog(expected["catalog"])
    assert report.status == "verified"
    assert report.history == "untracked_catalog_inference_only"
    assert not report.ddl_executed


@pytest.mark.parametrize("category", ["tables", "columns", "indexes", "constraints", "triggers", "functions", "service_grants"])
def test_partial_catalog_detected(category):
    expected = manifest()
    actual = copy.deepcopy(expected["catalog"])
    key = next(iter(actual[category]))
    del actual[category][key]
    report = compare_catalog(actual)
    assert report.status == "inconsistent_or_partial"
    assert category + ":" + key in report.missing


def test_rls_drift_and_extra_policy_rejected():
    actual = copy.deepcopy(manifest()["catalog"])
    actual["tables"]["candidate_profiles"] = "false"
    actual["policies"]["candidate_profiles.public_read"] = "ALL|{public}|true|true"
    report = compare_catalog(actual)
    assert "tables:candidate_profiles" in report.drift
    assert "policies:unexpected:candidate_profiles.public_read" in report.drift


def test_unsafe_grants_fail_preflight():
    actual = copy.deepcopy(manifest()["catalog"])
    actual["unsafe_grants"] = ["candidate_profiles"]
    assert compare_catalog(actual).status != "verified"


def test_empty_schema_is_not_ready():
    assert compare_catalog({}).status == "empty_schema"


def test_offline_plan_performs_no_ddl():
    result = subprocess.run([sys.executable, "backend/scripts/migration_preflight.py"], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0
    assert json.loads(result.stdout)["ddl_executed"] is False


@pytest.mark.skipif(not os.environ.get("PROFILE_TEST_DATABASE_URL"), reason="Disposable local PostgreSQL required")
def test_phase6b_postgres_catalog_and_readonly():
    path = Path(__file__).resolve().parents[1] / "scripts/verify_phase6b_migration.py"
    result = subprocess.run([sys.executable, str(path)], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr


def test_extra_service_role_grants_cannot_weaken_append_only_history():
    actual = copy.deepcopy(manifest()["catalog"])
    actual["service_grants"]["application_events.DELETE"] = "granted"
    assert "service_grants:unexpected:application_events.DELETE" in compare_catalog(actual).drift
