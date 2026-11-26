"""Gmail draft bridge + enrichment commands (READ + DRAFT ONLY: nothing here can deliver an email)."""

from __future__ import annotations

from typing import Any

from backend.app.browser_v2.cli.common import emit


async def mail_status_command(probe: bool, mail_app: bool, recent: int) -> int:
    """Draft bridge config + READ_AND_DRAFT_ONLY lock; --probe logs in (EXAMINE only), never writes."""
    from backend.app.ai_v2.router import load_env
    from backend.app.mail_v2.config import MailConfig
    from backend.app.mail_v2.imap_drafts import ImapDraftClient
    from backend.app.mail_v2.mail_app_drafts import MailAppDraftClient

    config = MailConfig.from_env(load_env())
    result: dict[str, Any] = {"permission": "READ_AND_DRAFT_ONLY",
                              "label": "Gmail Permission: Read + Draft Only (Sending Disabled)",
                              "config": config.public()}
    if probe and config.imap_configured:
        result["imap"] = await ImapDraftClient(config).check_connection()
    if recent and config.imap_configured:
        try:
            result["recent_drafts"] = await ImapDraftClient(config).list_recent_drafts(recent)
        except Exception as exc:  # noqa: BLE001 - diagnostic only
            result["recent_drafts_error"] = type(exc).__name__
    if mail_app:
        result["mail_app"] = await MailAppDraftClient(config).probe()
    emit(result)
    return 0 if config.active_channel() != "unconfigured" else 1


async def test_draft_command(to: str, company: str, role: str, jd_file: str | None, dry_run: bool,
                             no_llm: bool) -> int:
    """Compose one tailored draft and save it as a clearly marked [TEST DRAFT] (or preview with --dry-run)."""
    from pathlib import Path

    from backend.app.ai_v2.router import load_env
    from backend.app.ai_v2.runtime import AIRuntime
    from backend.app.browser_v2.service import open_store
    from backend.app.mail_v2.composer import DraftComposer, DraftJob
    from backend.app.mail_v2.config import MailConfig
    from backend.app.mail_v2.message import (
        TEST_SUBJECT_PREFIX,
        DraftValidationError,
        valid_recipient,
    )
    from backend.app.mail_v2.service import MailDraftService

    try:
        recipient = valid_recipient(to)
    except DraftValidationError as exc:
        emit({"saved": False, "error": str(exc)})
        return 2
    jd_text = Path(jd_file).read_text(encoding="utf-8")[:20_000] if jd_file else None
    env = load_env()
    store, backend = await open_store(require_db=False)
    try:
        profile, _ = await store.load_profile()
        router = None
        if not no_llm:
            ai = await AIRuntime.for_store(store, env=env)
            ai.bind_profile(profile)
            router = ai.router
        config = MailConfig.from_env(env)
        mail = MailDraftService(store, config)
        content = await DraftComposer(router).compose(
            DraftJob(role_title=role, company_name=company, jd_text=jd_text), profile,
            has_attachment=bool(config.resume_path))
        preview = {"to": recipient, "subject": TEST_SUBJECT_PREFIX + content.subject, "body": content.body,
                   "composer": content.composer, "llm_provider": content.provider,
                   "channel": config.active_channel(), "store": backend.split(" ")[0]}
        if dry_run:
            emit({"dry_run": True, "saved": False, "preview": preview})
            return 0
        outcome = await mail.save_test_draft(recipient, content,
                                             sender_name=profile.get("full_name") if profile else None)
        emit({"dry_run": False, "saved": outcome.created, **outcome.public(), "preview": preview,
              "note": "Draft only. Review it in Gmail > Drafts; nothing was delivered."})
        return 0 if outcome.created else 1
    finally:
        await store.close()


async def enrichment_status_command() -> int:
    from backend.app.ai_v2.router import load_env
    from backend.app.browser_v2.service import open_store
    from backend.app.enrichment_v2.service import EnrichmentService

    store, backend = await open_store(require_db=False)
    try:
        service = await EnrichmentService.for_store(store, env=load_env())
        emit({"store": backend, **await service.status()})
        return 0
    finally:
        await store.close()
