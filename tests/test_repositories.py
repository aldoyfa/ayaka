"""Tests for Ayaka storage repositories and AI persistent conversation memory."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from ayaka.storage.connection import ConnectionManager
from ayaka.storage.db import Database
from ayaka.storage.repositories import (
    AIConversationRepository,
    AlertRepository,
    MeetingRepository,
    TaskRepository,
)


@pytest.fixture
def test_db_path(tmp_path: Path) -> str:
    return str(tmp_path / "test_repo_ayaka.db")


def test_connection_manager_reuse(test_db_path: str):
    mgr = ConnectionManager(test_db_path)
    conn1 = mgr.get_connection()
    conn2 = mgr.get_connection()
    assert conn1 is conn2  # Reuses same connection for thread

    # Verify WAL mode
    cur = conn1.execute("PRAGMA journal_mode;")
    mode = cur.fetchone()[0]
    assert mode.lower() == "wal"


def test_ai_conversation_persistence(test_db_path: str):
    db = Database(test_db_path)
    user_id = "123456789"

    # Save multiple turns
    db.save_ai_message(user_id, "user", "Halo Ayaka!")
    db.save_ai_message(user_id, "assistant", "Halo Master! Ada yang bisa Ayaka bantu? 🌸")
    db.save_ai_message(user_id, "user", "Kapan deadline tugas NLP?")
    db.save_ai_message(user_id, "assistant", "Deadline tugas NLP besok malam jam 23:59 ya Master! ✨")

    # Fetch recent history
    history = db.get_ai_history(user_id, limit=10)
    assert len(history) == 4
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "Halo Ayaka!"
    assert history[1]["role"] == "assistant"
    assert history[3]["content"] == "Deadline tugas NLP besok malam jam 23:59 ya Master! ✨"

    # Test limit
    history_limited = db.get_ai_history(user_id, limit=2)
    assert len(history_limited) == 2
    assert history_limited[0]["role"] == "user"
    assert history_limited[0]["content"] == "Kapan deadline tugas NLP?"
    assert history_limited[1]["role"] == "assistant"


def test_ai_conversation_pruning(test_db_path: str):
    db = Database(test_db_path)
    user_id = "987654321"

    # Insert old conversation turn manually
    old_iso = (datetime.now(timezone.utc) - timedelta(hours=60)).isoformat()
    with db._conn() as conn:
        conn.execute(
            "INSERT INTO ai_conversations (user_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (user_id, "user", "Old message", old_iso),
        )

    # Insert fresh conversation turn
    db.save_ai_message(user_id, "user", "Recent message")

    # Prune conversations older than 48 hours
    pruned = db.prune_ai_history(max_age_hours=48)
    assert pruned == 1

    remaining = db.get_ai_history(user_id)
    assert len(remaining) == 1
    assert remaining[0]["content"] == "Recent message"


def test_repositories_direct_usage(test_db_path: str):
    conn_mgr = ConnectionManager(test_db_path)
    db = Database(test_db_path)  # ensures tables created

    task_repo = TaskRepository(conn_mgr)
    task_dict = {
        "id": "direct_task_1",
        "platform": "edunex",
        "title": "Direct Repo Task",
        "due_date": "2026-10-20T23:59:00",
    }
    t, is_new = task_repo.upsert_task(task_dict)
    assert is_new is True
    assert t["id"] == "direct_task_1"

    meeting_repo = MeetingRepository(conn_mgr)
    m, m_new, _ = meeting_repo.upsert_lecture_meeting({
        "id": "direct_m1",
        "meeting_date": "2026-10-15",
        "course_code": "IF5150",
        "course_name": "Sistem Terdistribusi",
        "start_time": "07:00",
        "end_time": "09:00",
    })
    assert m_new is True
    fetched_m = meeting_repo.get_lecture_meeting("2026-10-15", "IF5150")
    assert fetched_m is not None
    assert fetched_m["course_name"] == "Sistem Terdistribusi"

    alert_repo = AlertRepository(conn_mgr)
    assert alert_repo.is_gmail_processed("msg_999") is False
    alert_repo.record_gmail_message("msg_999", "Subj", "Sender", "Snip", "2026-10-11")
    assert alert_repo.is_gmail_processed("msg_999") is True
