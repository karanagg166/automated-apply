"""Naukri URLs, regexes, limits and the OTP provider type."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from datetime import datetime

ORIGIN = "https://www.naukri.com"
HOME_URL = ORIGIN + "/mnjuser/homepage"
PROFILE_URL = ORIGIN + "/mnjuser/profile"
HISTORY_URL = ORIGIN + "/myapply/historypage"
JOB_PATH = re.compile(r"^/job-listings-[a-zA-Z0-9%_-]+-(\d{10,20})/?$")
APPLY_SUCCESS = re.compile(
    r"you have successfully applied|applied successfully|successfully applied|"
    r"application (?:has been )?(?:sent|submitted) successfully", re.IGNORECASE)
PORTAL_LIMIT = re.compile(
    r"(?:daily|today'?s?)\s+(?:apply|application)s?\s+(?:limit|quota)|"
    r"reached\s+(?:the|your)\s+(?:daily\s+|maximum\s+)?(?:apply\s+|application\s+)?limit|"
    r"exceeded\s+(?:the|your)\s+(?:daily\s+)?(?:apply\s+|application\s+)?limit|"
    r"maximum\s+(?:number\s+of\s+)?applications\s+(?:for|per)\s+(?:the\s+)?day|"
    r"apply\s+limit\s+(?:reached|exceeded)", re.IGNORECASE)
HISTORY_SENT = re.compile(r"^application sent\b", re.IGNORECASE)
MAX_QUESTION_STEPS = 20
# Live canary 2026-11-27: "Enter Resume Verification ID and/or Verification URL. (if available)" -
# optional questions Naukri lets you skip are skipped when no stored fact answers them (truthful).
OPTIONAL_QUESTION = re.compile(r"\b(?:if (?:any|available|applicable)|optional)\b", re.IGNORECASE)
OTP_VALUE = re.compile(r"^\s*(\d{4,8})\s*$")
OtpProvider = Callable[[str, datetime], Awaitable[str | None]]

APPLY_SETTLE_POLLS = 24  # x 250 ms: the logged-in JD header re-renders after hydration
