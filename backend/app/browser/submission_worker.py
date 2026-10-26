"""No replay after dispatch intent. Recovery reads evidence or leaves uncertainty."""

from uuid import UUID

import httpx

from backend.app.agent.tools import ToolDenied
from backend.app.browser.submission import SubmissionService


class SubmissionWorker:
    def __init__(self, factory, settings, driver):
        self.factory, self.settings, self.driver = factory, settings, driver

    async def run_once(self):
        async with self.factory() as session:
            service = SubmissionService(session, self.settings)
            claimed = await service.claim()
            await (
                session.commit()
            )  # Durable single-use dispatch intent precedes all browser IO.
        if not claimed:
            return None
        preflight_failed, response = False, None
        try:
            async with self.factory() as session:
                service = SubmissionService(session, self.settings)
                _, current = await service.fenced(claimed.application_id, claimed.fence)
                await service.fresh(current)
                # Holding this lock linearizes cancellation with the single browser dispatch.
                # It is bounded by the driver's 15s network timeout and 30s RPC timeout.
                result = await self.driver.call(
                    "submit_application",
                    document_id=current.document_id,
                    document_digest=current.document_digest,
                    idempotency_key=str(current.idempotency_key),
                    expires_at=current.expires_at,
                )
                preflight_failed = result.get("preflight_failed") is True
                response = (
                    result.get("response") if not result.get("violations") else None
                )
        except Exception:
            response = None  # Lost RPCs are ambiguous after durable dispatch intent.
            if hasattr(self.driver, "abort"):
                await self.driver.abort()  # A late JSON-line response must never become another command's reply.
        async with self.factory() as session:
            service = SubmissionService(session, self.settings)
            try:
                s = await service.complete(
                    claimed.application_id,
                    claimed.fence,
                    response,
                    preflight_failed=preflight_failed,
                )
                await session.commit()
                return {
                    "status": s.state,
                    "application_id": str(s.application_id),
                    "evidence": s.evidence.model_dump(mode="json")
                    if s.evidence
                    else None,
                }
            except ToolDenied:
                return {
                    "status": "submission_uncertain",
                    "application_id": str(claimed.application_id),
                }

    async def reconcile(self, application_id: UUID):
        async with self.factory() as session:
            service = SubmissionService(session, self.settings)
            _, s = await service.load(application_id)
            service.validate_contract(s)
            if s.state != "submission_uncertain":
                return s
            url = s.receipt_url
        response = None
        try:
            # This URL is server-derived from an exact numeric loopback fixture origin.
            async with httpx.AsyncClient(
                timeout=5, follow_redirects=False, trust_env=False
            ) as client:
                async with client.stream(
                    "GET", url, headers={"Accept": "application/json"}
                ) as r:
                    raw = bytearray()
                    async for part in r.aiter_bytes():
                        raw.extend(part)
                        if len(raw) > 65536:
                            raise ValueError("receipt_too_large")
                    response = {
                        "url": str(r.url),
                        "status": r.status_code,
                        "content_type": r.headers.get("content-type", ""),
                        "body": raw.decode("utf8"),
                    }
        except (httpx.HTTPError, ValueError):
            pass
        async with self.factory() as session:
            result = await SubmissionService(session, self.settings).reconcile(
                application_id, response
            )
            await session.commit()
            return result
