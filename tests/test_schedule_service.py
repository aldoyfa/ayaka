"""Tests for Ayaka lecture schedule service and reminders."""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock
import zoneinfo

import pytest

from ayaka.config import Config
from ayaka.services.discord_bot import AyakaBot
from ayaka.services.schedule_service import ScheduleService
from ayaka.storage.db import Database


def test_schedule_reminders_db(tmp_path):
    db_file = tmp_path / "test.db"
    db = Database(str(db_file))

    rem_id = "morning:2026-10-10"
    assert db.is_schedule_reminder_sent(rem_id) is False

    db.record_schedule_reminder(
        reminder_id=rem_id,
        reminder_type="morning",
        scheduled_for="2026-10-10",
    )
    assert db.is_schedule_reminder_sent(rem_id) is True

    # Duplicate record shouldn't raise error
    db.record_schedule_reminder(
        reminder_id=rem_id,
        reminder_type="morning",
        scheduled_for="2026-10-10",
    )
    assert db.is_schedule_reminder_sent(rem_id) is True


def test_schedule_service_mock_fetch(tmp_path):
    db_file = tmp_path / "test.db"
    db = Database(str(db_file))

    config = Config.load()
    config.timezone = "Asia/Jakarta"
    config.google.schedule_calendar_id = "test-cal-id@group.calendar.google.com"

    mock_google = MagicMock()
    mock_events = MagicMock()
    mock_google._calendar_service.events.return_value = mock_events

    mock_events.list.return_value.execute.return_value = {
        "items": [
            {
                "id": "event_1",
                "summary": "IF5152 Visi Komputer",
                "location": "Lab 7602",
                "start": {"dateTime": "2026-10-12T09:00:00+07:00"},
                "end": {"dateTime": "2026-10-12T11:00:00+07:00"},
            },
            {
                "id": "event_cancelled",
                "status": "cancelled",
                "summary": "Cancelled class",
                "start": {"dateTime": "2026-10-12T13:00:00+07:00"},
                "end": {"dateTime": "2026-10-12T15:00:00+07:00"},
            },
        ]
    }

    service = ScheduleService(config, db, mock_google)
    events = service.get_events_for_date(date(2026, 10, 12))

    assert len(events) == 1
    assert events[0]["id"] == "event_1"
    assert events[0]["summary"] == "IF5152 Visi Komputer"
    assert events[0]["location"] == "Lab 7602"
    assert events[0]["start_dt"].hour == 9
    assert events[0]["end_dt"].hour == 11


def test_build_schedule_embed(tmp_path):
    db_file = tmp_path / "test.db"
    db = Database(str(db_file))
    config = Config.load()
    config.timezone = "Asia/Jakarta"

    mock_google = MagicMock()
    service = ScheduleService(config, db, mock_google)

    tz = zoneinfo.ZoneInfo("Asia/Jakarta")
    dt1 = datetime(2026, 10, 12, 9, 0, tzinfo=tz)
    dt2 = datetime(2026, 10, 12, 11, 0, tzinfo=tz)

    service.get_events_for_date = MagicMock(return_value=[
        {
            "id": "ev1",
            "summary": "IF5152 Visi Komputer",
            "location": "Lab 7602",
            "start_dt": dt1,
            "end_dt": dt2,
        }
    ])
    service.get_events_for_range = MagicMock(return_value=[
        {
            "id": "ev1",
            "summary": "IF5152 Visi Komputer",
            "location": "Lab 7602",
            "start_dt": dt1,
            "end_dt": dt2,
        }
    ])

    bot = AyakaBot(config, db, mock_google, service)

    # 1. Today
    embed_today = bot._build_schedule_embed(period="today")
    assert "Today's Lecture Schedule" in embed_today.title
    assert len(embed_today.fields) == 1
    assert "IF5152 Visi Komputer" in embed_today.fields[0].name
    assert "09:00 - 11:00 WIB" in embed_today.fields[0].value

    # 2. Tomorrow
    embed_tomorrow = bot._build_schedule_embed(period="tomorrow")
    assert "Tomorrow's Lecture Schedule" in embed_tomorrow.title

    # 3. Week
    embed_week = bot._build_schedule_embed(period="week")
    assert "Next 7 Days" in embed_week.title


