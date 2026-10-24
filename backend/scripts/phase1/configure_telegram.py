"""Owner-run private bot setup; getMe/webhook check, explicit numeric identity binding."""
import argparse
import asyncio
import getpass
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


async def main():
    from backend.app.core.config import Settings
    from backend.app.local_agent.telegram import BotAPI, TelegramError
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", required=True)
    args = parser.parse_args()
    path = Path(args.env_file).expanduser().absolute()
    if path.exists() and (path.is_symlink() or path.stat().st_mode & 0o077):
        raise SystemExit("private_regular_env_file_required")
    token = getpass.getpass("Private BotFather token (hidden): ")
    settings = Settings(_env_file=None, TELEGRAM_BOT_TOKEN=token)
    api = BotAPI(settings)
    try:
        me = await api.verify()
        print("Verified private bot @" + me.get("username", "unknown"))
        input("Send /start to this bot in your private conversation, then press Enter. ")
        updates = await api.call("getUpdates", {"timeout": 0, "limit": 20, "allowed_updates": ["message"]})
        candidates = sorted({(update["message"]["from"]["id"], update["message"]["chat"]["id"])
            for update in updates if update.get("message", {}).get("chat", {}).get("type") == "private"
            and update.get("message", {}).get("text", "").split("@")[0] == "/start"})
        print("Private /start identity pairs (user ID, chat ID):", candidates)
        user = int(input("Approved owner user ID: "))
        chat = int(input("Approved private chat ID: "))
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
        raise SystemExit(exc.code) from None


if __name__ == "__main__":
    asyncio.run(main())
