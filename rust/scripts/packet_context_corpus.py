"""Actual packet material recipe and matcher over fictional preloaded rows, without ORM/config."""
import argparse
import ast
import asyncio
import hashlib
import html
import json
import sys
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace as S
from uuid import UUID

from backend.app.schemas.candidate_profile import (
    CandidateProfileCreate,
    CandidateProfileRead,
)
from rust.scripts.packet_platform_corpus import oracle as platform_oracle

ROOT = Path(__file__).resolve().parents[2]


def oracle():
    scope = platform_oracle()
    scope.update(hashlib=hashlib, json=json, html=html, Job=S, SimpleNamespace=S, CandidateProfileCreate=CandidateProfileCreate, CandidateProfileRead=CandidateProfileRead, timedelta=timedelta)
    allowed = {"backend.app.execution.naukri", "backend.app.knowledge.opportunity", "backend.app.services.applications.platforms.naukri", "backend.app.knowledge.missing_input", "backend.app.integrations.gmail.history"}

    class Imports(ast.NodeTransformer):
        def visit_ImportFrom(self, node):
            if node.module not in allowed:
                raise ValueError("unexpected_material_oracle_import")
            return None

    def execute(path, nodes):
        module = Imports().visit(ast.Module(body=nodes, type_ignores=[]))
        exec(compile(ast.fix_missing_locations(module), path, "exec"), scope)

    def load(path, names):
        nodes = [n for n in ast.parse((ROOT / path).read_text()).body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names or isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id in names]
        execute(path, nodes)

    prefix = "backend/app/services/applications/"
    load(prefix + "resume_selector.py", {"digest", "private_resume_id", "select_resume"})
    load("backend/app/execution/naukri.py", {"matching_job", "reviewed_job_context"})
    load("backend/app/knowledge/opportunity.py", {"binding", "unsafe_instruction", "reviewed_context", "KEY"})
    load("backend/app/integrations/gmail/history.py", {"previously_applied"})
    path = "backend/app/services/application_assistant.py"
    load(path, {"CandidateProfile", "JobMatchResult", "skill_key", "title_key"})
    cls = next(n for n in ast.parse((ROOT / path).read_text()).body if isinstance(n, ast.ClassDef) and n.name == "ApplicationAssistant")
    execute(path, [next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "calculate_match")])
    # Its original constructor only creates an unused repository; retain the actual scorer.
    scope["ApplicationAssistant"] = type("ApplicationAssistant", (), {"__init__": lambda self, session: None, "calculate_match": scope["calculate_match"]})
    load("backend/app/services/job_discovery_matcher.py", {"SKILL_GAP_FACTOR", "JobDiscoveryMatcher"})

    async def revisions(session, profile, job):
        return session.revisions

    scope["approved_input_revisions"] = revisions
    path = prefix + "packet_builder.py"
    cls = next(n for n in ast.parse((ROOT / path).read_text()).body if isinstance(n, ast.ClassDef) and n.name == "PacketBuilder")
    source = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "context")
    start = next(i for i, n in enumerate(source.body) if isinstance(n, ast.If) and isinstance(n.test, ast.Compare) and isinstance(n.test.left, ast.Attribute) and n.test.left.attr == "source_platform")
    stub = ast.parse("async def material(self, job, profile, company, resources, stamps, observations, selected_resume):\n    pass\n").body[0]
    stub.body = source.body[start:]
    execute(path, [stub])
    return scope


def row(raw, dates=(), uuids=()):
    if raw is None:
        return None
    data = deepcopy(raw)
    for field in dates:
        if data.get(field):
            data[field] = datetime.fromisoformat(data[field])
    for field in uuids:
        if data.get(field):
            data[field] = UUID(data[field])
    return S(**data)


