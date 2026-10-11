"""SQLite storage facade for Ayaka.

Composes specialized domain repositories:
- TaskRepository: Academic task tracking and reminder milestones
- MeetingRepository: Lecture meeting schedules and modal enrichment
- AlertRepository: Gmail alerts, session alerts, and sync changelogs
- AIConversationRepository: Persistent conversational memory
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Generator, List, Optional, Tuple

from ayaka.storage.connection import ConnectionManager
from ayaka.storage.repositories import (
    AIConversationRepository,
    AlertRepository,
    MeetingRepository,
    TaskRepository,
)


class Database:
    """Central database coordinator managing schemas and repository access."""

    def __init__(self, db_path: str = "ayaka_state.db") -> None:
        self.db_path = str(db_path)
        self.conn_mgr = ConnectionManager(self.db_path)

        # Repositories
        self.tasks = TaskRepository(self.conn_mgr)
        self.meetings = MeetingRepository(self.conn_mgr)
        self.alerts = AlertRepository(self.conn_mgr)
        self.ai_conversations = AIConversationRepository(self.conn_mgr)

        self._ensure_dir()
        self.init_db()

    def _ensure_dir(self) -> None:
        path = Path(self.db_path)
        if path.parent and not path.parent.exists():
            path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager yielding a persistent thread connection in an active transaction."""
        with self.conn_mgr.transaction() as conn:
            yield conn

    def init_db(self) -> None:
        """Create database tables and performance indexes if they do not exist."""
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    platform TEXT NOT NULL,
                    course_id TEXT,
                    course_name TEXT,
                    title TEXT NOT NULL,
                    description TEXT,
                    due_date TEXT NOT NULL,
                    url TEXT,
                    is_completed INTEGER NOT NULL DEFAULT 0,
                    google_calendar_event_id TEXT,
                    google_tasks_task_id TEXT,
                    reminder_h3_sent INTEGER NOT NULL DEFAULT 0,
                    reminder_h1_sent INTEGER NOT NULL DEFAULT 0,
                    reminder_j6_sent INTEGER NOT NULL DEFAULT 0,
                    reminder_j1_sent INTEGER NOT NULL DEFAULT 0,
                    reminder_due_sent INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS gmail_messages (
                    message_id TEXT PRIMARY KEY,
                    subject TEXT,
                    sender TEXT,
                    snippet TEXT,
                    received_at TEXT,
                    alerted_at TEXT NOT NULL
                )
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sync_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT,
                    timestamp TEXT NOT NULL
                )
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schedule_reminders (
                    id TEXT PRIMARY KEY,
                    reminder_type TEXT NOT NULL,
                    event_id TEXT,
                    event_title TEXT,
                    scheduled_for TEXT NOT NULL,
                    sent_at TEXT NOT NULL
                )
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS session_alerts (
                    platform TEXT PRIMARY KEY,
                    last_alerted_at TEXT NOT NULL
                )
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS lecture_meetings (
                    id TEXT PRIMARY KEY,
                    meeting_date TEXT NOT NULL,
                    course_code TEXT NOT NULL,
                    course_name TEXT,
                    start_time TEXT NOT NULL,
                    end_time TEXT NOT NULL,
                    activity_type TEXT,
                    room TEXT,
                    lecturer TEXT,
                    topic TEXT,
                    notes TEXT,
                    edunex_url TEXT,
                    teams_url TEXT,
                    attendance_window TEXT,
                    detail_url TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

            # Performance Indexes
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_due_completed ON tasks (due_date, is_completed);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_platform ON tasks (platform);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_schedule_reminders_date ON schedule_reminders (scheduled_for);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_lecture_meetings_date ON lecture_meetings (meeting_date);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_lecture_meetings_course ON lecture_meetings (course_code);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ai_user_time ON ai_conversations (user_id, created_at);")

    # ----------------- TASK REPOSITORY DELEGATES -----------------

    def upsert_task(self, task: dict[str, Any] | Any) -> Tuple[dict[str, Any], bool]:
        return self.tasks.upsert_task(task)

    def get_task(self, task_id: str) -> Optional[dict[str, Any]]:
        return self.tasks.get_task(task_id)

    def list_tasks(
        self,
        include_completed: bool = False,
        platform: Optional[str] = None,
        limit: int = 100,
    ) -> List[dict[str, Any]]:
        return self.tasks.list_tasks(include_completed=include_completed, platform=platform, limit=limit)

    def mark_task_completed(self, task_id: str) -> bool:
        return self.tasks.mark_task_completed(task_id)

    def delete_task(self, task_id: str) -> bool:
        return self.tasks.delete_task(task_id)

    def update_google_ids(
        self,
        task_id: str,
        calendar_id: Optional[str] = None,
        tasks_id: Optional[str] = None,
    ) -> None:
        self.tasks.update_google_ids(task_id, calendar_id=calendar_id, tasks_id=tasks_id)

    def mark_reminder_sent(self, task_id: str, milestone: str) -> None:
        self.tasks.mark_reminder_sent(task_id, milestone)

    def get_tasks_needing_reminders(
        self, now_dt: datetime, milestones: Optional[List[Any]] = None
    ) -> List[Tuple[dict[str, Any], str]]:
        return self.tasks.get_tasks_needing_reminders(now_dt, milestones=milestones)

    def get_tasks_due_soon(self, hours: float = 36.0) -> List[dict[str, Any]]:
        return self.tasks.get_tasks_due_soon(hours)

    # ----------------- MEETING REPOSITORY DELEGATES -----------------

    def upsert_lecture_meeting(self, meeting: dict[str, Any]) -> tuple[dict[str, Any], bool, bool]:
        return self.meetings.upsert_lecture_meeting(meeting)

    def get_lecture_meeting(
        self,
        meeting_date: str,
        course_code: str = "",
        start_time: str = "",
    ) -> Optional[dict[str, Any]]:
        return self.meetings.get_lecture_meeting(meeting_date, course_code, start_time)

    def get_lecture_meetings_for_date(self, meeting_date: str) -> List[dict[str, Any]]:
        return self.meetings.get_lecture_meetings_for_date(meeting_date)

    def get_lecture_meetings_for_range(self, start_date: str, end_date: str) -> List[dict[str, Any]]:
        return self.meetings.get_lecture_meetings_for_range(start_date, end_date)

    # ----------------- ALERT REPOSITORY DELEGATES -----------------

    def is_gmail_processed(self, message_id: str) -> bool:
        return self.alerts.is_gmail_processed(message_id)

    def record_gmail_message(
        self,
        message_id: str,
        subject: str,
        sender: str,
        snippet: str,
        received_at: str,
    ) -> None:
        self.alerts.record_gmail_message(message_id, subject, sender, snippet, received_at)

    def log_sync(self, platform: str, status: str, message: str) -> None:
        self.alerts.log_sync(platform, status, message)

    def get_last_sync_status(self) -> dict[str, dict[str, Any]]:
        return self.alerts.get_last_sync_status()

    def is_schedule_reminder_sent(self, reminder_id: str) -> bool:
        return self.alerts.is_schedule_reminder_sent(reminder_id)

    def record_schedule_reminder(
        self,
        reminder_id: str,
        reminder_type: str,
        event_id: Optional[str] = None,
        event_title: Optional[str] = None,
        scheduled_for: str = "",
    ) -> None:
        self.alerts.record_schedule_reminder(reminder_id, reminder_type, event_id, event_title, scheduled_for)

    def should_alert_session_expired(self, platform: str, cooldown_hours: float = 12.0) -> bool:
        return self.alerts.should_alert_session_expired(platform, cooldown_hours)

    def record_session_alert(self, platform: str) -> None:
        self.alerts.record_session_alert(platform)

    def clear_session_alert(self, platform: str) -> None:
        self.alerts.clear_session_alert(platform)

    # ----------------- AI CONVERSATIONS DELEGATES -----------------

    def save_ai_message(self, user_id: str, role: str, content: str) -> None:
        self.ai_conversations.save_message(user_id, role, content)

    def get_ai_history(self, user_id: str, limit: int = 12) -> List[dict[str, str]]:
        return self.ai_conversations.get_history(user_id, limit)

    def clear_ai_history(self, user_id: str) -> None:
        self.ai_conversations.clear_history(user_id)

    def prune_ai_history(self, max_age_hours: int = 48) -> int:
        return self.ai_conversations.prune_expired(max_age_hours)
