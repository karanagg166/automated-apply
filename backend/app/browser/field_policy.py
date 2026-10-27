"""Defense in depth for untrusted form labels, including native inspections."""

import re

SENSITIVE = re.compile(
    r"password|passcode|passphrase|one.?time|\botp\b|\bmfa\b|\b2fa\b|two.?factor|"
    r"verification.?code|security.?code|credit.?card|debit.?card|card.?number|\bcvv\b|\bcvc\b|"
    r"card.?expir|name\s+on\s+(?:the\s+)?card|bank.?account|routing.?number|\biban\b|\bifsc\b|\bupi\b|payment|session|token|secret|"
    r"api.?key|private.?key|social.?security|\bssn\b|\baadhaar\b|\baadhar\b|"
    r"\bpan\s*(?:card|number|no)\b|tax.?id|national.?id|government.{0,15}\bid\b|passport|"
    r"driv(?:er|ing).?licen[sc]e|\bpin\b(?![\s-]*code)|security.?question|"
    r"\b(?:gender|race|ethnic\w*|religion|disabil\w*|veteran|military|sexual\w*|pronouns?|"
    r"marital|self.?identif\w*)\b|date.?of.?birth|birth.?date|\bdob\b",
    re.I,
)
ATTESTATION = re.compile(
    r"\b(?:consent|agree|agreement|terms|privacy|acknowledge|certif(?:y|ication)|"
    r"attest(?:ation)?|declare|declaration|hereby|gdpr|background\s*check|eeo|nda|"
    r"subscribe|permission|affirm|accept)\b|true\s+and\s+(?:correct|accurate)|"
    r"data\s*processing|non.?disclosure|accuracy\s+of\s+information",
    re.I,
)


def manual_only(*labels):
    text = " ".join(labels).replace("_", " ").replace("-", " ")
    return bool(SENSITIVE.search(text) or ATTESTATION.search(text))
