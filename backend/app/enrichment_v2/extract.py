"""Zero-cost email extraction, ranking and an SSRF-guarded public page fetcher.

Everything here is deterministic: regex over JD text / public HTML, domain
normalisation, filtering of noreply/support/placeholder/disposable addresses,
and a recruiter-first ranking. Nothing guesses or constructs an address.
"""

from __future__ import annotations

import asyncio
import html
import ipaddress
import re
import socket
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, replace
from urllib.parse import urljoin, urlsplit

import httpx

from backend.app.browser_v2.rules import normalize_company

_EMAIL = re.compile(
    r"(?<![\w.+-])([A-Za-z0-9][A-Za-z0-9._%+-]{0,63})@"
    r"((?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,24})(?![\w-])")
# "hr [at] acme [dot] com" / "hr(at)acme(dot)com" — only bracketed forms, never bare " at ".
_OBFUSCATED_AT = re.compile(r"\s*[\[(\{]\s*at\s*[\])\}]\s*", re.IGNORECASE)
_OBFUSCATED_DOT = re.compile(r"\s*[\[(\{]\s*dot\s*[\])\}]\s*", re.IGNORECASE)
_URL = re.compile(r"https?://[^\s<>\"')]+", re.IGNORECASE)
_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")

REJECT_LOCALS = frozenset({
    "noreply", "no-reply", "no_reply", "donotreply", "do-not-reply", "do_not_reply", "mailer-daemon",
    "postmaster", "abuse", "support", "help", "helpdesk", "billing", "sales", "marketing", "privacy",
    "legal", "security", "webmaster", "unsubscribe", "newsletter", "press", "media", "feedback",
    "compliance", "grievance", "dpo", "gdpr", "notifications", "notification", "alerts", "bounce",
    "invoice", "accounts", "customercare", "care", "service", "orders", "test", "user", "username",
    "email", "name", "yourname", "your.name", "firstname.lastname", "first.last", "john.doe", "jane.doe",
})
RECRUITING_LOCALS = ("hr", "careers", "career", "jobs", "job", "talent", "recruiting", "recruitment",
                     "recruiter", "recruiters", "hiring", "people", "resume", "resumes", "cv", "ta",
                     "joinus", "join", "workwithus", "apply", "humanresources", "peopleops", "staffing")
GENERIC_LOCALS = frozenset({"info", "contact", "hello", "hi", "team", "office", "enquiry", "enquiries",
                            "inquiry", "admin", "mail"})
PLACEHOLDER_DOMAINS = frozenset({
    "example.com", "example.org", "example.net", "example.in", "test.com", "domain.com", "email.com",
    "yourcompany.com", "company.com", "yourdomain.com", "mysite.com", "website.com", "sentry.io",
    "wixpress.com", "sentry-next.wixpress.com", "localhost", "invalid", "test", "local"})
DISPOSABLE_DOMAINS = frozenset({
    "mailinator.com", "guerrillamail.com", "10minutemail.com", "tempmail.com", "temp-mail.org",
    "yopmail.com", "trashmail.com", "sharklasers.com", "getnada.com", "dispostable.com", "maildrop.cc",
    "throwawaymail.com", "fakeinbox.com", "mintemail.com", "mohmal.com", "emailondeck.com"})
FREEMAIL_DOMAINS = frozenset({
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.in", "yahoo.in", "outlook.com", "hotmail.com",
    "live.com", "msn.com", "rediffmail.com", "icloud.com", "me.com", "protonmail.com", "proton.me",
    "aol.com", "gmx.com", "zohomail.in", "ymail.com"})
