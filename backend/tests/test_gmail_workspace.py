"""Fictional three-account history/drafts acceptance; no external network allowed."""

import json
from datetime import timedelta
from uuid import UUID

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import select

from backend.app.dashboard.models import OwnerPreference
from backend.app.integrations.connection_service import ConnectionService
from backend.app.integrations.gmail.drafts import (
    ACCOUNT,
    DRAFT,
    DraftAccountService,
    DraftApproval,
    DraftInput,
)
from backend.app.integrations.gmail.history import (
    ApplicationHistoryService,
    HistoryReview,
    previously_applied,
    reviewed_history,
)
from backend.app.integrations.gmail.read_service import GmailReadService, ReadPolicy
from backend.app.integrations.gmail.workspace import AccountConsent, Workspace
from backend.app.integrations.google_oauth import COMPOSE_SCOPES, GoogleOAuth
from backend.app.integrations.token_store import ConnectionError
from backend.app.local_agent.profile_confirmation import confirm_profile
from backend.app.models.discovery import now
from backend.tests.phase4a_fakes import (
    CALLBACK,
    GoogleFixture,
    oauth_settings,
    state_from,
)


async def authorize_read(session, settings, fake, client, email):
    fake.identity.update(email=email, sub=email + "-subject")
    fake.gmail_email = email
    service = ConnectionService(session, settings, GoogleOAuth(settings, client), read_only=True)
    result = await service.start(None, "browser")
    assert "login_hint" not in result["authorization_url"]
    return await service.callback(state_from(result), "browser", CALLBACK, "code")


async def test_account_chooser_identifies_two_distinct_accounts_and_rejects_duplicate(db_session):
    settings, fake = oauth_settings(), GoogleFixture()
    async with fake.client() as client:
        first = await authorize_read(db_session, settings, fake, client, "first@example.org")
        second = await authorize_read(db_session, settings, fake, client, "second@example.org")
        assert first["id"] != second["id"] and first["account_email"] == "first@example.org"
        with pytest.raises(ConnectionError, match="already_connected"):
            await authorize_read(db_session, settings, fake, client, "first@example.org")
        accounts = await GmailReadService(db_session, settings).accounts()
        assert {a["account_email"] for a in accounts if a["status"] == "connected"} == {"first@example.org", "second@example.org"}
        assert all(not a["permissions"]["send"] for a in accounts)


async def test_slot_account_binding_requires_consent_and_no_email(db_session, monkeypatch):
    settings, fake = oauth_settings(), GoogleFixture()
    async with fake.client() as client:
        monkeypatch.setattr("backend.app.integrations.connection_service.GoogleOAuth", lambda s: GoogleOAuth(s, client))
        service = Workspace(db_session, settings)
        assert len((await service.accounts())["accounts"]) == 3
        with pytest.raises(ConnectionError, match="consent"):
            await service.start("read_1", AccountConsent(account_consent=False), "browser")
        result = await service.start("read_1", AccountConsent(account_consent=True), "browser")
        assert "login_hint" not in result["authorization_url"]
        fake.identity.update(email="chosen@example.org", sub="chosen-subject")
        fake.gmail_email = "chosen@example.org"
        connection = ConnectionService(db_session, settings, GoogleOAuth(settings, client))
        with pytest.raises(ConnectionError, match="state"):
            await connection.callback(state_from(result), "other-browser", CALLBACK, "code")
        await connection.callback(state_from(result), "browser", CALLBACK, "code")
        accounts = (await service.accounts())["accounts"]
        assert accounts[0]["account_email"] == "chosen@example.org"
        assert accounts[1]["status"] == "not_connected"


@pytest.mark.parametrize("data", [
    {"history_months":25}, {"history_months":24,"folders":["INBOX"],"max_pages":2},
    {"folders":["INBOX","INBOX"]}, {"folders":["TRASH"]},
])
def test_historical_selection_limits(data):
    with pytest.raises(ValidationError):
        ReadPolicy(expected_version=0, **data)


