"""Owner CLI for the dedicated Brave profile and the Naukri adapter.

Run from the repository root:
    backend/venv/bin/python -m backend.app.browser_v2.cli login-setup
    backend/venv/bin/python -m backend.app.browser_v2.cli check-session --portal naukri --restart
    backend/venv/bin/python -m backend.app.browser_v2.cli test-apply --portal naukri --dry-run --limit 1
    backend/venv/bin/python -m backend.app.browser_v2.cli test-apply --portal naukri --live --limit 1
    backend/venv/bin/python -m backend.app.browser_v2.cli worker --dry-run --once
    backend/venv/bin/python -m backend.app.browser_v2.cli mcp
    backend/venv/bin/python -m backend.app.browser_v2.cli ai-status [--load-embedder]
    backend/venv/bin/python -m backend.app.browser_v2.cli ai-test [--provider groq]
    backend/venv/bin/python -m backend.app.browser_v2.cli seed-cache
    backend/venv/bin/python -m backend.app.browser_v2.cli test-qa --question "..." [--option Yes --option No]
    backend/venv/bin/python -m backend.app.browser_v2.cli worker --dry-run [--no-telegram]
    backend/venv/bin/python -m backend.app.browser_v2.cli telegram-status [--probe]
    backend/venv/bin/python -m backend.app.browser_v2.cli telegram-test
    backend/venv/bin/python -m backend.app.browser_v2.cli mail-status [--probe] [--mail-app] [--recent 5]
    backend/venv/bin/python -m backend.app.browser_v2.cli test-draft --to hr@example.com --company Acme \
        --role "Backend Engineer" [--dry-run]
    backend/venv/bin/python -m backend.app.browser_v2.cli enrichment-status
    backend/venv/bin/python -m backend.app.browser_v2.cli live-smoke --check db --check mail [--mail-app]
    backend/venv/bin/python -m backend.app.browser_v2.cli test-apply --portal greenhouse --board <token> --dry-run
    backend/venv/bin/python -m backend.app.browser_v2.cli set-portal-cred --portal instahyre
    backend/venv/bin/python -m backend.app.browser_v2.cli export-sft-dataset --out ~/sft.jsonl
    backend/venv/bin/python -m backend.app.browser_v2.cli agent-chat "how many applied today?"
    backend/venv/bin/python -m backend.app.browser_v2.cli health-check [--json] [--no-db]
    backend/venv/bin/python -m backend.app.browser_v2.cli test-apply --portal instahyre --dry-run --debug-selectors
    backend/venv/bin/python -m backend.app.browser_v2.cli sync-profile --portal naukri [--dry-run | --confirm-live]
    backend/venv/bin/python -m backend.app.browser_v2.cli probe-profile-page --portal naukri [--url <profile page>]

Gmail is READ + DRAFT ONLY: no command here can deliver an email.
"""

from __future__ import annotations

import asyncio

from backend.app.browser_v2 import profile as brave_profile
from backend.app.browser_v2.cli.commands_ai import (
    ai_status_command,
    ai_test_command,
    export_sft_command,
    seed_cache_command,
    test_qa_command,
)
from backend.app.browser_v2.cli.commands_browser import (
    SYNTHETIC_PDF,
    apply_one_command,
    check_session,
    debug_bundle,
    default_query,
    login_setup,
    synthetic_profile,
    test_apply,
    verify_submissions_command,
)
from backend.app.browser_v2.cli.commands_mail import (
    enrichment_status_command,
    mail_status_command,
    test_draft_command,
)
from backend.app.browser_v2.cli.commands_ops import (
    agent_chat_command,
    health_check_command,
    live_smoke_command,
    run_worker_command,
    set_portal_cred_command,
)
from backend.app.browser_v2.cli.commands_profile import (
    probe_profile_command,
    sync_profile_command,
)
from backend.app.browser_v2.cli.commands_telegram import (
    telegram_status_command,
    telegram_test_command,
)
from backend.app.browser_v2.cli.common import (
    MAX_DEBUG_BUNDLES,
    MAX_INSPECTIONS_PER_APPLY,
    PHASE1_LIVE_LIMIT,
    emit,
)
from backend.app.browser_v2.cli.parser import build_parser
from backend.app.browser_v2.portals import PORTALS

