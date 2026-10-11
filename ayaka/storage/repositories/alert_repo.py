"""Alert, Gmail, and Sync Log Repository for Ayaka SQLite storage.

Handles deduplication of Gmail alerts, schedule reminder dispatches,
session expiration cooldowns, and platform sync logging.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from ayaka.storage.repositories.base import BaseRepository


class AlertRepository(BaseRepository):
    """Repository handling alerts, logs, and notification deduplication."""

    # ----------------- GMAIL MESSAGES -----------------

    def is_gmail_processed(self, message_id: str) -> bool:
        """Check if a Gmail message has already been processed and alerted."""
        with self.conn_mgr.transaction() as conn:
            row = conn.execute(
                "SELECT 1 FROM gmail_messages WHERE message_id = ?", (message_id,)
            ).fetchone()
            return row is not None

    def record_gmail_message(
        self,
        message_id: str,
        subject: str,
        sender: str,
        snippet: str,
        received_at: str,
    ) -> None:
        """Record an alerted Gmail message to prevent duplicate alerts."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.conn_mgr.transaction() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO gmail_messages (
                    message_id, subject, sender, snippet, received_at, alerted_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (message_id, subject, sender, snippet, received_at, now_iso),
            )

    # ----------------- SYNC LOGS -----------------

    def log_sync(self, platform: str, status: str, message: str) -> None:
        """Log the result of a sync cycle."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.conn_mgr.transaction() as conn:
            conn.execute(
                "INSERT INTO sync_logs (platform, status, message, timestamp) VALUES (?, ?, ?, ?)",
                (platform, status, message, now_iso),
            )

    def get_last_sync_status(self) -> dict[str, dict[str, Any]]:
        """Retrieve most recent sync log per platform."""
        result: dict[str, dict[str, Any]] = {}
        with self.conn_mgr.transaction() as conn:
            rows = conn.execute(
                """
                SELECT platform, status, message, timestamp
                FROM sync_logs
                WHERE id IN (SELECT MAX(id) FROM sync_logs GROUP BY platform)
                """
            ).fetchall()
            for r in rows:
                result[r["platform"]] = {
                    "status": r["status"],
                    "message": r["message"],
                    "timestamp": r["timestamp"],
                }
        return result

    # ----------------- SCHEDULE REMINDERS -----------------

    def is_schedule_reminder_sent(self, reminder_id: str) -> bool:
        """Check if a specific schedule reminder (morning, start, attendance) was already dispatched."""
        with self.conn_mgr.transaction() as conn:
            row = conn.execute(
                "SELECT 1 FROM schedule_reminders WHERE id = ?", (reminder_id,)
            ).fetchone()
            return row is not None

    def record_schedule_reminder(
        self,
        reminder_id: str,
        reminder_type: str,
        event_id: Optional[str] = None,
        event_title: Optional[str] = None,
        scheduled_for: str = "",
    ) -> None:
        """Record a dispatched schedule reminder to prevent duplicate alerts."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.conn_mgr.transaction() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO schedule_reminders (
                    id, reminder_type, event_id, event_title, scheduled_for, sent_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (reminder_id, reminder_type, event_id, event_title, scheduled_for, now_iso),
            )

    # ----------------- SESSION ALERTS -----------------

    def should_alert_session_expired(self, platform: str, cooldown_hours: float = 12.0) -> bool:
        """Check if an alert for expired session should be sent based on cooldown."""
        with self.conn_mgr.transaction() as conn:
            row = conn.execute("SELECT last_alerted_at FROM session_alerts WHERE platform = ?", (platform,)).fetchone()
            if not row:
                return True
            try:
                last_dt = datetime.fromisoformat(row["last_alerted_at"])
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                diff = (datetime.now(timezone.utc) - last_dt).total_seconds()
                return diff > (cooldown_hours * 3600)
            except Exception:
                return True

    def record_session_alert(self, platform: str) -> None:
        """Record the timestamp of a sent session alert."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.conn_mgr.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO session_alerts (platform, last_alerted_at) VALUES (?, ?)",
                (platform, now_iso),
            )

    def clear_session_alert(self, platform: str) -> None:
        """Clear session alert when platform succeeds again."""
        with self.conn_mgr.transaction() as conn:
            conn.execute("DELETE FROM session_alerts WHERE platform = ?", (platform,))
