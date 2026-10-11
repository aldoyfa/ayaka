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


def parse_user_due_date(due_str: Optional[str], tz_name: str = "Asia/Jakarta") -> Optional[datetime]:
    """Parse user-provided deadline into a timezone-aware datetime.

    Supports:
    - ISO 8601 strings (e.g. 2026-10-15T23:59:00+07:00, 2026-10-15T23:59:00)
    - Formatted date strings: %Y-%m-%d %H:%M, %Y-%m-%d %H:%M:%S, %d/%m/%Y %H:%M
    - Date-only strings (%Y-%m-%d, %d/%m/%Y), defaulting time to 23:59:00
    - Natural language relative dates (e.g., 'besok malam', 'lusa jam 14:00', 'hari ini 17:00')

    Returns None if the string cannot be parsed.
    """
    if not due_str or not due_str.strip():
        return None

    tz = get_timezone(tz_name)
    raw = due_str.strip()

    # 1. Try ISO 8601 parsing
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
        if ":" not in raw and "t" not in raw.lower():
            dt = dt.replace(hour=23, minute=59, second=0, microsecond=0)
        return dt
    except Exception:
        pass

    # 2. Try explicit standard formats
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(raw, fmt)
            if fmt in ("%Y-%m-%d", "%d/%m/%Y") or ":" not in raw:
                dt = dt.replace(hour=23, minute=59, second=0, microsecond=0)
            return dt.replace(tzinfo=tz)
        except ValueError:
            continue

    # 3. Try natural language parsing (e.g., "besok", "lusa", "hari ini", "jam 15")
    s = raw.lower()
    now = datetime.now(tz)
    has_date_indicator = any(k in s for k in ("besok", "tomorrow", "lusa", "hari ini", "today", "minggu depan", "next week"))

    # Check for relative date markers or explicit date patterns in s
    date_match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    slash_match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)

    if not has_date_indicator and not date_match and not slash_match:
        # Not a recognizable date string
        return None

    # Time extraction: check for patterns like "23:59", "23.59", "jam 15", "10:00"
    hour = 23
    minute = 59
    time_match = re.search(r"(?:jam\s*)?(\d{1,2})[:.](\d{2})", s)
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2))
    elif re.search(r"jam\s*(\d{1,2})", s):
        h_match = re.search(r"jam\s*(\d{1,2})", s)
        hour = int(h_match.group(1)) if h_match else 23
        minute = 0
    elif "pagi" in s:
        hour, minute = 8, 0
    elif "siang" in s:
        hour, minute = 13, 0
    elif "sore" in s:
        hour, minute = 16, 0
    elif "malam" in s and not time_match:
        hour, minute = 23, 59

    # Day resolution
    target_date = now.date()
    if "lusa" in s:
        target_date = now.date() + timedelta(days=2)
    elif "besok" in s or "tomorrow" in s:
        target_date = now.date() + timedelta(days=1)
    elif "hari ini" in s or "today" in s:
        target_date = now.date()
    elif "minggu depan" in s or "next week" in s:
        target_date = now.date() + timedelta(days=7)
    elif date_match:
        target_date = date(int(date_match.group(1)), int(date_match.group(2)), int(date_match.group(3)))
    elif slash_match:
        target_date = date(int(slash_match.group(3)), int(slash_match.group(2)), int(slash_match.group(1)))

    return datetime(target_date.year, target_date.month, target_date.day, hour, minute, 0, tzinfo=tz)


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
