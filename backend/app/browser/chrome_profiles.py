"""Owner-scoped Chrome bindings and a bounded, opt-in native command mailbox.

Chrome profile UUIDs identify installations, never Google accounts. Separate
profile credentials authenticate the binding through the existing private host.
The owner lock serializes selection, task cancellation and command leases.
"""

import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import select, union_all

from backend.app.agent.tools import ToolDenied
from backend.app.browser.contracts import Contract
from backend.app.core.timing import timed
from backend.app.dashboard.models import OwnerPreference
from backend.app.execution import store
from backend.app.local_agent.contracts import PROFILE_OPERATIONS

PROFILE = "chr_prof:"
COMMAND = "chr_cmd:"
SELECTION = "chr_selection"
FIXED_PROFILE = "chr_fixed_profile"

NATIVE = PROFILE_OPERATIONS
LIVE_SECONDS = 100
TERMINAL = {"completed", "failed", "expired", "cancelled", "outcome_unknown"}


class ChromeProfile(Contract):
    id: UUID
    label: str
    version: int
    connected: bool
    selected: bool
    status: Literal["CONNECTED", "PROFILE_OFFLINE", "DISCONNECTED"]
    last_heartbeat: str
    browser_session_id: UUID
    window_id: int | None
    commands_enabled: bool


class ChromeProfiles(Contract):
    selection: dict
    profiles: list[ChromeProfile]
    channel_available: bool
    commands: list[dict]
    receipts: list[dict] = Field(default_factory=list)


class ProfileDisconnect(Contract):
    expected_version: int = Field(ge=1)


class ProfileSelection(Contract):
    expected_version: int = Field(ge=0)
    profile_binding_id: UUID | None


class ChromeCommandInput(Contract):
    request_id: UUID
    profile_binding_id: UUID
    selection_version: int = Field(ge=1)
    expected_profile_version: int = Field(ge=1)
    application_id: UUID
    packet_revision: int = Field(ge=1)
    action: Literal["open", "prepare", "pause", "resume", "cancel"]
    task_id: UUID | None = None
    expected_task_version: int | None = Field(default=None, ge=1)


def now():
    return datetime.now(timezone.utc)


def digest(secret):
    return hashlib.sha256(secret.get_secret_value().encode()).hexdigest()


async def records(session, prefix):
    await session.flush()
    return list(
        (
            await session.scalars(
                select(OwnerPreference)
                .where(OwnerPreference.key.startswith(prefix))
                .execution_options(populate_existing=True)
            )
        ).all()
    )


async def selection(session):
    row = await session.get(OwnerPreference, SELECTION, populate_existing=True)
    return row.value if row else {"version": 0, "profile_binding_id": None}


def online(value):
    return bool(
        value["connected"]
        and isinstance(value.get("window_id"), int)
        and value["window_id"] >= 0
        and (now() - datetime.fromisoformat(value["last_heartbeat"])).total_seconds()
        < LIVE_SECONDS
    )


def public(value, selected):
    return {
        k: value[k]
        for k in (
            "id",
            "label",
            "version",
            "connected",
            "last_heartbeat",
            "browser_session_id",
            "window_id",
            "commands_enabled",
        )
    } | {
        "selected": selected == value["id"],
        "status": "DISCONNECTED"
        if not value["connected"]
        else "CONNECTED"
        if online(value)
        else "PROFILE_OFFLINE",
    }


