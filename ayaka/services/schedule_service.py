"""Academic Lecture Schedule Service.

Interacts with Google Calendar to fetch lecture schedules and coordinate:
1. Daily morning briefing at 05:00 WIB
2. Class start proactive reminder
3. Attendance (presensi) proactive reminder 10 minutes before class ends
"""

from __future__ import annotations

import logging
import zoneinfo
from datetime import date, datetime, timedelta, timezone
from typing import Any, List, Optional

from ayaka.config import Config
from ayaka.services.google_sync import GoogleSyncService
from ayaka.storage.db import Database

logger = logging.getLogger("ayaka.services.schedule")


class ScheduleService:
    def __init__(self, config: Config, db: Database, google_sync: GoogleSyncService):
        self.config = config
        self.db = db
        self.google_sync = google_sync

    @property
    def timezone_obj(self):
        try:
            return zoneinfo.ZoneInfo(self.config.timezone)
        except Exception:
            return timezone.utc

    def get_calendar_id(self) -> str:
        """Get the configured schedule calendar ID, or attempt discovery."""
        return getattr(self.config.google, "schedule_calendar_id", "") or "primary"

    def get_events_for_date(self, target_date: date) -> List[dict[str, Any]]:
        """Fetch all calendar events scheduled on a specific date (in local timezone)."""
        if not self.google_sync._calendar_service:
            if not self.google_sync.authenticate():
                return []

        tz = self.timezone_obj
        cal_id = self.get_calendar_id()

        day_start_local = datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0, tzinfo=tz)
        day_end_local = datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59, tzinfo=tz)

        t_min = day_start_local.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        t_max = day_end_local.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

        try:
            with self.google_sync.lock:
                res = self.google_sync._calendar_service.events().list(
                    calendarId=cal_id,
                    timeMin=t_min,
                    timeMax=t_max,
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=50,
                ).execute()

            items = res.get("items", [])
            parsed_events: list[dict[str, Any]] = []

            for ev in items:
                if ev.get("status") == "cancelled":
                    continue

                start_raw = ev.get("start", {})
                end_raw = ev.get("end", {})
                start_str = start_raw.get("dateTime") or start_raw.get("date")
                end_str = end_raw.get("dateTime") or end_raw.get("date")

                if not start_str or not end_str:
                    continue

                try:
                    start_dt = datetime.fromisoformat(start_str)
                    if start_dt.tzinfo is None:
                        start_dt = start_dt.replace(tzinfo=tz)
                    else:
                        start_dt = start_dt.astimezone(tz)
                except Exception:
                    continue

                try:
                    end_dt = datetime.fromisoformat(end_str)
                    if end_dt.tzinfo is None:
                        end_dt = end_dt.replace(tzinfo=tz)
                    else:
                        end_dt = end_dt.astimezone(tz)
                except Exception:
                    continue

                parsed_event = {
                    "id": ev.get("id"),
                    "summary": ev.get("summary", "Perkuliahan"),
                    "location": ev.get("location", ""),
                    "description": ev.get("description", ""),
                    "start_dt": start_dt,
                    "end_dt": end_dt,
                    "html_link": ev.get("htmlLink", ""),
                }
                self._enrich_event(parsed_event)
                parsed_events.append(parsed_event)

            parsed_events.sort(key=lambda x: x["start_dt"])
            return parsed_events

        except Exception as e:
            logger.error(f"Error fetching calendar events for {target_date}: {e}")
            return []

    def _enrich_event(self, ev: dict[str, Any]) -> None:
        """Enrich a calendar event with detailed meeting modal data from SIX."""
        try:
            import re
            start_dt = ev.get("start_dt")
            if not start_dt:
                return

            date_str = start_dt.strftime("%Y-%m-%d")
            st_str = start_dt.strftime("%H:%M")
            summary = ev.get("summary", "")

            code_match = re.search(r"\b([A-Z]{2}[0-9]{4})\b", summary)
            code = code_match.group(1).upper() if code_match else ""

            detail = self.db.get_lecture_meeting(date_str, course_code=code, start_time=st_str)
            if not detail and getattr(self.config.academic, "has_six", False):
                try:
                    from ayaka.fetchers.six import SixFetcher
                    fetcher = SixFetcher(self.config)
                    fresh_meetings = fetcher.fetch_lecture_meetings(fetch_modals=True, future_only=True)
                    for m in fresh_meetings:
                        self.db.upsert_lecture_meeting(m)
                    detail = self.db.get_lecture_meeting(date_str, course_code=code, start_time=st_str)
                except Exception as fe:
                    logger.debug(f"Lazy SIX meeting sync failed: {fe}")

            if detail:
                ev["meeting_detail"] = detail
                if not ev.get("location") and detail.get("room"):
                    ev["location"] = detail["room"]
        except Exception as e:
            logger.debug(f"Error enriching calendar event: {e}")


    def get_events_for_range(self, start_date: date, end_date: date) -> List[dict[str, Any]]:
        """Fetch all calendar events within a date range."""
        if not self.google_sync._calendar_service:
            if not self.google_sync.authenticate():
                return []

        tz = self.timezone_obj
        cal_id = self.get_calendar_id()

        day_start_local = datetime(start_date.year, start_date.month, start_date.day, 0, 0, 0, tzinfo=tz)
        day_end_local = datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59, tzinfo=tz)

        t_min = day_start_local.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        t_max = day_end_local.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

        try:
            with self.google_sync.lock:
                res = self.google_sync._calendar_service.events().list(
                    calendarId=cal_id,
                    timeMin=t_min,
                    timeMax=t_max,
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=100,
                ).execute()

            items = res.get("items", [])
            parsed_events: list[dict[str, Any]] = []

            for ev in items:
                if ev.get("status") == "cancelled":
                    continue

                start_raw = ev.get("start", {})
                end_raw = ev.get("end", {})
                start_str = start_raw.get("dateTime") or start_raw.get("date")
                end_str = end_raw.get("dateTime") or end_raw.get("date")

                if not start_str or not end_str:
                    continue

                try:
                    start_dt = datetime.fromisoformat(start_str)
                    if start_dt.tzinfo is None:
                        start_dt = start_dt.replace(tzinfo=tz)
                    else:
                        start_dt = start_dt.astimezone(tz)
                except Exception:
                    continue

                try:
                    end_dt = datetime.fromisoformat(end_str)
                    if end_dt.tzinfo is None:
                        end_dt = end_dt.replace(tzinfo=tz)
                    else:
                        end_dt = end_dt.astimezone(tz)
                except Exception:
                    continue

                parsed_event = {
                    "id": ev.get("id"),
                    "summary": ev.get("summary", "Perkuliahan"),
                    "location": ev.get("location", ""),
                    "description": ev.get("description", ""),
                    "start_dt": start_dt,
                    "end_dt": end_dt,
                    "html_link": ev.get("htmlLink", ""),
                }
                self._enrich_event(parsed_event)
                parsed_events.append(parsed_event)

            parsed_events.sort(key=lambda x: x["start_dt"])
            return parsed_events
        except Exception as e:
            logger.error(f"Error fetching calendar events for range {start_date} to {end_date}: {e}")
            return []
