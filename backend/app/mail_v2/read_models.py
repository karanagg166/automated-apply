"""Read-only mail reader: limits, portal / recruiter / job-alert fingerprints and the message models."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.utils import parseaddr
from typing import Any

TIMEOUT_SEC = 20
MAX_BODY_CHARS = 6000
MAX_MESSAGES = 40
OTP_WINDOW = timedelta(minutes=3)

# Portal sender/subject fingerprints for OTP + magic-link mails.
PORTAL_MAIL: dict[str, tuple[re.Pattern[str], re.Pattern[str]]] = {
    "naukri": (re.compile(r"naukri\.com$", re.IGNORECASE), re.compile(r"otp|verification|one time|login", re.IGNORECASE)),
    "instahyre": (re.compile(r"instahyre\.com$", re.IGNORECASE), re.compile(r"otp|verif|login|sign ?in|code", re.IGNORECASE)),
    "internshala": (re.compile(r"internshala\.com$", re.IGNORECASE), re.compile(r"otp|verif|login|code", re.IGNORECASE)),
    "wellfound": (re.compile(r"(?:wellfound|angel)\.(?:com|co)$", re.IGNORECASE), re.compile(r"sign ?in|login|verif|code|magic", re.IGNORECASE)),
    "work_at_a_startup": (re.compile(r"(?:ycombinator|workatastartup)\.com$", re.IGNORECASE),
                          re.compile(r"sign ?in|login|verif|code", re.IGNORECASE)),
    "himalayas": (re.compile(r"himalayas\.app$", re.IGNORECASE), re.compile(r"sign ?in|login|verif|code|magic", re.IGNORECASE)),
}
OTP_CODE = re.compile(r"(?<![\d-])(\d{4,8})(?![\d-])")
OTP_CONTEXT = re.compile(r"\b(?:otp|one[- ]time|verification code|security code|login code|passcode|code is|"
                         r"your code|enter (?:the )?code)\b", re.IGNORECASE)
MAGIC_LINK = re.compile(r"https://[^\s<>\"']+(?:login|signin|sign_in|verify|magic|auth|token)[^\s<>\"']*", re.IGNORECASE)
INTERVIEW = re.compile(r"\b(?:interview|shortlist(?:ed)?|assessment|coding (?:round|test|challenge)|hr (?:call|round)|"
                       r"technical round|next (?:round|steps?)|schedule (?:a )?(?:call|chat)|take[- ]home)\b", re.IGNORECASE)
RECRUITER = re.compile(r"\b(?:recruit(?:er|ing|ment)|talent acquisition|hiring (?:manager|team)|your application)\b",
                       re.IGNORECASE)
ALERT_SENDERS: dict[str, re.Pattern[str]] = {
    "naukri": re.compile(r"(?:^|\.)naukri\.com$", re.IGNORECASE),
    "linkedin": re.compile(r"(?:^|\.)linkedin\.com$", re.IGNORECASE),
    "wellfound": re.compile(r"(?:^|\.)(?:wellfound|angel)\.(?:com|co)$", re.IGNORECASE),
}
ALERT_SUBJECT = re.compile(r"job alert|jobs? (?:for|matching|you might|recommended)|new jobs|recommended jobs|"
                           r"jobs? based on|hiring for", re.IGNORECASE)
JOB_LINKS: dict[str, re.Pattern[str]] = {
    "naukri": re.compile(r"https://www\.naukri\.com/job-listings-[A-Za-z0-9%_-]+-(\d{10,20})"),
    "linkedin": re.compile(r"https://(?:www\.)?linkedin\.com/(?:comm/)?jobs/view/(\d{6,20})"),
    "wellfound": re.compile(r"https://wellfound\.com/jobs/(\d{3,12})-[A-Za-z0-9-]*"),
}
NO_REPLY = re.compile(r"^(?:no-?reply|do-?not-?reply|notifications?|alerts?|mailer-daemon)@", re.IGNORECASE)


class MailReadError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class MailMessage:
    key: str
    sender: str
    subject: str
    received_at: datetime | None
    body: str
    source: str  # imap | gmail_api | mail_app

    @property
    def sender_address(self) -> str:
        return parseaddr(self.sender)[1].lower()

    @property
    def sender_domain(self) -> str:
        return self.sender_address.rsplit("@", 1)[-1] if "@" in self.sender_address else ""


@dataclass
class MailEvent:
    message_key: str
    kind: str  # RECRUITER_REPLY | INTERVIEW | JOB_ALERT (+ CONFIRMATION | OA_INVITE | REJECTED after 008)
    source: str
    sender: str | None
    subject: str | None
    snippet: str | None
    received_at: datetime | None
    platform: str | None = None
    company_name: str | None = None
    application_id: str | None = None
    alerted_at: datetime | None = None
    created_at: datetime | None = None
    id: str | None = None

    def public(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}
