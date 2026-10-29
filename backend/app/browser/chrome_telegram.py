"""Owner-only Chrome command adapter; no DOM values or submissions over chat."""

from uuid import NAMESPACE_URL, UUID, uuid5

from backend.app.browser.chrome_profiles import ChromeCommandInput, enqueue, listing
from backend.app.browser.extension_tasks import by_application
from backend.app.local_agent.contracts import Actor


async def command(session, settings, text, update_id, bot_username):
    if not isinstance(text, str) or not text.strip().split():
        return None
    first, *args = text.strip().split()
    name, _, mention = first.partition("@")
    if name != "/chrome":
        return None
    if mention and mention.lower() != (bot_username or "").lower():
        return "Chrome command rejected: wrong bot mention."
    state = await listing(session, settings)
    profile = next((p for p in state["profiles"] if p["selected"]), None)
    if args == ["status"]:
        recent = [c for c in state["commands"] if c["actor"] == "telegram"][-3:]
        lines = [
            f"Selected Chrome: {profile['label']} · {profile['status']}"
            if profile
            else "PROFILE_OFFLINE: no selected Chrome profile."
        ]
        lines += [
            f"{c['id']}: {c['action']} · {c['state']} · {c['reason'] or 'no fill or submission requested'}"
            for c in recent
        ]
        if profile:
            from backend.app.browser.extension_tasks import rows

            for task in (await rows(session))[-5:]:
                value = task.value
                if value.get("profile_binding_id") != str(profile["id"]):
                    continue
                receipt = value.get("verified_receipts", [])[-1:]
                method = (
                    receipt[0]["verification_method"] if receipt else "no_fill_receipt"
                )
                count = (
                    sum(
                        result["status"] == "filled" for result in receipt[0]["results"]
                    )
                    if receipt and method == "retained_after_blur"
                    else 0
                )
                lines.append(
                    f"Packet {value['application_id']} r{value['packet_revision']}: {value['state']}; {method}; {count} retained fields. Submission unconfirmed."
                )
        for receipt in state["receipts"][-3:]:
            method = receipt["verification_method"]
            count = (
                sum(item["status"] == "filled" for item in receipt["results"])
                if method == "retained_after_blur"
                else 0
            )
            lines.append(
                f"Receipt: profile {receipt['profile_binding_id']}; packet {receipt['application_id']} r{receipt['packet_revision']}; {method}; {count} retained fields; submission unconfirmed."
            )
        return "\n".join(lines)[:3400]
    if len(args) != 3 or args[0] not in {
        "open",
        "prepare",
        "pause",
        "resume",
        "cancel",
    }:
        return "Use /chrome status or /chrome open|prepare|pause|resume|cancel <packet UUID> <packet revision>. Filling requires the extension's separate field approval."
    if not profile or profile["status"] != "CONNECTED":
        return "PROFILE_OFFLINE: work paused. Open and connect the selected Chrome profile; no isolated browser was launched."
    try:
        identity, revision = UUID(args[1]), int(args[2])
        task = await by_application(session, identity)
        value = ChromeCommandInput(
            request_id=uuid5(
                NAMESPACE_URL,
                f"chrome:telegram:{settings.TELEGRAM_OWNER_CHAT_ID}:{update_id}",
            ),
            profile_binding_id=profile["id"],
            selection_version=state["selection"]["version"],
            expected_profile_version=profile["version"],
            application_id=identity,
            packet_revision=revision,
            action=args[0],
            task_id=task["id"] if task else None,
            expected_task_version=task["version"] if task else None,
        )
        queued = await enqueue(
            session,
            settings,
            Actor(channel="telegram", identity=str(settings.TELEGRAM_OWNER_USER_ID)),
            value,
        )
        return f"Chrome command {queued['id']}: {queued['state']} in {profile['label']}. /chrome status reports the execution receipt. No fill or submission requested."
    except ValueError as exc:
        from backend.app.agent.tools import ToolDenied

        return f"Chrome command paused: {str(exc) if isinstance(exc, ToolDenied) else 'invalid_packet_or_revision'}. No browser fallback."
