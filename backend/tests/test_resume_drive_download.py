"""Exercise network boundaries with mocked connections; never contact Google in CI."""

import asyncio
import io
import socket

import pytest

from backend.app.dashboard.resumes import extract_pdf
from backend.app.resume_sync import download as supervised
from backend.app.resume_sync import download_worker as worker
from backend.app.resume_sync.download_worker import DownloadError
from backend.app.resume_sync.facts import differences, extract_facts
from backend.tests.test_phase7_dashboard import pdf_bytes

FILE_ID = "fictional_drive_resume_001"


class Response:
    def __init__(self, status=200, raw=None, headers=None):
        self.status = status
        self.buffer = io.BytesIO(pdf_bytes() if raw is None else raw)
        self.headers = {"Content-Type": "application/pdf", **(headers or {})}

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def read(self, size):
        return self.buffer.read(size)


class Connection:
    def __init__(self, response, requests):
        self.response, self.requests = response, requests
        self.closed = False

    def request(self, *args, **kwargs):
        self.requests.append((args, kwargs))

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


def network(monkeypatch, responses):
    requests, connections = [], []
    def connect(host):
        connection = Connection(responses.pop(0), requests)
        connections.append(connection)
        return connection
    monkeypatch.setattr(worker, "connect", connect)
    return requests, connections


def test_public_download_follows_only_approved_google_file_and_uses_no_credentials(monkeypatch):
    requests, connections = network(monkeypatch, [Response(302, headers={"Location": f"https://drive.usercontent.google.com/download?id={FILE_ID}&export=download"}), Response(headers={"Content-Disposition": 'attachment; filename="fictional_resume.pdf"', "Last-Modified": "Mon, 05 Jan 2026 12:00:00 GMT", "ETag": '"revision"'})])
    result = worker.download(FILE_ID)
    assert result["file_name"] == "fictional_resume.pdf" and result["modified"]
    assert len(requests) == 2 and all(connection.closed for connection in connections)
    assert all("Authorization" not in kwargs["headers"] and "Cookie" not in kwargs["headers"] for _, kwargs in requests)


@pytest.mark.parametrize("location", ["https://127.0.0.1/download", "https://169.254.169.254/latest/meta-data/", "https://drive.google.com.evil.example/download", f"https://secret@drive.usercontent.google.com/download?id={FILE_ID}", f"http://drive.usercontent.google.com/download?id={FILE_ID}", "https://accounts.google.com/signin", "https://drive.usercontent.google.com/download?id=different-file-id", f"https://drive.usercontent.google.com/download?id={FILE_ID}&access_token=secret"])
def test_unsafe_redirects_are_rejected_before_connection(monkeypatch, location):
    requests, _ = network(monkeypatch, [Response(302, headers={"Location": location})])
    with pytest.raises(DownloadError, match="unsafe_redirect"):
        worker.download(FILE_ID)
    assert len(requests) == 1


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.1", "::1", "169.254.169.254", "::ffff:192.168.1.1", "100.64.0.1"])
def test_private_dns_is_rejected(monkeypatch, ip):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, (ip, 443))])
    with pytest.raises(DownloadError, match="nonpublic_dns"):
        worker.public_addresses("drive.google.com")


def test_connection_pins_public_address_and_retains_hostname_tls_verification(monkeypatch):
    calls = []
    raw_socket = object()
    tls_socket = object()
    monkeypatch.setattr(worker, "public_addresses", lambda host: ["8.8.8.8"])
    monkeypatch.setattr(socket, "create_connection", lambda target, timeout: calls.append((target, timeout)) or raw_socket)
    class Context:
        def wrap_socket(self, sock, server_hostname):
            assert sock is raw_socket and server_hostname == "drive.google.com"
            return tls_socket
    monkeypatch.setattr(worker.ssl, "create_default_context", Context)
    connection = worker.connect("drive.google.com")
    assert calls == [(("8.8.8.8", 443), 5)] and connection.sock is tls_socket
    assert connection.auto_open == 0


