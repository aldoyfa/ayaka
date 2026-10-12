"""Ayaka Time & Date Utilities.

Provides unified timezone-aware date parsing, natural language deadline resolution,
and duration formatting across Discord bot commands, AI agents, and scheduler loops.
"""

from __future__ import annotations

import re
import zoneinfo
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional


def get_timezone(tz_name: str = "Asia/Jakarta") -> zoneinfo.ZoneInfo | timezone:
    """Retrieve ZoneInfo for the given timezone name with safe UTC+7 fallback."""
    try:
        return zoneinfo.ZoneInfo(tz_name)
    except Exception:
        return timezone(timedelta(hours=7))


MONTH_MAP = {
    "januari": 1, "jan": 1, "january": 1,
    "februari": 2, "feb": 2, "february": 2,
    "maret": 3, "mar": 3, "march": 3,
    "april": 4, "apr": 4,
    "mei": 5, "may": 5,
    "juni": 6, "jun": 6, "june": 6,
    "juli": 7, "jul": 7, "july": 7,
    "agustus": 8, "agt": 8, "agu": 8, "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "oktober": 10, "okt": 10, "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "desember": 12, "des": 12, "december": 12, "dec": 12,
}


def parse_user_due_date(due_str: Optional[str], tz_name: str = "Asia/Jakarta") -> Optional[datetime]:
    """Parse user-provided deadline into a timezone-aware datetime.

    Supports:
    - ISO 8601 strings (e.g. 2026-10-15T23:59:00+07:00, 2026-10-15T23:59:00)
    - Dot and colon time formats (e.g. '2026-10-15 21.00', '2026-10-15 21:00', '21.00', 'jam 21.00')
    - Formatted date strings: YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY
    - Textual Indonesian month names: '15 Oktober 2026 21.00'
    - Date-only strings defaulting time to 23:59:00
    - Natural language relative dates (e.g., 'besok malam', 'lusa jam 14:00', 'hari ini 17:00')
    - Time-only strings (e.g. '21.00', '21:00', 'jam 21'), targeting today if future, else tomorrow.

    Returns None if the string cannot be parsed.
    """
    if not due_str or not due_str.strip():
        return None

    tz = get_timezone(tz_name)
    raw = due_str.strip()
    s_lower = raw.lower()
    now = datetime.now(tz)

    # 1. Full ISO 8601 with explicit "T" or timezone offset (e.g., 2026-10-15T23:59:00+07:00)
    if "t" in s_lower or "+" in raw or (raw.count(":") >= 2 and re.match(r"^\d{4}-\d{2}-\d{2}", raw)):
        try:
            iso_dt = datetime.fromisoformat(raw)
            if iso_dt.tzinfo is None:
                iso_dt = iso_dt.replace(tzinfo=tz)
            return iso_dt
        except Exception:
            pass

    # 2. Extract Date first to isolate it from time
    target_date = None
    date_matched_span = None

    # A. Relative day markers
    if "lusa" in s_lower:
        target_date = now.date() + timedelta(days=2)
    elif "besok" in s_lower or "tomorrow" in s_lower:
        target_date = now.date() + timedelta(days=1)
    elif "hari ini" in s_lower or "today" in s_lower:
        target_date = now.date()
    elif "minggu depan" in s_lower or "next week" in s_lower:
        target_date = now.date() + timedelta(days=7)
    else:
        # B. Textual month pattern: "15 Oktober 2026", "15 Okt 2026"
        month_match = re.search(r"\b(\d{1,2})\s+([a-zA-Z]+)\s+(\d{4})\b", s_lower)
        if month_match and month_match.group(2) in MONTH_MAP:
            d = int(month_match.group(1))
            m = MONTH_MAP[month_match.group(2)]
            y = int(month_match.group(3))
            try:
                target_date = date(y, m, d)
                date_matched_span = month_match.span()
            except ValueError:
                pass

        if target_date is None:
            # C. YYYY-MM-DD or YYYY/MM/DD or YYYY.MM.DD
            ymd = re.search(r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b", raw)
            if ymd:
                try:
                    target_date = date(int(ymd.group(1)), int(ymd.group(2)), int(ymd.group(3)))
                    date_matched_span = ymd.span()
                except ValueError:
                    pass

        if target_date is None:
            # D. DD-MM-YYYY or DD/MM/YYYY or DD.MM.YYYY
            dmy = re.search(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b", raw)
            if dmy:
                try:
                    target_date = date(int(dmy.group(3)), int(dmy.group(2)), int(dmy.group(1)))
                    date_matched_span = dmy.span()
                except ValueError:
                    pass

    # Exclude matched date span when searching for time (prevents DD.MM from being mistaken for HH.MM)
    time_search_str = s_lower
    if date_matched_span:
        start_idx, end_idx = date_matched_span
        time_search_str = s_lower[:start_idx] + " " + s_lower[end_idx:]

    # 3. Extract Time
    hour = None
    minute = None
    second = 0
    time_specified = False

    time_match = re.search(r"(?:(?:jam|pukul)\s*)?(\b\d{1,2})[.:](\d{2})(?:[.:](\d{2}))?\s*(am|pm)?\b", time_search_str)
    if time_match:
        h = int(time_match.group(1))
        m = int(time_match.group(2))
        sec = int(time_match.group(3)) if time_match.group(3) else 0
        ampm = time_match.group(4)
        if 0 <= h <= 24 and 0 <= m < 60 and 0 <= sec < 60:
            if ampm == "pm" and h < 12:
                h += 12
            elif ampm == "am" and h == 12:
                h = 0
            elif "malam" in time_search_str and h < 12:
                h += 12
            elif "sore" in time_search_str and h <= 6:
                h += 12
            elif "siang" in time_search_str and 1 <= h <= 3:
                h += 12
            hour, minute, second = h % 24, m, sec
            time_specified = True
    elif re.search(r"(?:jam|pukul)\s*(\d{1,2})\s*(am|pm)?\b", time_search_str):
        h_m = re.search(r"(?:jam|pukul)\s*(\d{1,2})\s*(am|pm)?\b", time_search_str)
        h = int(h_m.group(1))
        ampm = h_m.group(2)
        if 0 <= h <= 24:
            if ampm == "pm" and h < 12:
                h += 12
            elif ampm == "am" and h == 12:
                h = 0
            elif "malam" in time_search_str and h < 12:
                h += 12
            elif "sore" in time_search_str and h <= 6:
                h += 12
            elif "siang" in time_search_str and 1 <= h <= 3:
                h += 12
            hour, minute, second = h % 24, 0, 0
            time_specified = True
    elif re.search(r"\b(\d{1,2})\s*(am|pm)\b", time_search_str):
        h_m = re.search(r"\b(\d{1,2})\s*(am|pm)\b", time_search_str)
        h = int(h_m.group(1))
        ampm = h_m.group(2)
        if 0 <= h <= 12:
            if ampm == "pm" and h < 12:
                h += 12
            elif ampm == "am" and h == 12:
                h = 0
            hour, minute, second = h, 0, 0
            time_specified = True
    elif "pagi" in time_search_str:
        hour, minute, second = 8, 0, 0
        time_specified = True
    elif "siang" in time_search_str:
        hour, minute, second = 13, 0, 0
        time_specified = True
    elif "sore" in time_search_str:
        hour, minute, second = 16, 0, 0
        time_specified = True
    elif "malam" in time_search_str:
        hour, minute, second = 23, 59, 0
        time_specified = True

    # If neither date nor time found
    if target_date is None and not time_specified:
        return None

    # Time specified but date not specified (e.g. "21.00", "jam 21.00", "21:00")
    if target_date is None:
        target_time = (hour, minute, second)
        now_time = (now.hour, now.minute, now.second)
        if target_time > now_time:
            target_date = now.date()
        else:
            target_date = now.date() + timedelta(days=1)

    # Date specified but time not specified -> default to 23:59:00
    if not time_specified:
        hour, minute, second = 23, 59, 0

    return datetime(target_date.year, target_date.month, target_date.day, hour, minute, second, tzinfo=tz)


def parse_natural_due_date(due_str: Optional[str], tz_name: str = "Asia/Jakarta") -> datetime:
    """Parse relative or formatted deadline strings into a timezone-aware datetime.

    Defaults to tomorrow at 23:59:00 if due_str is None, empty, or unparseable.
    Used primarily by the AI Agent and casual natural language workflows.
    """
    tz = get_timezone(tz_name)
    now = datetime.now(tz)
    default_dt = (now + timedelta(days=1)).replace(hour=23, minute=59, second=0, microsecond=0)

    if not due_str or not due_str.strip():
        return default_dt

    parsed = parse_user_due_date(due_str, tz_name=tz_name)
    return parsed if parsed is not None else default_dt


def format_uptime(delta: timedelta) -> str:
    """Format timedelta uptime into a clean human-readable string (e.g. '2d 5h 30m')."""
    total_seconds = int(delta.total_seconds())
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)

    parts: list[str] = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")

    return " ".join(parts) if parts else "less than a minute"
