"""Phase 5 local Gmail draft bridge — STRICTLY READ + DRAFT ONLY.

Primary channel: IMAP APPEND into the Gmail Drafts mailbox (works behind a locked
screen, no macOS Automation prompt). Fallback: a silent Mail.app outgoing message
saved with visible:false (never brought to the foreground). Nothing in this package can deliver
mail: there is no SMTP client, no delivery call and no Gmail delivery scope;
tests/test_gmail_no_send_guardrail.py enforces that statically and at runtime.
"""

PERMISSION = "READ_AND_DRAFT_ONLY"