async def invalidate(session, identity, reason):
    from backend.app.browser import extension_tasks as tasks

    for task in await tasks.rows(session):
        if (
            task.value.get("profile_binding_id") == identity
            and task.value["state"] not in tasks.TERMINAL
        ):
            value = task.value
            if value["state"] == "FILLING":
                task.value = {
                    **value,
                    "verified_receipts": [
                        *value["verified_receipts"],
                        {
                            "plan_id": value["plan_id"],
                            "authorization_id": value["authorization_id"],
                            "packet_revision": value["packet_revision"],
                            "profile_version": value["profile_version"],
                            "verification_method": "unknown",
                            "state": "manual_required",
                            "results": [],
                            "reason": reason,
                            "recorded_at": now().isoformat(),
                            "submitted": False,
                        },
                    ][-50:],
                }
            stop_reason = (
                value.get("reason")
                if value.get("reason") in {"owner_pause", "global_stop"}
                else reason
            )
            tasks.move(
                session,
                task,
                "PAUSED",
                stop_reason,
                plan_id=None,
                authorization_id=None,
                browser_connection="disconnected",
                tab_active=False,
            )
    # Even plans prepared before a task exists belong to this profile. Switching
    # away and back must not revive an old exact-field review.
    for plan in await records(session, "fill_plan:"):
        if plan.value.get("profile_binding_id") == identity and plan.value.get(
            "state"
        ) in {"preview", "authorized"}:
            plan.value = {
                **plan.value,
                "state": "read_only",
                "approved_fields": [],
                "expires_at": now().isoformat(),
            }
    for command in await records(session, COMMAND):
        if (
            command.value["profile_binding_id"] == identity
            and command.value["state"] not in TERMINAL
        ):
            unknown = command.value["state"] in {"leased", "executing"}
            command.value = {
                **command.value,
                "state": "outcome_unknown" if unknown else "cancelled",
                "reason": reason,
                "version": command.value["version"] + 1,
            }


@timed("profile_authorization")
async def require_profile(session, command, *, selected=True, receipt=False, read_only=False):
    if not read_only:
        await store.memory_row(session, lock=True)
    keys = [PROFILE + str(command.profile_binding_id), FIXED_PROFILE, SELECTION]
    if command.chrome_command_id:
        keys.append(COMMAND + str(command.chrome_command_id))
    await session.flush()
    snapshot = {row.key: row for row in (await session.scalars(
        select(OwnerPreference).where(OwnerPreference.key.in_(keys))
        .execution_options(populate_existing=True)
    )).all()}
    row = snapshot.get(PROFILE + str(command.profile_binding_id))
    selected_value = snapshot.get(SELECTION)
    selected_value = selected_value.value if selected_value else {"version": 0, "profile_binding_id": None}
    if (
        not row
        or not command.profile_secret
        or not hmac.compare_digest(
            row.value["secret_hash"], digest(command.profile_secret)
        )
    ):
        raise ToolDenied("PROFILE_OFFLINE")
    if receipt:
        return row
    fixed = snapshot.get(FIXED_PROFILE)
    if selected and fixed and fixed.value["profile_binding_id"] != row.value["id"]:
        raise ToolDenied("PROFILE_OFFLINE")
    if not online(row.value):
        if not read_only:
            await invalidate(session, row.value["id"], "PROFILE_OFFLINE")
        raise ToolDenied("PROFILE_OFFLINE")
    if selected and selected_value["profile_binding_id"] != row.value["id"]:
        raise ToolDenied("PROFILE_NOT_SELECTED")
    if str(command.browser_session_id) != row.value["browser_session_id"]:
        raise ToolDenied("PROFILE_SESSION_CHANGED")
    if command.chrome_command_id and command.command not in NATIVE:
        lease = snapshot.get(COMMAND + str(command.chrome_command_id))
        value = lease.value if lease else {}
        if (value.get("state") != "executing"
                or value.get("version") != command.expected_command_version
                or value.get("lease_token") != str(command.command_lease_token)
                or value.get("profile_binding_id") != row.value["id"]
                or value.get("browser_session_id") != str(command.browser_session_id)
                or value.get("selection_version") != selected_value["version"]
                or value.get("expected_profile_version") != row.value["version"]
                or datetime.fromisoformat(value.get("expires_at", "1970-01-01T00:00:00+00:00")) <= now()
                or datetime.fromisoformat(value.get("lease_expires_at") or "1970-01-01T00:00:00+00:00") <= now()
                or (command.application_id and value.get("application_id") != str(command.application_id))
                or (value.get("action") == "prepare" and value.get("task_id") != str(command.task_id))):
            raise ToolDenied("profile_command_expired")
    return row


