"""Credential-free Google download worker: public DNS, pinned TLS, bounded reads.

Runs with no inherited credentials and a hard deadline imposed by the parent.
Only this module performs network IO; URLs and remote error bodies are never logged.
"""

import base64
import http.client
import ipaddress
import json
import re
import socket
import ssl
import sys
import time
from email.message import Message
from urllib.parse import parse_qs, urljoin, urlsplit

MAX_BYTES = 5 * 1024 * 1024
HOSTS = {"drive.google.com", "drive.usercontent.google.com"}


class DownloadError(Exception):
    """Fixed categories only; never contains remote data or a request URL."""


def validate_target(url: str, file_id: str):
    try:
        parsed = urlsplit(url)
        query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
        if (
            len(url) > 4096 or not url.isascii()
            or any(ord(c) <= 32 for c in url)
            or parsed.scheme != "https" or parsed.hostname not in HOSTS
            or parsed.netloc != parsed.hostname or parsed.fragment
            or parsed.path not in {"/uc", "/download"}
            or query.get("id") != [file_id]
            or set(query) - {"id", "export", "authuser", "confirm", "uuid"}
            or any(len(v) != 1 for v in query.values())
        ):
            raise ValueError
    except (ValueError, AttributeError):
        raise DownloadError("unsafe_redirect") from None
    return parsed


def public_addresses(host: str):
    addresses = sorted({item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise DownloadError("nonpublic_dns")
    return addresses


def connect(host: str):
    # No second DNS lookup: connect to a previously validated numeric address.
    address = public_addresses(host)[0]
    connection = http.client.HTTPSConnection(host, timeout=5)
    connection.auto_open = 0
    sock = socket.create_connection((address, 443), timeout=5)
    try:
        connection.sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
    except BaseException:
        sock.close()
        raise
    return connection


def filename(value: str | None):
    message = Message()
    message["Content-Disposition"] = value or ""
    name = message.get_filename() or "resume.pdf"
    # Use only a safe PDF basename for display; never as a filesystem path.
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,195}\.pdf", name, re.I):
        return "resume.pdf"
    return name


def download(file_id: str):
    if not re.fullmatch(r"[A-Za-z0-9_-]{10,200}", file_id):
        raise DownloadError("invalid_file_id")
    url = f"https://drive.google.com/uc?export=download&id={file_id}"
    deadline = time.monotonic() + 30
    for _ in range(4):
        if time.monotonic() > deadline:
            raise DownloadError("download_timeout")
        parsed = validate_target(url, file_id)
        connection = connect(parsed.hostname)
        try:
            connection.request("GET", parsed.path + "?" + parsed.query, headers={
                "Accept": "application/pdf", "Accept-Encoding": "identity",
                "User-Agent": "AutomatedApply-OwnerResumeSync/1",
            })
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader("Location")
                if not location:
                    raise DownloadError("unsafe_redirect")
                url = urljoin(url, location)
                validate_target(url, file_id)
                continue
            if response.status in {401, 403}:
                raise DownloadError("access_denied_or_revoked")
            if response.status in {404, 410}:
                raise DownloadError("file_missing_or_access_revoked")
            if response.status == 429:
                raise DownloadError("drive_rate_limited")
            if response.status != 200:
                raise DownloadError("drive_unavailable")
            content_type = response.getheader("Content-Type", "").split(";")[0].lower()
            if content_type not in {"application/pdf", "application/octet-stream"}:
                raise DownloadError("not_a_pdf_or_permission_required")
            if response.getheader("Content-Encoding", "identity").lower() != "identity":
                raise DownloadError("unsupported_content_encoding")
            size = response.getheader("Content-Length")
            if size is not None and (not size.isdigit() or int(size) > MAX_BYTES):
                raise DownloadError("pdf_too_large")
            raw = bytearray()
            while True:
                if time.monotonic() > deadline:
                    raise DownloadError("download_timeout")
                chunk = response.read(min(65536, MAX_BYTES + 1 - len(raw)))
                if not chunk:
                    break
                raw.extend(chunk)
                if len(raw) > MAX_BYTES:
                    raise DownloadError("pdf_too_large")
            if not raw.startswith(b"%PDF-"):
                raise DownloadError("not_a_pdf_or_permission_required")
            if size is not None and len(raw) != int(size):
                raise DownloadError("incomplete_download")
            return {
                "pdf": base64.b64encode(raw).decode("ascii"),
                "file_name": filename(response.getheader("Content-Disposition")),
                "modified": (response.getheader("Last-Modified") or "")[:100] or None,
                "etag": (response.getheader("ETag") or "")[:500] or None,
                "drive_revision": None,
            }
        finally:
            connection.close()
    raise DownloadError("redirect_limit")


def main():
    try:
        payload = json.loads(sys.stdin.buffer.read(512))
        result = download(payload["file_id"])
    except DownloadError as exc:
        result = {"error": str(exc)}
    except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException):
        result = {"error": "bounded_network_check_failed"}
    sys.stdout.write(json.dumps(result))


if __name__ == "__main__":
    main()
