"""Tests for Ayaka storage, task state, and reminder milestone triggers."""

from datetime import datetime, timedelta, timezone
import pytest
from ayaka.storage.db import Database


def test_database_init_and_task_upsert(tmp_path):
    db_file = tmp_path / "test.db"
    db = Database(str(db_file))

    due = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    task_data = {
        "id": "edunex:assign:101",
        "platform": "edunex",
        "course_id": "IF2110",
        "course_name": "Algorithms and Data Structures",
        "title": "Assignment 1 - List ADT",
        "description": "Implement linked list in C language",
        "due_date": due,
        "url": "https://edunex.itb.ac.id/courses/101/assignment/1",
    }

    # First insert
    saved, is_new = db.upsert_task(task_data)
    assert is_new is True
    assert saved["title"] == "Assignment 1 - List ADT"
    assert saved["is_completed"] == 0

    # Second upsert (same ID, no date change)
    task_data["description"] = "Description updated"
    saved_again, is_new_again = db.upsert_task(task_data)
    assert is_new_again is False
    assert saved_again["description"] == "Description updated"


def test_mark_task_completed(tmp_path):
    db_file = tmp_path / "test.db"
    db = Database(str(db_file))

    task_data = {
        "id": "six:exam:201",
        "platform": "six",
        "course_id": "MA1201",
        "course_name": "Calculus IIA",
        "title": "Midterm Exam Calculus IIA",
        "due_date": (datetime.now(timezone.utc) + timedelta(days=5)).isoformat(),
    }
    db.upsert_task(task_data)

    assert len(db.list_tasks(include_completed=False)) == 1
    assert db.mark_task_completed("six:exam:201") is True

    # Completed tasks should be filtered out by default
    assert len(db.list_tasks(include_completed=False)) == 0
    assert len(db.list_tasks(include_completed=True)) == 1


def test_reminder_milestones_evaluation(tmp_path):
    db_file = tmp_path / "test.db"
    db = Database(str(db_file))
    now = datetime.now(timezone.utc)

    # 1. Task H-3 (remaining ~40 hours)
    db.upsert_task({
        "id": "task_h3",
        "platform": "edunex",
        "title": "Task H-3",
        "due_date": (now + timedelta(hours=40)).isoformat(),
    })

    # 2. Task H-1 (remaining ~12 hours)
    db.upsert_task({
        "id": "task_h1",
        "platform": "edunex",
        "title": "Task H-1",
        "due_date": (now + timedelta(hours=12)).isoformat(),
    })

    # 3. Task J-6 (remaining ~4 hours)
    db.upsert_task({
        "id": "task_j6",
        "platform": "omnicampus",
        "title": "Task J-6",
        "due_date": (now + timedelta(hours=4)).isoformat(),
    })

    # 4. Task J-1 (remaining ~30 mins = 0.5 hour)
    db.upsert_task({
        "id": "task_j1",
        "platform": "six",
        "title": "Task J-1",
        "due_date": (now + timedelta(minutes=30)).isoformat(),
    })

    # 5. Task Due (remaining -10 mins = -0.16 hour)
    db.upsert_task({
        "id": "task_due",
        "platform": "edunex",
        "title": "Task Due Now",
        "due_date": (now - timedelta(minutes=10)).isoformat(),
    })

    reminders = db.get_tasks_needing_reminders(now)
    assert len(reminders) == 5

    rem_dict = {t["id"]: milestone for t, milestone in reminders}
    assert rem_dict["task_h3"] == "h3"
    assert rem_dict["task_h1"] == "h1"
    assert rem_dict["task_j6"] == "j6"
    assert rem_dict["task_j1"] == "j1"
    assert rem_dict["task_due"] == "due"

    # Mark h3 sent
    db.mark_reminder_sent("task_h3", "h3")
    reminders_after = db.get_tasks_needing_reminders(now)
    rem_dict_after = {t["id"]: milestone for t, milestone in reminders_after}
    assert "task_h3" not in rem_dict_after
