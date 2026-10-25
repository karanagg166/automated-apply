"""Private encrypted PDF storage, conservative suggestions, explicit review."""

import asyncio
import hashlib
import json
import re
import sys
from contextlib import suppress
from pathlib import Path

from cryptography.fernet import Fernet
from fastapi import HTTPException

from backend.app.core.config import get_settings

MAX_PDF = 5 * 1024 * 1024
SKILLS = (
    "Python",
    "FastAPI",
    "PostgreSQL",
    "Redis",
    "Next.js",
    "React",
    "TypeScript",
    "Node.js",
    "RAG",
    "LangChain",
    "Docker",
    "Java",
    "C++",
    "JavaScript",
    "SQL",
    "Git",
)


def cipher():
    secret = get_settings().RESUME_ENCRYPTION_KEY
    if not secret:
        raise HTTPException(
            503,
            "Configure a dedicated RESUME_ENCRYPTION_KEY before uploading a private resume",
        )
    return Fernet(secret.get_secret_value().encode())


async def extract_pdf(raw):
    if not raw.startswith(b"%PDF-") or len(raw) > MAX_PDF:
        raise HTTPException(422, "Upload a PDF of at most 5 MiB")
    worker = str(Path(__file__).with_name("resume_worker.py"))
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        worker,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env={"PATH": "/usr/bin:/bin"},
    )

    async def supervise_memory():
        if sys.platform != "darwin":
            return
        while process.returncode is None:
            probe = await asyncio.create_subprocess_exec(
                "/bin/ps",
                "-o",
                "rss=",
                "-p",
                str(process.pid),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            rss, _ = await probe.communicate()
            if rss.strip().isdigit() and int(rss.strip()) > 768 * 1024:
                with suppress(ProcessLookupError):
                    process.kill()
                return
            await asyncio.sleep(0.1)

    watcher = asyncio.create_task(supervise_memory())
    try:
        output, _ = await asyncio.wait_for(process.communicate(raw), 10)
    except TimeoutError:
        with suppress(ProcessLookupError):
            process.kill()
        await process.wait()
        raise HTTPException(422, "PDF parsing exceeded its safety limit") from None
    finally:
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.kill()
            await process.wait()
        watcher.cancel()
        with suppress(asyncio.CancelledError):
            await watcher
    if process.returncode or len(output) > 200000:
        raise HTTPException(
            422, "PDF could not be safely parsed; use a plain PDF with at most 20 pages"
        )
    return json.loads(output)


def suggestions(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    email = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
    name = next(
        (s for s in lines[:3] if re.fullmatch(r"[A-Za-z][A-Za-z .'-]{2,100}", s)), ""
    )
    skills = [
        skill
        for skill in SKILLS
        if re.search(r"(?<!\w)" + re.escape(skill) + r"(?!\w)", text, re.I)
    ]
    return {
        "full_name": name,
        "email": email.group() if email else "",
        "verified_skills": skills,
    }


def encrypt(raw):
    return cipher().encrypt(raw), hashlib.sha256(raw).hexdigest()


def verified_pdf(resume):
    from cryptography.fernet import InvalidToken
    try:
        raw = cipher().decrypt(resume.ciphertext)
    except (InvalidToken, ValueError):
        raise HTTPException(409, "Private PDF integrity check failed; restore the original file and encryption key") from None
    if not raw.startswith(b"%PDF-") or hashlib.sha256(raw).hexdigest() != resume.sha256:
        raise HTTPException(409, "Private PDF checksum verification failed")
    return raw
