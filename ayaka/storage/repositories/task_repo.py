"""Task Repository for Ayaka SQLite storage.

Handles CRUD operations, change tracking, Google ID associations,
and deadline reminder milestone evaluations for academic tasks.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Optional, Tuple

from ayaka.storage.repositories.base import BaseRepository


class TaskRepository(BaseRepository):
    """Repository handling all academic task queries and persistence."""

    def upsert_task(self, task: dict[str, Any] | Any) -> Tuple[dict[str, Any], bool]:
        """Insert a new task or update existing one if due_date/title changed.

        Returns (updated_or_existing_task, is_new).
        """
        if hasattr(task, "to_dict"):
            task = task.to_dict()

        now_iso = datetime.now(timezone.utc).isoformat()
        task_id = str(task["id"])

        with self.conn_mgr.transaction() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            is_newly_completed = False
            due_date_changed = False
            title_changed = False

            if row is None:
                new_completed = int(task.get("is_completed", 0))
                conn.execute(
                    """
                    INSERT INTO tasks (
                        id, platform, course_id, course_name, title, description,
                        due_date, url, is_completed, google_calendar_event_id,
                        google_tasks_task_id, reminder_h3_sent, reminder_h1_sent,
                        reminder_j6_sent, reminder_j1_sent, reminder_due_sent,
                        created_at, updated_at
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0, 0, ?, ?
                    )
                    """,
                    (
                        task_id,
                        task.get("platform", "manual"),
                        task.get("course_id", ""),
                        task.get("course_name", ""),
                        task.get("title", ""),
                        task.get("description", ""),
                        str(task.get("due_date", "")),
                        task.get("url", ""),
                        new_completed,
                        task.get("google_calendar_event_id"),
                        task.get("google_tasks_task_id"),
                        now_iso,
                        now_iso,
                    ),
                )
                is_new = True
                if new_completed == 1:
                    is_newly_completed = True
            else:
                old_due = row["due_date"]
                new_due = str(task.get("due_date", old_due))
                reset_flags = bool(new_due and old_due and new_due != old_due)
                due_date_changed = reset_flags

                old_title = row["title"]
                new_title = task.get("title") or old_title
                if new_title != old_title:
                    title_changed = True

                old_completed = int(row["is_completed"])
                platform_completed = int(task.get("is_completed", 0)) if "is_completed" in task else old_completed
                new_completed = 1 if (old_completed == 1 or platform_completed == 1) else 0

                if old_completed == 0 and new_completed == 1:
                    is_newly_completed = True

                update_sql = """
                    UPDATE tasks SET
                        course_id = coalesce(?, course_id),
                        course_name = coalesce(?, course_name),
                        title = coalesce(?, title),
                        description = coalesce(?, description),
                        due_date = ?,
                        url = coalesce(?, url),
                        is_completed = ?,
                        updated_at = ?
                """
                params = [
                    task.get("course_id"),
                    task.get("course_name"),
                    task.get("title"),
                    task.get("description"),
                    new_due,
                    task.get("url"),
                    new_completed,
                    now_iso,
                ]

                if reset_flags:
                    update_sql += """,
                        reminder_h3_sent = 0,
                        reminder_h1_sent = 0,
                        reminder_j6_sent = 0,
                        reminder_j1_sent = 0,
                        reminder_due_sent = 0
                    """

                update_sql += " WHERE id = ?"
                params.append(task_id)
                conn.execute(update_sql, params)
                is_new = False

            updated_row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            res = dict(updated_row)
            res["_is_newly_completed"] = is_newly_completed
            res["_due_date_changed"] = due_date_changed
            res["_title_changed"] = title_changed
            return res, is_new

    def get_task(self, task_id: str) -> Optional[dict[str, Any]]:
        """Retrieve task by its unique ID."""
        with self.conn_mgr.transaction() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row:
                return dict(row)
            return None

    def list_tasks(
        self,
        include_completed: bool = False,
        platform: Optional[str] = None,
        limit: int = 100,
    ) -> List[dict[str, Any]]:
        """List tasks ordered by due_date ascending."""
        with self.conn_mgr.transaction() as conn:
            query = "SELECT * FROM tasks WHERE 1=1"
            params: list[Any] = []

            if not include_completed:
                query += " AND is_completed = 0"

            if platform:
                query += " AND platform = ?"
                params.append(platform)

            query += " ORDER BY due_date ASC LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def mark_task_completed(self, task_id: str) -> bool:
        """Mark task as completed and update timestamp."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.conn_mgr.transaction() as conn:
            cur = conn.execute(
                "UPDATE tasks SET is_completed = 1, updated_at = ? WHERE id = ?",
                (now_iso, task_id),
            )
            return cur.rowcount > 0

    def delete_task(self, task_id: str) -> bool:
        """Permanently delete a task from the database."""
        with self.conn_mgr.transaction() as conn:
            cur = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            return cur.rowcount > 0

    def update_google_ids(
        self,
        task_id: str,
        calendar_id: Optional[str] = None,
        tasks_id: Optional[str] = None,
    ) -> None:
        """Associate external Google Calendar event ID and Google Tasks ID."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.conn_mgr.transaction() as conn:
            conn.execute(
                """
                UPDATE tasks SET
                    google_calendar_event_id = coalesce(?, google_calendar_event_id),
                    google_tasks_task_id = coalesce(?, google_tasks_task_id),
                    updated_at = ?
                WHERE id = ?
                """,
                (calendar_id, tasks_id, now_iso, task_id),
            )

    def mark_reminder_sent(self, task_id: str, milestone: str) -> None:
        """Mark specific reminder flag (h3, h1, j6, j1, due)."""
        valid_milestones = {
            "h3": "reminder_h3_sent",
            "h1": "reminder_h1_sent",
            "j6": "reminder_j6_sent",
            "j1": "reminder_j1_sent",
            "due": "reminder_due_sent",
        }
        col = valid_milestones.get(milestone.lower())
        if not col:
            raise ValueError(f"Unknown milestone: {milestone}")

        with self.conn_mgr.transaction() as conn:
            conn.execute(f"UPDATE tasks SET {col} = 1 WHERE id = ?", (task_id,))

    def get_tasks_needing_reminders(
        self, now_dt: datetime
    ) -> List[Tuple[dict[str, Any], str]]:
        """Evaluate all active tasks against milestone thresholds.

        Milestones:
        - H-3: Remaining <= 72h and > 24h
        - H-1: Remaining <= 24h and > 6h
        - J-6: Remaining <= 6h and > 1h
        - J-1: Remaining <= 1h and > 0h
        - Due: Remaining <= 0h and >= -2h (at deadline / start)

        Returns list of tuples: (task_dict, milestone_key).
        """
        pending = self.list_tasks(include_completed=False)
        due_alerts: list[Tuple[dict[str, Any], str]] = []

        for task in pending:
            try:
                due_str = task["due_date"]
                due_dt = datetime.fromisoformat(due_str)
                if due_dt.tzinfo is None:
                    due_dt = due_dt.replace(tzinfo=timezone.utc)
            except Exception:
                continue

            hours_remaining = (due_dt - now_dt).total_seconds() / 3600.0

            if hours_remaining <= 0 and hours_remaining >= -2.0 and not task["reminder_due_sent"]:
                due_alerts.append((task, "due"))
            elif 0 < hours_remaining <= 1.0 and not task["reminder_j1_sent"]:
                due_alerts.append((task, "j1"))
            elif 1.0 < hours_remaining <= 6.0 and not task["reminder_j6_sent"]:
                due_alerts.append((task, "j6"))
            elif 6.0 < hours_remaining <= 24.0 and not task["reminder_h1_sent"]:
                due_alerts.append((task, "h1"))
            elif 24.0 < hours_remaining <= 72.0 and not task["reminder_h3_sent"]:
                due_alerts.append((task, "h3"))

        return due_alerts

    def get_tasks_due_soon(self, hours: float = 36.0) -> List[dict[str, Any]]:
        """Retrieve pending tasks due within the given number of hours."""
        now = datetime.now(timezone.utc)
        tasks = self.list_tasks(include_completed=False)
        due_soon: list[dict[str, Any]] = []
        for t in tasks:
            try:
                due_dt = datetime.fromisoformat(t["due_date"])
                if due_dt.tzinfo is None:
                    due_dt = due_dt.replace(tzinfo=timezone.utc)
                diff_hours = (due_dt - now).total_seconds() / 3600.0
                if 0 <= diff_hours <= hours:
                    due_soon.append(t)
            except Exception:
                continue
        return due_soon
