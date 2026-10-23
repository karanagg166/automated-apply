"""Disposable PG17 employer-context proof with injected or explicit live local generation."""

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


async def verify_paraphrase_reuse(client, packet, draft, settings):
    """Fictional owner approves reuse, then a fresh form asks a paraphrase.

    The fixed DOM change is a test fixture operation, never an application API.
    The new packet request must return the existing approved draft and source;
    fresh generated output cannot satisfy these assertions.
    """
    from backend.app.browser.owner_approval import approval_header
    from backend.app.browser.runner import browser
    from backend.app.db.session import close_db_engine

    response = await client.patch(
        f"/api/v1/application-answers/drafts/{draft}",
        json={"review_status": "reviewed"},
    )
    assert response.status_code == 200, response.text
    data = {
        "expected_profile_version": response.json()["candidate_profile_version"],
        "scope": "same_job",
        "confirm_reviewed_answer": True,
    }
    path = f"/api/v1/application-answers/drafts/{draft}/approve-reuse"
    assert (await client.post(path, json=data)).status_code == 403
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
    assert response.status_code == 200, response.text
    await close_db_engine()
    bank = await client.get("/api/v1/application-answers/reuse-approvals")
    assert bank.json()["approvals"][draft]["approved"]

    route = "/api/v1/browser-applications/" + packet["id"]
    state = (await client.get(route)).json()
    response = await client.post(
        route + "/open",
        json={
            "expected_revision": state["packet"]["revision"],
            "approve_dedicated_profile": True,
            "confirm_destination_permission": True,
        },
    )
    assert response.status_code == 200, response.text
    page = browser.sessions[packet["id"]].page
    await page.locator("form label").first.evaluate(
        "label => { label.firstChild.textContent = 'What attracts you to this role?'; }"
    )
    response = await client.post(
        route + "/actions",
        json={"expected_revision": state["packet"]["revision"], "action": "analyze"},
    )
    assert response.status_code == 200, response.text
    state = response.json()
    question = next(
        f
        for f in state["analysis"]["fields"]
        if f["question"] == "What attracts you to this role?"
    )
    response = await client.post(
        f"/api/v1/application-packets/{packet['id']}/questions/{question['field_id']}/generate",
        json={"expected_revision": state["packet"]["revision"]},
    )
    assert response.status_code == 200, response.text
    current = response.json()
    field = next(f for f in current["fields"] if f["id"] == question["field_id"])
    assert field["validation_status"] == "draft_ready", field
    assert field["requires_review"] and field["review_status"] == "pending"
    assert field["provenance"]["source"] == "approved_answer", field
    assert field["provenance"]["answer_draft_id"] == draft
    assert await page.locator("textarea").input_value() == ""
    response = await client.post(
        f"/api/v1/application-packets/{packet['id']}/review",
        json={
            "expected_revision": current["revision"],
            "action": "review",
            "confirm_resume": True,
            "confirm_destination": True,
            "reviewed_field_ids": [
                f["id"] for f in current["fields"] if f["effective_answer"]
            ],
        },
    )
    assert response.status_code == 200, response.text
    response = await client.post(
        route + "/actions",
        json={
            "expected_revision": response.json()["revision"],
            "action": "fill",
            "confirm_reviewed_values": True,
            "confirm_page_context": True,
        },
    )
    assert response.status_code == 200, response.text
    assert await page.locator("textarea").input_value() == field["effective_answer"]
    await browser.close(packet["id"])
    await close_db_engine()
    saved = (await client.get(route)).json()["packet"]
    restored = next(f for f in saved["fields"] if f["id"] == field["id"])
    assert restored["review_status"] == "reviewed"
    assert restored["provenance"]["source"] == "approved_answer"
    assert restored["effective_answer"] == field["effective_answer"]
    assert (
        await client.post(path.replace("approve-reuse", "revoke-reuse"))
    ).status_code == 200
    bank = await client.get("/api/v1/application-answers/reuse-approvals")
    assert not bank.json()["approvals"][draft]["approved"]
    print(
        "PASS: durable owner-approved paraphrase reuse, fresh form review and actual fill without a model request",
        flush=True,
    )