# Hosts that are never the employer (job portals, ATS hosts, social, link shorteners).
NON_EMPLOYER_HOSTS = frozenset({
    "naukri.com", "instahyre.com", "internshala.com", "linkedin.com", "indeed.com", "wellfound.com",
    "angel.co", "himalayas.app", "weworkremotely.com", "hiringcafe.com", "workatastartup.com",
    "ycombinator.com", "greenhouse.io", "lever.co", "ashbyhq.com", "smartrecruiters.com", "glassdoor.com",
    "monster.com", "foundit.in", "shine.com", "iimjobs.com", "hirist.com", "hirist.tech", "cutshort.io",
    "remotive.com", "arbeitnow.com", "workday.com", "myworkdayjobs.com", "google.com", "forms.gle",
    "facebook.com", "twitter.com", "x.com", "instagram.com", "youtube.com", "youtu.be", "github.com",
    "bit.ly", "t.co", "tinyurl.com", "lnkd.in", "medium.com", "wa.me", "whatsapp.com", "t.me",
    "apple.com", "microsoft.com", "example.com"})
FILE_TLDS = frozenset({"png", "jpg", "jpeg", "gif", "svg", "webp", "css", "js", "ico", "pdf", "mp4", "json"})
RECRUITER_TITLE = re.compile(r"recruit|talent|\bhr\b|human resources|people (?:ops|operations|partner)|hiring|"
                             r"sourc(?:er|ing)", re.IGNORECASE)
MANAGER_TITLE = re.compile(r"engineering manager|head of engineering|\bcto\b|vp engineering|founder|"
                           r"tech(?:nical)? lead|director of engineering", re.IGNORECASE)


@dataclass(frozen=True)
class EmailCandidate:
    email: str
    source: str  # jd_text | careers_page | apollo | apify | signalhire | cache
    score: int
    kind: str  # recruiting | person | generic | freemail_recruiting
    title: str | None = None
    first_name: str | None = None

    def public(self) -> dict[str, object]:
        return {"email": self.email, "source": self.source, "score": self.score, "kind": self.kind,
                "title": self.title, "first_name": self.first_name}

    @classmethod
    def from_public(cls, data: dict[str, object]) -> EmailCandidate | None:
        email, source = data.get("email"), data.get("source")
        if not isinstance(email, str) or not isinstance(source, str):
            return None
        score = data.get("score")
        title, first = data.get("title"), data.get("first_name")
        return cls(email=email, source=source, score=score if isinstance(score, int) else 0,
                   kind=str(data.get("kind") or "person"), title=title if isinstance(title, str) else None,
                   first_name=first if isinstance(first, str) else None)


# --- domains ----------------------------------------------------------------------------
def normalize_domain(value: str | None) -> str | None:
    """`https://www.Acme.co.in/careers` -> `acme.co.in`. IP literals and junk -> None."""
    if not value or not isinstance(value, str):
        return None
    raw = value.strip().lower()
    if "@" in raw and "://" not in raw:
        raw = raw.rsplit("@", 1)[-1]
    host = urlsplit(raw if "://" in raw else "https://" + raw).hostname or ""
    host = host.rstrip(".").removeprefix("www.")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        return None
    if not host or len(host) > 253 or "." not in host:
        return None
    try:
        ipaddress.ip_address(host)
        return None
    except ValueError:
        pass
    labels = host.split(".")
    if not all(_LABEL.match(label) for label in labels) or labels[-1].isdigit():
        return None
    return host


def registrable_match(email_domain: str, company_domain: str | None) -> bool:
    """hr@careers.acme.com matches acme.com (subdomain of the company)."""
    if not company_domain:
        return False
    return email_domain == company_domain or email_domain.endswith("." + company_domain)


def is_non_employer(domain: str | None) -> bool:
    return bool(domain) and any(registrable_match(domain or "", host) for host in NON_EMPLOYER_HOSTS)


def company_cache_key(company_domain: str | None, company_name: str | None) -> str | None:
    """Cache key: the normalized domain, else `name:<normalized company>` (no paid lookups for those)."""
    if company_domain:
        return company_domain
    name = normalize_company(company_name)
    return f"name:{name.replace(' ', '-')}"[:200] if len(name) >= 2 else None


