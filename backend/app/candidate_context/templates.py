"""Read bounded, owner-selected registry/context files under one explicit root."""

import hashlib
import os
import re
import stat
from pathlib import Path

from backend.app.candidate_context.common import ContextError
from backend.app.candidate_context.configuration import (
    CandidateConfiguration,
    ProjectConfiguration,
)
from backend.app.candidate_context.projects import (
    EvidenceReference,
    FactTopic,
    ProjectFact,
    make_fact,
    suspicious_text,
)

TOPICS: dict[str, FactTopic] = {
    "problem_solved": "overview",
    "business_use_case": "business_use_case",
    "architecture_hld": "architecture",
    "frontend_technology": "frontend",
    "backend_technology": "backend",
    "database": "database",
    "cache": "cache",
    "queue_messaging": "queue",
    "authentication_security": "authentication_security",
    "deployment_infrastructure": "deployment",
    "important_apis": "api",
    "engineering_challenges": "challenge",
    "personal_contribution": "contribution",
    "verified_features": "feature",
    "scaling_design_decisions": "design_decision",
    "measured_outcomes": "measured_outcome",
    "interview_talking_points": "interview",
}


def safe_read(root: Path, relative: str, maximum: int = 128 * 1024) -> str:
    root = root.resolve(strict=True)
    path = root / relative
    if Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ContextError("unsafe_context_path")
    current = path
    while current != root:
        if current.is_symlink():
            raise ContextError("unsafe_context_path")
        current = current.parent
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as file:
            identity = os.fstat(file.fileno())
            if not stat.S_ISREG(identity.st_mode) or identity.st_size > maximum:
                raise ContextError("context_file_missing_or_too_large")
            raw = file.read(maximum + 1)
            if len(raw) > maximum:
                raise ContextError("context_file_missing_or_too_large")
            return raw.decode("utf-8")
    except (OSError, UnicodeError):
        raise ContextError("context_file_unreadable") from None


def safe_yaml(value: str):
    import yaml
    from yaml.tokens import AliasToken, AnchorToken

    if len(value.encode()) > 128 * 1024:
        raise ContextError("context_file_too_large")
    try:
        for index, token in enumerate(yaml.scan(value)):
            if index > 5000:
                raise ContextError("context_yaml_too_complex")
            if isinstance(token, (AliasToken, AnchorToken)):
                raise ContextError("yaml_aliases_not_supported")
        return yaml.safe_load(value)
    except (yaml.YAMLError, RecursionError):
        raise ContextError("invalid_context_yaml") from None


def load_registry(
    root: Path, relative: str = "candidate_context/templates/project_registry.yaml"
) -> tuple[ProjectConfiguration, ...]:
    value = safe_yaml(safe_read(root, relative, 32768))
    if (
        not isinstance(value, dict)
        or set(value) != {"schema_version", "projects"}
        or value["schema_version"] != 1
    ):
        raise ContextError("invalid_project_registry")
    try:
        config = CandidateConfiguration(projects=value["projects"])
        return config.projects
    except (ValueError, TypeError):
        raise ContextError("invalid_project_registry") from None


def load_project_facts(
    root: Path, project: ProjectConfiguration
) -> tuple[ProjectFact, ...]:
    if not project.context_file:
        return ()
    text = safe_read(root, project.context_file)
    match = re.match(r"\A---\n(.*?)\n---(?:\n|$)", text, re.S)
    if not match:
        raise ContextError("project_frontmatter_required")
    data = safe_yaml(match[1])
    if not isinstance(data, dict):
        raise ContextError("invalid_project_context")
    name = data.get("project_name")
    if name and name != project.name:
        raise ContextError("project_template_name_mismatch")
    reference = EvidenceReference(
        file=project.context_file,
        content_sha256=hashlib.sha256(text.encode()).hexdigest(),
        line_end=len(text.splitlines()),
    )
    references = data.get("references", [])
    if not isinstance(references, list) or len(references) > 9:
        raise ContextError("invalid_project_references")
    try:
        evidence = (
            reference,
            *(
                EvidenceReference(**{**reference.model_dump(), "url": url})
                for url in references
            ),
        )
    except ValueError:
        raise ContextError("invalid_project_references") from None
    facts = []
    for field, topic in TOPICS.items():
        value = data.get(field)
        if value in (None, "", []):
            continue
        if not isinstance(value, str) or suspicious_text(value):
            raise ContextError("unsafe_or_invalid_owner_claim")
        facts.append(
            make_fact(
                topic,
                value,
                "owner_supplied",
                evidence,
                personal_claim=field
                in {
                    "personal_contribution",
                    "measured_outcomes",
                    "engineering_challenges",
                },
            )
        )
    return tuple(facts)