def test_meeting_enrichment_and_modal_formatting(tmp_path):
    db_file = tmp_path / "test.db"
    db = Database(str(db_file))
    config = Config.load()
    config.timezone = "Asia/Jakarta"

    # 1. Insert modal meeting into DB
    meeting_data = {
        "id": "12345678_m123",
        "meeting_date": "2026-10-12",
        "course_code": "IF5152",
        "course_name": "Visi Komputer",
        "start_time": "09:00",
        "end_time": "11:00",
        "activity_type": "Kuliah - Tatap Muka",
        "room": "7609 7610",
        "lecturer": "Nugraha Priya Utama, S.T, M.A., Ph.D.",
        "topic": "Pengenalan Deep Learning",
        "notes": "Membawa laptop",
        "edunex_url": "https://edunex.itb.ac.id/course/123",
        "teams_url": "https://teams.microsoft.com/l/meetup/123",
        "attendance_window": "Presensi mandiri dapat dilakukan pada 12 Okt 2026 09:00 - 11:00",
        "detail_url": "https://six.itb.ac.id/app/pertemuan/123",
    }
    db.upsert_lecture_meeting(meeting_data)

    mock_google = MagicMock()
    service = ScheduleService(config, db, mock_google)

    tz = zoneinfo.ZoneInfo("Asia/Jakarta")
    dt1 = datetime(2026, 10, 12, 9, 0, tzinfo=tz)
    dt2 = datetime(2026, 10, 12, 11, 0, tzinfo=tz)

    ev = {
        "id": "ev1",
        "summary": "IF5152 Visi Komputer",
        "location": "",
        "start_dt": dt1,
        "end_dt": dt2,
    }

    service._enrich_event(ev)

    assert "meeting_detail" in ev
    assert ev["location"] == "7609 7610"
    assert ev["meeting_detail"]["lecturer"] == "Nugraha Priya Utama, S.T, M.A., Ph.D."
    assert ev["meeting_detail"]["activity_type"] == "Kuliah - Tatap Muka"

    bot = AyakaBot(config, db, mock_google, service)
    formatted = bot._format_meeting_field_value(ev, include_links=True)

    assert "09:00 - 11:00 WIB" in formatted
    assert "Tipe:** Kuliah - Tatap Muka" in formatted
    assert "Ruang:** `7609 7610`" in formatted
    assert "Dosen:** Nugraha Priya Utama" in formatted
    assert "Topik:** Pengenalan Deep Learning" in formatted
    assert "Presensi:** Presensi mandiri" in formatted
    assert "Catatan:** Membawa laptop" in formatted
    assert "[Edunex](https://edunex.itb.ac.id/course/123)" in formatted
    assert "[MS Teams](https://teams.microsoft.com/l/meetup/123)" in formatted


def test_action_views():
    from ayaka.services.discord_bot import AttendanceActionView, ClassStartActionView

    att_view = AttendanceActionView(
        six_url="https://six.itb.ac.id/mhs/1",
        edunex_url="https://edunex.itb.ac.id/course/1",
        teams_url="https://teams.microsoft.com/meet/1",
    )
    # Check buttons
    labels = [getattr(b, "item", b).label for b in att_view.children]
    assert "Open SIX" in labels
    assert "Open Edunex" in labels
    assert "MS Teams" in labels
    assert "Checked In" in labels

    start_view = ClassStartActionView(
        edunex_url="https://edunex.itb.ac.id/course/1",
        teams_url="https://teams.microsoft.com/meet/1",
        six_url="https://six.itb.ac.id/mhs/1",
    )
    start_labels = [b.label for b in start_view.children if hasattr(b, "label")]
    assert "Open Edunex" in start_labels
    assert "Join Teams" in start_labels
    assert "Open SIX" in start_labels


def test_upsert_lecture_meeting_topic_change(tmp_path):
    db_file = tmp_path / "test.db"
    db = Database(str(db_file))

    m1 = {
        "id": "six:meeting:101",
        "meeting_date": "2026-10-15",
        "course_code": "IF5152",
        "course_name": "Visi Komputer",
        "start_time": "09:00",
        "end_time": "11:00",
        "topic": "Old Topic",
        "room": "7609",
    }
    saved, is_new, was_updated = db.upsert_lecture_meeting(m1)
    assert is_new is True
    assert was_updated is False

    # Second upsert with updated topic
    m2 = dict(m1)
    m2["topic"] = "Updated Deep Learning Topic"
    saved2, is_new2, was_updated2 = db.upsert_lecture_meeting(m2)
    assert is_new2 is False
    assert was_updated2 is True
    assert saved2.get("_topic_changed") is True
    assert saved2.get("_old_topic") == "Old Topic"

    # Verify DB has updated topic
    row = db.get_lecture_meeting("2026-10-15", course_code="IF5152")
    assert row["topic"] == "Updated Deep Learning Topic"


