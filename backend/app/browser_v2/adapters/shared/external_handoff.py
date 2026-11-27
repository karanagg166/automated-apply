"""External hosted-ATS (Greenhouse / Lever) classification and handoff targets."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

# --- external ATS classification ------------------------------------------------------------
GREENHOUSE_HOSTS = frozenset({"boards.greenhouse.io", "job-boards.greenhouse.io", "job-boards.eu.greenhouse.io",
                              "boards.eu.greenhouse.io"})
LEVER_HOSTS = frozenset({"jobs.lever.co", "jobs.eu.lever.co"})
SUPPORTED_ATS = frozenset({"greenhouse", "lever"})
GREENHOUSE_PATH = re.compile(r"^/(?:embed/job_app|[A-Za-z0-9_-]{1,100}/jobs/\d{1,20})")
LEVER_PATH = re.compile(r"^/[A-Za-z0-9_.-]{1,100}/[0-9a-f-]{8,64}(?:/apply)?/?$")


def classify_ats(url: str | None) -> str | None:
    """greenhouse | lever for a hosted ATS application URL (https only), else None."""
    if not url:
        return None
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https":
        return None
    if host in GREENHOUSE_HOSTS and GREENHOUSE_PATH.match(parts.path):
        return "greenhouse"
    if host in LEVER_HOSTS and LEVER_PATH.match(parts.path):
        return "lever"
    return None


def ats_of_host(url: str | None) -> str | None:
    """greenhouse | lever by https host alone (embed/form paths included), else None."""
    parts = urlsplit(url or "")
    host = (parts.hostname or "").lower()
    if parts.scheme != "https":
        return None
    if host in GREENHOUSE_HOSTS:
        return "greenhouse"
    if host in LEVER_HOSTS:
        return "lever"
    return None


@dataclass(frozen=True)
class AtsHandoff:
    """A supported hosted-ATS posting found behind another portal's external apply link."""

    platform: str  # greenhouse | lever
    external_job_id: str
    url: str  # canonical posting URL the ATS adapter can look up (board in the path)
    board: str | None
    board_guessed: bool = False


_GH_ID = re.compile(r"^\d{1,20}$")
_LEVER_ID = re.compile(r"^[0-9a-f-]{8,64}$")
_GENERIC_LABELS = frozenset({"www", "careers", "career", "jobs", "job", "apply", "boards", "work", "join", "hire",
                             "hiring", "co", "com", "io", "ai", "in", "org", "net", "app", "dev", "tech"})


def _board_guess(host: str) -> str | None:
    """stripe.com -> stripe, careers.acme.io -> acme (only for ?gh_jid= custom career sites)."""
    labels = [p for p in host.lower().split(".") if p and p not in _GENERIC_LABELS]
    candidate = labels[-1] if labels else None
    return candidate if candidate and re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,99}", candidate) else None


def ats_handoff_target(url: str | None) -> AtsHandoff | None:
    """Greenhouse/Lever posting behind an external apply link, deduped by its global job id.

    Supports boards.greenhouse.io / job-boards.greenhouse.io /<board>/jobs/<id>, the embed form
    (?for=<board>&token=<id>), custom career sites carrying ?gh_jid=<id> (board guessed from the
    domain, fail-closed if wrong) and jobs.lever.co/<board>/<uuid>[/apply]. https only.
    """
    if not url:
        return None
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        return None
    host = parts.hostname.lower()
    params = parse_qs(parts.query)

    def first(key: str) -> str | None:
        values = params.get(key)
        return values[0] if values else None

    segments = [s for s in parts.path.split("/") if s]
    if host in GREENHOUSE_HOSTS:
        if parts.path.startswith("/embed/job_app"):
            board, token = first("for"), first("token")
            if board and token and _GH_ID.match(token):
                return AtsHandoff("greenhouse", token, f"https://job-boards.greenhouse.io/{board}/jobs/{token}", board)
            return None
        if len(segments) >= 3 and segments[1] == "jobs" and _GH_ID.match(segments[2]):
            board = segments[0]
            return AtsHandoff("greenhouse", segments[2], f"https://job-boards.greenhouse.io/{board}/jobs/{segments[2]}",
                              board)
        return None
    if host in LEVER_HOSTS:
        if len(segments) >= 2 and _LEVER_ID.match(segments[1]):
            return AtsHandoff("lever", segments[1], f"https://{host}/{segments[0]}/{segments[1]}", segments[0])
        return None
    gh_jid = first("gh_jid")
    if gh_jid and _GH_ID.match(gh_jid):
        board = _board_guess(host)
        if board:
            return AtsHandoff("greenhouse", gh_jid, f"https://job-boards.greenhouse.io/{board}/jobs/{gh_jid}", board,
                              board_guessed=True)
    return None


def ats_form_url(url: str, ats: str) -> str:
    """Lever postings take their form at /apply; Greenhouse embeds it on the posting page."""
    if ats == "lever":
        parts = urlsplit(url)
        path = parts.path.rstrip("/")
        return f"https://{parts.hostname}{path if path.endswith('/apply') else path + '/apply'}"
    return url