def infer_company_domain(company_domain: str | None, job_url: str | None, jd_text: str | None,
                         jd_emails: Iterable[EmailCandidate] = ()) -> str | None:
    """Explicit domain > employer URL in the JD > corporate email domain in the JD > employer job URL."""
    explicit = normalize_domain(company_domain)
    if explicit and not is_non_employer(explicit):
        return explicit
    for url in _URL.findall(jd_text or ""):
        domain = normalize_domain(url)
        if domain and not is_non_employer(domain) and domain.rsplit(".", 1)[-1] not in FILE_TLDS:
            return domain
    for candidate in jd_emails:
        domain = candidate.email.rsplit("@", 1)[-1]
        if domain not in FREEMAIL_DOMAINS and not is_non_employer(domain):
            return domain
    domain = normalize_domain(job_url)
    if domain and not is_non_employer(domain):
        return domain
    return None


# --- extraction + ranking ---------------------------------------------------------------
def deobfuscate(text: str) -> str:
    text = html.unescape(text)
    text = _OBFUSCATED_AT.sub("@", text)
    return _OBFUSCATED_DOT.sub(".", text)


def classify(email: str, company_domain: str | None) -> tuple[str, int] | None:
    """(kind, base score) for an acceptable address, None when it must be rejected."""
    local, _, domain = email.partition("@")
    local_core = local.split("+", 1)[0]
    if local_core in REJECT_LOCALS or local_core.startswith(("noreply", "no-reply", "donotreply")):
        return None
    tld = domain.rsplit(".", 1)[-1]
    if tld in FILE_TLDS or domain in PLACEHOLDER_DOMAINS or domain in DISPOSABLE_DOMAINS:
        return None
    if any(registrable_match(domain, host) for host in ("example.com", "example.org", "example.net")):
        return None
    if is_non_employer(domain):
        return None
    recruiting = local_core in RECRUITING_LOCALS or bool(
        re.match(r"^(?:hr|careers?|jobs?|talent|recruit\w*|hiring|people|resumes?|cv)[._-]", local_core)
        or re.search(r"[._-](?:hr|careers?|jobs?|talent|recruit\w*|hiring)$", local_core))
    if domain in FREEMAIL_DOMAINS:
        # A free-mail address is accepted only when the employer published it as a hiring inbox.
        return ("freemail_recruiting", 20) if recruiting else None
    on_domain = registrable_match(domain, company_domain)
    if company_domain and not on_domain:
        return None  # a corporate address of some other company (vendor, client, portal)
    bonus = 50 if on_domain else 0
    if recruiting:
        return "recruiting", 40 + bonus
    if local_core in GENERIC_LOCALS:
        return "generic", 5 + bonus
    return "person", 30 + bonus


def extract_emails(text: str | None, *, source: str, company_domain: str | None = None,
                   limit: int = 20) -> list[EmailCandidate]:
    """Ranked, de-duplicated acceptable addresses found verbatim in `text`."""
    if not text:
        return []
    found: dict[str, EmailCandidate] = {}
    source_bonus = {"jd_text": 5, "careers_page": 3}.get(source, 0)
    for match in _EMAIL.finditer(deobfuscate(text)[:500_000]):
        email = f"{match.group(1)}@{match.group(2)}".lower().strip(".")
        if len(email) > 254 or ".." in email:
            continue
        verdict = classify(email, company_domain)
        if verdict is None:
            continue
        kind, score = verdict
        candidate = EmailCandidate(email=email, source=source, score=score + source_bonus, kind=kind)
        if email not in found or found[email].score < candidate.score:
            found[email] = candidate
        if len(found) >= limit:
            break
    return rank(found.values())


def rank(candidates: Iterable[EmailCandidate]) -> list[EmailCandidate]:
    return sorted(candidates, key=lambda c: (-c.score, c.email))