async def build():
    scope = oracle()
    now = datetime(2026,11,15,12,tzinfo=timezone.utc)
    profile_id = "10000000-0000-0000-0000-000000000001"
    base_profile = dict(CandidateProfileCreate(full_name="Fictional Person",email="fictional@example.com",verified_skills=["Rust"],verified_experience_years=0).model_dump(mode="json"), id=profile_id,version=4,singleton_key="primary",created_at=now.isoformat(),updated_at=now.isoformat())
    profiles = [None, base_profile, {**deepcopy(base_profile),"full_name":" Changed Fictional Name ","preferences":{"target_titles":["Rust Engineer"],"remote_preference":"remote","minimum_salary":12345.67,"salary_currency":"INR","salary_period":"year"}}, {**deepcopy(base_profile),"github_url":"https://github.com/fictional","preferences":{"current_compensation":{"amount":"123456.75","currency":"INR","period":"year","kind":"ctc"}}}]
    job = dict(id="20000000-0000-0000-0000-000000000001",company_id="30000000-0000-0000-0000-000000000001",title="Rust Engineer",description="The employer builds Rust APIs.",source_platform="naukri",job_url="https://www.naukri.com/job-listings-fictional-123456789012",application_url=None,skills_required=["Rust"],location="Fictional City",remote_type="remote",is_remote=True,employment_type="full_time",experience_level="junior",salary_min="12345.00",salary_max="23456.75",salary_currency="INR",salary_period="year",date_posted=now.isoformat(),last_observed_at=now.isoformat(),source_verification_status="observed",status="discovered",discovery_metadata={})
    jobs = [job]
    for field,value in [("description",None),("last_observed_at",None),("last_observed_at",(now-timedelta(days=30)).isoformat()),("last_observed_at",(now-timedelta(days=30,microseconds=1)).isoformat()),("status","archived"),("source_platform","unknown"),("discovery_metadata",dict(source_name="naukri",company_name="Corrected Employer",title="Reviewed Rust Engineer",description="Reviewed Rust role",skills_required=["Rust"],remote_type="remote",salary_min=12000.0,salary_max=24000.0,salary_currency="INR",salary_period="year",application_url=None,date_posted=now.isoformat())),("discovery_metadata",{"data_provenance":{"valid_through":"2026-11-14"}})]:
        jobs.append({**deepcopy(job),field:value})
    company = dict(id=job["company_id"],name="Fictional Labs",domain="example.com",metadata_={"startup_discovery":{"stage":"seed","source":"work_at_a_startup"}})
    jobs.append({**deepcopy(job),"source_platform":"unknown","job_url":"https://example.com/posting"})
    for age in [timedelta(days=14),timedelta(days=14,microseconds=1),timedelta(seconds=-1)]:
        saved=dict(binding=scope["binding"](S(**job),S(**company)),reviewed_at=(now-age).isoformat(),source_url="https://example.com/source",job_text="The employer builds Rust APIs.",company_text="Fictional Labs develops queue software.")
        saved["digest"]=scope["digest"](saved)
        jobs.append({**deepcopy(job),"discovery_metadata":{"application_opportunity":saved}})
    companies = [company, None]
    resource = dict(id="40000000-0000-0000-0000-000000000001",resource_type="resume",label=" Fictional Resume ",url="https://example.com/resume.pdf",user_confirmed=True,is_primary=True,source_type="user",updated_at=now.isoformat())
    inventories = [[],[resource],[{**resource,"source_type":"private_upload","url":"private-resume:50000000-0000-0000-0000-000000000001"}],[resource,{**resource,"id":"40000000-0000-0000-0000-000000000002","is_primary":False,"url":"https://example.com/second.pdf"}],[resource,{**resource,"id":"40000000-0000-0000-0000-000000000003","resource_type":"other","is_primary":False,"url":"https://example.com/other"}],[{**resource,"updated_at":(now+timedelta(microseconds=1)).isoformat()}]]
    evidence = [[],[["60000000-0000-0000-0000-000000000001",now.isoformat(),False]],[["60000000-0000-0000-0000-000000000001",now.isoformat(),True]],[["60000000-0000-0000-0000-000000000001",(now+timedelta(microseconds=1)).isoformat(),True]]]
    observations = [[],[["naukri",job["job_url"]],["naukri",job["job_url"]],["other","https://example.com/source"],["other","not a URL"]]]
    revisions = [[],[["needs_input:"+"a"*32,3,"approved","b"*64]],[["needs_input:"+"a"*32,4,"draft","c"*64]]]
    records, cases = [], []
    # Vary each material component independently against a normal complete baseline.
    baseline=dict(profile=1,job=0,company=0,resources=1,evidence=0,observations=0,revisions=0,selected=None)
    settings=[baseline]
    for field,values in dict(profile=range(len(profiles)),job=range(len(jobs)),company=range(len(companies)),resources=range(len(inventories)),evidence=range(len(evidence)),observations=range(len(observations)),revisions=range(len(revisions)),selected=[None,resource["id"],"40000000-0000-0000-0000-000000000099"]).items():
        settings.extend({**baseline,field:value} for value in values)
    for indexes in settings:
        raw=dict(profile=profiles[indexes["profile"]],job=jobs[indexes["job"]],company=companies[indexes["company"]],resources=inventories[indexes["resources"]] if profiles[indexes["profile"]] else [],evidence=evidence[indexes["evidence"]] if profiles[indexes["profile"]] else [],observations=observations[indexes["observations"]],revisions=revisions[indexes["revisions"]] if profiles[indexes["profile"]] else [],selected=indexes["selected"])
        native_job=row(raw["job"],["date_posted","last_observed_at"],["id","company_id"])
        for money in ["salary_min","salary_max"]:
            if getattr(native_job,money) is not None:
                setattr(native_job,money,Decimal(getattr(native_job,money)))
        profile=row(raw["profile"],["created_at","updated_at"],["id"])
        native_resources=[row(r,["updated_at"],["id"]) for r in raw["resources"]]
        stamps=[[UUID(i),datetime.fromisoformat(t),confirmed] for i,t,confirmed in raw["evidence"]]
        self=S(platforms=scope["application_platforms"](),session=S(revisions=raw["revisions"]))
        scope["get_settings"]=lambda:S(ENVIRONMENT="production",BROWSER_ALLOWED_ORIGINS=[])
        _,_,snapshot=await scope["material"](self,native_job,profile,row(raw["company"],uuids=["id"]),native_resources,stamps,sorted(raw["observations"]),UUID(raw["selected"]) if raw["selected"] else None)
        records.append(raw)
        cases.append(snapshot.model_dump(mode="json"))
    if "backend.app.core.config" in sys.modules or "backend.app.models.base" in sys.modules:
        raise ValueError("material_oracle_loaded_runtime")
    return dict(now=now.isoformat(),records=records,outputs=cases)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--check",action="store_true")
    check=parser.parse_args().check
    corpus=asyncio.run(build())
    target=ROOT/"rust/agent-runtime/tests/fixtures/packet-context-corpus.json"
    encoded=json.dumps(corpus,ensure_ascii=False,indent=2)+"\n"
    if check:
        if target.read_text()!=encoded:
            raise SystemExit("packet_context_corpus_drift")
    else:
        target.write_text(encoded)
    print(f"fictional_packet_material_contexts:{len(corpus['records'])}")


if __name__=="__main__":
    main()
