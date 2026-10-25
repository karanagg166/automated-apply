"""Fictional configuration contracts only; no environment or account reads."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.candidate_context.common import ContextError
from backend.app.candidate_context.configuration import (
    CandidateConfiguration,
    ProfileLinks,
    ProjectConfiguration,
    ResumeSource,
    configuration_change,
    configuration_from_environment,
    drive_identity,
    seed_missing_environment,
)
from backend.app.candidate_context.templates import (
    load_project_facts,
    load_registry,
    safe_yaml,
)


def test_empty_configuration_has_only_missing_facts_and_default_priorities():
    config = CandidateConfiguration()
    assert config.resume is None
    assert all(
        value is None or value == []
        for value in config.links.model_dump(mode="json").values()
    )
    assert [p.priority for p in config.projects] == [1, 2, 3]
    assert all(
        not p.name and not p.tech_stack and p.repository_url is None
        for p in config.projects
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://example.org",
        "https://127.0.0.1/a",
        "https://user:pass@example.org",  # pragma: allowlist secret -- rejected fictional credential URL
        "https://localhost/a",
        "file:///etc/passwd",
        "https://169.254.169.254/a",
        "https://example.org:8443/a",
    ],
)
def test_unsafe_profile_urls_rejected(url):
    with pytest.raises(ValidationError):
        ProfileLinks(codechef=url)


def test_serialization_and_change_audit_does_not_include_link_values():
    previous = CandidateConfiguration()
    current = CandidateConfiguration(
        links=ProfileLinks(codechef="https://example.org/fictional")
    )
    audit = configuration_change(
        previous, current, source="owner_dashboard", actor_ref="fictional-owner"
    )
    assert audit.changed_fields == ("links",)
    assert audit.previous_hash != audit.current_hash
    assert "https://" not in audit.model_dump_json()
    assert (
        CandidateConfiguration.model_validate_json(current.model_dump_json()) == current
    )


def test_environment_seeding_preserves_nonempty_values_without_mutation():
    original = {
        "CANDIDATE_GITHUB_URL": "https://github.com/fictional-owner",
        "PROJECT_01_NAME": "Owner value",
        "BLANK": " ",
    }
    result = seed_missing_environment(
        original,
        {
            "CANDIDATE_GITHUB_URL": "",
            "PROJECT_01_NAME": "",
            "BLANK": "default",
            "NEW": "",
        },
    )
    assert result["PROJECT_01_NAME"] == "Owner value" and result["BLANK"] == "default"
    assert original["BLANK"] == " " and "NEW" not in original


def test_existing_environment_names_and_no_hardcoded_personal_data():
    config = configuration_from_environment(
        {
            "CANDIDATE_ORIGINAL_LINKEDIN_URL": "https://www.linkedin.com/in/fictional",
            "PROJECT_02_PRIORITY": "4",
        }
    )
    assert str(config.links.linkedin).endswith("/fictional")
    assert config.projects[1].priority == 4
    assert configuration_from_environment({}).resume is None


def test_resume_requires_separately_bound_account_and_exact_source_identity():
    with pytest.raises(ValidationError):
        configuration_from_environment(
            {"CANDIDATE_RESUME_DRIVE_FILE_ID": "fictional_drive_pdf_001"}
        )
    config = configuration_from_environment(
        {
            "CANDIDATE_RESUME_DRIVE_FILE_ID": "fictional_drive_pdf_001",
            "RESUME_DRIVE_ACCOUNT_REF": "fictional-account",
            "RESUME_DRIVE_SYNC_INTERVAL_HOURS": "6",
        }
    )
    assert config.resume.interval_minutes == 360
    assert not config.resume.auto_sync_enabled


@pytest.mark.parametrize(
    "url",
    [
        "https://drive.google.com/open?id=fictional_drive_pdf_001",
        "https://drive.google.com/file/d/fictional_drive_pdf_001/view?authuser=1",
        "https://drive.google.com.evil.example/file/d/fictional_drive_pdf_001/view",
        "https://drive.google.com/file/d/fictional_drive_pdf_001/view#fragment",
        "https://docs.google.com/document/d/fictional_drive_pdf_001/edit",
    ],
)
def test_unsupported_sharing_links_rejected(url):
    with pytest.raises(ValueError):
        drive_identity(url)


def test_drive_identity_normalizes_supported_url_and_rejects_mismatched_id():
    assert drive_identity(
        "https://drive.google.com/file/d/fictional_drive_pdf_001/view?usp=sharing"
    )[1].endswith("/view")
    with pytest.raises(ValueError):
        ResumeSource(
            canonical_url="https://drive.google.com/file/d/fictional_drive_pdf_001/view",
            file_id="fictional_drive_pdf_002",
            account_ref="fictional-account",
        )


def test_duplicate_priorities_and_ids_rejected_and_additional_projects_supported():
    projects = [
        ProjectConfiguration(id=f"project-{i}", priority=i) for i in range(1, 8)
    ]
    assert len(CandidateConfiguration(projects=tuple(projects)).projects) == 7
    with pytest.raises(ValidationError, match="duplicate_project_priority"):
        CandidateConfiguration(
            projects=(projects[0], projects[1].model_copy(update={"priority": 1}))
        )
    with pytest.raises(ValidationError, match="duplicate_project_id"):
        CandidateConfiguration(
            projects=(projects[0], projects[0].model_copy(update={"priority": 2}))
        )


@pytest.mark.parametrize(
    "value",
    [
        "/tmp/project.md",
        "candidate_context/../secrets/private.md",
        "candidate_context/x.txt",
        "candidate_context\\x.md",
    ],
)
def test_unsafe_context_paths_rejected(value):
    with pytest.raises(ValidationError):
        ProjectConfiguration(id="project-test", priority=1, context_file=value)


def test_empty_templates_are_unapproved_and_do_not_generate_claims():
    root = Path(__file__).resolve().parents[2]
    registry = load_registry(root)
    assert len(registry) == 3
    assert all(load_project_facts(root, project) == () for project in registry)
    for project in registry:
        text = (root / project.context_file).read_text()
        assert "human_approval_status: unapproved" in text


def test_yaml_aliases_and_symlinked_templates_rejected(tmp_path):
    with pytest.raises(ContextError, match="aliases"):
        safe_yaml("x: &x [1]\ny: *x")
    (tmp_path / "candidate_context").mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("---\nproject_name: ''\n---\n")
    (tmp_path / "candidate_context/project.md").symlink_to(outside)
    project = ProjectConfiguration(
        id="project-test", priority=1, context_file="candidate_context/project.md"
    )
    with pytest.raises(ContextError, match="unsafe_context_path"):
        load_project_facts(tmp_path, project)
