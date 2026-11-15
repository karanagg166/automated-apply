"""Execute actual adapter definitions on fictional URLs with an injected clock/policy."""
import argparse
import ast
import json
import re
import sys
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from pydantic import TypeAdapter, ValidationError

from backend.app.core.job_urls import ats_job_url
from backend.app.core.urls import PublicHTTPSURL
from rust.scripts.packet_contract_corpus import packet_models

ROOT = Path(__file__).resolve().parents[2]


def oracle():
    scope = packet_models()
    instant = datetime(2026, 11, 15, 12, tzinfo=timezone.utc)

    class Clock(datetime):
        @classmethod
        def now(cls, _zone=None):
            return instant

    scope.update(re=re, date=date, datetime=Clock, timezone=timezone, urlsplit=urlsplit, urlunsplit=urlunsplit, parse_qsl=parse_qsl, TypeAdapter=TypeAdapter, ValidationError=ValidationError, PublicHTTPSURL=PublicHTTPSURL, ats_job_url=ats_job_url)
    allowed = {"backend.app.core.config", "backend.app.browser.runner", "backend.app.services.job_sources.public_ats", "backend.app.core.job_urls", "backend.app.execution.naukri", "backend.app.browser.site_policy"}

    class Imports(ast.NodeTransformer):
        def visit_ImportFrom(self, node):
            if node.module not in allowed:
                raise ValueError("unexpected_platform_oracle_import")
            return None

    def load(path, names):
        tree = ast.parse((ROOT / path).read_text())
        nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names or isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id in names]
        module = Imports().visit(ast.Module(body=nodes, type_ignores=[]))
        exec(compile(ast.fix_missing_locations(module), path, "exec"), scope)

    prefix = "backend/app/services/applications/platforms/"
    load(prefix + "base.py", {"safe_url"})
    load("backend/app/browser/asset_policy.py", {"RESTRICTED_HOSTS"})
    load("backend/app/browser/site_policy.py", {"application_page_url"})
    load("backend/app/execution/naukri.py", {"normalized_url"})
    load("backend/app/services/job_sources/public_ats.py", {"hosted_job_url"})
    # Only called after the adapter's explicit testing/origin checks; no browser runtime.
    scope["origin"] = lambda value: f"{urlsplit(value).scheme}://{urlsplit(value).hostname}:{urlsplit(value).port or (443 if urlsplit(value).scheme == 'https' else 80)}"
    for filename, names in [("browser.py", {"AssistedEmployerPlatform"}), ("naukri.py", {"naukri_host", "posting_unavailable", "NaukriPlatform"}), ("owner_page.py", {"manual_page_url", "OwnerPagePlatform"}), ("public_listing.py", {"HOSTS", "PublicListingPlatform"}), ("registry.py", {"application_platforms"})]:
        load(prefix + filename, names)
    return scope


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    check = parser.parse_args().check
    scope = oracle()
    policies = [dict(testing=False, origins=[]), dict(testing=False, origins=["https://employer.example:443"]), dict(testing=True, origins=["http://127.0.0.1:8700", "https://employer.example:443"])]
    pairs = [("https://www.naukri.com/job-listings-fictional-123456789012", None), ("https://sub.naukri.com/a", "https://employer.example/apply"), ("https://example.com/reference", "https://employer.example/apply"), ("http://127.0.0.1:8700/job", "http://127.0.0.1:8700/apply"), ("https://boards.greenhouse.io/example/jobs/123", "https://boards.greenhouse.io/example/jobs/123"), ("https://remotive.com/job/123", "https://employer.example/apply"), ("https://www.arbeitnow.com/jobs/123", "https://employer.example/apply"), ("https://news.ycombinator.com/item?id=123", "https://employer.example/apply"), ("https://jobs.lever.co/example/abc-123", "https://jobs.lever.co/example/abc-123/apply"), ("https://jobs.lever.co/example/abc-123", "https://jobs.lever.co/example/DIFFERENT/apply"), ("https://jobs.lever.co/example/abc-123?source=board", "https://jobs.lever.co/example/abc-123/apply"), ("https://jobs.ashbyhq.com/example/abc-123", "https://jobs.ashbyhq.com/example/abc-123/application"), ("https://jobs.smartrecruiters.com/Example/12345-role?source=board", "https://jobs.smartrecruiters.com/Example/12345-other?oga=true"), ("https://jobs.smartrecruiters.com/Example/12345-role?extra=A", "https://jobs.smartrecruiters.com/Example/12345-role?extra=B"), ("https://example.zohorecruit.in/jobs/Careers/123/Example?source=board", "https://example.zohorecruit.in/jobs/Careers/123/Example?source=board"), ("https://employer.example/apply", "https://employer.example/apply"), ("https://docs.google.com/forms/d/e/fictional/viewform", "https://docs.google.com/forms/d/e/fictional/viewform"), ("https://example.wd1.myworkdayjobs.com/en-US/Jobs/job/Place/Role", "https://example.wd1.myworkdayjobs.com/en-US/Jobs/job/Place/Role"), ("https://example.com", "https://127.0.0.1/apply"), ("https://naukri.com.evil.example/post", None), ("invalid", "https://employer.example/apply")]
    jobs = []
    for source in ["manual_browser", "naukri", "NAUKRI", "owner_extension", *scope["HOSTS"], "unknown"]:
        for original, application in pairs:
            jobs.append(dict(source_platform=source, job_url=original, application_url=application, status="discovered", source_verification_status="source_reported", discovery_metadata={}))
    base = dict(source_platform="naukri", job_url=pairs[0][0], application_url=None, status="discovered", source_verification_status="observed", discovery_metadata={})
    for field, values in dict(status=["archived", "closed", "applied"], source_verification_status=["expired", "invalid", "closed"], discovery_metadata=[None, {"data_provenance": {"posting_status": "closed"}}, *[{"data_provenance": {"valid_through": d}} for d in ["2026-11-14", "2026-11-15", "2026-11-16", "20261115", "2026-W46-7", "2026W467", "2026-W46", "2026W46", "not-a-date", "2026-02-30", "2026-11-15T12:00:00Z", True, 3, "", None, " 2026-11-15"]]]).items():
        for value in values:
            jobs.append({**deepcopy(base), field: value})
    observations = [[], [["naukri", pairs[0][0]]], [["NAUKRI", pairs[0][0]]], [["naukri", "https://evil.example/job"]], [["naukri", "https://naukri.com.evil.example/job"]], [["naukri", "https://www.naukri.com/second"], ["naukri", pairs[0][0]]]]
    adapters = scope["application_platforms"]()
    capabilities = [a.capabilities().model_dump(mode="json") for a in adapters]
    results, index, cases = [], {}, []
    for p, policy in enumerate(policies):
        scope["get_settings"] = lambda policy=policy: SimpleNamespace(ENVIRONMENT="testing" if policy["testing"] else "production", BROWSER_ALLOWED_ORIGINS=policy["origins"])
        for j, raw in enumerate(jobs):
            job = SimpleNamespace(**raw)
            for o, observed in enumerate(observations):
                adapter = next((a for a in adapters if a.recognizes(job, observed)), None)
                result = dict(platform=adapter.capabilities().platform if adapter else None, preparation_supported=adapter is not None, destination=(adapter.destination(job, observed) if adapter else scope["Destination"](kind="unknown")).model_dump(mode="json"))
                key = json.dumps(result, sort_keys=True)
                if key not in index:
                    index[key] = len(results)
                    results.append(result)
                cases.append([j, o, p, index[key]])
    if "backend.app.core.config" in sys.modules or "backend.app.models.base" in sys.modules:
        raise ValueError("platform_oracle_loaded_runtime")
    corpus = dict(now="2026-11-15", policies=policies, jobs=jobs, observations=observations, capabilities=capabilities, results=results, cases=cases)
    target = ROOT / "rust/agent-runtime/tests/fixtures/packet-platform-corpus.json"
    encoded = json.dumps(corpus, ensure_ascii=False, separators=(",", ":")) + "\n"
    if check:
        if target.read_text() != encoded:
            raise SystemExit("packet_platform_corpus_drift")
    else:
        target.write_text(encoded)
    print(f"fictional_packet_destinations:{len(cases)} unique_results:{len(results)}")


if __name__ == "__main__":
    main()
