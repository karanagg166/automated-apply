"""Optional runtime overlay cannot weaken the existing public catalog contract."""

import json
from copy import deepcopy

import pytest

from backend.app.operations import rust_schema


def test_absent_runtime_preserves_existing_manifest_without_loading_optional_files(monkeypatch, tmp_path):
    monkeypatch.setattr(rust_schema, "MANIFEST", tmp_path / "missing.json")
    expected = {"tables": {"existing": "true"}}
    assert rust_schema.expected_overlay(expected, {"tables": {"existing": "true"}}) is expected


def test_partial_runtime_is_rejected_before_catalog_merge():
    with pytest.raises(RuntimeError, match="rust_runtime_schema_partial_install"):
        rust_schema.expected_overlay({}, {"tables": {"rust_agent_runs": "true"}})


def test_complete_runtime_overlay_preserves_all_existing_objects():
    expected = {"tables": {"existing": "true"}, "constraints": {"existing.check": "pinned"}}
    original = deepcopy(expected)
    actual = {"tables": dict.fromkeys(rust_schema.TABLES, "true")}
    result = rust_schema.expected_overlay(expected, actual)
    assert result["tables"]["existing"] == "true"
    assert result["constraints"]["existing.check"] == "pinned"
    assert set(result["tables"]) == {"existing", *rust_schema.TABLES}
    assert expected == original


def test_changed_review_package_cannot_be_recognized_as_the_pinned_install(monkeypatch, tmp_path):
    package = tmp_path / "changed.sql"
    package.write_text("unreviewed SQL")
    monkeypatch.setattr(rust_schema, "PACKAGE", package)
    with pytest.raises(RuntimeError, match="rust_runtime_schema_reverification_required"):
        rust_schema.expected_overlay({}, {"tables": dict.fromkeys(rust_schema.TABLES, "true")})


def test_existing_namespace_collision_cannot_be_silently_overwritten():
    with pytest.raises(RuntimeError, match="rust_runtime_schema_namespace_collision"):
        rust_schema.expected_overlay({"tables": {"rust_agent_runs": "unrelated"}},
                                     {"tables": dict.fromkeys(rust_schema.TABLES, "true")})


def test_packaged_audit_tables_have_their_exact_restricted_catalog_shape():
    manifest = json.loads(rust_schema.MANIFEST.read_text())
    assert manifest["catalog"]["unsafe_grants"] == []
    assert set(manifest["catalog"]["tables"]) == rust_schema.TABLES
    for name in rust_schema.TABLES:
        assert manifest["catalog"]["policies"][name + ".job_agent_backend"] == "ALL|{job_agent_runtime}|true|true"
