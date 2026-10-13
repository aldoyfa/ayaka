"""Lecture Meeting Repository for Ayaka SQLite storage.

Handles persistence, modal enrichment, topic change tracking,
and schedule lookup queries for lecture meetings.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Optional

from ayaka.storage.repositories.base import BaseRepository


class MeetingRepository(BaseRepository):
    """Repository handling all lecture meeting queries and modal data."""

    def upsert_lecture_meeting(self, meeting: dict[str, Any]) -> tuple[dict[str, Any], bool, bool]:
        """Insert or replace lecture meeting modal details.

        Returns: (meeting, is_new, was_updated)
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        mid = str(meeting["id"])
        with self.conn_mgr.transaction() as conn:
            existing = conn.execute("SELECT * FROM lecture_meetings WHERE id = ?", (mid,)).fetchone()
            is_new = existing is None
            was_updated = False

            # Keep previously known details when this scrape came back without them
            # (modal fetch timeout, partial page): INSERT OR REPLACE would otherwise blank them.
            if existing:
                for field in ("activity_type", "room", "lecturer", "topic", "notes",
                              "edunex_url", "teams_url", "attendance_window"):
                    if not meeting.get(field) and existing[field]:
                        meeting[field] = existing[field]
                        if field in ("topic", "room", "notes"):
                            meeting[f"_kept_{field}"] = True

            new_topic = meeting.get("topic", "")
            new_room = meeting.get("room", "")
            new_notes = meeting.get("notes", "")

            if existing:
                old_topic = existing["topic"] or ""
                old_room = existing["room"] or ""
                old_notes = existing["notes"] or ""
                if (new_topic and new_topic != old_topic) or (new_room and new_room != old_room) or (new_notes and new_notes != old_notes):
                    was_updated = True
                    meeting["_topic_changed"] = (new_topic != old_topic)
                    meeting["_old_topic"] = old_topic
                    meeting["_room_changed"] = (new_room != old_room)

            raw_durl = meeting.get("detail_url", "")
            if raw_durl:
                raw_durl = raw_durl.split("?returnTo=")[0]
                if raw_durl.startswith("/"):
                    raw_durl = f"https://six.itb.ac.id{raw_durl}"

            conn.execute(
                """
                INSERT OR REPLACE INTO lecture_meetings (
                    id, meeting_date, course_code, course_name, start_time, end_time,
                    activity_type, room, lecturer, topic, notes,
                    edunex_url, teams_url, attendance_window, detail_url, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mid,
                    meeting.get("meeting_date", ""),
                    meeting.get("course_code", "").upper(),
                    meeting.get("course_name", ""),
                    meeting.get("start_time", ""),
                    meeting.get("end_time", ""),
                    meeting.get("activity_type", ""),
                    meeting.get("room", ""),
                    meeting.get("lecturer", ""),
                    new_topic,
                    new_notes,
                    meeting.get("edunex_url", ""),
                    meeting.get("teams_url", ""),
                    meeting.get("attendance_window", ""),
                    raw_durl,
                    now_iso,
                ),
            )
            meeting["detail_url"] = raw_durl
            return meeting, is_new, was_updated

    def get_lecture_meeting(
        self,
        meeting_date: str,
        course_code: str = "",
        start_time: str = "",
    ) -> Optional[dict[str, Any]]:
        """Find a specific meeting detail by date, course code, and/or start time."""
        clean_code = course_code.strip().upper()
        with self.conn_mgr.transaction() as conn:
            query = "SELECT * FROM lecture_meetings WHERE meeting_date = ?"
            params: list[Any] = [meeting_date]
            if clean_code:
                query += " AND course_code = ?"
                params.append(clean_code)
            if start_time:
                query += " AND start_time LIKE ?"
                params.append(f"{start_time[:5]}%")
            row = conn.execute(query, tuple(params)).fetchone()
            if row:
                return dict(row)

            # Fallback: if course_code provided without time match, return first matching for that date
            if clean_code:
                fallback_row = conn.execute(
                    "SELECT * FROM lecture_meetings WHERE meeting_date = ? AND course_code = ?",
                    (meeting_date, clean_code),
                ).fetchone()
                if fallback_row:
                    return dict(fallback_row)

        return None

    def get_lecture_meetings_for_date(self, meeting_date: str) -> List[dict[str, Any]]:
        """Fetch all lecture meetings on a given date sorted by start time."""
        with self.conn_mgr.transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM lecture_meetings WHERE meeting_date = ? ORDER BY start_time ASC",
                (meeting_date,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_lecture_meetings_for_range(self, start_date: str, end_date: str) -> List[dict[str, Any]]:
        """Fetch all lecture meetings in date range sorted by date and start time."""
        with self.conn_mgr.transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM lecture_meetings WHERE meeting_date >= ? AND meeting_date <= ? ORDER BY meeting_date ASC, start_time ASC",
                (start_date, end_date),
            ).fetchall()
            return [dict(r) for r in rows]
