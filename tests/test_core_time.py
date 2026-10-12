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


def test_parse_user_due_date_dot_time_and_indonesian_formats():
    # 1. Indonesian dot time: "2026-10-15 21.00" must parse to 21:00, NOT 23:59!
    dt1 = parse_user_due_date("2026-10-15 21.00")
    assert dt1 is not None
    assert dt1.year == 2026 and dt1.month == 10 and dt1.day == 15
    assert dt1.hour == 21 and dt1.minute == 0

    # 2. Dot time with minutes: "2026-10-15 21.30"
    dt2 = parse_user_due_date("2026-10-15 21.30")
    assert dt2 is not None
    assert dt2.hour == 21 and dt2.minute == 30

    # 3. With "jam" prefix: "2026-10-15 jam 21.00"
    dt3 = parse_user_due_date("2026-10-15 jam 21.00")
    assert dt3 is not None
    assert dt3.hour == 21 and dt3.minute == 0

    # 4. Textual Indonesian month: "15 Oktober 2026 21.00"
    dt4 = parse_user_due_date("15 Oktober 2026 21.00")
    assert dt4 is not None
    assert dt4.year == 2026 and dt4.month == 10 and dt4.day == 15
    assert dt4.hour == 21 and dt4.minute == 0

    # 5. DD/MM/YYYY and DD-MM-YYYY with dot time
    dt5 = parse_user_due_date("15/10/2026 21.00")
    assert dt5 is not None
    assert dt5.year == 2026 and dt5.month == 10 and dt5.day == 15
    assert dt5.hour == 21 and dt5.minute == 0

    dt6 = parse_user_due_date("15-10-2026 21.00")
    assert dt6 is not None
    assert dt6.year == 2026 and dt6.month == 10 and dt6.day == 15
    assert dt6.hour == 21 and dt6.minute == 0

    # 6. Time only: "21.00"
    dt_time = parse_user_due_date("21.00")
    assert dt_time is not None
    assert dt_time.hour == 21 and dt_time.minute == 0


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
