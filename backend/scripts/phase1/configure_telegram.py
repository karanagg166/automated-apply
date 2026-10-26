"""Owner-run private bot setup; getMe/webhook check, explicit numeric identity binding."""
import argparse
import asyncio
import getpass
import json
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


async def main():
    from backend.app.core.config import Settings
    from backend.app.local_agent.telegram import BotAPI, TelegramError
    from backend.app.local_agent.telegram_pairing import discover_owner
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--discovery-timeout-seconds", type=int, default=120)
    args = parser.parse_args()
    if not 30 <= args.discovery_timeout_seconds <= 300:
        raise SystemExit("discovery_timeout_must_be_30_to_300_seconds")
    if not sys.stdin.isatty():
        raise SystemExit("interactive_private_terminal_required")
    path = Path(args.env_file).expanduser().absolute()
    if path.exists() and (path.is_symlink() or path.stat().st_mode & 0o077):
        raise SystemExit("private_regular_env_file_required")
    token = getpass.getpass("Private BotFather token (hidden): ")
    settings = Settings(_env_file=None, TELEGRAM_BOT_TOKEN=token)
    api = BotAPI(settings)
    try:
        me = await api.verify()
        print("Verified private bot @" + me.get("username", "unknown"))
        challenge = "aa_" + secrets.token_hex(12)
        print("Webhook verified absent. Do not run another polling worker during setup.")
        print("Send this exact fresh pairing command in your private conversation with @" + me.get("username", "unknown") + ":")
        print("/start " + challenge)
        print("Waiting up to", args.discovery_timeout_seconds, "seconds; leave this terminal running.")
        def progress(event):
            if event["state"] == "retrying":
                print("Retrying bounded setup poll:", event["error_code"], flush=True)
            else:
                print("Waiting for pairing: updates observed", event["updates_seen"],
                      "private messages", event["private_messages_seen"], flush=True)
        pair = await discover_owner(api, me.get("username", ""), challenge,
            timeout_seconds=args.discovery_timeout_seconds, on_progress=progress)
        candidates = [pair]
        print("Verified fresh private /start identity pair (user ID, chat ID):", pair)
        try:
            user = int(input("Approved owner user ID (copy observed numeric ID): "))
            chat = int(input("Approved private chat ID (copy observed numeric ID): "))
        except ValueError:
            raise SystemExit("numeric_owner_identity_required") from None
        if user <= 0 or chat <= 0 or (user, chat) not in candidates:
            raise SystemExit("owner_private_start_not_observed")
        lines = path.read_text().splitlines() if path.exists() else []
        values = {"TELEGRAM_BOT_TOKEN": token, "TELEGRAM_OWNER_USER_ID": str(user), "TELEGRAM_OWNER_CHAT_ID": str(chat)}
        lines = [line for line in lines if line.partition("=")[0] not in values]
        lines += [key + "=" + json.dumps(value) for key, value in values.items()]
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600), "w") as file:
            file.write("\n".join(lines) + "\n")
        print("owner_binding_saved; start the separate Telegram worker. No webhook changed.")
    except TelegramError as exc:
        if exc.code == "telegram_polling_conflict":
            print("Another getUpdates consumer conflicts with setup. Stop only your known bot worker (possibly on another device/service), then retry. No worker was stopped automatically.")
        elif exc.code == "telegram_webhook_conflict_owner_approval_required":
            print("A webhook is active. No delivery mode was changed; owner approval is required before altering it.")
        elif exc.code == "telegram_private_start_not_observed_before_deadline":
            print("No fresh pairing message was observed. Confirm the exact bot username and command, and check known external pollers. IDs were not guessed or saved.")
        raise SystemExit(exc.code) from None


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        raise SystemExit("setup_cancelled_no_owner_binding_saved") from None
