"""Tests for ayaka.core.time module."""

from datetime import datetime, timedelta
import zoneinfo

import pytest

from ayaka.core.time import (
    format_uptime,
    get_timezone,
    parse_natural_due_date,
    parse_user_due_date,
)


def test_get_timezone():
    tz = get_timezone("Asia/Jakarta")
    assert tz is not None
    assert "Jakarta" in str(tz)

    fallback_tz = get_timezone("Invalid/NonExistent_Zone")
    assert fallback_tz is not None


def test_parse_user_due_date_iso():
    tz = zoneinfo.ZoneInfo("Asia/Jakarta")
    dt = parse_user_due_date("2026-10-15T23:59:00+07:00")
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 10
    assert dt.day == 15
    assert dt.hour == 23
    assert dt.minute == 59


def test_parse_user_due_date_formatted():
    dt = parse_user_due_date("2026-11-01 14:30")
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 11
    assert dt.day == 1
    assert dt.hour == 14
    assert dt.minute == 30

    # Date only defaults to 23:59:00
    dt_date_only = parse_user_due_date("2026-12-31")
    assert dt_date_only is not None
    assert dt_date_only.hour == 23
    assert dt_date_only.minute == 59


def test_parse_user_due_date_natural():
    tz = zoneinfo.ZoneInfo("Asia/Jakarta")
    now = datetime.now(tz)

    # Relative day: "besok malam"
    dt = parse_user_due_date("besok malam")
    assert dt is not None
    assert dt.date() == (now + timedelta(days=1)).date()
    assert dt.hour == 23 and dt.minute == 59

    # Relative day: "lusa jam 14:00"
    dt_lusa = parse_user_due_date("lusa jam 14:00")
    assert dt_lusa is not None
    assert dt_lusa.date() == (now + timedelta(days=2)).date()
    assert dt_lusa.hour == 14 and dt_lusa.minute == 0


def test_parse_user_due_date_invalid():
    assert parse_user_due_date(None) is None
    assert parse_user_due_date("") is None
    assert parse_user_due_date("random string without date") is None


def test_parse_natural_due_date_default_fallback():
    tz = zoneinfo.ZoneInfo("Asia/Jakarta")
    now = datetime.now(tz)

    # Empty string should default to tomorrow at 23:59:00
    dt = parse_natural_due_date("")
    assert dt.date() == (now + timedelta(days=1)).date()
    assert dt.hour == 23 and dt.minute == 59


def test_format_uptime():
    delta = timedelta(days=3, hours=4, minutes=12)
    assert format_uptime(delta) == "3d 4h 12m"

    delta_short = timedelta(seconds=15)
    assert format_uptime(delta_short) == "less than a minute"

    delta_hours = timedelta(hours=2)
    assert format_uptime(delta_hours) == "2h"