__all__ = [
    "MAX_DEBUG_BUNDLES",
    "MAX_INSPECTIONS_PER_APPLY",
    "PHASE1_LIVE_LIMIT",
    "PORTALS",
    "SYNTHETIC_PDF",
    "agent_chat_command",
    "ai_status_command",
    "ai_test_command",
    "brave_profile",
    "build_parser",
    "check_session",
    "debug_bundle",
    "default_query",
    "emit",
    "enrichment_status_command",
    "export_sft_command",
    "health_check_command",
    "live_smoke_command",
    "login_setup",
    "mail_status_command",
    "main",
    "probe_profile_command",
    "run_worker_command",
    "seed_cache_command",
    "set_portal_cred_command",
    "sync_profile_command",
    "synthetic_profile",
    "telegram_status_command",
    "telegram_test_command",
    "test_apply",
    "test_draft_command",
    "test_qa_command",
    "verify_submissions_command",
]


def main(argv: list[str] | None = None) -> int:
    """Commands are looked up on this package module at call time (tests monkeypatch e.g. `login_setup`)."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "set-portal-cred":
            return set_portal_cred_command(args.portal)
        if args.command == "export-sft-dataset":
            return asyncio.run(export_sft_command(args.out))
        if args.command == "agent-chat":
            return asyncio.run(agent_chat_command(args.text))
        if args.command == "health-check":
            return asyncio.run(health_check_command(args.json, not args.no_db))
        if args.command == "verify-submissions":
            return asyncio.run(verify_submissions_command(args.portal))
        if args.command == "sync-profile":
            return asyncio.run(sync_profile_command(args.portal, args.confirm_live, args.yes))
        if args.command == "probe-profile-page":
            return asyncio.run(probe_profile_command(args.portal, args.url))
        if args.command == "apply-one":
            return asyncio.run(apply_one_command(args.portal, args.url, args.confirm_live, args.yes))
        if args.command == "facts":
            from backend.app.browser_v2 import facts_cli as facts_module

            return facts_module.run(args)
        if args.command == "login-setup":
            from backend.app.browser_v2.portals import LOGIN_PORTALS

            portals = sorted(brave_profile.LOGIN_URLS) if args.all else (args.portal or sorted(LOGIN_PORTALS))
            return login_setup(portals)
        if args.command == "mail-status":
            return asyncio.run(mail_status_command(args.probe, args.mail_app, max(0, min(args.recent, 50))))
        if args.command == "test-draft":
            return asyncio.run(test_draft_command(args.to, args.company, args.role, args.jd_file, args.dry_run,
                                                  args.no_llm))
        if args.command == "enrichment-status":
            return asyncio.run(enrichment_status_command())
        if args.command == "live-smoke":
            checks = args.check or ["db", "ai", "telegram", "mail", "enrichment"]
            return asyncio.run(live_smoke_command(checks, args.mail_app, not args.no_llm_ping, args.portal))
        if args.command == "check-session":
            return asyncio.run(check_session(args.portal, args.restart, args.debug_selectors))
        if args.command == "test-apply":
            return asyncio.run(test_apply(args.portal, args.live, max(1, args.limit), args.query,
                                          args.url, args.yes, boards=args.board,
                                          debug_selectors=args.debug_selectors,
                                          synthetic=args.synthetic_profile))
        if args.command == "worker":
            return asyncio.run(run_worker_command(args.dry_run, args.once, telegram=not args.no_telegram))
        if args.command == "telegram-status":
            return asyncio.run(telegram_status_command(args.probe))
        if args.command == "telegram-test":
            return asyncio.run(telegram_test_command())
        if args.command == "ai-status":
            return asyncio.run(ai_status_command(args.load_embedder))
        if args.command == "ai-test":
            return asyncio.run(ai_test_command(args.provider))
        if args.command == "seed-cache":
            return asyncio.run(seed_cache_command())
        if args.command == "test-qa":
            return asyncio.run(test_qa_command(args.question, args.option, args.no_llm, args.no_save))
        from backend.app.browser_v2.browser_mcp import mcp

        mcp.run()
        return 0
    except brave_profile.ProfileError as exc:
        emit({"error": str(exc)})
        return 2
