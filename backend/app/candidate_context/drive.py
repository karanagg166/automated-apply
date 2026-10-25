"""Google Drive v3 adapter with injected, account-bound authorization.

Only fixed Google API endpoints are used. Sharing URLs, redirects and provider
response URLs never become request targets. The caller provides credentials only
through a token callback after verifying Drive scope and exact owner/file access.
"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import datetime

import httpx
from pydantic import Field, SecretStr, ValidationError

from backend.app.candidate_context.common import ContextError, Contract
from backend.app.candidate_context.configuration import ResumeSource
from backend.app.candidate_context.resume import (
    MAX_PDF_BYTES,
    DriveMetadata,
    PDFDownload,
)

DRIVE_READ_SCOPES = frozenset(
    {
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/drive.readonly",
    }
)


class DriveAuthorization(Contract):
    account_ref: str = Field(min_length=1, max_length=120)
    allowed_file_ids: frozenset[str] = Field(min_length=1, max_length=50)
    scopes: frozenset[str]
    access_token: SecretStr = Field(repr=False)


class AuthorizedDriveClient:
    def __init__(
        self,
        authorization: Callable[[], Awaitable[DriveAuthorization]],
        *,
        client: httpx.AsyncClient | None = None,
    ):
        self._authorization, self._client = authorization, client

    async def _request(self, source: ResumeSource, *, media: bool):
        authorization = await self._authorization()
        if source.account_ref != authorization.account_ref:
            raise ContextError("drive_account_mismatch")
        if (
            source.file_id not in authorization.allowed_file_ids
            or not authorization.scopes & DRIVE_READ_SCOPES
        ):
            raise ContextError("drive_source_not_authorized")
        token = authorization.access_token.get_secret_value()
        if not token or any(ord(c) <= 32 for c in token):
            raise ContextError("drive_permission_expired")
        url = "https://www.googleapis.com/drive/v3/files/" + source.file_id
        params = (
            {"alt": "media"}
            if media
            else {
                "fields": "id,mimeType,size,version,headRevisionId,modifiedTime,sha256Checksum,trashed,capabilities(canDownload)"
            }
        )

        async def request(client):
            async with client.stream(
                "GET",
                url,
                params=params,
                headers={
                    "Authorization": "Bearer " + token,
                    "Accept-Encoding": "identity",
                },
                follow_redirects=False,
                timeout=15,
            ) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    raise ContextError("drive_redirect_rejected")
                if response.status_code in {401, 403}:
                    raise ContextError("drive_permission_expired")
                if response.status_code in {404, 410}:
                    raise ContextError("drive_file_unavailable")
                if response.status_code == 429:
                    raise ContextError("drive_rate_limited")
                if response.status_code != 200:
                    raise ContextError("drive_response_invalid")
                if (
                    response.headers.get("Content-Encoding", "identity").lower()
                    != "identity"
                ):
                    raise ContextError("drive_response_invalid")
                limit = MAX_PDF_BYTES if media else 16384
                length = response.headers.get("Content-Length")
                if length is not None and (not length.isdigit() or int(length) > limit):
                    raise ContextError("drive_response_too_large")
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > limit:
                        raise ContextError("drive_response_too_large")
                if length is not None and len(raw) != int(length):
                    raise ContextError("partial_or_changed_download")
                mime = (
                    response.headers.get("Content-Type", "")
                    .split(";")[0]
                    .strip()
                    .lower()
                )
                return bytes(raw), mime, response.headers.get("ETag")

        try:
            async with asyncio.timeout(20):
                if self._client:
                    return await request(self._client)
                async with httpx.AsyncClient(
                    trust_env=False, follow_redirects=False
                ) as client:
                    return await request(client)
        except (httpx.HTTPError, TimeoutError):
            raise ContextError("drive_network_failed") from None

    async def metadata(self, source: ResumeSource) -> DriveMetadata:
        raw, mime, etag = await self._request(source, media=False)
        try:
            if mime != "application/json":
                raise ValueError
            data = json.loads(raw)
            if (
                data.get("trashed") is not False
                or data.get("capabilities", {}).get("canDownload") is not True
            ):
                raise ContextError("drive_source_not_authorized")
            result = DriveMetadata(
                file_id=data["id"],
                account_ref=source.account_ref,
                mime_type=data["mimeType"],
                size=data["size"],
                version=data.get("version"),
                revision_id=data.get("headRevisionId"),
                etag=etag,
                modified_at=datetime.fromisoformat(
                    data["modifiedTime"].replace("Z", "+00:00")
                )
                if data.get("modifiedTime")
                else None,
                sha256=data.get("sha256Checksum"),
            )
            if result.file_id != source.file_id:
                raise ContextError("drive_source_not_authorized")
            return result
        except ContextError:
            raise
        except (ValueError, KeyError, TypeError, AttributeError, ValidationError):
            raise ContextError("drive_response_invalid") from None

    async def download(
        self, source: ResumeSource, metadata: DriveMetadata
    ) -> PDFDownload:
        if (
            metadata.file_id != source.file_id
            or metadata.account_ref != source.account_ref
        ):
            raise ContextError("drive_source_not_authorized")
        raw, mime, _ = await self._request(source, media=True)
        if mime != "application/pdf":
            raise ContextError("invalid_pdf")
        if len(raw) != metadata.size:
            raise ContextError("partial_or_changed_download")
        return PDFDownload(raw=raw)
