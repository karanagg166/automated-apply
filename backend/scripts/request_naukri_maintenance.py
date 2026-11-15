"""Request one extension-owned inactive Naukri profile tab through the native poll.

No browser scripting, focus change, installation or employer action here. The
selected extension validates the account-bound request and creates its own inactive
ordinary profile tab. Chrome WebUI navigation remains suspended. Stop the queue first.
"""

import argparse
import asyncio
import json
import sys
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


async def request_setup(env_file, *, naukri_profile=False):
    if not naukri_profile:
        raise ValueError("extension_manager_navigation_suspended")
    from backend.app.core.config import configure_operator
    from backend.app.operations.configuration import load_settings

    settings = load_settings(env_file)
    configure_operator(settings)
    if not settings.CHROME_PROFILE_COMMANDS_ENABLED:
        raise ValueError("PROFILE_COMMANDS_DISABLED")

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from backend.app.automation.store import instant
    from backend.app.browser import chrome_profiles as profiles
    from backend.app.browser.profile_launcher import launch_arguments
    from backend.app.dashboard.models import OwnerPreference
    from backend.app.db.safety import database_connect_args
    from backend.app.execution import application_queue as queue
    from backend.app.execution import store
    from backend.app.execution.naukri_identity import require as require_account
    from backend.app.execution.naukri_native import MAINTENANCE

    engine = create_async_engine(settings.DATABASE_URL, hide_parameters=True, poolclass=NullPool,
                                 connect_args=database_connect_args(settings))
    try:
        async with async_sessionmaker(engine, expire_on_commit=False, autoflush=False)() as session:
            await store.memory_row(session, lock=True)
            config = await queue.configuration(session)
            if config["state"] != "STOPPED":
                raise ValueError("queue_must_be_stopped_for_maintenance")
            if not config["policy"]["platforms"]["naukri"]["enabled"]:
                raise ValueError("platform_disabled")
            if (await store.configuration(session)).mode == "OFF":
                raise ValueError("execution_mode_off")
            selected = await profiles.selection(session)
            identity = selected.get("profile_binding_id")
            row = await session.get(OwnerPreference, profiles.PROFILE + str(identity), populate_existing=True)
            fixed = await session.get(OwnerPreference, profiles.FIXED_PROFILE, populate_existing=True)
            if (not row or not fixed or fixed.value.get("profile_binding_id") != identity
                    or not profiles.online(row.value) or not row.value["commands_enabled"]
                    or row.value["window_id"] is None):
                raise ValueError("PROFILE_OFFLINE")
            launch_arguments(fixed.value)  # Validate the owner-verified mapping; never launch it.
            profile = row.value
            account = await require_account(session, profile_binding_id=identity)
            previous = await session.get(OwnerPreference, MAINTENANCE, populate_existing=True)
            now = await instant(session)
            if previous and previous.value.get("expires_at"):
                from datetime import datetime

                if datetime.fromisoformat(previous.value["expires_at"]) > now:
                    raise ValueError("maintenance_intent_still_pending")
            request = {
                "kind": "open_naukri_profile_setup", "request_id": str(uuid4()),
                "expires_at": (now + timedelta(seconds=90)).isoformat(),
                "account_binding_revision": account["revision"],
                "candidate_profile_id": account["candidate_profile_id"],
                "binding": {"profile_binding_id": identity, "profile_version": profile["version"],
                            "selection_version": selected["version"], "browser_session_id": profile["browser_session_id"],
                            "window_id": profile["window_id"], "tab_id": None},
            }
            await queue.put(session, MAINTENANCE, request)
            await session.commit()
            return {"requested": True, "request_id": request["request_id"], "expires_in_seconds": 90,
                    "opened_verified": False, "submitted": False}
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--request-setup", action="store_true", required=True)
    parser.add_argument("--naukri-profile", action="store_true",
                        help="Open only the approved account's ordinary inactive Naukri profile")
    args = parser.parse_args()
    try:
        print(json.dumps(asyncio.run(request_setup(args.env_file, naukri_profile=args.naukri_profile))))
    except Exception as exc:
        from backend.app.db.errors import database_failure_code

        known = {"PROFILE_COMMANDS_DISABLED", "queue_must_be_stopped_for_maintenance",
                 "execution_mode_off", "PROFILE_OFFLINE", "platform_disabled",
                 "extension_manager_navigation_suspended", "maintenance_intent_still_pending"}
        print(json.dumps({"requested": False, "error_type": type(exc).__name__,
                          "failure_code": str(exc) if str(exc) in known else database_failure_code(exc)}))
        raise SystemExit(1) from None
