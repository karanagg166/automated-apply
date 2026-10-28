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
            return (
                f"Naukri: {(await store.configuration(session)).mode}; live account not verified; automated submission unavailable.\n"
                + "\n".join(
                    f"{r.value['id']}: {r.value['state']}"
                    for r in await store.rows(session)
                )
            )
    except (ValueError, ToolDenied):
        return "Naukri command rejected. Check the exact saved job/application reference and current state."
    return "/naukri find | apply <job UUID...> | pause <application UUID> | resume <application UUID> | cancel <application UUID> | status"