@timed("profile_status")
async def listing(session, settings):
    # The usual status read has no mutation. Only stale commands/tasks need
    # the owner fence; re-read under that fence before changing them.
    return await _listing(session, settings, locked=False)


async def _listing(session, settings, *, locked):
    from backend.app.browser import extension_tasks as tasks

    # One server statement gives this status read a coherent snapshot and
    # avoids five remote round trips while occupying the single business slot.
    # Each disjoint branch retains the existing records query semantics.
    await session.flush()
    snapshot = list((await session.scalars(
        select(OwnerPreference).from_statement(union_all(
            select(OwnerPreference).where(OwnerPreference.key == SELECTION),
            *(select(OwnerPreference).where(OwnerPreference.key.startswith(prefix))
              for prefix in (PROFILE, tasks.PREFIX, COMMAND, "ext_receipt:")),
        )).execution_options(populate_existing=True)
    )).all())
    selected = next((row.value for row in snapshot if row.key == SELECTION),
                    {"version": 0, "profile_binding_id": None})
    profiles = [row for row in snapshot if row.key.startswith(PROFILE)]
    tasks_now = [row for row in snapshot if row.key.startswith(tasks.PREFIX)]
    # UNION ALL does not guarantee row order. Bound history by creation time,
    # with a stable key tie-breaker, so a new command/receipt cannot disappear
    # behind older rows after a database scan or physical row order changes.
    commands_now = sorted(
        (row for row in snapshot if row.key.startswith(COMMAND)),
        key=lambda row: (row.created_at, row.key),
    )
    receipts_now = sorted(
        (row for row in snapshot if row.key.startswith("ext_receipt:")),
        key=lambda row: (row.created_at, row.key),
    )
    offline = [
        row for row in profiles
        if not online(row.value) and (
            any(
                task.value.get("profile_binding_id") == row.value["id"]
                and task.value["state"] not in tasks.TERMINAL | {"PAUSED"}
                for task in tasks_now
            )
            or any(
                cmd.value["profile_binding_id"] == row.value["id"]
                and cmd.value["state"] not in TERMINAL
                for cmd in commands_now
            )
        )
    ]
    expired = [
        item for item in commands_now
        if item.value["state"] not in TERMINAL
        and datetime.fromisoformat(item.value["expires_at"]) <= now()
    ]
    if (offline or expired) and not locked:
        await store.memory_row(session, lock=True)
        return await _listing(session, settings, locked=True)
    for row in offline:
        await invalidate(session, row.value["id"], "PROFILE_OFFLINE")
    for item in commands_now:
        value = item.value
        if (
            value["state"] not in TERMINAL
            and datetime.fromisoformat(value["expires_at"]) <= now()
        ):
            item.value = {
                **value,
                "state": "outcome_unknown"
                if value["state"] in {"leased", "executing"}
                else "expired",
                "reason": "command_expired",
                "version": value["version"] + 1,
            }
    return {
        "selection": selected,
        "profiles": [
            public(row.value, selected["profile_binding_id"]) for row in profiles
        ],
        "channel_available": settings.CHROME_PROFILE_COMMANDS_ENABLED,
        "receipts": [row.value for row in receipts_now][-30:],
        "commands": [
            {
                k: v
                for k, v in r.value.items()
                if k not in {"lease_token", "payload_hash"}
            }
            for r in commands_now
        ][-30:],
    }


