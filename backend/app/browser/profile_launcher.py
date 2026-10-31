"""Optional normal-Chrome startup. A verified binding, never a window, routes work."""

import asyncio
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from backend.app.core.config import get_settings
from backend.app.dashboard.models import OwnerPreference
from backend.app.execution.store import memory_row
from backend.app.models.discovery import now

FIXED = "chr_fixed_profile"
ATTEMPT = "chr_profile_launch"


def launch_arguments(mapping):
    directory = mapping.get("profile_directory", "")
    root = Path.home() / "Library/Application Support/Google/Chrome"
    # Do not resolve symlinks or read profile files. The owner verified this path in chrome://version.
    if (not re.fullmatch(r"Default|Profile [1-9][0-9]{0,3}", directory)
            or mapping.get("chrome_profile_path") != str(root / directory)
            or mapping.get("verified_via") != "owner_selected_chrome_version_page"
            or not mapping.get("profile_binding_id")):
        raise ValueError("PROFILE_OFFLINE")
    return ["/usr/bin/open", "-g", "-a", "/Applications/Google Chrome.app", "--args", "--profile-directory=" + directory]


async def automation_active(session):
    """Either Naukri scheduler can authorize startup; global OFF fences both."""
    await session.flush()
    rows = (await session.scalars(select(OwnerPreference).where(
        OwnerPreference.key.in_(["naukri_automation", "application_queue_policy", "exec_config:naukri"])
    ).execution_options(populate_existing=True))).all()
    values = {row.key: row.value for row in rows}
    if values.get("exec_config:naukri", {}).get("mode") == "OFF":
        return False
    queue = values.get("application_queue_policy", {})
    platform = queue.get("policy", {}).get("platforms", {}).get("naukri", {})
    return (values.get("naukri_automation", {}).get("state") == "RUNNING"
            or (queue.get("state") == "RUNNING" and platform.get("enabled") is True))


async def process(arguments):
    child = await asyncio.create_subprocess_exec(*arguments, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    try:
        return await asyncio.wait_for(child.wait(), 15)
    except TimeoutError:
        child.kill()
        await child.wait()
        return -1


async def ensure_fixed_profile(factory, *, settings=None, run=process):
    settings = settings or get_settings()
    if not settings.CHROME_FIXED_PROFILE_LAUNCH_ENABLED or sys.platform != "darwin":
        return "PROFILE_OFFLINE"
    async with factory() as session, session.begin():
        # An online status observation launches and dispatches nothing. Avoid
        # serializing normal browser RPCs behind this read on every worker tick.
        # The durable queue and legacy scheduler have independent controls.
        # Startup must stop with both channels, including global OFF.
        if not await automation_active(session):
            return "PROFILE_OFFLINE"
        fixed = await session.get(OwnerPreference, FIXED)
        selected = await session.get(OwnerPreference, "chr_selection")
        if not fixed or not selected or selected.value.get("profile_binding_id") != fixed.value.get("profile_binding_id"):
            return "PROFILE_OFFLINE"
        mapping = dict(fixed.value)
        if mapping.get("automatic_launch_enabled") is not True:
            return "PROFILE_OFFLINE"
        try:
            arguments = launch_arguments(mapping)
        except ValueError:
            return "PROFILE_OFFLINE"
        profile = await session.get(OwnerPreference, "chr_prof:" + mapping["profile_binding_id"])
        from backend.app.browser.chrome_profiles import online

        if profile and online(profile.value):
            return "CONNECTED"
        # Reserve a real launch only after obtaining authority and re-reading
        # everything that could have changed while waiting for the owner lock.
        await memory_row(session, lock=True)
        for record in (fixed, selected):
            await session.refresh(record)
        if (not await automation_active(session) or fixed.value != mapping
                or selected.value.get("profile_binding_id") != mapping["profile_binding_id"]):
            return "PROFILE_OFFLINE"
        if profile:
            await session.refresh(profile)
            if online(profile.value):
                return "CONNECTED"
        attempt = await session.get(OwnerPreference, ATTEMPT)
        if attempt and datetime.fromisoformat(attempt.value["next_attempt_at"]) > now():
            return "PROFILE_OFFLINE"
        # Reserve before invoking LaunchServices. The next tick must observe the UUID's own fresh heartbeat.
        value = {"profile_binding_id": mapping["profile_binding_id"], "attempted_at": now().isoformat(),
            "next_attempt_at": (now() + timedelta(minutes=5)).isoformat(), "status": "PROFILE_OFFLINE"}
        if attempt:
            attempt.value = value
        else:
            session.add(OwnerPreference(key=ATTEMPT, value=value))
    # If any normal Chrome is already running, do not open/reuse a possibly different profile.
    if await run(["/usr/bin/pgrep", "-x", "Google Chrome"]) == 0:
        return "PROFILE_OFFLINE"
    # Recheck Stop after the process probe and before launch; dispatch has its own stronger fences.
    async with factory() as session, session.begin():
        await memory_row(session, lock=True)
        fixed = await session.get(OwnerPreference, FIXED)
        if not await automation_active(session) or not fixed or fixed.value != mapping:
            return "PROFILE_OFFLINE"
        # Serialize the bounded launch with Stop. Once Stop is acknowledged no delayed launch remains.
        await run(arguments)
    # Launch success is never connection success. No employer work is dispatched here.
    return "PROFILE_OFFLINE"
