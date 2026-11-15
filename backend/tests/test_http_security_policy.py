"""Packaging drift and owner-approval coverage across the actual registered API."""

import json
from pathlib import Path
from uuid import UUID

from fastapi.routing import APIRoute, iter_route_contexts

from backend.app.browser.owner_approval import require_owner_approval
from backend.app.core.http_policy import maximum_body_bytes, requires_owner_approval
from backend.app.main import app

ROOT = Path(__file__).resolve().parents[2]


def test_packaged_http_policies_match_authoritative_contract():
    canonical = json.loads((ROOT / "contracts/http-security.json").read_text())
    for path in (
        "backend/app/core/http-security.generated.json",
        "frontend/src/lib/http-security.generated.json",
    ):
        assert json.loads((ROOT / path).read_text()) == canonical


def test_registered_owner_approval_dependencies_match_shared_contract():
    observed = 0
    for context in iter_route_contexts(app.routes):
        route = context.original_route
        if not isinstance(route, APIRoute):
            continue
        sample = context.path
        for parameter in route.param_convertors:
            sample = sample.replace("{" + parameter + "}", str(UUID(int=1)))
        guarded = any(
            d.call is require_owner_approval for d in route.dependant.dependencies
        )
        for method in route.methods:
            assert requires_owner_approval(sample, method) == guarded, (
                route.path,
                method,
            )
        observed += guarded
    assert observed == 8


def test_request_body_classes_cover_sensitive_and_nested_application_routes():
    assert maximum_body_bytes("/api/v1/dashboard/resumes") == 5 * 1024 * 1024
    assert maximum_body_bytes("/api/v1/local-agent/chrome") == 256 * 1024
    for path in (
        "/api/v1/browser-applications",
        "/api/v1/application-packets/a/review",
        "/api/v1/jobs/a/application-preview",
        "/api/v1/application-answers/generate",
    ):
        assert maximum_body_bytes(path) == 64 * 1024
    assert maximum_body_bytes("/api/v1/discovery/runs") == 1024 * 1024


def test_static_job_search_precedes_uuid_detail_route():
    paths = [context.path for context in iter_route_contexts(app.routes)]
    assert paths.index("/api/v1/jobs/search") < paths.index("/api/v1/jobs/{job_id}")
