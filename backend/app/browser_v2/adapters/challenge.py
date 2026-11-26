"""Shared fail-closed CAPTCHA / bot-challenge detection for every Playwright probe.

Live calibration (2026-11-26, naukri.com/nlogin/login): the plain login page carries an
*invisible* reCAPTCHA (`div.g-recaptcha[data-size=invisible]`, height 0). Matching any
`[data-sitekey]` misclassified every login wall as a CAPTCHA challenge. An active challenge
must be a rendered widget (non-zero box) that is not an invisible/badge-only reCAPTCHA, or
explicit challenge copy; Google's mandatory "protected by reCAPTCHA" notice is ignored.
"""

from __future__ import annotations

import json

CHALLENGE_SELECTOR = (
    'iframe[src*="captcha"]:not([src*="size=invisible"]),iframe[src*="challenges.cloudflare"],'
    'iframe[title*="challenge" i],[data-sitekey]:not([data-size="invisible"])'
)
# Copy that only appears on a real interstitial (never on the reCAPTCHA legal notice).
CHALLENGE_TEXT = (r"captcha|verify (?:that )?you are (?:a )?human|unusual traffic|access denied|"
                  r"too many requests|press and hold")
RECAPTCHA_NOTICE = r"(?:this (?:site|page) is )?protected by (?:re)?captcha[^\n.]*\.?"
# Cloudflare / Akamai / DataDome interstitial titles (live: instahyre.com "Just a moment...", blank body).
CHALLENGE_TITLE = r"^\s*(?:just a moment|attention required|one more step|security check|verifying you are human|" \
                  r"access denied|please wait while we verify)"

# Defines `challengeNodes()` (rendered widgets), `challengeTitle()` (interstitial title) and
# `challengeText(body)` (title or copy, reCAPTCHA notice stripped).
CHALLENGE_HELPERS_JS = (
    "const challengeNodes = () => { let nodes = []; try { nodes = [...document.querySelectorAll("
    + json.dumps(CHALLENGE_SELECTOR)
    + ")]; } catch (e) { return false; } return nodes.some((el) => { if (!el || !el.isConnected) return false;"
    " const r = el.getBoundingClientRect(); return r.width > 1 && r.height > 1"
    " && getComputedStyle(el).visibility !== 'hidden'; }); };\n"
    "const challengeTitle = () => /" + CHALLENGE_TITLE + "/i.test(document.title || '');\n"
    "const challengeText = (body) => challengeTitle() || /" + CHALLENGE_TEXT + "/i.test((body || '').replace(/"
    + RECAPTCHA_NOTICE + "/ig, ' '));\n"
)