async def select_profile(session, data):
    await store.memory_row(session, lock=True)
    current = await selection(session)
    if data.expected_version != current["version"]:
        raise ToolDenied("PROFILE_SELECTION_CONFLICT")
    identity = str(data.profile_binding_id) if data.profile_binding_id else None
    fixed = await session.get(OwnerPreference, FIXED_PROFILE)
    if identity and fixed and fixed.value["profile_binding_id"] != identity:
        raise ToolDenied("FIXED_PROFILE_REQUIRED")
    if identity:
        row = await session.get(OwnerPreference, PROFILE + identity)
        if not row or not row.value["connected"]:
            raise ToolDenied("PROFILE_OFFLINE")
    await invalidate(session, None, "profile_binding_required")
    if current["profile_binding_id"]:
        await invalidate(
            session, current["profile_binding_id"], "profile_selection_changed"
        )
    value = {"version": current["version"] + 1, "profile_binding_id": identity}
    row = await session.get(OwnerPreference, SELECTION)
    if row:
        row.value = value
    else:
        session.add(OwnerPreference(key=SELECTION, value=value))
    return value


async def disconnect(session, identity, version):
    await store.memory_row(session, lock=True)
    row = await session.get(
        OwnerPreference, PROFILE + str(identity), populate_existing=True
    )
    if not row or row.value["version"] != version:
        raise ToolDenied("PROFILE_REVISION_CONFLICT")
    row.value = {
        **row.value,
        "connected": False,
        "commands_enabled": False,
        "version": version + 1,
    }
    await invalidate(session, str(identity), "profile_disconnected")
    current = await selection(session)
    if current["profile_binding_id"] == str(identity):
        await select_profile(
            session,
            ProfileSelection(
                expected_version=current["version"], profile_binding_id=None
            ),
        )
    return {"disconnected": True, "submitted": False}


async def enqueue(session, settings, actor, data):
    from backend.app.browser import extension_tasks as tasks
    from backend.app.browser.service import FormService

    await store.memory_row(session, lock=True)
    if actor.channel not in {"owner", "telegram"} or (
        actor.channel == "telegram"
        and actor.identity != str(settings.TELEGRAM_OWNER_USER_ID)
    ):
        raise ToolDenied("owner_identity_required")
    previous = await session.get(OwnerPreference, COMMAND + str(data.request_id))
    payload_hash = hashlib.sha256(data.model_dump_json().encode()).hexdigest()
    if previous:
        if previous.value["payload_hash"] != payload_hash:
            raise ToolDenied("command_id_conflict")
        return previous.value
    selected = await selection(session)
    fixed = await session.get(OwnerPreference, FIXED_PROFILE)
    if fixed and fixed.value["profile_binding_id"] != str(data.profile_binding_id):
        raise ToolDenied("PROFILE_OFFLINE")
    if (
        data.selection_version != selected["version"]
        or str(data.profile_binding_id) != selected["profile_binding_id"]
    ):
        raise ToolDenied("PROFILE_SELECTION_CONFLICT")
    profile = await session.get(OwnerPreference, PROFILE + str(data.profile_binding_id))
    if not profile or not online(profile.value):
        if profile:
            await invalidate(session, profile.value["id"], "PROFILE_OFFLINE")
        raise ToolDenied("PROFILE_OFFLINE")
    if profile.value["version"] != data.expected_profile_version:
        raise ToolDenied("PROFILE_REVISION_CONFLICT")
    if (
        not settings.CHROME_PROFILE_COMMANDS_ENABLED
        or not profile.value["commands_enabled"]
    ):
        raise ToolDenied("PROFILE_COMMANDS_DISABLED")
    packet, _, destination = await FormService(session, settings).context(
        data.application_id, "manual_extension"
    )
    if packet.revision != data.packet_revision:
        raise ToolDenied("extension_task_context_stale")
    if data.action != "open":
        if not data.task_id:
            raise ToolDenied("extension_task_required")
        task = (await tasks.load(session, data.task_id)).value
        if (
            task["application_id"] != str(data.application_id)
            or task.get("profile_binding_id") != str(data.profile_binding_id)
            or task["version"] != data.expected_task_version
        ):
            raise ToolDenied("extension_task_revision_conflict")
    pending = [
        r for r in await records(session, COMMAND) if r.value["state"] not in TERMINAL
    ]
    if len(pending) >= 20:
        raise ToolDenied("profile_queue_full")
    value = {
        **data.model_dump(mode="json"),
        "id": str(data.request_id),
        "version": 1,
        "payload_hash": payload_hash,
        "actor": actor.channel,
        "state": "queued",
        "reason": None,
        "browser_session_id": profile.value["browser_session_id"],
        "destination": destination,
        "expires_at": (now() + timedelta(seconds=120)).isoformat(),
        "lease_expires_at": None,
        "lease_token": None,
        "submitted": False,
    }
    session.add(OwnerPreference(key=COMMAND + value["id"], value=value))
    return value


