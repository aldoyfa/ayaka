"""AI Conversation Repository for Ayaka SQLite storage.

Provides persistent chat context across bot restarts, preventing in-memory
state leaks while managing automatic TTL pruning.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

from ayaka.storage.repositories.base import BaseRepository


class AIConversationRepository(BaseRepository):
    """Repository handling persistent conversational memory for the AI agent."""

    def save_message(self, user_id: str, role: str, content: str) -> None:
        """Persist a conversation turn (user or assistant)."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.conn_mgr.transaction() as conn:
            conn.execute(
                """
                INSERT INTO ai_conversations (user_id, role, content, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, role, content, now_iso),
            )

    def get_history(self, user_id: str, limit: int = 12) -> List[dict[str, str]]:
        """Retrieve recent conversation history for a user in chronological order."""
        with self.conn_mgr.transaction() as conn:
            rows = conn.execute(
                """
                SELECT role, content FROM ai_conversations
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()

            # Reverse to maintain chronological order for LLM context
            return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    def clear_history(self, user_id: str) -> None:
        """Clear all conversation history for a specific user."""
        with self.conn_mgr.transaction() as conn:
            conn.execute("DELETE FROM ai_conversations WHERE user_id = ?", (user_id,))

    def prune_expired(self, max_age_hours: int = 48) -> int:
        """Prune conversation turns older than max_age_hours to bound storage size."""
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).isoformat()
        with self.conn_mgr.transaction() as conn:
            cur = conn.execute("DELETE FROM ai_conversations WHERE created_at < ?", (cutoff,))
            return cur.rowcount
