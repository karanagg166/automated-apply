"""Complete a fictional application through actual PG17, TCP API and Playwright.

CI injects a fictional provider. Explicit live acceptance can use a cloud-disabled
local model. Both paths use fictional facts, encrypted PDF and loopback employer.
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


async def verify(
    client, packet, settings, writes, *, receipt_mode="valid", live_model=None
):
    from backend.app.browser.owner_approval import approval_header
    from backend.app.browser.runner import browser
    from backend.app.db.session import close_db_engine

    route = "/api/v1/browser-applications/" + packet["id"]

    async def post(path, data, *, owner=False, status=200):
        if owner:
            raw = json.dumps(data).encode()
            response = await client.post(
                path,
                content=raw,
                headers={
                    "Content-Type": "application/json",
                    "X-Browser-Owner-Approval": approval_header(
                        settings.BROWSER_OWNER_APPROVAL_KEY.get_secret_value(),
                        path,
                        raw,
                        nonce=uuid4().hex,
                        timestamp=int(time.time()),
                    ),
                },
            )
        else:
            response = await client.post(path, json=data)
        assert response.status_code == status, response.text
        return response.json()

    await post(
        route + "/open",
        {
            "expected_revision": packet["revision"],
            "approve_dedicated_profile": True,
            "confirm_destination_permission": True,
        },
    )
    state = await post(
        route + "/actions",
        {"expected_revision": packet["revision"], "action": "analyze"},
    )
    assert len(state["analysis"]["fields"]) == 5
    source = await post(
        route + "/opportunity-preview",
        {"expected_revision": state["packet"]["revision"]},
    )
    approval = {
        k: source[k]
        for k in ("expected_revision", "capture_digest", "job_text", "company_text")
    }
    approval["confirm_company_job_and_source"] = True
    await post(route + "/opportunity-approve", approval, owner=True)
    state = (await client.get(route)).json()
    state = await post(
        route + "/actions",
        {"expected_revision": state["packet"]["revision"], "action": "analyze"},
    )
    question = next(f for f in state["analysis"]["fields"] if f["kind"] == "textarea")
    generated = await post(
        f"/api/v1/application-packets/{packet['id']}/questions/{question['field_id']}/generate",
        {"expected_revision": state["packet"]["revision"]},
    )
    answer = next(f for f in generated["fields"] if f["id"] == question["field_id"])
    assert answer["validation_status"] == "draft_ready", answer
    assert answer["requires_review"] and answer["review_status"] != "reviewed"
    draft_id = answer["provenance"]["answer_draft_id"]
    assert draft_id and answer["provenance"]["evidence_references"]
    proposed = answer["effective_answer"]
    runtime = browser.sessions[packet["id"]]

    async def fill(revision):
        return await post(
            route + "/actions",
            {
                "expected_revision": revision,
                "action": "fill",
                "confirm_reviewed_values": True,
                "confirm_page_context": True,
            },
        )

    # Explicit fill confirmation alone must not bypass the generated-field review.
    await fill(generated["revision"])
    assert await runtime.page.locator("textarea").input_value() == ""
    assert not await runtime.page.locator("[name=consent]").is_checked()
    reviewed = await post(
        f"/api/v1/application-packets/{packet['id']}/review",
        {
            "expected_revision": generated["revision"],
            "action": "review",
            "confirm_resume": True,
            "confirm_destination": True,
            "reviewed_field_ids": [
                f["id"] for f in generated["fields"] if f["effective_answer"]
            ],
        },
    )
    revision = reviewed["revision"]
    state = await fill(revision)
    assert state["analysis"]["diagnostic"] == "filled_review_on_website", state
    assert await runtime.page.locator("textarea").input_value() == proposed
    assert (
        await runtime.page.locator("[name=email]").input_value() == "alex@example.com"
    )
    await post(
        route + "/submission-preview",
        {"expected_revision": revision, "confirm_page_context": True},
        status=409,
    )
    consent = next(f for f in state["analysis"]["fields"] if f["kind"] == "checkbox")
    state = await post(
        route + "/consent",
        {
            "expected_revision": revision,
            "field_id": consent["field_id"],
            "checked": True,
            "confirm_page_context": True,
        },
        owner=True,
    )
    revision = state["packet"]["revision"]

    # FormData must agree with the visible reviewed controls, including consent.
    for target in ("motivation", "email", "consent"):
        await runtime.page.evaluate(
            """target => {
          window.__aaFixtureRewrite = event => event.formData.set(target, 'unreviewed replacement');
          document.forms[0].addEventListener('formdata', window.__aaFixtureRewrite);
        }""",
            target,
        )
        await post(
            route + "/submission-preview",
            {"expected_revision": revision, "confirm_page_context": True},
            status=409,
        )
        await runtime.page.evaluate(
            "document.forms[0].removeEventListener('formdata', window.__aaFixtureRewrite)"
        )

    async def authorize(*, check_unsigned=False):
        preview = await post(
            route + "/submission-preview",
            {"expected_revision": revision, "confirm_page_context": True},
        )
        assert preview["adapter"] == "local_mock_v2"
        narrative = next(
            f for f in preview["fields"] if f["field_id"] == question["field_id"]
        )
        assert (
            narrative["value"] == proposed
            and narrative["source"] == answer["provenance"]["source"]
        )
        data = {
            "expected_revision": revision,
            "preview_digest": preview["preview_digest"],
            "confirm_exact_application": True,
            "reviewed_consent_ids": [
                c["consent_id"] for c in preview["consents"] if c["checked"]
            ],
        }
        if check_unsigned:
            await post(route + "/authorize-submission", data, status=403)
        return preview, await post(route + "/authorize-submission", data, owner=True)

    preview, grant = await authorize(check_unsigned=True)

    def command(grant):
        return {
            "expected_revision": revision,
            "grant_id": grant["grant_id"],
            "grant_token": grant["grant_token"],
            "idempotency_key": "mock-v2-complete-application-001",
        }

    # Browser edits after approval cannot become an unchecked outgoing narrative.
    await runtime.page.locator("textarea").fill("Changed after owner review")
    await post(route + "/submit", command(grant), status=409)
    assert writes == []
    await runtime.page.locator("textarea").fill(proposed)
    preview, fresh = await authorize()
    await post(route + "/submit", command(grant), status=403)
    writes.mode = receipt_mode
    outcomes = await asyncio.gather(
        *[post(route + "/submit", command(fresh)) for _ in range(2)]
    )
    expected = "verified" if receipt_mode == "valid" else "unknown"
    assert all(outcome["state"] == expected for outcome in outcomes), outcomes
    assert outcomes[0]["attempt_id"] == outcomes[1]["attempt_id"]
    assert writes == ["/mock/v2/applications"]
    attempt_id = outcomes[0]["attempt_id"]
    received = dict(writes.accepted_entries[attempt_id])
    assert received["motivation"] == proposed.replace("\n", "\r\n")
    assert received["resume"]["sha256"] == preview["resume_sha256"]
    assert writes.receipts[attempt_id]["payload_digest"] == preview["payload_digest"]
    await browser.close(packet["id"])
    await close_db_engine()
    state = (await client.get(route)).json()
    if receipt_mode != "valid":
        assert state["packet"]["lifecycle_state"] == "submission_unknown"
        await verify_database_protocol_guards(
            settings, attempt_id, writes.receipts[attempt_id]
        )
        await post(
            route + "/submit",
            {**command(fresh), "idempotency_key": "mock-v2-forbidden-new-attempt"},
            status=409,
        )
        assert (await post(route + "/submit", command(fresh)))["state"] == "unknown"
        writes.mode = "valid"
        worker = await asyncio.create_subprocess_exec(
            sys.executable,
            str(ROOT / "backend/scripts/verify_browser_submission.py"),
            "--recover-worker",
            packet["id"],
            env={
                **os.environ,
                "BROWSER_FIXTURE_DATABASE_URL": settings.DATABASE_URL.replace(
                    "postgresql+asyncpg://", "postgresql://", 1
                ),
                "BROWSER_FIXTURE_ORIGIN": settings.BROWSER_ALLOWED_ORIGINS[0],
            },
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        output, error = await asyncio.wait_for(worker.communicate(), timeout=30)
        assert worker.returncode == 0, error.decode()
        assert json.loads(output)["state"] == "verified", output.decode()
        state = (await client.get(route)).json()
    assert state["packet"]["lifecycle_state"] == "provider_confirmed_submitted"
    assert state["packet"]["tracking_state"] == "applied_verified"
    assert state["execution"]["receipt"]["fixture"] == "automated-apply-employer-v2"
    assert state["execution"]["receipt"]["payload_digest"] == preview["payload_digest"]
    assert not state["real_employer_submission_enabled"] and writes == [
        "/mock/v2/applications"
    ]
    saved_field = next(
        f for f in state["packet"]["fields"] if f["id"] == question["field_id"]
    )
    assert (
        saved_field["effective_answer"] == proposed
        and saved_field["provenance"]["answer_draft_id"] == draft_id
    )
    evidence = await client.get(
        f"/api/v1/application-answers/drafts/{draft_id}/opportunity-evidence"
    )
    assert evidence.status_code == 200 and evidence.json()["evidence"], evidence.text
    drafts = (await client.get("/api/v1/application-answers/drafts")).json()
    draft = next(d for d in drafts if d["id"] == draft_id)
    assert draft["answer"] == proposed and draft["review_status"] == "draft"
    if live_model:
        from datetime import datetime, timezone

        from backend.app.dashboard.models import OwnerPreference
        from backend.app.db.session import get_session_factory

        assert draft["provider"] == "ollama" and draft["model"] == live_model
        async with get_session_factory()() as observer:
            usage = await observer.get(
                OwnerPreference,
                "ai:ollama:" + datetime.now(timezone.utc).strftime("%Y-%m"),
            )
            assert usage.value["requests"] == 1
    print(
        "PASS: PG17 + TCP FastAPI + Chromium complete application: URL, grounded generation, reviewed answer/PDF, signed consent/grant, single mock POST, independent V2 receipt and durable tracking",
        flush=True,
    )
    print(
        json.dumps(
            {
                "model": live_model or "fictional injected provider",
                "answer": proposed,
                "receipt_fixture": state["execution"]["receipt"]["fixture"],
                "tracking": state["packet"]["tracking_state"],
                "recovered_in_new_worker": receipt_mode != "valid",
            }
        ),
        flush=True,
    )


async def verify_database_protocol_guards(settings, attempt_id, receipt):
    """Exercise the optional proposal directly in the already validated local child."""
    import asyncpg

    connection = await asyncpg.connect(
        settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)
    )
    try:
        for statement, args, message in [
            (
                "UPDATE job_agent.browser_submission_attempts SET adapter='local_mock_v1' WHERE id=$1",
                [UUID(attempt_id)],
                "Attempt lacks exact consumed authorization",
            ),
            (
                "UPDATE job_agent.browser_submission_attempts SET state='verified',receipt=$2::jsonb WHERE id=$1",
                [
                    UUID(attempt_id),
                    json.dumps({**receipt, "fixture": "automated-apply-employer-v1"}),
                ],
                "Receipt does not match dispatched application",
            ),
        ]:
            try:
                await connection.execute(statement, *args)
            except asyncpg.RaiseError as error:
                assert str(error) == message, str(error)
            else:
                raise AssertionError(
                    "Database accepted a cross-version execution record"
                )
        assert (
            await connection.fetchval(
                "SELECT state FROM job_agent.browser_submission_attempts WHERE id=$1",
                UUID(attempt_id),
            )
            == "unknown"
        )
    finally:
        await connection.close()


def receiver_case(change):
    import hashlib

    import httpx

    from backend.app.services.applications.resume_selector import digest
    from backend.tests.browser_employers import employer_site

    attempt = uuid4()
    pdf = b"%PDF-1.4\nfictional" if change != "pdf" else b"not a PDF"
    motivation = "Approved fictional narrative." if change != "empty" else ""
    entries = [
        ["name", "Alex Example"],
        ["email", "alex@example.com"],
        ["motivation", motivation],
        [
            "resume",
            {
                "name": "resume.pdf",
                "size": len(pdf),
                "sha256": hashlib.sha256(pdf).hexdigest(),
            },
        ],
        ["consent", "yes"],
    ]
    parts = [(name, (None, value)) for name, value in entries[:3]]
    parts.extend(
        [
            (
                "resume",
                (
                    "resume.pdf",
                    pdf,
                    "text/plain" if change == "mime" else "application/pdf",
                ),
            ),
            ("consent", (None, "yes")),
        ]
    )
    if change == "extra":
        entries.append(["unreviewed", "unexpected"])
        parts.append(("unreviewed", (None, "unexpected")))
    parts.extend(
        [
            ("_aa_attempt_id", (None, str(attempt))),
            ("_aa_payload_digest", (None, digest(entries))),
        ]
    )
    if change == "duplicate_reserved":
        parts.append(("_aa_attempt_id", (None, str(attempt))))
    with (
        employer_site() as (base, writes),
        httpx.Client(trust_env=False, follow_redirects=False) as client,
    ):
        response = client.post(base + "/mock/v2/applications", files=parts)
        if change:
            assert response.status_code == 422
            assert not writes.receipts
        else:
            assert response.status_code == 303
            receipt = client.get(base + f"/mock/receipts/{attempt}").json()
            assert receipt["fixture"] == "automated-apply-employer-v2"
            assert receipt["payload_digest"] == digest(entries)
            assert (
                dict(writes.accepted_entries[str(attempt)])["motivation"] == motivation
            )


def verify_receiver_contract():
    for change in [None, "extra", "empty", "pdf", "mime", "duplicate_reserved"]:
        receiver_case(change)
    print(
        "PASS: independent V2 receiver accepts exact payload and rejects hidden fields, empty narratives, invalid PDFs/MIME and duplicate identifiers",
        flush=True,
    )


if __name__ == "__main__":
    from backend.scripts.browser_mock_demo import run

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt-mode", choices=["valid", "wrong"], default="valid")
    parser.add_argument("--receiver-contract", action="store_true")
    parser.add_argument("--multiline-answer", action="store_true")
    args = parser.parse_args()
    if args.receiver_contract:
        verify_receiver_contract()
    else:
        asyncio.run(
            run(
                os.environ["PROFILE_TEST_DATABASE_URL"],
                complete_application_demo=True,
                receipt_mode=args.receipt_mode,
                multiline_answer=args.multiline_answer,
            )
        )
