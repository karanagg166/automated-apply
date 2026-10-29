"""Explicit, optional Mail operations. No mailbox files, credentials or send action."""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


async def main(args):
    from backend.app.core.config import configure_operator
    from backend.app.integrations.token_store import ConnectionError
    from backend.app.local_agent.apple_mail import AppleMail, Draft, scripting
    from backend.app.operations.configuration import load_settings

    settings = load_settings(args.env_file)
    configure_operator(settings)
    if args.action == "discover":
        # Owner-invoked account-name discovery only; never reads a message.
        result = await scripting({"action": "accounts"})
    else:
        from backend.app.db.session import close_db_engine, get_session_factory
        try:
            async with get_session_factory()() as session:
                service = AppleMail(session, settings)
                if args.action == "accounts":
                    result = await service.accounts()
                elif args.action == "search":
                    result = await service.search(args.account_id)
                elif args.action == "read":
                    result = await service.read(args.account_id, args.message_id)
                else:
                    path = Path(args.draft_file)
                    if path.is_symlink() or path.stat().st_mode & 0o077:
                        raise ConnectionError("private_draft_file_required")
                    result = await service.draft(args.account_id, Draft.model_validate_json(path.read_bytes()))
        finally:
            await close_db_engine()
    output = json.dumps(result, indent=2) + "\n"
    if args.output:
        descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w") as file:
            file.write(output)
        print("Private Mail evidence saved")
    else:
        print(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["discover", "accounts", "search", "read", "draft"])
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--account-id")
    parser.add_argument("--message-id", type=int)
    parser.add_argument("--draft-file")
    parser.add_argument("--output")
    arguments = parser.parse_args()
    if arguments.action in {"search", "read", "draft"} and not arguments.account_id:
        parser.error("explicit_account_id_required")
    if arguments.action == "read" and (arguments.message_id is None or arguments.message_id < 0):
        parser.error("explicit_message_id_required")
    if arguments.action == "draft" and not arguments.draft_file:
        parser.error("private_draft_file_required")
    try:
        asyncio.run(main(arguments))
    except Exception as exc:
        from backend.app.integrations.token_store import ConnectionError
        print(str(exc) if isinstance(exc, ConnectionError) else "local_mail_operation_failed", file=sys.stderr)
        raise SystemExit(1) from None