async def native(session, settings, actor, command):
    from backend.app.local_agent.contracts import Result

    if actor.channel != "chrome" or actor.identity != settings.CHROME_EXTENSION_ID:
        return Result(
            request_id=command.request_id,
            ok=False,
            capability="chrome_profile",
            error_code="extension_identity_required",
        )
    try:
        # No nested rollback: expiry/selection invalidation must survive a denial.
        await store.memory_row(session, lock=True)
        if command.command == "connect_chrome_profile":
            if (
                not command.profile_binding_id
                or not command.profile_secret
                or not command.browser_session_id
                or command.window_id is None
                or not command.profile_label
            ):
                raise ToolDenied("profile_connection_fields_required")
            row = await session.get(
                OwnerPreference, PROFILE + str(command.profile_binding_id)
            )
            if row and not hmac.compare_digest(
                row.value["secret_hash"], digest(command.profile_secret)
            ):
                raise ToolDenied("profile_identity_conflict")
            if not row:
                if len(await records(session, PROFILE)) >= 8:
                    raise ToolDenied("profile_limit_reached")
                row = OwnerPreference(
                    key=PROFILE + str(command.profile_binding_id), value={"version": 0}
                )
                session.add(row)
            if (row.value.get("browser_session_id")
                    and (row.value["browser_session_id"] != str(command.browser_session_id)
                         or row.value.get("window_id") != command.window_id)):
                from backend.app.execution.naukri_form_loss import session_replaced

                await session_replaced(session, str(command.profile_binding_id), row.value["browser_session_id"], settings,
                                       previous_window_id=row.value.get("window_id"),
                                       window_only=row.value["browser_session_id"] == str(command.browser_session_id))
            await invalidate(
                session, str(command.profile_binding_id), "profile_reconnected"
            )
            row.value = {
                "id": str(command.profile_binding_id),
                "owner": "primary",
                "native_host": "com.automated_apply.agent",
                "secret_hash": digest(command.profile_secret),
                "label": command.profile_label,
                "version": row.value["version"] + 1,
                "connected": True,
                "browser_session_id": str(command.browser_session_id),
                "window_id": command.window_id,
                "commands_enabled": False,
                "last_heartbeat": now().isoformat(),
            }
            data = {
                "profile": public(
                    row.value, (await selection(session))["profile_binding_id"]
                )
            }
        elif command.command == "heartbeat_chrome_profile":
            row = await require_profile(session, command, selected=False, receipt=True)
            if not row.value["connected"]:
                raise ToolDenied("PROFILE_OFFLINE")
            changed = row.value["browser_session_id"] != str(command.browser_session_id)
            window_changed = row.value.get("window_id") != command.window_id
            if not command.browser_session_id:
                raise ToolDenied("PROFILE_SESSION_CHANGED")
            enabled = (
                command.profile_commands_enabled is True
                and settings.CHROME_PROFILE_COMMANDS_ENABLED
            )
            if changed or (row.value["commands_enabled"] and not enabled):
                await invalidate(
                    session,
                    row.value["id"],
                    "browser_restart" if changed else "profile_commands_disabled",
                )
            if changed or window_changed:
                from backend.app.execution.naukri_form_loss import session_replaced

                await session_replaced(session, row.value["id"], row.value["browser_session_id"], settings,
                                       previous_window_id=row.value.get("window_id"), window_only=not changed)
            if changed:
                from backend.app.browser import extension_tasks as tasks

                for task in await tasks.rows(session):
                    if (
                        task.value.get("profile_binding_id") == row.value["id"]
                        and task.value["state"] not in tasks.TERMINAL
                    ):
                        tasks.move(
                            session,
                            task,
                            "PAUSED",
                            task.value.get("reason") or "browser_restart",
                            browser_session_id=str(command.browser_session_id),
                            tab_id=None,
                            window_id=command.window_id,
                            tab_active=False,
                            network_guard_active=False,
                            plan_id=None,
                            authorization_id=None,
                            browser_connection="disconnected",
                            counts={
                                **task.value["counts"],
                                "completed": 0,
                                "ready": 0,
                                "existing": 0,
                            },
                        )
            row.value = {
                **row.value,
                "browser_session_id": str(command.browser_session_id),
                "window_id": command.window_id,
                "last_heartbeat": now().isoformat(),
                "commands_enabled": enabled,
                "version": row.value["version"]
                + int(changed or window_changed or enabled != row.value["commands_enabled"]),
            }
            data = {
                "profile": public(
                    row.value, (await selection(session))["profile_binding_id"]
                )
            }
            if command.window_id is None:
                # A windowless heartbeat authenticates the extension, not an
                # available browser. Only current owner policy may permit an
                # inactive neutral window; employer work still needs a second
                # heartbeat with its actual window and normal queue admission.
                from backend.app.browser.profile_launcher import automation_active
                from backend.app.execution.naukri_identity import require

                allowed = False
                if (enabled and data["profile"]["selected"]
                        and await automation_active(session)):
                    try:
                        await require(session, profile_binding_id=row.value["id"])
                        allowed = True
                    except ToolDenied:
                        pass
                data["background_window_allowed"] = allowed
        elif command.command == "disconnect_chrome_profile":
            row = await require_profile(session, command, selected=False, receipt=True)
            data = await disconnect(
                session, row.value["id"], command.expected_profile_version
            )
        else:
            row = await require_profile(session, command)
            if (
                not settings.CHROME_PROFILE_COMMANDS_ENABLED
                or not row.value["commands_enabled"]
            ):
                raise ToolDenied("PROFILE_COMMANDS_DISABLED")
            current = await selection(session)
            commands = await records(session, COMMAND)
            for item in commands:
                value = item.value
                if (
                    value["state"] in TERMINAL
                    or value["profile_binding_id"] != row.value["id"]
                ):
                    continue
                expired = datetime.fromisoformat(value["expires_at"]) <= now()
                stale = (
                    value["selection_version"] != current["version"]
                    or value["browser_session_id"] != row.value["browser_session_id"]
                    or value["expected_profile_version"] != row.value["version"]
                )
                lease_expired = (
                    value["lease_expires_at"]
                    and datetime.fromisoformat(value["lease_expires_at"]) <= now()
                )
                if expired or stale or lease_expired:
                    item.value = {
                        **value,
                        "state": "outcome_unknown"
                        if value["state"] in {"leased", "executing"}
                        else "expired",
                        "reason": "expired_or_profile_changed",
                        "version": value["version"] + 1,
                    }
            if command.command == "poll_chrome_command":
                # A leased command is never redelivered. Ambiguous outcomes require manual review.
                pending = sorted(
                    (
                        item
                        for item in commands
                        if item.value["profile_binding_id"] == row.value["id"]
                        and item.value["state"] == "queued"
                    ),
                    key=lambda item: item.value["expires_at"],
                )
                busy = any(
                    item.value["profile_binding_id"] == row.value["id"]
                    and item.value["state"] in {"leased", "executing"}
                    for item in commands
                )
                item = pending[0] if pending and not busy else None
                if item:
                    item.value = {
                        **item.value,
                        "state": "leased",
                        "version": item.value["version"] + 1,
                        "lease_token": str(uuid4()),
                        "lease_expires_at": (now() + timedelta(seconds=90)).isoformat(),
                    }
                data = {"command": item.value if item else None}
            else:
                await session.flush()
                item = await session.get(
                    OwnerPreference,
                    COMMAND + str(command.chrome_command_id),
                    populate_existing=True,
                )
                if (
                    not item
                    or item.value["profile_binding_id"] != row.value["id"]
                    or item.value["lease_token"] != str(command.command_lease_token)
                    or item.value["version"] != command.expected_command_version
                ):
                    raise ToolDenied("profile_command_revision_conflict")
                value = item.value
                if command.command == "start_chrome_command":
                    if value["state"] != "leased":
                        raise ToolDenied("profile_command_expired")
                    from backend.app.browser.service import FormService

                    packet, _, destination = await FormService(
                        session, settings
                    ).context(UUID(value["application_id"]), "manual_extension")
                    if (
                        packet.revision != value["packet_revision"]
                        or destination != value["destination"]
                    ):
                        raise ToolDenied("extension_task_context_stale")
                    item.value = {
                        **value,
                        "state": "executing",
                        "version": value["version"] + 1,
                    }
                else:
                    if value["state"] not in {"leased", "executing"}:
                        raise ToolDenied("profile_command_expired")
                    item.value = {
                        **value,
                        "state": command.command_outcome or "outcome_unknown",
                        "reason": command.command_error,
                        "version": value["version"] + 1,
                    }
                data = {"command": item.value}
        await session.flush()
        return Result(
            request_id=command.request_id,
            ok=True,
            capability="chrome_profile",
            data={**data, "submitted": False},
        )
    except ValueError as exc:
        return Result(
            request_id=command.request_id,
            ok=False,
            capability="chrome_profile",
            error_code=str(exc)
            if isinstance(exc, ToolDenied)
            else "profile_context_rejected",
        )