async def test_24_month_inbox_sent_scan_batches_headers_only_and_encrypts_metadata(db_session):
    settings, fake = oauth_settings(GMAIL_READ_SYNC_ENABLED=True, GMAIL_RETENTION_ENABLED=True), GoogleFixture()
    async with fake.client() as client:
        account = await authorize_read(db_session, settings, fake, client, "history@example.org")
        aid = UUID(account["id"])
        calls = []
        def respond(request):
            calls.append(request)
            assert request.method == "GET" and "q" not in request.url.params
            if request.url.path.endswith("/messages"):
                assert request.url.params["maxResults"] == "25"
                folder = request.url.params.get_list("labelIds")
                return httpx.Response(200, json={"messages":[{"id":"inbox" if folder == ["INBOX"] else "sent"}]})
            message_id = request.url.path.rsplit("/",1)[-1]
            return httpx.Response(200,json={"id":message_id,"threadId":"thread", "internalDate":str(int((now()-timedelta(days=500)).timestamp()*1000)), "labelIds":["INBOX" if message_id=="inbox" else "SENT"],"payload":{"headers":[{"name":"Subject","value":"Application confirmation at Fictional Team"},{"name":"From","value":"jobs@fictional.example"},{"name":"To","value":"owner@example.org"}]}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as mailbox:
            service = GmailReadService(db_session,settings,google=GoogleOAuth(settings,client),client=mailbox)
            await service.configure(aid,ReadPolicy(expected_version=0, enabled=True,folders=["INBOX","SENT"], history_months=24,retain_metadata=True))
            first = await service.sync(aid)
            assert first["sync"]["status"] == "partial" and len(calls)==2
            second = await service.sync(aid)
            assert second["sync"]["status"] == "completed" and len(calls)==4
            evidence = await service.evidence(aid)
            assert len(evidence)==2
            assert {e["metadata"]["folder"] for e in evidence} == {"INBOX","SENT"}
            assert all(e["submission_confirmed"] is False and e["status_confirmed"] is False for e in evidence)
            stored = (await db_session.scalars(select(OwnerPreference).where(OwnerPreference.key.startswith("gmail_msg:")))).all()
            assert "Application confirmation" not in json.dumps([r.value for r in stored])
            assert all(r.value.get("encrypted_metadata") for r in stored)


async def test_reviewed_history_deduplicates_accounts_survives_raw_expiry_and_is_reversible(db_session):
    ids = [UUID("11111111-1111-4111-8111-111111111111"), UUID("22222222-2222-4222-8222-222222222222")]
    for i, aid in enumerate(ids):
        db_session.add(OwnerPreference(key="gmail_msg:"+str(i)*32,value={"account_id":str(aid),"expires_at":(now()+timedelta(days=1)).isoformat()}))
    await db_session.commit()
    service = ApplicationHistoryService(db_session)
    data = dict(expected_version=0,company="Fictional Team",role="Backend Engineer",applied_at=now()-timedelta(days=400),status="applied",confirmed_application=True,retention_days=365,owner_reviewed=True,evidence={ids[0]:["0"*32]})
    first = await service.review(HistoryReview(**data))
    second = await service.review(HistoryReview(**{**data,"expected_version":1,"confirmed_application":False,"status":"uncertain","evidence":{ids[1]:["1"*32]}}))
    assert first["id"] == second["id"] and len(second["evidence"])==2
    assert second["confirmed_application"] is True and second["status"] == "applied"
    assert len(await service.list())==1
    from backend.app.models.company import Company
    from backend.app.models.job import Job
    company=Company(name="Fictional Team",domain="fictional.example")
    job=Job(title="Backend Engineer",job_url="https://fictional.example/jobs/one",source_platform="manual")
    assert previously_applied(job,company,await reviewed_history(db_session))
    job.title="Frontend Engineer"
    assert not previously_applied(job,company,await reviewed_history(db_session))
    for i in range(2):
        row=await db_session.get(OwnerPreference,"gmail_msg:"+str(i)*32)
        row.value={**row.value,"expires_at":(now()-timedelta(seconds=1)).isoformat()}
    await db_session.commit()
    assert len(await service.list())==1
    assert (await db_session.get(OwnerPreference,"gmail_msg:"+"0"*32)).value=={"status":"purged"}
    changed=await service.retention(first["id"],2,60)
    assert changed["retention_days"]==60
    await service.forget(first["id"],3)
    assert await service.list()==[] and await reviewed_history(db_session)==[]


async def test_drafts_scope_is_separate_and_never_accepts_read_account_identity(db_session):
    settings,fake=oauth_settings(),GoogleFixture()
    async with fake.client() as client:
        await authorize_read(db_session,settings,fake,client,"read@example.org")
        fake.token["scope"]=" ".join(sorted(COMPOSE_SCOPES))
        service=DraftAccountService(db_session,settings,GoogleOAuth(settings,client))
        start=await service.start("browser")
        with pytest.raises(ConnectionError,match="separate_outreach"):
            await service.callback(state_from(start),"browser",CALLBACK,"code")
        fake.identity.update(email="outreach@example.org",sub="outreach-subject")
        fake.gmail_email="outreach@example.org"
        start=await service.start("browser")
        connected=await service.callback(state_from(start),"browser",CALLBACK,"code")
        assert connected["account_email"]=="outreach@example.org" and connected["sending_enabled"] is False
        assert connected["permissions"]["send"] is False
        assert "fictional-refresh" not in str((await db_session.get(OwnerPreference,ACCOUNT)).value)
        with pytest.raises(ConnectionError,match="replayed"):
            await service.callback(state_from(start),"browser",CALLBACK,"code")


async def test_exact_reviewed_draft_one_write_unknown_dispatch_no_retry(db_session,phase2_profile):
    settings,fake=oauth_settings(GMAIL_DRAFTS_ENABLED=True),GoogleFixture()
    await confirm_profile(db_session,phase2_profile,phase2_profile.version)
    await db_session.commit()
    async with fake.client() as oauth:
        fake.token["scope"]=" ".join(sorted(COMPOSE_SCOPES))
        calls=[]
        def respond(request):
            calls.append(request)
            assert request.method=="POST" and request.url.path.endswith("/users/me/drafts")
            return httpx.Response(200,json={"id":"draft-one"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as mailbox:
            service=DraftAccountService(db_session,settings,GoogleOAuth(settings,oauth),mailbox)
            start=await service.start("browser")
            await service.callback(state_from(start),"browser",CALLBACK,"code")
            draft=await service.save(DraftInput(recipient="founder@fictional.example",company="Fictional Team",role="Backend Engineer",context="I reviewed your public Python infrastructure work."))
            assert calls==[] and "verified skills" in draft["content"]["body"]
            approval=DraftApproval(expected_version=1,content_hash=draft["content_hash"],owner_reviewed=True, expected_account_generation=2)
            with pytest.raises(ConnectionError,match="review"):
                await service.create_in_gmail(draft["id"],approval.model_copy(update={"owner_reviewed":False}))
            result=await service.create_in_gmail(draft["id"],approval)
            assert result["sent"] is False and len(calls)==1
            await service.create_in_gmail(draft["id"],approval)
            assert len(calls)==1
            other=await service.save(DraftInput(recipient="other@fictional.example",company="Other Team",role="Engineer",context="I reviewed the engineering role and public team work."))
            async def timeout(*args):
                calls.append("ambiguous")
                raise ConnectionError("gmail_draft_creation_unconfirmed")
            service.client=None
            from unittest.mock import patch
            with patch("backend.app.integrations.gmail.drafts.GmailDraftClient.create",timeout):
                approval=DraftApproval(expected_version=1,content_hash=other["content_hash"],owner_reviewed=True, expected_account_generation=2)
                with pytest.raises(ConnectionError,match="unconfirmed"):
                    await service.create_in_gmail(other["id"],approval)
                with pytest.raises(ConnectionError,match="reconciliation"):
                    await service.create_in_gmail(other["id"],approval)
                assert calls.count("ambiguous")==1
            assert (await db_session.get(OwnerPreference,DRAFT+other["id"])).value["status"]=="unknown"
            assert all(len(key)<=50 for key in (await db_session.scalars(select(OwnerPreference.key))).all())


async def test_draft_writes_disabled_by_default(db_session):
    service=DraftAccountService(db_session,oauth_settings())
    with pytest.raises(ConnectionError,match="disabled"):
        await service.create_in_gmail("a"*32,DraftApproval(expected_version=1,content_hash="a"*64,owner_reviewed=True, expected_account_generation=2))


def test_history_preserves_query_job_identity_and_different_known_requisitions():
    from types import SimpleNamespace

    from backend.app.integrations.gmail.history import canonical_url
    company=SimpleNamespace(name="Fictional Team")
    history=[{"confirmed_application":True,"company":"Fictional Team","role":"Engineer","job_url":canonical_url("https://fictional.example/careers?jobId=123&utm_source=email")}]
    job=SimpleNamespace(title="Engineer",job_url="https://fictional.example/careers?jobId=456",application_url=None)
    assert not previously_applied(job,company,history)
    job.job_url="https://fictional.example/careers?utm_medium=alert&jobId=123"
    assert previously_applied(job,company,history)
    history[0]["confirmed_application"]=False
    assert not previously_applied(job,company,history)


async def test_local_retention_scrubs_raw_and_expired_oauth_but_keeps_reviewed_history(db_session):
    from backend.app.integrations.gmail.retention import sweep
    db_session.add_all([
        OwnerPreference(key="gmail_msg:expired",value={"encrypted_metadata":"fictional_envelope","expires_at":(now()-timedelta(seconds=1)).isoformat()}),
        OwnerPreference(key="gmail_draft_oauth:expired",value={"verifier":"fictional_envelope","expires_at":(now()-timedelta(seconds=1)).isoformat()}),
        OwnerPreference(key="gmail_application:reviewed",value={"id":"reviewed","company":"Fictional Team","role":"Engineer","applied_at":now().isoformat(),"expires_at":(now()+timedelta(days=365)).isoformat()}),
    ])
    await db_session.commit()
    await sweep(db_session)
    assert (await db_session.get(OwnerPreference,"gmail_msg:expired")).value=={"status":"purged"}
    assert (await db_session.get(OwnerPreference,"gmail_draft_oauth:expired")).value=={"consumed":True,"expired":True}
    assert len(await reviewed_history(db_session))==1


async def test_confirmed_job_is_removed_from_new_recommendations_only(db_session,phase2_profile):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from backend.app.schemas.discovery import DiscoveryQuery, RunRequest
    from backend.app.schemas.normalized_job import NormalizedJob
    from backend.app.services.job_discovery_service import JobDiscoveryService
    test_session_factory=async_sessionmaker(db_session.bind,expire_on_commit=False)
    url="https://fictional.example/jobs/already-applied"
    db_session.add(OwnerPreference(key="gmail_application:known",value={"confirmed_application":True,"company":"Fictional Team","role":"Backend Engineer","job_url":url,"expires_at":(now()+timedelta(days=365)).isoformat()}))
    await db_session.commit()
    from sqlalchemy import event
    history_reads=[]
    def observe(conn,cursor,statement,parameters,context,executemany):
        if statement.lstrip().upper().startswith("SELECT") and "gmail_application:" in parameters:
            history_reads.append(statement)
    event.listen(db_session.get_bind(), "before_cursor_execute",observe)
    result=await JobDiscoveryService(db_session,test_session_factory).run(RunRequest(source="manual",query=DiscoveryQuery(limit=2),use_profile=True,allow_paid=False,idempotency_key="gmail-history-recommendation-exclusion",manual_jobs=[NormalizedJob(source_name="manual",source_job_id="known",original_url=url,title="Backend Engineer",company_name="Fictional Team").model_dump(mode="json"),NormalizedJob(source_name="manual",source_job_id="different",original_url="https://fictional.example/jobs/new-requisition",title="Backend Engineer",company_name="Fictional Team").model_dump(mode="json")]))
    event.remove(db_session.get_bind(),"before_cursor_execute",observe)
    assert len(result["job_ids"])==2 and len(result["rankings"])==1
    assert len(history_reads)==1
