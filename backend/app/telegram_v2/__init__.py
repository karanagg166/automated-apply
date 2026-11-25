"""Phase 4 Telegram HITL bot: Bot API long polling only (no webhook, no tunnel).

Independent of the frozen Rust agent and the legacy local_agent Telegram worker;
only the env var names (TELEGRAM_BOT_TOKEN, TELEGRAM_OWNER_CHAT_ID,
TELEGRAM_OWNER_USER_ID) are shared so existing private env files work unchanged.
"""