async def enqueue_campaign(session, settings, campaign, job, *, inspect_only):
    """Natural-language commands default to Chrome; broad fill requests grant no fields."""
    from uuid import NAMESPACE_URL, uuid5

    from backend.app.local_agent.contracts import Actor
    from backend.app.models.application_packet import ApplicationPacket

    state = await listing(session, settings)
    profile = next((item for item in state["profiles"] if item["selected"]), None)
    if not profile or profile["status"] != "CONNECTED":
        return {
            "status": "PROFILE_OFFLINE",
            "reason": "selected_chrome_profile_has_no_fresh_connection",
            "submitted": False,
        }
    if not inspect_only:
        return {
            "status": "extension_field_approval_required",
            "reason": "Review and authorize exact fields in the selected Chrome extension.",
            "submitted": False,
        }
    packet = await session.scalar(
        select(ApplicationPacket).where(ApplicationPacket.job_id == job.id)
    )
    if not packet:
        return {
            "status": "needs_input",
            "missing_information": ["Prepare an application draft first."],
            "submitted": False,
        }
    channel, _, identity = campaign.actor.partition(":")
    data = ChromeCommandInput(
        request_id=uuid5(NAMESPACE_URL, f"chrome:campaign:{campaign.id}:{job.id}"),
        profile_binding_id=profile["id"],
        selection_version=state["selection"]["version"],
        expected_profile_version=profile["version"],
        application_id=packet.id,
        packet_revision=packet.revision,
        action="open",
    )
    try:
        command = await enqueue(
            session, settings, Actor(channel=channel, identity=identity), data
        )
        return {
            "status": "pending_chrome",
            "command_id": command["id"],
            "missing_information": [
                "Open is queued in selected Chrome. Inspect and review in the extension; no fields are authorized."
            ],
            "submitted": False,
        }
    except ToolDenied as exc:
        return {"status": str(exc), "submitted": False}