async def verify(client, packet, settings, *, live_model=None):
    from backend.app.browser.owner_approval import approval_header
    from backend.app.browser.runner import browser

    route = "/api/v1/browser-applications/" + packet["id"]
    response = await client.post(
        route + "/open",
        json={
            "expected_revision": packet["revision"],
            "approve_dedicated_profile": True,
            "confirm_destination_permission": True,
        },
    )
    assert response.status_code == 200, response.text
    preview = await client.post(
        route + "/opportunity-preview", json={"expected_revision": packet["revision"]}
    )
    assert preview.status_code == 200, preview.text
    data = {
        k: preview.json()[k]
        for k in ("expected_revision", "capture_digest", "job_text", "company_text")
    }
    data["confirm_company_job_and_source"] = True
    raw = json.dumps(data).encode()
    response = await client.post(
        route + "/opportunity-approve",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Browser-Owner-Approval": approval_header(
                settings.BROWSER_OWNER_APPROVAL_KEY.get_secret_value(),
                route + "/opportunity-approve",
                raw,
                nonce=uuid4().hex,
                timestamp=int(time.time()),
            ),
        },
    )
    assert response.status_code == 200, response.text
    state = (await client.get(route)).json()
    assert state["packet"]["revision"] == packet["revision"] + 1
    response = await client.post(
        route + "/actions",
        json={"expected_revision": state["packet"]["revision"], "action": "analyze"},
    )
    assert response.status_code == 200, response.text
    state = response.json()
    question = next(
        f for f in state["analysis"]["fields"] if f["question"].startswith("Why do you")
    )
    response = await client.post(
        f"/api/v1/application-packets/{packet['id']}/questions/{question['field_id']}/generate",
        json={"expected_revision": state["packet"]["revision"]},
    )
    assert response.status_code == 200, response.text
    current = response.json()
    field = next(f for f in current["fields"] if f["id"] == question["field_id"])
    assert field["validation_status"] == "draft_ready", field
    if live_model:
        assert field["requires_review"] and field["effective_answer"]
        assert "PRIVATE-FORM-VALUE" not in field["effective_answer"]
    else:
        assert (
            "Example Circuit" in field["effective_answer"]
            and "I built backend" in field["effective_answer"]
        )
    response = await client.post(
        f"/api/v1/application-packets/{packet['id']}/review",
        json={
            "expected_revision": current["revision"],
            "action": "review",
            "confirm_resume": True,
            "confirm_destination": True,
            "reviewed_field_ids": [
                f["id"] for f in current["fields"] if f["effective_answer"]
            ],
        },
    )
    assert response.status_code == 200, response.text
    revision = response.json()["revision"]
    response = await client.post(
        route + "/actions",
        json={
            "expected_revision": revision,
            "action": "fill",
            "confirm_reviewed_values": True,
            "confirm_page_context": True,
        },
    )
    assert response.status_code == 200, response.text
    assert (
        await browser.sessions[packet["id"]].page.locator("textarea").input_value()
        == field["effective_answer"]
    )
    draft = field["provenance"]["answer_draft_id"]
    await browser.close(packet["id"])
    response = await client.get(
        f"/api/v1/application-answers/drafts/{draft}/opportunity-evidence"
    )
    assert response.status_code == 200, response.text
    evidence = response.json()["evidence"]
    assert evidence and evidence[0]["source_url"].endswith("/opportunity")
    if live_model:
        from datetime import datetime, timezone

        from backend.app.dashboard.models import OwnerPreference
        from backend.app.db.session import close_db_engine, get_session_factory

        await close_db_engine()
        drafts = (await client.get("/api/v1/application-answers/drafts")).json()
        saved = next(d for d in drafts if d["id"] == draft)
        assert saved["provider"] == "ollama" and saved["model"] == live_model
        assert saved["review_status"] == "draft" and not saved["stale"]
        project = await client.post(
            "/api/v1/application-answers/generate",
            json={
                "question": "Describe a project you built",
                "writing_style": "concise",
                "max_characters": 600,
                "max_words": 90,
                "save_draft": True,
            },
        )
        assert project.status_code == 200, project.text
        project_answer = project.json()
        assert (
            project_answer["status"] == "draft_ready" and project_answer["used_llm"]
        ), project_answer
        assert (
            project_answer["provider"] == "ollama"
            and project_answer["model"] == live_model
        )
        assert project_answer["requires_review"] and not any(
            r["source_type"].startswith("opportunity_")
            for r in project_answer["evidence_references"]
        )
        for question_text, expected_status in [
            ("What is your current CTC?", "needs_input"),
            ("What is your notice period?", "draft_ready"),
        ]:
            resolved = await client.post(
                "/api/v1/application-answers/generate", json={"question": question_text}
            )
            assert resolved.status_code == 200, resolved.text
            assert (
                resolved.json()["status"] == expected_status
                and not resolved.json()["used_llm"]
            ), resolved.text
        key = "ai:ollama:" + datetime.now(timezone.utc).strftime("%Y-%m")
        async with get_session_factory()() as observer:
            row = await observer.get(OwnerPreference, key)
            assert row.value["requests"] == 2, row.value
        print(
            "PASS: PG17 + TCP FastAPI + Chromium + live cloud-disabled Ollama, grounded company proposal, explicit field review, actual filling, persisted draft/evidence and factual bypass; fictional data and no submission",
            flush=True,
        )
        print(
            json.dumps(
                {
                    "model": live_model,
                    "answer": field["effective_answer"],
                    "provider": saved["provider"],
                    "review_status": saved["review_status"],
                    "employer_sources": len(evidence),
                    "project_answer": project_answer["answer"],
                }
            ),
            flush=True,
        )
    else:
        assert "Example Circuit" in evidence[0]["excerpt"]
        await verify_paraphrase_reuse(client, packet, draft, settings)
        print(
            "PASS: PG17 + TCP FastAPI + Chromium capture, signed source review, fictional grounded proposal, reviewed fill and durable evidence; no live model or employer submission",
            flush=True,
        )


if __name__ == "__main__":
    from backend.scripts.browser_mock_demo import run

    asyncio.run(run(os.environ["PROFILE_TEST_DATABASE_URL"], opportunity_demo=True))
