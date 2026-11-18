"""Actual PG17/TCP/Chromium set selection, persistence, schema and privilege checks."""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


async def verify(
    client, packet, settings, writes, database_url, *, without_schema=False
):
    import asyncpg

    from backend.app.browser.runner import browser
    from backend.app.db.session import close_db_engine

    base = packet["snapshot"]["destination"]["application_url"].rsplit("/", 1)[0]
    for index, kind in enumerate(
        ("select", "checkbox", "aria") if not without_schema else ("select",)
    ):
        if index:
            response = await client.post(
                "/api/v1/browser-applications",
                json={
                    "application_url": base + "/multiple-" + kind,
                    "company_name": "Example Circuit",
                    "job_title": "Backend Engineer multiple " + kind,
                    "idempotency_key": "fictional-pg-multiple-" + kind,
                },
            )
            assert response.status_code == 200, response.text
            packet = response.json()
        route = "/api/v1/browser-applications/" + packet["id"]
        response = await client.post(
            route + "/open",
            json={
                "expected_revision": packet["revision"],
                "executor": "isolated_browser",
                "approve_dedicated_profile": True,
                "confirm_destination_permission": True,
            },
        )
        assert response.status_code == 200, response.text
        runtime = browser.sessions[packet["id"]]
        response = await client.post(
            route + "/actions",
            json={"expected_revision": packet["revision"], "action": "analyze"},
        )
        assert response.status_code == 200, response.text
        state = response.json()
        field = next(
            f
            for f in state["analysis"]["fields"]
            if f["kind"] in {"multi_select", "checkbox_group"}
        )
        if without_schema:
            assert (
                not field["supported"]
                and "database capability" in field["manual_reason"]
            )
            added = await client.post(
                "/api/v1/application-packets/" + packet["id"] + "/questions",
                json={
                    "expected_revision": state["packet"]["revision"],
                    "questions": [
                        {
                            "question": "Technical skills",
                            "field_type": "multi_select",
                            "options": ["Python", "Go"],
                        }
                    ],
                },
            )
            assert added.status_code == 422
            await browser.close(packet["id"])
            assert writes == []
            print(
                "PASS: PG17 flag alone does not enable missing multi-select schema",
                flush=True,
            )
            return
        assert field["supported"]
        item = next(
            f for f in state["packet"]["fields"] if f["id"] == field["field_id"]
        )
        assert (
            json.loads(item["effective_answer"]) == ["Python", "FastAPI"]
            and item["requires_review"]
        )
        response = await client.post(
            route + "/actions",
            json={
                "expected_revision": state["packet"]["revision"],
                "action": "fill",
                "confirm_reviewed_values": True,
                "confirm_page_context": True,
            },
        )
        assert response.status_code == 200, response.text
        # Positive fixtures start empty; an unreviewed proposal must not select anything.
        if kind == "select":
            assert await runtime.page.locator("#choices").evaluate(
                "e=>[...e.selectedOptions].map(o=>o.label)"
            ) == []
        else:
            assert await runtime.page.locator("#choices").evaluate(
                "e=>![...e.querySelectorAll('input[type=checkbox],[role=checkbox]')]"
                ".some(c=>c.checked || c.getAttribute('aria-checked')==='true')"
            )
        response = await client.post(
            "/api/v1/application-packets/" + packet["id"] + "/review",
            json={
                "expected_revision": state["packet"]["revision"],
                "action": "review",
                "reviewed_field_ids": [field["field_id"]],
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
        state = response.json()
        assert state["analysis"]["diagnostic"] == "filled_review_on_website"
        valid = next(
            v
            for v in state["analysis"]["validation"]
            if v["field_id"] == field["field_id"]
        )
        assert valid["complete"]
        if kind == "select":
            actual = await runtime.page.locator("#choices").evaluate(
                "e=>[...e.selectedOptions].map(o=>o.label)"
            )
        else:
            actual = await runtime.page.locator("#choices").evaluate(
                "e=>[...e.querySelectorAll('input[type=checkbox],[role=checkbox]')]"
                ".filter(c=>c.checked || c.getAttribute('aria-checked')==='true')"
                ".map(c=>(c.labels ? [...c.labels].map(l=>l.innerText).join(' ') : '')"
                " || c.getAttribute('aria-label'))"
            )
        assert actual == ["Python", "FastAPI"]
        assert not await runtime.page.locator("#consent").is_checked()
        assert writes == [] and state["packet"]["tracking_state"] == "not_applied"
        connection = await asyncpg.connect(database_url)
        try:
            for role in ("anon", "authenticated", "service_role"):
                assert not await connection.fetchval(
                    "SELECT has_function_privilege($1,'job_agent.valid_multi_select_answer(text,jsonb,boolean)','EXECUTE')",
                    role,
                )
            for bad in ('["Unknown"]', '["Python","Python"]', "[]", "{}", "not json"):
                transaction = connection.transaction()
                await transaction.start()
                try:
                    await connection.execute(
                        "UPDATE job_agent.application_packet_fields SET human_answer=$1 WHERE id=$2",
                        bad,
                        item["id"],
                    )
                except asyncpg.CheckViolationError as error:
                    assert (
                        error.constraint_name == "ck_application_fields_multi_select_v1"
                    )
                else:
                    raise AssertionError("Raw SQL accepted an invalid selection set")
                finally:
                    await transaction.rollback()
            # A marker without validator permission cannot activate application writes.
            for role in ("anon", "authenticated"):
                assert not await connection.fetchval(
                    "SELECT has_table_privilege($1,'job_agent.application_packet_fields','SELECT')",
                    role,
                )
        finally:
            await connection.close()
        await browser.close(packet["id"])
        await close_db_engine()
        saved = (await client.get(route)).json()
        assert (
            not saved["connected"]
            and saved["packet"]["tracking_state"] == "not_applied"
        )
        kept = next(f for f in saved["packet"]["fields"] if f["id"] == item["id"])
        assert (
            json.loads(kept["effective_answer"]) == ["Python", "FastAPI"]
            and kept["review_status"] == "reviewed"
        )
    print(
        "PASS: PG17 + TCP FastAPI + Chromium native/checkbox/ARIA multiple sets, review, SQL rejection, denied public access and durable tracking",
        flush=True,
    )


if __name__ == "__main__":
    from backend.scripts.browser_mock_demo import run

    parser = argparse.ArgumentParser()
    parser.add_argument("--without-schema", action="store_true")
    args = parser.parse_args()
    asyncio.run(
        run(
            os.environ["PROFILE_TEST_DATABASE_URL"],
            multiple_demo="without_schema" if args.without_schema else True,
        )
    )
