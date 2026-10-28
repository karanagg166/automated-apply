"""Owner-reviewed application history, separate from expiring mailbox evidence."""

import hashlib
import re
from datetime import datetime, timedelta, timezone
from uuid import UUID

from pydantic import Field, StrictBool, model_validator
from sqlalchemy import select, update

from backend.app.ai.schemas import Contract
from backend.app.core.urls import PublicHTTPSURL
from backend.app.dashboard.models import OwnerPreference
from backend.app.integrations.token_store import ConnectionError

PREFIX = "gmail_application:"


def canonical_url(value):
    if not value:
        return None
    from backend.app.core.job_urls import ats_job_url, canonical_job_url
    try:
        return ats_job_url(str(value)) or canonical_job_url(str(value))
    except ValueError:
        return None


class HistoryReview(Contract):
    expected_version: int = Field(ge=0)
    company: str = Field(min_length=1, max_length=200)
    role: str = Field(min_length=1, max_length=200)
    applied_at: datetime
    job_url: PublicHTTPSURL | None = None
    evidence: dict[UUID, list[str]] = Field(min_length=1, max_length=2)
    status: str = Field(pattern="^(applied|recruiter_response|interview|rejected|status_update|uncertain)$")
    confirmed_application: StrictBool
    retention_days: int = Field(ge=14, le=7300)
    owner_reviewed: StrictBool

    @model_validator(mode="after")
    def reviewed(self):
        if not self.owner_reviewed or not self.company.strip() or not self.role.strip():
            raise ValueError("Review company, role, date and evidence")
        if self.applied_at.tzinfo is None or self.applied_at > datetime.now(timezone.utc):
            raise ValueError("Choose an observed application date with timezone")
        if any(not ids or len(ids) > 25 or any(not re.fullmatch(r"[a-f0-9]{32}", i) for i in ids)
               for ids in self.evidence.values()):
            raise ValueError("Select bounded message evidence")
        return self


async def reviewed_history(session):
    from backend.app.knowledge.missing_input import storage_available

    # Earlier migration verifiers predate private owner/history storage. There
    # cannot be retained reviewed history in an absent store; do not issue a
    # failing SELECT or register worker models to perform this optional read.
    if not await storage_available(session):
        return []
    rows = (await session.scalars(select(OwnerPreference).where(
        OwnerPreference.key.startswith(PREFIX)
    ).limit(5001))).all()
    if len(rows) > 5000:
        raise ConnectionError("gmail_history_limit_reached")
    current = datetime.now(timezone.utc).isoformat()
    return [r.value for r in rows if r.value.get("expires_at", "") > current and not r.value.get("deleted")]


def previously_applied(job, company, history):
    if not history:
        return False
    name = (company.name if company else "").strip().casefold()
    urls = {canonical_url(getattr(job, key, None)) for key in ("job_url", "application_url")}
    urls.discard(None)
    return any(row.get("confirmed_application") and (
        row.get("job_url") in urls or
        ((not row.get("job_url") or not urls) and name and row.get("company", "").strip().casefold() == name
         and row.get("role", "").strip().casefold() == job.title.strip().casefold())
    ) for row in history)


class ApplicationHistoryService:
    def __init__(self, session):
        self.session = session

    async def list(self):
        await self.session.execute(update(OwnerPreference).where(
            OwnerPreference.key.startswith("gmail_msg:"),
            OwnerPreference.value["expires_at"].as_string() <= datetime.now(timezone.utc).isoformat()
        ).values(value={"status": "purged"}))
        # Expired structured records are scrubbed independently of the raw 14-day store.
        rows = (await self.session.scalars(select(OwnerPreference).where(
            OwnerPreference.key.startswith(PREFIX)
        ).limit(5001))).all()
        if len(rows) > 5000:
            raise ConnectionError("gmail_history_limit_reached")
        current = datetime.now(timezone.utc).isoformat()
        result = []
        for row in rows:
            if row.value.get("expires_at", "") <= current or row.value.get("deleted"):
                row.value = {"deleted": True, "version": row.value.get("version", 0) + 1}
            else:
                result.append(row.value)
        await self.session.commit()
        return sorted(result, key=lambda r: datetime.fromisoformat(r["applied_at"]), reverse=True)

    async def review(self, data):
        from backend.app.integrations.gmail.read_service import MESSAGE

        identity = canonical_url(data.job_url) or (data.company.strip().casefold() + "\n" + data.role.strip().casefold())
        key = hashlib.sha256(identity.encode()).hexdigest()[:32]
        # Serialize same-opportunity reviews across independent mailboxes/processes.
        if self.session.get_bind().dialect.name == "postgresql":
            from sqlalchemy import text
            await self.session.execute(text("SELECT pg_advisory_xact_lock(407006, 2)"))
        existing = await reviewed_history(self.session)
        duplicate = next((item for item in existing if (
            item.get("job_url") == canonical_url(data.job_url) if data.job_url and item.get("job_url") else
            item["company"].strip().casefold() == data.company.strip().casefold()
            and item["role"].strip().casefold() == data.role.strip().casefold()
        )), None)
        if duplicate:
            key = duplicate["id"]
        row = await self.session.get(OwnerPreference, PREFIX + key, with_for_update=True, populate_existing=True)
        old = row.value if row else {}
        if old.get("version", 0) != data.expected_version:
            raise ConnectionError("gmail_history_version_conflict")
        evidence = {account: list(ids) for account, ids in old.get("evidence", {}).items()}
        for account_id, ids in data.evidence.items():
            for evidence_id in ids:
                item = await self.session.get(OwnerPreference, MESSAGE + evidence_id)
                if (not item or item.value.get("account_id") != str(account_id)
                        or item.value.get("expires_at", "") <= datetime.now(timezone.utc).isoformat()):
                    raise ConnectionError("gmail_history_evidence_unavailable")
            evidence[str(account_id)] = sorted(set(evidence.get(str(account_id), []) + ids))[:100]
        current = datetime.now(timezone.utc)
        value = {"id": key, "version": old.get("version", 0) + 1,
                 **data.model_dump(mode="json", exclude={"expected_version", "owner_reviewed", "evidence"}),
                 "company": data.company.strip(), "role": data.role.strip(),
                 "job_url": canonical_url(data.job_url) or old.get("job_url"), "evidence": evidence,
                 "confirmed_application": data.confirmed_application or old.get("confirmed_application", False),
                 "status": old.get("status", "uncertain") if data.status == "uncertain" else data.status,
                 "reviewed_at": current.isoformat(), "expires_at": (current + timedelta(days=data.retention_days)).isoformat()}
        if row:
            row.value = value
        else:
            self.session.add(OwnerPreference(key=PREFIX + key, value=value))
        await self.session.commit()
        return value

    async def forget(self, history_id, version):
        row = await self.session.get(OwnerPreference, PREFIX + history_id, with_for_update=True, populate_existing=True)
        if not row or row.value.get("version") != version:
            raise ConnectionError("gmail_history_version_conflict")
        row.value = {"deleted": True, "version": version + 1}
        await self.session.commit()
        return {"deleted": True}

    async def retention(self, history_id, version, days):
        row = await self.session.get(OwnerPreference, PREFIX + history_id, with_for_update=True, populate_existing=True)
        if not row or row.value.get("version") != version or row.value.get("deleted"):
            raise ConnectionError("gmail_history_version_conflict")
        row.value = {**row.value, "version": version + 1, "retention_days": days,
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()}
        await self.session.commit()
        return row.value
