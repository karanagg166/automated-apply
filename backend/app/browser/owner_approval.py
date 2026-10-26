"""Separate dashboard owner intent from delegated API/CLI bearer access.

The authenticated, CSRF-protected BFF signs only exact owner approval/consent bodies.
AGY receives the application bearer, never this separate server-side signing key.
"""

import hashlib
import hmac
import re
import time

from fastapi import Depends, HTTPException, Request
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.dashboard.models import OwnerPreference
from backend.app.db.session import get_db_session


def approval_header(key, path, body, *, nonce, timestamp):
    message = "\n".join(
        ["POST", path, str(timestamp), nonce, hashlib.sha256(body).hexdigest()]
    )
    signature = hmac.new(key.encode(), message.encode(), hashlib.sha256).hexdigest()
    return f"v1:{timestamp}:{nonce}:{signature}"


async def require_owner_approval(
    request: Request, session: AsyncSession = Depends(get_db_session)
):
    key = get_settings().BROWSER_OWNER_APPROVAL_KEY
    if not key:
        raise HTTPException(
            503,
            "Configure a separate dashboard owner approval key before authorizing consent or submission",
        )
    supplied = request.headers.get("X-Browser-Owner-Approval", "")
    match = re.fullmatch(r"v1:(\d{10}):([a-f0-9]{32}):([a-f0-9]{64})", supplied)
    if not match or abs(time.time() - int(match[1])) > 30:
        raise HTTPException(
            403, "Submission authorization requires current dashboard owner approval"
        )
    expected = approval_header(
        key.get_secret_value(),
        request.url.path,
        await request.body(),
        nonce=match[2],
        timestamp=int(match[1]),
    )
    if not hmac.compare_digest(expected, supplied):
        raise HTTPException(403, "Owner approval does not match this exact operation")
    insert = (
        pg_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert
    )
    claimed = await session.scalar(
        insert(OwnerPreference)
        .values(key="owner-proof:" + match[2], value={"operation": request.url.path})
        .on_conflict_do_nothing()
        .returning(OwnerPreference.key)
    )
    if not claimed:
        raise HTTPException(
            403, "Owner approval was already used; review again in the dashboard"
        )
