import pytest
from datetime import datetime, timedelta
import zoneinfo

from ayaka.config import Config
from ayaka.storage.db import Database
from ayaka.services.ai_agent import AIAgent, parse_natural_due_date


@pytest.fixture
def test_db(tmp_path):
    db_file = tmp_path / "test_ayaka.db"
    return Database(str(db_file))


@pytest.fixture
def test_config(tmp_path):
    config = Config.load()
    config.database_path = str(tmp_path / "test_ayaka.db")
    return config


def test_parse_natural_due_date():
    tz = zoneinfo.ZoneInfo("Asia/Jakarta")
    now = datetime.now(tz)

    # 1. "besok malam"
    dt1 = parse_natural_due_date("besok malam", tz_name="Asia/Jakarta")
    assert dt1.date() == (now + timedelta(days=1)).date()
    assert dt1.hour == 23 and dt1.minute == 59

    # 2. "lusa jam 14:30"
    dt2 = parse_natural_due_date("lusa jam 14:30", tz_name="Asia/Jakarta")
    assert dt2.date() == (now + timedelta(days=2)).date()
    assert dt2.hour == 14 and dt2.minute == 30

    # 3. Explicit date "2026-11-20 09:00"
    dt3 = parse_natural_due_date("2026-11-20 09:00", tz_name="Asia/Jakarta")
    assert dt3.year == 2026 and dt3.month == 11 and dt3.day == 20
    assert dt3.hour == 9 and dt3.minute == 0


def test_ai_agent_tool_lifecycle(test_config, test_db):
    agent = AIAgent(config=test_config, db=test_db)

    # 1. Add Task
    add_res = agent._execute_tool(
        "add_task",
        {
            "title": "Tugas Paper NLP",
            "due_date": "besok malam",
            "course_id": "IF5153",
            "description": "Resume chapter 4",
        },
    )
    assert "Successfully added task" in add_res
    assert "Tugas Paper NLP" in add_res

    # 2. List Tasks
    list_res = agent._execute_tool("list_tasks", {"status": "pending", "search": "NLP"})
    assert "Tugas Paper NLP" in list_res

    # 3. Complete Task
    comp_res = agent._execute_tool("complete_task", {"task_query": "Paper NLP"})
    assert "Completed 'Tugas Paper NLP'" in comp_res

    # Verify in DB
    tasks = test_db.list_tasks(include_completed=True)
    assert len(tasks) == 1
    assert tasks[0]["is_completed"] == 1

    # 4. Delete Task
    del_res = agent._execute_tool("delete_task", {"task_query": "Paper NLP"})
    assert "Deleted task 'Tugas Paper NLP'" in del_res

    # Verify deleted in DB
    remaining = test_db.list_tasks(include_completed=True)
    assert len(remaining) == 0


def test_delete_task_exact_title_priority(test_config, test_db):
    agent = AIAgent(config=test_config, db=test_db)

    # Add two similar tasks
    agent._execute_tool("add_task", {"title": "HW1 for Session2", "due_date": "2026-10-15"})
    agent._execute_tool("add_task", {"title": "Late Submission HW1 for Session2", "due_date": "2026-10-20"})

    tasks_before = test_db.list_tasks(include_completed=True)
    assert len(tasks_before) == 2

    # Delete only "HW1 for Session2"
    res = agent._execute_tool("delete_task", {"task_query": "HW1 for Session2"})
    assert "HW1 for Session2" in res

    # "Late Submission HW1 for Session2" MUST still exist!
    tasks_after = test_db.list_tasks(include_completed=True)
    assert len(tasks_after) == 1
    assert tasks_after[0]["title"] == "Late Submission HW1 for Session2"
