"""Shared HTTP boundary metadata; generated package-local data ships in backend images."""

import json
import re
from pathlib import Path

POLICY = json.loads(
    Path(__file__).with_name("http-security.generated.json").read_text()
)
if POLICY.get("schema_version") != 1:
    raise RuntimeError("unsupported_http_policy_version")
PRIVATE_PREFIXES = tuple(POLICY["private_prefixes"])
CALLBACKS = frozenset(POLICY["unauthenticated_callbacks"])
APPROVAL_PATTERNS = tuple(re.compile(pattern) for pattern in POLICY["owner_approval"])


def application_request(path: str) -> bool:
    return (
        path.startswith(tuple(POLICY["application_prefixes"]))
        or POLICY["application_path_fragment"] in path
    )


def maximum_body_bytes(path: str) -> int:
    limits = POLICY["request_limits"]
    if path == "/api/v1/dashboard/resumes":
        return limits["resume"]
    if path == "/api/v1/local-agent/chrome":
        return limits["chrome"]
    return limits["application"] if application_request(path) else limits["default"]


def requires_owner_approval(path: str, method: str) -> bool:
    relative = path.removeprefix("/api/v1/")
    return method == "POST" and any(p.fullmatch(relative) for p in APPROVAL_PATTERNS)