@pytest.mark.parametrize("response,error", [
    (Response(403), "access_denied_or_revoked"), (Response(401), "access_denied_or_revoked"),
    (Response(404), "file_missing_or_access_revoked"), (Response(410), "file_missing_or_access_revoked"),
    (Response(429), "drive_rate_limited"), (Response(500), "drive_unavailable"),
    (Response(raw=b"<html>sign in</html>", headers={"Content-Type": "text/html"}), "not_a_pdf_or_permission_required"),
    (Response(raw=b"<html>not a PDF</html>"), "not_a_pdf_or_permission_required"),
    (Response(headers={"Content-Length": str(5 * 1024 * 1024 + 1)}), "pdf_too_large"),
    (Response(raw=b"%PDF-" + b"x" * (5 * 1024 * 1024)), "pdf_too_large"),
    (Response(headers={"Content-Encoding": "gzip"}), "unsupported_content_encoding"),
    (Response(headers={"Content-Length": "4000"}), "incomplete_download"),
])
def test_remote_failures_are_fixed_categories(monkeypatch, response, error):
    network(monkeypatch, [response])
    with pytest.raises(DownloadError, match=error):
        worker.download(FILE_ID)


def test_redirect_count_is_bounded(monkeypatch):
    network(monkeypatch, [Response(302, headers={"Location": f"https://drive.google.com/uc?id={FILE_ID}"}) for _ in range(4)])
    with pytest.raises(DownloadError, match="redirect_limit"):
        worker.download(FILE_ID)


async def test_cancelled_download_kills_and_reaps_worker_with_no_secrets(monkeypatch):
    started = asyncio.Event()
    class Process:
        returncode = None
        killed = False
        reaped = False
        async def communicate(self, payload):
            assert b"file_id" in payload and b"secret" not in payload
            started.set()
            await asyncio.Event().wait()
        def kill(self):
            self.killed, self.returncode = True, -9
        async def wait(self):
            self.reaped = True
    process = Process()
    async def create(*args, **kwargs):
        assert kwargs["env"] == {"PATH": "/usr/bin:/bin"}
        return process
    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    task = asyncio.create_task(supervised.fetch_pdf(FILE_ID))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert process.killed and process.reaped


async def test_plain_pdf_and_benign_local_open_action_are_supported():
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import ArrayObject, DictionaryObject, NameObject
    writer = PdfWriter()
    writer.append(PdfReader(io.BytesIO(pdf_bytes())))
    writer._root_object[NameObject("/OpenAction")] = DictionaryObject({NameObject("/S"): NameObject("/GoTo"), NameObject("/D"): ArrayObject([writer.pages[0].indirect_reference, NameObject("/Fit")])})
    buffer = io.BytesIO(); writer.write(buffer)
    assert (await extract_pdf(buffer.getvalue()))["pages"] == 1


@pytest.mark.parametrize("kind", ["javascript", "chained", "encrypted", "empty", "too_many_pages", "page_additional_action"])
async def test_pdf_structure_security_rejects_unsafe_files(kind):
    from fastapi import HTTPException
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, TextStringObject
    writer = PdfWriter()
    if kind != "empty":
        writer.add_blank_page(width=612, height=792)
    if kind == "javascript":
        writer.add_js("app.alert('fictional')")
    elif kind == "chained":
        writer._root_object[NameObject("/OpenAction")] = DictionaryObject({NameObject("/S"): NameObject("/GoTo"), NameObject("/Next"): DictionaryObject({NameObject("/S"): NameObject("/JavaScript"), NameObject("/JS"): TextStringObject("app.alert('fictional')")})})
    elif kind == "encrypted":
        writer.encrypt("fictional-only")
    elif kind == "too_many_pages":
        for _ in range(20):
            writer.add_blank_page(width=612, height=792)
    elif kind == "page_additional_action":
        writer.pages[0][NameObject("/AA")] = DictionaryObject({NameObject("/O"): DictionaryObject({NameObject("/S"): NameObject("/JavaScript")})})
    buffer = io.BytesIO(); writer.write(buffer)
    with pytest.raises(HTTPException):
        await extract_pdf(buffer.getvalue())


def test_review_diff_covers_all_resume_categories_without_inventing_dates():
    text = "Alex Sample\nSkills\nPython Redis\nExperience\nExample Org Engineer\nJan 2024 - Present\nEducation\nExample University\nProjects\nExample Project\nAchievements\nExample Award\nSummary\nOpen source contributor https://example.org/portfolio"
    facts = extract_facts(text)
    diff = differences(None, facts, ["Python", "FastAPI"])
    assert {item["category"] for item in diff} == {"skills", "work_experience", "employment_dates", "education", "projects", "professional_links", "achievements", "other_claims"}
    assert facts["sections"]["employment_dates"] == ["Jan 2024 - Present"]
    assert facts["sections"]["professional_links"] == ["https://example.org/portfolio"]
    assert "start_date" not in str(facts)