def test_future_only_filtering():
    from unittest.mock import AsyncMock, MagicMock, patch
    from ayaka.fetchers.six import SixFetcher

    config = Config.load()
    config.academic.six_cookie = "test_cookie"
    fetcher = SixFetcher(config)

    html_calendar = """
    <table class="table-bordered">
        <tr><th>Senin</th></tr>
        <tr>
            <td>
                <div>1 Oktober 2026</div>
                <a class="linkpertemuan" data-url="/kelas/pertemuan/1/mhs/1" data-kuliah="IF5152 Visi Komputer">
                    (Kuliah 7609) 09:00-11:00
                </a>
            </td>
            <td>
                <div>11 Oktober 2026</div>
                <a class="linkpertemuan" data-url="/kelas/pertemuan/2/mhs/1" data-kuliah="IF5152 Visi Komputer">
                    (Kuliah 7609) 09:00-11:00
                </a>
            </td>
            <td>
                <div>18 Oktober 2026</div>
                <a class="linkpertemuan" data-url="/kelas/pertemuan/3/mhs/1" data-kuliah="IF5152 Visi Komputer">
                    (Kuliah 7609) 09:00-11:00
                </a>
            </td>
        </tr>
    </table>
    """

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = html_calendar
        mock_resp.url = "https://six.itb.ac.id/schedule"
        mock_get.return_value = mock_resp

        # 1. With future_only=True and cutoff=2026-10-11
        meetings = fetcher.fetch_lecture_meetings(fetch_modals=False, future_only=True, from_date="2026-10-11")
        assert len(meetings) == 2
        dates = [m["meeting_date"] for m in meetings]
        assert "2026-10-01" not in dates
        assert "2026-10-11" in dates
        assert "2026-10-18" in dates

        # 2. With future_only=False
        all_meetings = fetcher.fetch_lecture_meetings(fetch_modals=False, future_only=False)
        assert len(all_meetings) == 3


@pytest.mark.anyio
async def test_send_class_advance_reminder(tmp_path):
    from unittest.mock import AsyncMock

    db_file = tmp_path / "test.db"
    db = Database(str(db_file))
    config = Config.load()
    config.discord.user_id = 123456789

    bot = AyakaBot(config, db)
    mock_user = AsyncMock()
    bot.fetch_user = AsyncMock(return_value=mock_user)

    tz = zoneinfo.ZoneInfo("Asia/Jakarta")
    dt1 = datetime(2026, 10, 12, 9, 0, tzinfo=tz)
    dt2 = datetime(2026, 10, 12, 11, 0, tzinfo=tz)

    event = {
        "id": "ev_adv",
        "summary": "IF5152 Visi Komputer",
        "location": "Lab 7602",
        "start_dt": dt1,
        "end_dt": dt2,
        "meeting_detail": {
            "lecturer": "Dr. Nugraha",
            "topic": "Neural Nets",
            "room": "Lab 7602",
        },
    }

    sent = await bot.send_class_advance_reminder(event, minutes_before=15)
    assert sent is True
    assert mock_user.send.called
    kwargs = mock_user.send.call_args.kwargs
    embed = kwargs.get("embed")
    assert embed is not None
    assert "Upcoming Class: IF5152 Visi Komputer (in 15 min)" in embed.title
    assert "15 minutes" in embed.description




def test_meeting_upsert_keeps_known_details_when_modal_fetch_fails(tmp_path):
    db = Database(str(tmp_path / "keep.db"))
    full = {
        "id": "six:meeting:1", "meeting_date": "2026-10-20", "course_code": "IF5152",
        "course_name": "Visi", "start_time": "09:00", "end_time": "11:00",
        "activity_type": "Kuliah", "room": "R1", "lecturer": "Dr. Jane", "topic": "Detection",
        "notes": "", "edunex_url": "https://edunex.itb.ac.id/c/1", "teams_url": "",
        "attendance_window": "Presensi 09:00-11:00", "detail_url": "/kelas/pertemuan/1/mhs/1",
    }
    db.upsert_lecture_meeting(dict(full))

    bare = dict(full, activity_type="", lecturer="", topic="", edunex_url="", attendance_window="")
    saved, _, _ = db.upsert_lecture_meeting(bare)
    stored = db.get_lecture_meeting("2026-10-20", "IF5152", "09:00")

    assert stored["lecturer"] == "Dr. Jane"
    assert stored["topic"] == "Detection"
    assert stored["edunex_url"] == "https://edunex.itb.ac.id/c/1"
    assert stored["attendance_window"] == "Presensi 09:00-11:00"
    assert saved["lecturer"] == "Dr. Jane"
