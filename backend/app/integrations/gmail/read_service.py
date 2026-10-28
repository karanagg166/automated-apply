"""Explicit, bounded and restartable per-account Gmail reads; disabled by default."""

import asyncio
import hashlib
import re
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
from uuid import uuid4

from pydantic import EmailStr, Field, StrictBool, model_validator
from sqlalchemy import select, update

from backend.app.ai.schemas import Contract
from backend.app.core.urls import PublicHTTPSURL
from backend.app.dashboard.models import OwnerPreference
from backend.app.integrations.connection_service import (
    ConnectionService,
    account_output,
)
from backend.app.integrations.gmail.read_client import GmailReadClient, content_evidence
from backend.app.integrations.google_oauth import READ_SCOPES, SCOPES
from backend.app.integrations.token_store import ConnectionError
from backend.app.models.connected_account import GmailReadAccount
from backend.app.services.discovery_budget import insert_for

POLICY = "gmail_sync:"
MESSAGE = "gmail_msg:"
TOPIC = re.compile(
    r"\b(?:job|jobs|application|interview|hiring|vacancy|career|recruit(?:er|ing|ment)?|position|follow[ -]?up)\b",
    re.I,
)


class ReadConnect(Contract):
    expected_email: EmailStr
    read_body: StrictBool = False
    account_consent: StrictBool

    @model_validator(mode="after")
    def consent(self):
        if not self.account_consent:
            raise ValueError("Account-level consent required")
        return self


class ReadPolicy(Contract):
    expected_version: int = Field(ge=0)
    enabled: StrictBool = False
    sender_allowlist: list[EmailStr] = Field(default_factory=list, max_length=25)
    label_allowlist: list[str] = Field(default_factory=list, max_length=10)
    query_allowlist: str | None = Field(None, min_length=1, max_length=300)
    read_body: StrictBool = False
    body_purpose: str | None = Field(None, min_length=10, max_length=300)
    backfill_days: int = Field(7, ge=1, le=30)
    retention_days: int = Field(14, ge=1, le=90)
    max_pages: int = Field(1, ge=1, le=3)

    @model_validator(mode="after")
    def selection(self):
        if any(
            not re.fullmatch(r"Label_[A-Za-z0-9_-]{1,100}", label)
            for label in self.label_allowlist
        ):
            raise ValueError("Choose explicit custom job-related labels")
        if self.enabled and not (self.sender_allowlist or self.label_allowlist):
            raise ValueError("A sender or curated label allowlist is required")
        if self.enabled and not self.read_body and not self.label_allowlist:
            raise ValueError(
                "Metadata sync requires a custom label; Gmail metadata scope does not support q"
            )
        if self.read_body and not self.body_purpose:
            raise ValueError("Explain why headers do not suffice")
        if self.query_allowlist and not self.read_body:
            raise ValueError("Gmail metadata scope does not support q")
        return self


class LeadImport(Contract):
    job_url: PublicHTTPSURL
    title: str = Field(min_length=1, max_length=255)
    company_name: str | None = Field(None, min_length=1, max_length=255)
    company_domain: str | None = Field(None, max_length=255)
    reviewed_job_evidence: StrictBool

    @model_validator(mode="after")
    def reviewed(self):
        if not self.reviewed_job_evidence:
            raise ValueError("Review the actual vacancy and provide its factual title")
        return self


