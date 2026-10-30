"""Explicit Naukri commands use the same durable execution store as the dashboard."""

from uuid import UUID

from sqlalchemy import select

from backend.app.agent.tools import ToolDenied
from backend.app.execution import store
from backend.app.models.job import Job


async def command(session, text):
    words = text.split()
    if not words or words[0].split("@")[0] != "/naukri":
        return None
    action = words[1] if len(words) > 1 else "status"
    try:
        if action == "queue" and len(words) == 3 and words[2] in {"start", "pause", "resume", "stop"}:
            from backend.app.execution import application_queue as queue
            from backend.app.execution.queue_contracts import QueueControl

            current = await queue.configuration(session)
            value = await queue.control(session, QueueControl(action="start" if words[2] == "resume" else words[2], expected_revision=current["revision"]))
            return f"Naukri queue: {value['state']}; saved platform policy and limits apply. Live acceptance remains pending."
        if action == "add" and len(words) == 3:
            from backend.app.execution.application_queue import enqueue

            value = await enqueue(session, "naukri", words[2], "saved_verified_job")
            return f"Naukri queue {value['id']}: {value['stage']}. No application sent by this command."
        if action == "queue" and len(words) == 2:
            from backend.app.execution.application_queue import listing

            value = await listing(session, platform="naukri", limit=5)
            return f"Naukri queue: {value['configuration']['state']}; {value['counts']}. Direct Apply candidate; genuine installed acceptance pending."
        if action == "automation" and len(words) == 3 and words[2] in {"start", "pause", "stop"}:
            from backend.app.execution import recurring
            from backend.app.execution.contracts import AutomationControl
            current = await recurring.record(session)
            value = await recurring.control(session, AutomationControl(action=words[2], expected_revision=current["revision"]))
            return f"Naukri automation: {value['state']}; preparation only; submission unavailable."
        if action == "find" and len(words) == 2:
            jobs = (
                await session.scalars(
                    select(Job)
                    .where(Job.source_platform == "naukri")
                    .order_by(Job.created_at.desc())
                    .limit(20)
                )
            ).all()
            return "Saved owner-imported Naukri jobs (no portal search executed):\n" + (
                "\n".join(f"{j.id} — {j.title}\n{j.job_url}" for j in jobs)
                or "None. Import a posting or job-alert facts in the dashboard."
            )
        if action == "apply" and len(words) >= 3:
            executions = await store.start(
                session, [UUID(value) for value in words[2:27]]
            )
            return "\n".join(
                f"{e['id']}: {e['state']}; preparation only, no submission."
                for e in executions
            )
        if action in {"pause", "resume", "cancel"} and len(words) == 3:
            row = await store.load(session, UUID(words[2]))
            value = await store.control(
                session, row.value["id"], action, row.value["revision"]
            )
            return f"{value['id']}: {value['state']}. Check application history before any manual submission."
        if action == "status" and len(words) <= 2:
            from backend.app.execution.application_queue import listing
            from backend.app.execution.recurring import status

            automation = await status(session)
            queued = await listing(session, platform="naukri", limit=5)
            return (
                f"Naukri queue: {queued['configuration']['state']}; {queued['counts']}. Live installed acceptance pending.\n"
                f"Legacy preparation: {automation['state']}; scope {automation['scope']}; worker {'online' if automation['worker_online'] else 'offline'}; source {automation['source']}.\n"
                f"Counts: {automation['counts']}. Blockers: {', '.join(automation['blockers'])}.\n"
                + "\n".join(
                    f"{r.value['id']}: {r.value['state']}"
                    for r in await store.rows(session)
                )
            )
    except (ValueError, ToolDenied):
        return "Naukri command rejected. Check the exact saved job/application reference and current state."
    return "/naukri add <job URL> | queue [start|pause|resume|stop] | find | apply <job UUID...> | pause <application UUID> | resume <application UUID> | cancel <application UUID> | status"