def provider_candidate(email: str | None, *, source: str, company_domain: str, title: str | None = None,
                       first_name: str | None = None) -> EmailCandidate | None:
    """Validate a provider-reported address: syntax, company domain, no placeholders/noreply."""
    if not isinstance(email, str) or not _EMAIL.fullmatch(email.strip()):
        return None
    email = email.strip().lower()
    if email.startswith(("email_not_unlocked", "not_unlocked")):
        return None
    if not registrable_match(email.rsplit("@", 1)[-1], company_domain):
        return None
    verdict = classify(email, company_domain)
    if verdict is None:
        return None
    kind, score = verdict
    if title and RECRUITER_TITLE.search(title):
        score, kind = score + 35, "recruiting"
    elif title and MANAGER_TITLE.search(title):
        score += 25
    first = first_name.strip()[:40] if isinstance(first_name, str) and first_name.strip() else None
    return EmailCandidate(email=email, source=source, score=score, kind=kind,
                          title=title[:120] if isinstance(title, str) else None, first_name=first)


def tag_source(candidates: Iterable[EmailCandidate], source: str) -> list[EmailCandidate]:
    return [replace(c, source=source) for c in candidates]


# --- SSRF-guarded public page fetcher ---------------------------------------------------
class UnsafeTarget(ValueError):
    """Private, loopback, link-local, metadata or otherwise non-public destination."""


Resolver = Callable[[str], Awaitable[list[str]]]


async def system_resolver(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    return sorted({str(info[4][0]) for info in infos})


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return True


def public_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_global and not address.is_multicast


async def assert_public_url(url: str, resolver: Resolver = system_resolver) -> str:
    parts = urlsplit(url)
    if parts.scheme not in ("https", "http"):
        raise UnsafeTarget("scheme_not_allowed")
    if parts.username or parts.password:
        raise UnsafeTarget("credentials_in_url")
    if parts.port not in (None, 80, 443):
        raise UnsafeTarget("port_not_allowed")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host or host == "localhost" or host.endswith((".local", ".internal", ".localhost", ".lan", ".home")):
        raise UnsafeTarget("host_not_public")
    if _is_ip_literal(host):
        raise UnsafeTarget("ip_literal_not_allowed")
    try:
        addresses = await asyncio.wait_for(resolver(host), timeout=5)
    except (OSError, TimeoutError) as exc:
        raise UnsafeTarget("dns_failed") from exc
    if not addresses or not all(public_ip(a) for a in addresses):
        raise UnsafeTarget("resolves_to_private_address")
    return host


class PageFetcher:
    """GET a public HTML page: https/http only, public IPs only (re-checked on every redirect),
    strict timeout, 400 KB cap, no cookies/env proxies. Returns text or None."""

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None,
                 resolver: Resolver = system_resolver, timeout_sec: float = 6.0,
                 max_bytes: int = 400_000, max_redirects: int = 3) -> None:
        self.transport = transport
        self.resolver = resolver
        self.timeout_sec = timeout_sec
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects

    async def fetch(self, url: str) -> str | None:
        async with httpx.AsyncClient(transport=self.transport, timeout=self.timeout_sec, follow_redirects=False,
                                     trust_env=False, headers={"User-Agent": "Mozilla/5.0 (Macintosh)",
                                                               "Accept": "text/html,text/plain"}) as client:
            current = url
            for _ in range(self.max_redirects + 1):
                await assert_public_url(current, self.resolver)
                async with client.stream("GET", current) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("location")
                        if not location:
                            return None
                        current = urljoin(current, location)
                        continue
                    if response.status_code != 200:
                        return None
                    kind = response.headers.get("content-type", "").lower()
                    if kind and not kind.startswith(("text/html", "text/plain", "application/xhtml")):
                        return None
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > self.max_bytes:
                            break
                    return bytes(body[: self.max_bytes]).decode(response.encoding or "utf-8", errors="replace")
        return None


CAREERS_PATHS = ("/careers", "/contact", "/")
