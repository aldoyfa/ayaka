"""Tests for Ayaka Architecture Refactoring & Enhancements.

Covers:
- BaseFetcher and AcademicTask contract
- SessionExpiredException handling
- TaskFilters.add_task_to_blacklist persistence
- Database session alerts, WAL config, get_tasks_due_soon, and delete_task
- AttendanceActionView UI components and state transitions
- Date parsing and uptime formatting helpers
- Upcoming deadlines timeline construction
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ayaka.fetchers.base import AcademicTask, BaseFetcher, SessionExpiredException
from ayaka.services.discord_bot import (
    AttendanceActionView,
    _format_uptime,
    _parse_user_due_date,
)
from ayaka.storage.db import Database
from ayaka.task_filters import TaskFilters


class DummyFetcher(BaseFetcher):
    """Dummy fetcher implementation for contract testing."""

    platform_name = "dummy"

    def __init__(self, should_expire: bool = False):
        super().__init__(None)  # type: ignore
        self.should_expire = should_expire

    @property
    def is_configured(self) -> bool:
        return True

    def fetch_tasks(self) -> list[AcademicTask]:
        if self.should_expire:
            raise SessionExpiredException("dummy", "HTTP 401 Unauthorized")
        return [
            AcademicTask(
                id="dummy:101",
                platform="dummy",
                course_id="IF3110",
                course_name="Web Dev",
                title="Lab 1",
                due_date=(datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
            )
        ]


def test_base_fetcher_contract():
    fetcher = DummyFetcher(should_expire=False)
    assert fetcher.platform_name == "dummy"
    tasks = fetcher.fetch_tasks()
    assert len(tasks) == 1
    t = tasks[0]
    assert t.id == "dummy:101"
    assert t.course_name == "Web Dev"

    dict_repr = t.to_dict()
    assert dict_repr["id"] == "dummy:101"
    assert dict_repr["platform"] == "dummy"


def test_session_expired_exception():
    fetcher = DummyFetcher(should_expire=True)
    with pytest.raises(SessionExpiredException) as exc_info:
        fetcher.fetch_tasks()
    assert exc_info.value.platform == "dummy"
    assert "dummy" in str(exc_info.value)
    assert "HTTP 401" in str(exc_info.value)



def test_task_filters_add_blacklist(tmp_path: Path):
    filter_file = tmp_path / "task_filters.json"
    initial_content = {
        "blacklist": {
            "task_ids": [
                {"id": 11111, "reason": "Old assignment"}
            ]
        }
    }
    filter_file.write_text(json.dumps(initial_content), encoding="utf-8")

    # Add new task ID
    success = TaskFilters.add_task_to_blacklist(filter_file, 22222, "Duplicate assignment")
    assert success is True

    # Read back
    data = json.loads(filter_file.read_text(encoding="utf-8"))
    ids = [item["id"] if isinstance(item, dict) else item for item in data["blacklist"]["task_ids"]]
    assert 11111 in ids
    assert 22222 in ids

    # Adding duplicate should return True and not duplicate entry
    success_dup = TaskFilters.add_task_to_blacklist(filter_file, 22222, "Duplicate assignment")
    assert success_dup is True
    data2 = json.loads(filter_file.read_text(encoding="utf-8"))
    assert len(data2["blacklist"]["task_ids"]) == 2


def test_database_session_alerts_and_wal(tmp_path: Path):
    db_file = tmp_path / "test_ayaka.db"
    db = Database(str(db_file))

    # Test WAL mode
    with db._conn() as conn:
        journal_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        assert journal_mode.lower() == "wal"

    # Test initial alert check
    assert db.should_alert_session_expired("edunex", cooldown_hours=12.0) is True

    # Record alert
    db.record_session_alert("edunex")

    # Second check within cooldown must return False
    assert db.should_alert_session_expired("edunex", cooldown_hours=12.0) is False

    # Check different platform is independent
    assert db.should_alert_session_expired("six", cooldown_hours=12.0) is True

    # Clear alert
    db.clear_session_alert("edunex")
    assert db.should_alert_session_expired("edunex", cooldown_hours=12.0) is True


def test_database_tasks_due_soon_and_delete(tmp_path: Path):
    db_file = tmp_path / "test_tasks.db"
    db = Database(str(db_file))

    now = datetime.now(timezone.utc)
    due_in_10h = (now + timedelta(hours=10)).isoformat()
    due_in_40h = (now + timedelta(hours=40)).isoformat()

    db.upsert_task({
        "id": "t1",
        "platform": "edunex",
        "title": "Assignment 1",
        "due_date": due_in_10h,
    })
    db.upsert_task({
        "id": "t2",
        "platform": "six",
        "title": "Assignment 2",
        "due_date": due_in_40h,
    })

    # Should find t1 (due within 36h) but not t2
    due_soon = db.get_tasks_due_soon(hours=36.0)
    assert len(due_soon) == 1
    assert due_soon[0]["id"] == "t1"

    # Delete task
    assert db.delete_task("t1") is True
    assert db.delete_task("t1") is False  # Already deleted
    assert len(db.get_tasks_due_soon(hours=36.0)) == 0


def test_date_parsing_and_uptime():
    # ISO format
    dt1 = _parse_user_due_date("2026-10-15T23:59:00+07:00")
    assert dt1 is not None
    assert dt1.year == 2026
    assert dt1.month == 10
    assert dt1.day == 15

    # Standard format YYYY-MM-DD HH:MM
    dt2 = _parse_user_due_date("2026-11-01 14:30")
    assert dt2 is not None
    assert dt2.hour == 14
    assert dt2.minute == 30

    # Date-only defaults to 23:59
    dt3 = _parse_user_due_date("2026-12-31")
    assert dt3 is not None
    assert dt3.hour == 23
    assert dt3.minute == 59

    # Invalid string returns None
    assert _parse_user_due_date("not-a-date") is None

    # Uptime formatter
    delta = timedelta(days=2, hours=5, minutes=30)
    uptime_str = _format_uptime(delta)
    assert uptime_str == "2d 5h 30m"

    short_delta = timedelta(seconds=25)
    assert _format_uptime(short_delta) == "less than a minute"


def test_attendance_action_view():
    view = AttendanceActionView()
    # Should have 3 children: Open SIX button, Open Edunex button, Checked In button
    assert len(view.children) == 3

    labels = [getattr(c, "label", "") for c in view.children]
    assert any("SIX" in l for l in labels)
    assert any("Edunex" in l for l in labels)
    assert any("Checked In" in l for l in labels)

    urls = [getattr(c, "url", None) for c in view.children if getattr(c, "url", None)]
    assert any("https://six.itb.ac.id" in u for u in urls)
    assert any("https://edunex.itb.ac.id" in u for u in urls)


def test_db_upsert_completion_and_change_tracking(tmp_path: Path):
    db_file = tmp_path / "test_upsert.db"
    db = Database(str(db_file))

    # 1. New task (uncompleted)
    t1 = {
        "id": "t1",
        "platform": "edunex",
        "title": "Assignment 1",
        "due_date": "2026-10-15T23:59:00",
        "is_completed": 0,
    }
    saved, is_new = db.upsert_task(t1)
    assert is_new is True
    assert saved["is_completed"] == 0
    assert saved["_is_newly_completed"] is False
    assert saved["_due_date_changed"] is False
    assert saved["_title_changed"] is False

    # 2. Update task: completed on platform
    t1_done = dict(t1, is_completed=1)
    saved_done, is_new_again = db.upsert_task(t1_done)
    assert is_new_again is False
    assert saved_done["is_completed"] == 1
    assert saved_done["_is_newly_completed"] is True
    assert saved_done["_due_date_changed"] is False

    # Verify directly from DB
    row = db.get_task("t1")
    assert row is not None
    assert row["is_completed"] == 1

    # 3. Repeat upsert: stays completed, but not newly completed
    saved_repeat, is_new_rep = db.upsert_task(t1_done)
    assert is_new_rep is False
    assert saved_repeat["is_completed"] == 1
    assert saved_repeat["_is_newly_completed"] is False

    # 4. Update deadline and title
    t1_changed = dict(t1_done, title="Assignment 1 Revised", due_date="2026-10-20T23:59:00")
    saved_chg, _ = db.upsert_task(t1_changed)
    assert saved_chg["_due_date_changed"] is True
    assert saved_chg["_title_changed"] is True
    assert saved_chg["title"] == "Assignment 1 Revised"


def test_task_pagination_view():
    from unittest.mock import MagicMock
    from ayaka.services.discord_bot import TaskPaginationView, AyakaBot
    from ayaka.dialogue import DialogueManager

    mock_bot = MagicMock(spec=AyakaBot)
    mock_bot.dialogue_mgr = DialogueManager()
    mock_bot.get_author_icon.return_value = "https://example.com/icon.png"

    sample_tasks = [
        {
            "id": f"task_{i}",
            "platform": "edunex",
            "course_id": "IF101",
            "title": f"Task {i}",
            "due_date": "2026-10-15T23:59:00",
            "is_completed": 0,
        }
        for i in range(12)
    ]

    view = TaskPaginationView(
        bot=mock_bot,
        tasks=sample_tasks,
        author_id=123456,
        all_tasks=False,
        per_page=5,
    )

    # 12 items / 5 per page -> 3 pages
    assert view.total_pages == 3
    assert view.current_page == 0
    assert view.prev_button.disabled is True
    assert view.next_button.disabled is False
    assert view.indicator_button.label == "Page 1/3"

    # Embed page 0 has 5 fields
    embed_p0 = view.build_embed()
    assert len(embed_p0.fields) == 5
    assert "Page 1 of 3" in embed_p0.footer.text

    # Page 1
    view.current_page = 1
    view._update_buttons()
    assert view.prev_button.disabled is False
    assert view.next_button.disabled is False
    assert view.indicator_button.label == "Page 2/3"

    embed_p1 = view.build_embed()
    assert len(embed_p1.fields) == 5

    # Page 2 (last page, 2 remaining items)
    view.current_page = 2
    view._update_buttons()
    assert view.prev_button.disabled is False
    assert view.next_button.disabled is True
    assert view.indicator_button.label == "Page 3/3"

    embed_p2 = view.build_embed()
    assert len(embed_p2.fields) == 2
    assert "Page 3 of 3" in embed_p2.footer.text


def test_build_sync_embed():
    from unittest.mock import MagicMock
    from ayaka.services.discord_bot import AyakaBot
    from ayaka.dialogue import DialogueManager

    bot = MagicMock(spec=AyakaBot)
    bot.dialogue_mgr = DialogueManager()
    bot.get_author_icon.return_value = "https://example.com/icon.png"

    # 1. Test clean sync (no changes)
    clean_stats = {
        "new_tasks": 0,
        "updated_tasks": 0,
        "completed_tasks": 0,
        "expired_sessions": [],
        "added_items": [],
        "updated_items": [],
        "completed_items": [],
    }
    embed_clean = AyakaBot._build_sync_embed(bot, "all", clean_stats)
    assert "no new changes detected" in embed_clean.description

    # 2. Test sync with changes
    dirty_stats = {
        "new_tasks": 1,
        "updated_tasks": 1,
        "completed_tasks": 1,
        "expired_sessions": ["omnicampus"],
        "added_items": [{"id": "t1", "title": "New Assignment", "platform": "edunex", "due_date": "2026-10-20"}],
        "updated_items": [{"id": "t2", "title": "Updated Task", "platform": "edunex", "due_date": "2026-10-22"}],
        "completed_items": [{"id": "t3", "title": "Submitted Homework", "platform": "omnicampus"}],
    }
    embed_dirty = AyakaBot._build_sync_embed(bot, "all", dirty_stats)
    field_names = [f.name for f in embed_dirty.fields]
    assert any("Completed Tasks" in name for name in field_names)
    assert any("Newly Discovered Tasks" in name for name in field_names)
    assert any("Updated Deadlines" in name for name in field_names)
    assert any("Expired Sessions" in name for name in field_names)

