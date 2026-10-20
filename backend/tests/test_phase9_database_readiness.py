"""A restricted backend must satisfy an explicit contract, never bypass RLS."""

import copy
import json
import os
import ssl
import subprocess
import sys
from pathlib import Path

import pytest

from backend.app.operations.migrations import MANIFEST, compare_catalog
from backend.app.operations.runtime_security import restricted_manifest
from backend.scripts.check_database import diagnostic_error


def test_hardened_catalog_requires_explicit_contract():
    expected = json.loads(MANIFEST.read_text())
    actual = restricted_manifest(expected)["catalog"]
    assert compare_catalog(actual).status != "verified"
    assert compare_catalog(actual, restricted_runtime=True).status == "verified"
    assert json.loads(MANIFEST.read_text()) == expected


@pytest.mark.parametrize("fault", ["policy_role", "policy_condition", "disabled_rls", "service_grant", "function"])
def test_hardened_catalog_rejects_security_and_definition_drift(fault):
    actual = copy.deepcopy(restricted_manifest(json.loads(MANIFEST.read_text()))["catalog"])
    key = "private_resumes.job_agent_backend"
    if fault == "policy_role":
        actual["policies"][key] = "ALL|{public}|true|true"
    elif fault == "policy_condition":
        actual["policies"][key] = "ALL|{job_agent_runtime}|false|true"
    elif fault == "disabled_rls":
        actual["tables"]["jobs"] = "false"
    elif fault == "service_grant":
        actual["service_grants"]["private_resumes.SELECT"] = "granted"
    else:
        actual["functions"]["candidate_profile_version()"] = "different definition"
    assert compare_catalog(actual, restricted_runtime=True).status != "verified"


def test_schema_with_only_conflicting_functions_is_not_empty():
    assert compare_catalog({"functions": {"conflict()": "unrelated"}}).status != "empty_schema"


@pytest.mark.parametrize("exception,code", [
    (ssl.SSLCertVerificationError("private endpoint"), "database_tls_failed"),
    (ConnectionRefusedError("private endpoint"), "database_network_failed"),
    (RuntimeError("database_runtime_table_permissions_incompatible"), "database_runtime_table_permissions_incompatible"),
    (RuntimeError("postgresql://owner:private@private-host/db"), "database_configuration_connection_or_schema_incompatible"),  # pragma: allowlist secret — fictional redaction fixture
])
def test_database_diagnostics_are_specific_and_redacted(exception, code):
    assert diagnostic_error(exception) == code


@pytest.mark.parametrize("sqlstate,code", [
    ("28P01", "database_authentication_failed"), ("42501", "database_permission_denied"),
])
def test_wrapped_driver_diagnostics(sqlstate, code):
    class DriverError(Exception):
        pass

    original = DriverError("private-password")
    original.sqlstate = sqlstate
    wrapper = RuntimeError("private DSN")
    wrapper.__cause__ = original
    assert diagnostic_error(wrapper) == code


@pytest.mark.skipif(not os.environ.get("PROFILE_TEST_DATABASE_URL"), reason="Isolated localhost PostgreSQL required")
def test_restricted_runtime_postgresql():
    script = Path(__file__).resolve().parents[1] / "scripts/verify_phase9_runtime.py"
    result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
