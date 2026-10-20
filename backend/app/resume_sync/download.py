"""Supervised downloader. Cancellation and timeouts kill and reap the worker."""

import asyncio
import base64
import json
import sys
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from backend.app.dashboard.resumes import MAX_PDF
from backend.app.resume_sync.download_worker import DownloadError

ERRORS = {
    "invalid_file_id", "unsafe_redirect", "nonpublic_dns", "download_timeout",
    "access_denied_or_revoked", "file_missing_or_access_revoked", "drive_rate_limited",
    "drive_unavailable", "not_a_pdf_or_permission_required", "unsupported_content_encoding",
    "pdf_too_large", "incomplete_download", "redirect_limit", "bounded_network_check_failed",
}


@dataclass(frozen=True)
class DownloadedPDF:
    raw: bytes
    file_name: str
    modified_at: datetime | None = None
    etag: str | None = None
    drive_revision: str | None = None


async def fetch_pdf(file_id: str) -> DownloadedPDF:
    process = await asyncio.create_subprocess_exec(
        sys.executable, str(Path(__file__).with_name("download_worker.py")),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL, env={"PATH": "/usr/bin:/bin"},
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(json.dumps({"file_id": file_id}).encode()), 40)
    except TimeoutError:
        raise DownloadError("download_timeout") from None
    finally:
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.kill()
            await process.wait()
    if process.returncode or len(output) > 7 * 1024 * 1024:
        raise DownloadError("bounded_network_check_failed")
    try:
        data = json.loads(output)
        if data.get("error"):
            raise DownloadError(data["error"] if data["error"] in ERRORS else "bounded_network_check_failed")
        raw = base64.b64decode(data["pdf"], validate=True)
        if len(raw) > MAX_PDF or not raw.startswith(b"%PDF-"):
            raise ValueError
        modified = None
        if data.get("modified"):
            try:
                modified = parsedate_to_datetime(data["modified"]).astimezone(timezone.utc)
            except (ValueError, TypeError, OverflowError):
                modified = None  # Metadata never substitutes for the byte checksum.
        return DownloadedPDF(raw, data["file_name"], modified, data.get("etag"), data.get("drive_revision"))
    except (ValueError, TypeError, KeyError):
        raise DownloadError("bounded_network_check_failed") from None