class GmailReadService:
    def __init__(self, session, settings, *, google=None, client=None):
        self.session, self.settings, self.google, self.client = (
            session,
            settings,
            google,
            client,
        )

    def connection(self, account_id):
        return ConnectionService(
            self.session,
            self.settings,
            self.google,
            read_only=True,
            account_id=account_id,
        )

    async def account(self, account_id, lock=False):
        account = await self.connection(account_id).account(lock=lock)
        if not account:
            raise ConnectionError("gmail_read_account_not_found")
        return account

    async def accounts(self):
        from backend.app.integrations.gmail.schema import require_read_schema

        await require_read_schema(self.session, self.settings)
        accounts = (
            await self.session.scalars(
                select(GmailReadAccount)
                .where(
                    GmailReadAccount.provider == "gmail",
                )
                .order_by(GmailReadAccount.connected_at, GmailReadAccount.id)
            )
        ).all()
        return [await self.status(account.id) for account in accounts]

    async def policy_row(self, account_id, lock=False):
        return await self.session.get(
            OwnerPreference,
            POLICY + account_id.hex,
            with_for_update=lock,
            populate_existing=True,
        )

    async def status(self, account_id):
        account = await self.account(account_id)
        row = await self.policy_row(account_id)
        value = (
            row.value
            if row
            else {"version": 0, "status": "selection_required", "policy": None}
        )
        return {
            **account_output(account),
            "sync": {
                k: v
                for k, v in value.items()
                if k not in {"page_token", "lease_id", "lease_until"}
            },
            "sync_enabled": self.settings.GMAIL_READ_SYNC_ENABLED,
            "body_access_reviewed": self.settings.GMAIL_READ_BODY_REVIEWED,
        }

    async def configure(self, account_id, policy):
        account = await self.account(account_id, lock=True)
        if policy.read_body and (
            set(account.granted_scopes) != READ_SCOPES
            or not self.settings.GMAIL_READ_BODY_REVIEWED
        ):
            raise ConnectionError("gmail_body_access_review_required")
        if set(account.granted_scopes) not in (SCOPES, READ_SCOPES):
            raise ConnectionError("gmail_readonly_scope_required")
        row = await self.policy_row(account_id, lock=True)
        version = row.value["version"] if row else 0
        if version != policy.expected_version:
            raise ConnectionError("gmail_sync_version_conflict")
        value = {
            "account_id": str(account_id),
            "version": version + 1,
            "policy": policy.model_dump(mode="json", exclude={"expected_version"}),
            "status": "ready" if policy.enabled else "disabled",
            "window_start": None,
            "window_end": None,
            "checkpoint": None,
        }
        if row:
            changed = await self.session.execute(
                update(OwnerPreference)
                .where(
                    OwnerPreference.key == row.key,
                    OwnerPreference.value["version"].as_integer() == version,
                )
                .values(value=value)
                .execution_options(synchronize_session=False)
            )
            if changed.rowcount != 1:
                raise ConnectionError("gmail_sync_version_conflict")
        else:
            inserted = (
                await self.session.execute(
                    insert_for(self.session)(OwnerPreference)
                    .values(
                        key=POLICY + account_id.hex,
                        value=value,
                    )
                    .on_conflict_do_nothing()
                    .returning(OwnerPreference.key)
                )
            ).scalar_one_or_none()
            if inserted is None:
                raise ConnectionError("gmail_sync_version_conflict")
        await self.session.commit()
        return await self.status(account_id)

    async def purge(self, account_id, *, all_messages=False):
        query = update(OwnerPreference).where(
            OwnerPreference.key.startswith(MESSAGE),
            OwnerPreference.value["account_id"].as_string() == str(account_id),
        )
        if not all_messages:
            query = query.where(
                OwnerPreference.value["expires_at"].as_string()
                <= datetime.now(timezone.utc).isoformat()
            )
        await self.session.execute(query.values(value={"status": "purged"}))

    async def disconnect(self, account_id):
        await self.account(account_id)
        result = await self.connection(account_id).disconnect()
        await self.purge(account_id, all_messages=True)
        row = await self.policy_row(account_id, lock=True)
        if row:
            row.value = {
                "version": row.value["version"] + 1,
                "status": "disabled",
                "policy": {"enabled": False},
            }
        await self.session.commit()
        return result

    async def evidence(self, account_id, offset=0, limit=25):
        await self.account(account_id)
        await self.purge(account_id)
        await self.session.commit()
        rows = (
            await self.session.scalars(
                select(OwnerPreference)
                .where(
                    OwnerPreference.key.startswith(MESSAGE),
                    OwnerPreference.value["account_id"].as_string() == str(account_id),
                )
                .order_by(OwnerPreference.created_at.desc(), OwnerPreference.key)
                .offset(offset)
                .limit(limit)
            )
        ).all()
        return [r.value for r in rows]

    async def sync(self, account_id):
        if not self.settings.GMAIL_READ_SYNC_ENABLED:
            raise ConnectionError("gmail_read_sync_disabled")
        connection = self.connection(account_id)
        # Refresh commits before taking the account lock used by sync/disconnect/configuration.
        token = await connection.access_token()
        account = await self.account(account_id, lock=True)
        if account.status != "connected":
            raise ConnectionError("gmail_not_connected")
        if set(account.granted_scopes) not in (SCOPES, READ_SCOPES):
            raise ConnectionError("gmail_readonly_scope_required")
        row = await self.policy_row(account_id, lock=True)
        if not row or not row.value.get("policy", {}).get("enabled"):
            raise ConnectionError("gmail_job_selection_required")
        value = dict(row.value)
        if value.get("lease_until") and datetime.fromisoformat(
            value["lease_until"]
        ) > datetime.now(timezone.utc):
            raise ConnectionError("gmail_sync_already_running")
        policy = ReadPolicy(expected_version=value["version"], **value["policy"])
        if policy.read_body and (
            set(account.granted_scopes) != READ_SCOPES
            or not self.settings.GMAIL_READ_BODY_REVIEWED
        ):
            raise ConnectionError("gmail_body_access_review_required")
        # Claim a durable lease, then release the pool slot before bounded HTTP.
        end = (
            datetime.fromisoformat(value["window_end"])
            if value.get("window_end")
            else datetime.now(timezone.utc)
        )
        start = (
            datetime.fromisoformat(value["window_start"])
            if value.get("window_start")
            else max(
                end - timedelta(days=policy.backfill_days),
                datetime.fromisoformat(value["checkpoint"]) - timedelta(minutes=5)
                if value.get("checkpoint")
                else end - timedelta(days=policy.backfill_days),
            )
        )
        value.update(
            window_start=start.isoformat(), window_end=end.isoformat(), status="syncing"
        )
        lease = uuid4().hex
        generation = account.token_generation
        value.update(
            lease_id=lease,
            lease_until=(
                datetime.now(timezone.utc) + timedelta(seconds=120)
            ).isoformat(),
        )
        row.value = value
        await self.session.commit()
        reader = GmailReadClient(token, self.client)
        inserted = scanned = 0
        records = []

        async def guard():
            current = await self.account(account_id)
            state = await self.policy_row(account_id)
            valid = (
                current.status == "connected"
                and current.token_generation == generation
                and state
                and state.value.get("lease_id") == lease
                and state.value["version"] == value["version"]
            )
            await self.session.commit()  # no runtime pool slot or row lock across HTTP
            if not valid:
                raise ConnectionError("gmail_sync_account_or_selection_changed")

        try:
            async with asyncio.timeout(90):
                for _ in range(policy.max_pages):
                    query = None
                    if policy.read_body:
                        query = f"after:{int(start.timestamp())} before:{int(end.timestamp()) + 1}"
                        if policy.sender_allowlist:
                            query += (
                                " {"
                                + " ".join(
                                    "from:" + str(s) for s in policy.sender_allowlist
                                )
                                + "}"
                            )
                        if policy.query_allowlist:
                            query += " (" + policy.query_allowlist + ")"
                    await guard()
                    page = await reader.messages(
                        labels=policy.label_allowlist,
                        query=query,
                        page_token=value.get("page_token"),
                    )
                    messages = page.get("messages", [])
                    if not isinstance(messages, list) or len(messages) > 25:
                        raise ConnectionError("gmail_read_invalid_response")
                    for entry in messages:
                        if not isinstance(entry, dict):
                            raise ConnectionError("gmail_read_invalid_response")
                        message_id = entry.get("id")
                        digest = hashlib.sha256(
                            f"{account_id}:{message_id}".encode()
                        ).hexdigest()[:32]
                        prior = await self.session.get(
                            OwnerPreference, MESSAGE + digest
                        )
                        await self.session.commit()
                        if prior or any(r["id"] == digest for r in records):
                            continue
                        await guard()
                        metadata = await reader.message(message_id)
                        scanned += 1
                        if metadata.get("id") != message_id:
                            raise ConnectionError("gmail_message_identity_mismatch")
                        try:
                            received = datetime.fromtimestamp(
                                int(metadata["internalDate"]) / 1000, timezone.utc
                            )
                            headers = metadata["payload"]["headers"]
                            # Duplicate From/Subject headers are ambiguous and must not be trusted.
                            by_name = {}
                            for header in headers:
                                name = header["name"].casefold()
                                if name in {"from", "subject"} and name in by_name:
                                    raise ValueError("duplicate header")
                                by_name[name] = header["value"]
                            sender = parseaddr(by_name.get("from", ""))[1].casefold()
                            subject = by_name.get("subject", "")
                            if len(subject) > 4000 or not isinstance(sender, str):
                                raise ValueError("invalid header")
                        except (
                            KeyError,
                            TypeError,
                            ValueError,
                            OverflowError,
                            OSError,
                        ):
                            raise ConnectionError(
                                "gmail_message_metadata_invalid"
                            ) from None
                        if not start <= received <= end or not TOPIC.search(subject):
                            continue
                        if policy.sender_allowlist and sender not in {
                            str(s).casefold() for s in policy.sender_allowlist
                        }:
                            continue
                        if policy.label_allowlist and not set(
                            policy.label_allowlist
                        ).issubset(set(metadata.get("labelIds", []))):
                            continue
                        evidence = {
                            "links": [],
                            "signals": [],
                            "verification_status": "requires_review",
                            "submission_confirmed": False,
                            "status_confirmed": False,
                            "signal_basis": "metadata_only_no_status_inference",
                        }
                        if policy.read_body:
                            await guard()
                            message = await reader.message(message_id, body=True)
                            if message.get("id") != message_id or message.get(
                                "threadId"
                            ) != metadata.get("threadId"):
                                raise ConnectionError("gmail_message_identity_mismatch")
                            evidence = content_evidence(message.get("payload", {}))
                        thread = metadata.get("threadId")
                        if not isinstance(thread, str) or not re.fullmatch(
                            r"[A-Za-z0-9_-]{1,200}", thread
                        ):
                            raise ConnectionError("gmail_thread_id_invalid")
                        record = {
                            "id": digest,
                            "account_id": str(account_id),
                            "message_id": message_id,
                            "thread_id": thread,
                            "received_at": received.isoformat(),
                            "observed_at": datetime.now(timezone.utc).isoformat(),
                            "expires_at": (
                                datetime.now(timezone.utc)
                                + timedelta(days=policy.retention_days)
                            ).isoformat(),
                            "subject_digest": hashlib.sha256(
                                subject.encode()
                            ).hexdigest(),
                            **evidence,
                        }
                        records.append(record)
                    next_token = page.get("nextPageToken")
                    if next_token is not None and (
                        not isinstance(next_token, str)
                        or len(next_token) > 2048
                        or next_token == value.get("page_token")
                    ):
                        raise ConnectionError("gmail_page_token_invalid")
                    value["page_token"] = next_token
                    if not next_token:
                        value.update(
                            checkpoint=end.isoformat(),
                            window_start=None,
                            window_end=None,
                        )
                        break
            value.update(
                status="partial" if value.get("page_token") else "completed",
                last_sync_at=datetime.now(timezone.utc).isoformat(),
                inserted=inserted,
                scanned=scanned,
                last_error=None,
            )
        except (ConnectionError, TimeoutError) as exc:
            if isinstance(exc, TimeoutError):
                exc = ConnectionError("gmail_sync_timeout")
            # All selected evidence and the page checkpoint commit atomically. A failed
            # page may repeat GETs; uniqueness protects imported evidence after restart.
            await self.session.rollback()
            row = await self.policy_row(account_id, lock=True)
            if row and row.value.get("lease_id") == lease:
                row.value = {
                    **row.value,
                    "lease_id": None,
                    "lease_until": None,
                    "status": "reauthorization_required"
                    if str(exc) == "gmail_read_permission_required"
                    else "failed",
                    "last_error": str(exc),
                }
                await self.session.commit()
            raise exc
        current = await self.account(account_id, lock=True)
        row = await self.policy_row(account_id, lock=True)
        if (
            current.status != "connected"
            or current.token_generation != generation
            or not row
            or row.value.get("lease_id") != lease
            or row.value["version"] != value["version"]
        ):
            await self.session.rollback()
            raise ConnectionError("gmail_sync_account_or_selection_changed")
        for record in records:
            added = (
                await self.session.execute(
                    insert_for(self.session)(OwnerPreference)
                    .values(
                        key=MESSAGE + record["id"],
                        value=record,
                    )
                    .on_conflict_do_nothing()
                    .returning(OwnerPreference.key)
                )
            ).scalar_one_or_none()
            inserted += added is not None
        value.update(inserted=inserted, lease_id=None, lease_until=None)
        row.value = value
        await self.purge(account_id)
        await self.session.commit()
        return await self.status(account_id)

    async def leads(self, account_id, offset=0, limit=25):
        evidence = await self.evidence(account_id, offset, limit)
        unique = {}
        for message in evidence:
            for url in message.get("links", []):
                key = hashlib.sha256((str(account_id) + url).encode()).hexdigest()[:32]
                lead = unique.setdefault(
                    key,
                    {
                        "id": key,
                        "url": url,
                        "evidence_ids": [],
                        "verification_status": "requires_review",
                        "confirmed_vacancy": False,
                    },
                )
                lead["evidence_ids"].append(message["id"])
                imported = message.get("imported_leads", {}).get(url, [])
                lead["imported_job_ids"] = sorted(set(lead.get("imported_job_ids", []) + imported))
                lead["import_state"] = (
                    "imported" if lead["imported_job_ids"] else
                    "legacy_message_import_unknown" if (
                        lead.get("import_state") == "legacy_message_import_unknown"
                        or set(message.get("imported_job_ids", [])) - {
                            job_id for ids in message.get("imported_leads", {}).values()
                            for job_id in ids
                        }
                    ) else
                    "not_imported"
                )
        return list(unique.values())

    async def import_lead(self, account_id, evidence_id, data):
        from backend.app.schemas.normalized_job import NormalizedJob
        from backend.app.services.job_ingestion import JobIngestionService

        await self.account(account_id, lock=True)
        if not re.fullmatch(r"[a-f0-9]{32}", evidence_id):
            raise ConnectionError("gmail_evidence_not_found")
        row = await self.session.get(
            OwnerPreference,
            MESSAGE + evidence_id,
            with_for_update=True,
            populate_existing=True,
        )
        if (
            not row
            or row.value.get("account_id") != str(account_id)
            or row.value.get("expires_at", "") <= datetime.now(timezone.utc).isoformat()
        ):
            raise ConnectionError("gmail_evidence_not_found")
        url = str(data.job_url)
        if url not in row.value.get("links", []):
            raise ConnectionError("gmail_lead_not_in_selected_evidence")
        identity = hashlib.sha256(url.encode()).hexdigest()
        result = await JobIngestionService(self.session).ingest_jobs(
            [
                NormalizedJob(
                    source_name="gmail_alert",
                    source_job_id="reviewed_email_" + identity,
                    original_url=url,
                    title=data.title,
                    company_name=data.company_name,
                    company_domain=data.company_domain,
                    source_verification_status="requires_review",
                    is_confirmed_current=False,
                    data_provenance={"method": "owner_reviewed_email_lead"},
                )
            ]
        )
        if result.failed_count or result.rejected_count or len(result.job_ids) != 1:
            # A single reviewed lead is successful only after durable ingestion.
            # Keep its evidence unmarked so the owner can review and retry.
            raise ConnectionError("gmail_lead_import_failed")
        row.value = {
            **row.value,
            "imported_leads": {**row.value.get("imported_leads", {}), url: result.job_ids},
            "imported_job_ids": sorted(
                set(row.value.get("imported_job_ids", []) + result.job_ids)
            ),
        }
        await self.session.commit()
        return result
