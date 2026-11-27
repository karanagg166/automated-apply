"""argparse construction for the browser_v2 owner CLI (subcommands + facts_cli registration)."""

from __future__ import annotations

import argparse

from backend.app.browser_v2 import profile as brave_profile
from backend.app.browser_v2.portals import PORTALS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="browser_v2", description="Dedicated Brave profile tools")
    commands = parser.add_subparsers(dest="command", required=True)
    login = commands.add_parser("login-setup", help="open plain Brave on the dedicated profile")
    login.add_argument("--portal", action="append", choices=sorted(brave_profile.LOGIN_URLS),
                       help="repeatable; default: portals with a live adapter (naukri)")
    login.add_argument("--all", action="store_true", help="open all 8 browser-portal login pages")
    check = commands.add_parser("check-session", help="verify the persistent login")
    check.add_argument("--portal", default="naukri", choices=sorted(PORTALS))
    check.add_argument("--restart", action="store_true", help="also verify after a browser restart")
    check.add_argument("--debug-selectors", action="store_true",
                       help="save a PII-scrubbed DOM probe + screenshot under receipts/diagnostics/")
    apply = commands.add_parser("test-apply", help="discover and apply (dry-run or one live)")
    apply.add_argument("--portal", default="naukri", choices=sorted(PORTALS))
    apply.add_argument("--board", action="append", default=[],
                       help="greenhouse/lever board token for this run (repeatable; else preferences)")
    mode = apply.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--live", action="store_true")
    apply.add_argument("--limit", type=int, default=1)
    apply.add_argument("--query", help="search keywords (default: first preferences.target_roles)")
    apply.add_argument("--url", help="apply to this exact job URL instead of searching")
    apply.add_argument("--yes", action="store_true", help="skip the typed live confirmation")
    apply.add_argument("--synthetic-profile", action="store_true",
                       help="dry-run + memory store only: fictional example.com identity to calibrate form filling")
    apply.add_argument("--debug-selectors", action="store_true",
                       help="dry-run only: save PII-scrubbed DOM probe bundles (max 3) under receipts/diagnostics/")
    worker = commands.add_parser("worker", help="24/7 loop driven by public.worker_control")
    worker.add_argument("--dry-run", action="store_true",
                        help="never click Apply (also forced by DRY_RUN=true)")
    worker.add_argument("--once", action="store_true", help="run exactly one cycle now, then exit")
    worker.add_argument("--no-telegram", action="store_true",
                        help="do not run the Telegram HITL poller/dispatcher (isolated debugging)")
    tg_status = commands.add_parser("telegram-status", help="Telegram HITL config, poll offset and conflict state")
    tg_status.add_argument("--probe", action="store_true",
                           help="also call getMe/getWebhookInfo/getUpdates live to detect a 409 conflict")
    commands.add_parser("telegram-test", help="send one test ping to the owner chat")
    commands.add_parser("mcp", help="serve the browser tools over FastMCP stdio")
    status = commands.add_parser("ai-status", help="free LLM providers, failover order, embedding model")
    status.add_argument("--load-embedder", action="store_true",
                        help="load (and on first use download, ~80 MB) the local ONNX embedding model")
    ai_test = commands.add_parser("ai-test", help="live 1-request JSON probe of each configured free LLM provider")
    ai_test.add_argument("--provider", action="append", default=[], help="limit to this provider (repeatable)")
    commands.add_parser("langfuse-test", help="verify Langfuse keys and send one synthetic trace (no PII)")
    commands.add_parser("seed-cache", help="seed semantic_cache from reviewed application_answer_drafts")
    qa = commands.add_parser("test-qa", help="run the 4-tier screening answer pipeline for one question")
    qa.add_argument("--question", required=True)
    qa.add_argument("--option", action="append", default=[], help="a choice option (repeatable)")
    qa.add_argument("--no-llm", action="store_true", help="stop after Tier 1 (no external LLM call)")
    qa.add_argument("--no-save", action="store_true", help="do not cache an accepted LLM answer")
    mail = commands.add_parser("mail-status", help="Gmail draft bridge (IMAP / Mail.app), READ + DRAFT ONLY")
    mail.add_argument("--probe", action="store_true", help="IMAP login + read-only EXAMINE of Drafts")
    mail.add_argument("--mail-app", action="store_true",
                      help="probe Mail.app scripting (may show the one-time macOS Automation prompt)")
    mail.add_argument("--recent", type=int, default=0, help="list N recent Gmail draft headers (read-only)")
    draft = commands.add_parser("test-draft", help="compose + save one [TEST DRAFT] in Gmail Drafts (never delivered)")
    draft.add_argument("--to", required=True)
    draft.add_argument("--company", required=True)
    draft.add_argument("--role", required=True)
    draft.add_argument("--jd-file", help="optional plain-text JD to tailor the draft")
    draft.add_argument("--dry-run", action="store_true", help="print the composed draft; save nothing")
    draft.add_argument("--no-llm", action="store_true", help="deterministic template only")
    commands.add_parser("enrichment-status", help="Apollo/Apify/SignalHire config + today's free credits")
    smoke = commands.add_parser("live-smoke", help="opt-in non-destructive live checks (JSON report)")
    smoke.add_argument("--check", action="append", choices=["db", "browser", "ai", "telegram", "mail",
                                                            "enrichment"],
                       help="repeatable; default: db ai telegram mail enrichment (browser is opt-in)")
    smoke.add_argument("--mail-app", action="store_true", help="also probe Mail.app scripting")
    smoke.add_argument("--no-llm-ping", action="store_true", help="skip the 1-request free LLM health ping")
    smoke.add_argument("--portal", default="naukri", choices=["naukri"])
    cred = commands.add_parser("set-portal-cred", help="store a portal login in the macOS Keychain (auto re-login)")
    cred.add_argument("--portal", required=True, choices=sorted(PORTALS))
    sft = commands.add_parser("export-sft-dataset", help="PII-scrubbed verified Q&A -> chat JSONL for fine-tuning")
    sft.add_argument("--out", required=True, help="output .jsonl path (written 0600)")
    chat = commands.add_parser("agent-chat", help="one message to the LangGraph control agent")
    chat.add_argument("text")
    one = commands.add_parser("apply-one", help="Phase 8 canary: ONE job by URL (dry-run unless --confirm-live)")
    one.add_argument("--portal", required=True, choices=sorted(PORTALS))
    one.add_argument("--url", required=True, help="exact job URL on that portal")
    one.add_argument("--confirm-live", action="store_true",
                     help="really apply (still asks you to type 'APPLY <portal>'); default is a dry-run")
    one.add_argument("--yes", action="store_true", help="with --confirm-live: skip the typed confirmation")
    verify = commands.add_parser("verify-submissions",
                                 help="confirm SUBMISSION_UNKNOWN rows from the portal's application history")
    verify.add_argument("--portal", default="naukri", choices=sorted(PORTALS))
    from backend.app.browser_v2 import facts_cli

    facts_cli.register(commands)
    health = commands.add_parser("health-check", help="non-destructive 24/7 watchdog report (Phase 6B)")
    health.add_argument("--json", action="store_true", help="machine-readable JSON")
    health.add_argument("--no-db", action="store_true", help="skip the single read-only DB probe")
    from backend.app.browser_v2.profile_sync.adapters import PROFILE_PORTALS

    sync = commands.add_parser("sync-profile", help="Phase 9D: sync the canonical profile to ONE portal "
                                                    "(dry-run unless --confirm-live)")
    sync.add_argument("--portal", required=True, choices=PROFILE_PORTALS)
    sync_mode = sync.add_mutually_exclusive_group()
    sync_mode.add_argument("--dry-run", action="store_true", help="report the diff only (the default)")
    sync_mode.add_argument("--confirm-live", action="store_true",
                           help="really save changed fields (asks you to type 'SYNC <portal>'; needs "
                                "profile_sync.<portal>.live = true)")
    sync.add_argument("--yes", action="store_true", help="with --confirm-live: skip the typed confirmation")
    probe = commands.add_parser("probe-profile-page",
                                help="PII-scrubbed outline of the logged-in profile page (selector calibration; "
                                     "stop the worker first)")
    probe.add_argument("--portal", required=True, choices=PROFILE_PORTALS)
    probe.add_argument("--url", help="profile page URL (required where no verified default exists)")
    return parser
