"""Controlled contracts only; no claim of live portal compatibility."""

import json
import re
from urllib.parse import urlsplit

from backend.app.agent.tools import ToolDenied
from backend.app.browser.submission_contracts import SubmissionEvidence


def fixture_contract(url, settings, correlation):
    p = urlsplit(url)
    origin = f"{p.scheme}://{p.netloc}"
    match = re.fullmatch(
        r"/fixtures/(greenhouse|lever|google)/([a-z0-9-]{1,40})/jobs/([a-z0-9-]{1,40})/apply",
        p.path,
    )
    if (
        settings.ENVIRONMENT != "testing"
        or not settings.BROWSER_FIXTURE_ORIGIN
        or p.scheme != "http"
        or p.hostname != "127.0.0.1"
        or origin != settings.BROWSER_FIXTURE_ORIGIN
        or p.username
        or p.password
        or p.query
        or p.fragment
        or not match
    ):
        raise ToolDenied("fixture_submission_only_manual_required")
    base = origin + p.path.removesuffix("/apply")
    return {
        "adapter": match[1],
        "origin": origin,
        "application_url": url,
        "request_url": base + "/applications",
        "confirmation_url": base + "/confirmation/" + str(correlation),
        "receipt_url": base + "/receipts/" + str(correlation),
    }


def verify_response(submission, response, now, *, reconciliation=False):
    """An HTTP 200 or click alone conveys no success. Raw bodies never persist."""
    expected = (
        submission.receipt_url
        if reconciliation
        else (
            submission.request_url
            if submission.adapter == "greenhouse"
            else submission.confirmation_url
        )
    )
    if (
        not isinstance(response, dict)
        or response.get("url") not in {expected, submission.request_url}
        or not isinstance(response.get("body"), str)
        or len(response["body"]) > 65536
    ):
        return "submission_uncertain", None
    code, body = response.get("status"), response.get("body", "")
    correlation = str(submission.idempotency_key)
    try:
        if response.get("url") == submission.request_url and code in {409, 422}:
            data = json.loads(body)
            if (
                response.get("content_type", "").split(";")[0] == "application/json"
                and data.get("correlation_id") == correlation
                and data.get("status") in {"rejected", "validation_failed"}
            ):
                return "failed", None
        if response.get("url") != expected:
            return "submission_uncertain", None
        if reconciliation or submission.adapter != "google":
            if response.get("content_type", "").split(";")[0] != "application/json":
                return "submission_uncertain", None
            data = json.loads(body)
            if data.get("correlation_id") != correlation:
                return "submission_uncertain", None
            if code in {409, 422} and data.get("status") in {
                "rejected",
                "validation_failed",
            }:
                return "failed", None
            if code != 200 or data.get("status") != "received":
                return "submission_uncertain", None
            if reconciliation or submission.adapter == "greenhouse":
                app_id = data["application"]["id"]
                kind = "application_acknowledgment"
            else:
                if data.get("accepted") is not True:
                    return "submission_uncertain", None
                app_id, kind = data["applicationId"], "employer_confirmation_response"
        else:
            if (
                code != 200
                or response.get("content_type", "").split(";")[0] != "text/html"
            ):
                return "submission_uncertain", None
            # Exact supported success marker in the trusted HTTP body, never arbitrary page text.
            match = re.fullmatch(
                r'<!doctype html><title>Application received</title><main data-receipt="(fixture-[a-z0-9-]{1,80})" data-correlation="([a-f0-9-]{36})">Your response has been recorded\.</main>',
                body,
            )
            if not match or match[2] != correlation:
                return "submission_uncertain", None
            app_id, kind = match[1], "known_confirmation_page"
        evidence = SubmissionEvidence(
            type=kind,
            destination=expected,
            timestamp=now.isoformat(),
            application_id=app_id,
            correlation_id=submission.idempotency_key,
        )
        return "submitted", evidence
    except (ValueError, KeyError, TypeError, AttributeError):
        return "submission_uncertain", None
