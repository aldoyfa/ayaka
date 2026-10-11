"""Tests for Config loader and config.json operational settings parsing."""

import json
from pathlib import Path
from ayaka.config import Config


def test_config_loads_from_config_json(tmp_path):
    config_file = tmp_path / "config.json"
    config_content = {
        "system": {
            "timezone": "Asia/Jakarta",
            "database_path": "test_state.db",
        },
        "gmail": {
            "monitor_domains": ["test.itb.ac.id"],
            "important_keywords": ["tugas", "customkeyword"],
            "max_results": 20,
            "poll_interval_minutes": 10,
        },
        "scheduler": {
            "academic_sync_interval_minutes": 15,
            "reminder_poll_interval_seconds": 30,
        },
        "platforms": {
            "edunex": {"base_url": "https://custom-edunex.itb.ac.id"},
            "six": {"base_url": "https://custom-six.itb.ac.id"},
            "omnicampus": {"base_url": "https://custom.omnicamp.us"},
        },
        "google": {
            "calendar_id": "test_cal",
            "tasks_list_id": "test_tasks",
        },
    }
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(config_content, f)

    cfg = Config.load(base_dir=tmp_path)
    assert cfg.gmail.domains == ["test.itb.ac.id"]
    assert "customkeyword" in cfg.gmail.keywords
    assert cfg.gmail.max_results == 20
    assert cfg.gmail.poll_interval_minutes == 10
    assert cfg.scheduler.sync_interval_minutes == 15
    assert cfg.academic.endpoints.edunex_base_url == "https://custom-edunex.itb.ac.id"
    assert cfg.academic.endpoints.six_base_url == "https://custom-six.itb.ac.id"
    assert cfg.google.calendar_id == "test_cal"
    assert cfg.google.tasks_list_id == "test_tasks"


def test_update_env_variable(tmp_path):
    from ayaka.config import update_env_variable
    import os

    env_path = tmp_path / ".env"
    env_path.write_text("FOO=bar\nOMNICAMPUS_TOKEN=old_token\n# comment\n", encoding="utf-8")

    success = update_env_variable("OMNICAMPUS_TOKEN", "new_token_123", env_path=env_path)
    assert success is True
    assert os.environ.get("OMNICAMPUS_TOKEN") == "new_token_123"

    content = env_path.read_text(encoding="utf-8")
    assert "OMNICAMPUS_TOKEN=new_token_123\n" in content
    assert "FOO=bar\n" in content
    assert "# comment\n" in content
    assert "old_token" not in content

    # Test appending new variable
    update_env_variable("NEW_VAR", "hello_world", env_path=env_path)
    content2 = env_path.read_text(encoding="utf-8")
    assert "NEW_VAR=hello_world\n" in content2


def test_dynamic_academic_config(tmp_path, monkeypatch):
    config_file = tmp_path / "config.json"
    config_content = {
        "platforms": {
            "edunex": {"period_id": 42},
            "six": {"student_id": "18299999", "semester_code": "2027-2"},
            "omnicampus": {"course_ids": [101, 102]},
        }
    }
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(config_content, f)

    cfg = Config.load(base_dir=tmp_path)
    assert cfg.academic.edunex_period_id == 42
    assert cfg.academic.six_student_id == "18299999"
    assert cfg.academic.six_semester_code == "2027-2"
    assert cfg.academic.omnicampus_course_ids == [101, 102]

    # Test environment variable override
    monkeypatch.setenv("EDUNEX_PERIOD_ID", "99")
    monkeypatch.setenv("SIX_STUDENT_ID", "13521000")
    monkeypatch.setenv("SIX_SEMESTER_CODE", "2028-1")
    monkeypatch.setenv("OMNICAMPUS_COURSE_IDS", "201, 202, 203")

    cfg_env = Config.load(base_dir=tmp_path)
    assert cfg_env.academic.edunex_period_id == 99
    assert cfg_env.academic.six_student_id == "13521000"
    assert cfg_env.academic.six_semester_code == "2028-1"
    assert cfg_env.academic.omnicampus_course_ids == [201, 202, 203]


def test_config_reminders_from_config_json(tmp_path):
    config_file = tmp_path / "config.json"
    config_content = {
        "reminders": {
            "tasks": {
                "enabled": True,
                "milestones": [
                    {"key": "h2", "label": "H-2", "hours": 48},
                    {"key": "j12", "label": "J-12", "hours": 12},
                    {"key": "due", "label": "Due", "hours": 0},
                ],
            },
            "lectures": {
                "enabled": True,
                "morning_briefing_hour": 6,
                "morning_briefing_tasks_lookahead_hours": 24,
                "class_start_reminder_minutes_before": 5,
                "attendance_reminder_minutes_before_end": 15,
            },
        }
    }
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(config_content, f)

    cfg = Config.load(base_dir=tmp_path)
    assert cfg.reminders.tasks.enabled is True
    assert len(cfg.reminders.tasks.milestones) == 3
    assert cfg.reminders.tasks.milestones[0].key == "h2"
    assert cfg.reminders.tasks.milestones[0].hours == 48.0
    assert cfg.reminders.lectures.morning_briefing_hour == 6
    assert cfg.reminders.lectures.morning_briefing_tasks_lookahead_hours == 24.0
    assert cfg.reminders.lectures.class_start_reminder_minutes_before == 5
    assert cfg.reminders.lectures.attendance_reminder_minutes_before_end == 15


def test_config_nested_lecture_reminders(tmp_path):
    config_file = tmp_path / "config.json"
    config_content = {
        "reminders": {
            "lectures": {
                "enabled": True,
                "morning_briefing": {
                    "enabled": False,
                    "hour": 7,
                    "tasks_lookahead_hours": 12,
                },
                "advance_reminder": {
                    "enabled": True,
                    "minutes_before": 20,
                },
                "class_start": {
                    "enabled": False,
                    "minutes_before": 2,
                },
                "attendance": {
                    "enabled": True,
                    "minutes_before_end": 5,
                },
            }
        }
    }
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(config_content, f)

    cfg = Config.load(base_dir=tmp_path)
    lec = cfg.reminders.lectures
    assert lec.enabled is True
    assert lec.morning_briefing_enabled is False
    assert lec.morning_briefing_hour == 7
    assert lec.morning_briefing_tasks_lookahead_hours == 12.0
    assert lec.advance_reminder_enabled is True
    assert lec.advance_reminder_minutes_before == 20
    assert lec.class_start_reminder_enabled is False
    assert lec.class_start_reminder_minutes_before == 2
    assert lec.attendance_reminder_enabled is True
    assert lec.attendance_reminder_minutes_before_end == 5


