"""Google Workspace Synchronization Service.

Synchronizes academic deadlines and activities to:
1. Google Calendar (as scheduled deadline events)
2. Google Tasks (as actionable checklist items)
Also handles marking items as completed in Google Tasks when marked done in Ayaka.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from ayaka.config import Config
from ayaka.storage.db import Database

logger = logging.getLogger("ayaka.services.google")

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/tasks",
    "https://www.googleapis.com/auth/gmail.readonly",
]


class GoogleSyncService:
    def __init__(self, config: Config, db: Database):
        self.config = config
        self.db = db
        self.creds = None
        self._calendar_service = None
        self._tasks_service = None

    def authenticate(self) -> bool:
        """Authenticate with Google OAuth using token.json or credentials.json."""
        token_path = Path(self.config.google.token_file)
        cred_path = Path(self.config.google.credentials_file)

        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build

            if token_path.is_file():
                self.creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

            if not self.creds or not self.creds.valid:
                if self.creds and self.creds.expired and self.creds.refresh_token:
                    self.creds.refresh(Request())
                    with open(token_path, "w", encoding="utf-8") as token_file:
                        token_file.write(self.creds.to_json())
                elif cred_path.is_file():
                    from google_auth_oauthlib.flow import InstalledAppFlow
                    flow = InstalledAppFlow.from_client_secrets_file(str(cred_path), SCOPES)
                    self.creds = flow.run_local_server(port=0)
                    with open(token_path, "w", encoding="utf-8") as token_file:
                        token_file.write(self.creds.to_json())
                else:
                    logger.warning("No Google credentials.json or token.json found.")
                    return False

            self._calendar_service = build("calendar", "v3", credentials=self.creds, cache_discovery=False)
            self._tasks_service = build("tasks", "v1", credentials=self.creds, cache_discovery=False)
            return True
        except Exception as e:
            logger.error(f"Google authentication error: {e}")
            return False

    def sync_task(self, task: dict[str, Any]) -> None:
        """Sync a single task to Google Calendar and/or Google Tasks based on config."""
        if not self._calendar_service or not self._tasks_service:
            if not self.authenticate():
                return

        calendar_id = None
        if getattr(self.config.google, "sync_calendar", False):
            calendar_id = self.sync_to_calendar(task)

        tasks_id = None
        if getattr(self.config.google, "sync_tasks", True):
            tasks_id = self.sync_to_tasks(task)

        if calendar_id or tasks_id:
            self.db.update_google_ids(task["id"], calendar_id=calendar_id, tasks_id=tasks_id)

    def sync_to_calendar(self, task: dict[str, Any]) -> Optional[str]:
        """Create or update deadline event in Google Calendar."""
        if not self._calendar_service:
            return None

        cal_id = self.config.google.calendar_id
        event_id = task.get("google_calendar_event_id")

        import zoneinfo

        try:
            tz = zoneinfo.ZoneInfo(self.config.timezone)
        except Exception:
            tz = timezone.utc

        try:
            due_dt = datetime.fromisoformat(task["due_date"])
            if due_dt.tzinfo is None:
                due_dt = due_dt.replace(tzinfo=tz)
        except Exception:
            return None

        # Create a 30-minute block ending at deadline
        end_time = due_dt.isoformat()
        start_time = (due_dt - timedelta(minutes=30)).isoformat()

        body = {
            "summary": f"[Ayaka] {task['title']}",
            "description": (
                f"Course: {task.get('course_name') or task.get('course_id')}\n"
                f"Platform: {task.get('platform')}\n"
                f"Link: {task.get('url')}\n\n"
                f"{task.get('description', '')}"
            ),
            "start": {"dateTime": start_time, "timeZone": self.config.timezone},
            "end": {"dateTime": end_time, "timeZone": self.config.timezone},
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "popup", "minutes": 60},
                    {"method": "popup", "minutes": 1440},  # 24h
                ],
            },
        }

        try:
            if event_id:
                ev = self._calendar_service.events().patch(calendarId=cal_id, eventId=event_id, body=body).execute()
                return ev.get("id")
            else:
                ev = self._calendar_service.events().insert(calendarId=cal_id, body=body).execute()
                return ev.get("id")
        except Exception as e:
            logger.error(f"Error syncing to Google Calendar: {e}")
            return None

    def sync_to_tasks(self, task: dict[str, Any]) -> Optional[str]:
        """Create or update to-do task in Google Tasks."""
        if not self._tasks_service:
            return None

        list_id = self.config.google.tasks_list_id
        task_id = task.get("google_tasks_task_id")

        import zoneinfo

        try:
            tz = zoneinfo.ZoneInfo(self.config.timezone)
        except Exception:
            tz = timezone.utc

        try:
            due_dt = datetime.fromisoformat(task["due_date"])
            if due_dt.tzinfo is None:
                due_dt = due_dt.replace(tzinfo=tz)
            # Google Tasks expects RFC 3339 formatted with Z in UTC
            due_utc = due_dt.astimezone(timezone.utc)
            due_rfc = due_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        except Exception:
            due_rfc = None

        body = {
            "title": f"[{task.get('course_id') or task.get('platform')}] {task['title']}",
            "notes": f"Platform: {task.get('platform')}\nLink: {task.get('url')}\n{task.get('description', '')}",
            "status": "completed" if task.get("is_completed") else "needsAction",
        }
        if due_rfc:
            body["due"] = due_rfc

        try:
            if task_id:
                t = self._tasks_service.tasks().patch(tasklist=list_id, task=task_id, body=body).execute()
                return t.get("id")
            else:
                t = self._tasks_service.tasks().insert(tasklist=list_id, body=body).execute()
                return t.get("id")
        except Exception as e:
            logger.error(f"Error syncing to Google Tasks: {e}")
            return None

    def mark_completed_in_google(self, task_id: str) -> None:
        """Mark task as completed in Google Tasks."""
        if not self._tasks_service:
            if not self.authenticate():
                return

        task = self.db.get_task(task_id)
        if not task or not task.get("google_tasks_task_id"):
            return

        try:
            self._tasks_service.tasks().patch(
                tasklist=self.config.google.tasks_list_id,
                task=task["google_tasks_task_id"],
                body={"status": "completed"},
            ).execute()
        except Exception as e:
            logger.error(f"Error updating task status in Google Tasks: {e}")

    def delete_from_google(self, task_id: str) -> None:
        """Delete task from Google Tasks and Google Calendar if present."""
        if not self._tasks_service or not self._calendar_service:
            if not self.authenticate():
                return

        task = self.db.get_task(task_id)
        if not task:
            return

        # 1. Delete from Google Tasks
        if task.get("google_tasks_task_id"):
            try:
                self._tasks_service.tasks().delete(
                    tasklist=self.config.google.tasks_list_id,
                    task=task["google_tasks_task_id"],
                ).execute()
                logger.info(f"Deleted task {task['google_tasks_task_id']} from Google Tasks.")
            except Exception as e:
                logger.error(f"Error deleting task from Google Tasks: {e}")

        # 2. Delete from Google Calendar
        if task.get("google_calendar_event_id"):
            try:
                self._calendar_service.events().delete(
                    calendarId=self.config.google.calendar_id,
                    eventId=task["google_calendar_event_id"],
                ).execute()
                logger.info(f"Deleted event {task['google_calendar_event_id']} from Google Calendar.")
            except Exception as e:
                logger.error(f"Error deleting event from Google Calendar: {e}")

