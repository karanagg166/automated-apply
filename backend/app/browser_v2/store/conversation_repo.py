"""PostgresStore agent conversation memory (followup 005): sliding window per chat_key."""

from __future__ import annotations

from backend.app.browser_v2.store.agent_records import (
    CHAT_KEY,
    TURNS_PER_CHAT,
    ConversationTurn,
    check_turn_limit,
)
from backend.app.browser_v2.store.base import PostgresBase


class ConversationRepo(PostgresBase):
    async def append_turn(self, turn: ConversationTurn) -> None:
        """Insert one turn, then prune the chat to its newest 200 rows."""
        await self.connection.execute(
            "INSERT INTO public.agent_conversation_turns (chat_key, role, content) VALUES ($1, $2, $3)",
            turn.chat_key, turn.role, turn.content)
        await self.connection.execute(
            """DELETE FROM public.agent_conversation_turns WHERE chat_key = $1 AND id IN (
                   SELECT id FROM public.agent_conversation_turns WHERE chat_key = $1
                   ORDER BY created_at DESC, id DESC OFFSET $2)""",
            turn.chat_key, TURNS_PER_CHAT)

    async def recent_turns(self, chat_key: str, limit: int = 12) -> list[ConversationTurn]:
        """The newest `limit` turns, returned oldest -> newest."""
        if not CHAT_KEY.match(chat_key or ""):
            return []
        rows = await self.connection.fetch(
            """SELECT id, chat_key, role, content, created_at FROM public.agent_conversation_turns
               WHERE chat_key = $1 ORDER BY created_at DESC, id DESC LIMIT $2""",
            chat_key, check_turn_limit(limit))
        return [ConversationTurn.from_row(row) for row in reversed(rows)]

    async def clear_turns(self, chat_key: str) -> int:
        if not CHAT_KEY.match(chat_key or ""):
            return 0
        result = await self.connection.execute(
            "DELETE FROM public.agent_conversation_turns WHERE chat_key = $1", chat_key)
        return int(str(result).rsplit(" ", 1)[-1] or 0)
