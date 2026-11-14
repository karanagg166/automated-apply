"""AST-only legacy saved-link oracle; no settings, network or ORM initialization."""
import argparse
import ast
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from pydantic import TypeAdapter, ValidationError

from backend.app.core.urls import PublicHTTPSURL
from backend.app.schemas.candidate_resources import ResolvedLink
from rust.scripts.resume_corpus import extract

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    check = parser.parse_args().check
    scope = dict(TypeAdapter=TypeAdapter, ValidationError=ValidationError, PublicHTTPSURL=PublicHTTPSURL, ResolvedLink=ResolvedLink, Settings=object, STANDARD_FIELDS={"github": "github_url", "linkedin": "linkedin_url", "portfolio": "portfolio_url"})
    path = "backend/app/services/profile_link_resolver.py"
    tree = ast.parse((ROOT / path).read_text())
    constants = [node for node in tree.body if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in {"ALIASES", "ENV_FIELDS"}]
    exec(compile(ast.Module(body=constants, type_ignores=[]), path, "exec"), scope)
    extract(path, ["ProfileLinkResolver"], scope)
    base_profile = {"version": 1, "github_url": None, "linkedin_url": None, "portfolio_url": None}
    profiles = [base_profile, {**base_profile, "version": 4}, {**base_profile, "github_url": "https://github.com/fictional"}, {**base_profile, "github_url": "http://github.com/fictional"}]
    base = {"id": "10000000-0000-0000-0000-000000000001", "resource_type": "resume", "label": "Fictional resume", "url": "https://example.com/saved", "user_confirmed": True, "is_primary": True, "source_type": "user", "updated_at": "2026-11-14T00:00:00Z"}
    groups = [[], [base], [{**base, "user_confirmed": False}], [{**base, "url": "private-resume:20000000-0000-0000-0000-000000000001", "source_type": "private_upload"}], [base, {**base, "id": "10000000-0000-0000-0000-000000000002", "is_primary": False}], [{**base, "is_primary": False}, {**base, "id": "10000000-0000-0000-0000-000000000002", "is_primary": False}], [{**base, "resource_type": "github"}]]
    cases = []
    for profile in profiles:
        for resources in groups:
            for configured in [False, True]:
                defaults = {kind: "https://example.com/default-" + kind for kind in scope["ENV_FIELDS"]} if configured else {}
                settings = SimpleNamespace(**{scope["ENV_FIELDS"][kind]: value for kind, value in defaults.items()})
                resolver = scope["ProfileLinkResolver"](SimpleNamespace(**profile), [SimpleNamespace(**{**r, "id": UUID(r["id"])}) for r in resources], settings)
                cases.append({"profile": profile, "resources": resources, "defaults": defaults, "output": [resolver.resolved(kind).model_dump(mode="json") for kind in scope["ALIASES"]]})
    path = ROOT / "rust/agent-runtime/tests/fixtures/link-corpus.json"
    encoded = json.dumps(cases, ensure_ascii=False, indent=2) + "\n"
    if check:
        if path.read_text() != encoded:
            raise SystemExit("link_corpus_drift")
    else:
        path.write_text(encoded)
    print(f"fictional_link_cases:{len(cases)} per_case_types:9")


if __name__ == "__main__":
    main()
