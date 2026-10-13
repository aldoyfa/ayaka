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


def test_ai_agent_system_prompt_reflects_config(test_config, test_db):
    test_config.reminders.lectures.advance_reminder_enabled = True
    test_config.reminders.lectures.advance_reminder_minutes_before = 15
    test_config.reminders.lectures.morning_briefing_hour = 6
    agent = AIAgent(config=test_config, db=test_db)
    prompt = agent._build_system_prompt()
    assert "Advance preparation reminder: sent 15 minutes before class begins" in prompt
    assert "Morning briefing: every morning at 06:00 WIB" in prompt


def test_ai_agent_clear_history(test_config, test_db):
    agent = AIAgent(config=test_config, db=test_db)
    user_id = "user_42"
    test_db.save_ai_message(user_id, "user", "Hello Ayaka")
    test_db.save_ai_message(user_id, "assistant", "Hello Master!")
    agent.histories[user_id] = [{"role": "user", "content": "Hello Ayaka"}]

    assert len(test_db.get_ai_history(user_id)) == 2
    assert user_id in agent.histories

    agent.clear_history(user_id)
    assert len(test_db.get_ai_history(user_id)) == 0
    assert user_id not in agent.histories


def test_ai_agent_system_prompt_language_rule(test_config, test_db):
    agent = AIAgent(config=test_config, db=test_db)
    prompt = agent._build_system_prompt()
    assert "Strict Language Matching" in prompt
    assert "You MUST ALWAYS respond in the EXACT SAME language as Master's MOST RECENT message." in prompt



def _seed(db, *titles):
    for i, title in enumerate(titles):
        db.upsert_task({
            "id": f"manual:{i:08d}x", "platform": "manual", "course_id": "IF1",
            "title": title, "due_date": "2026-12-01T10:00:00+07:00",
        })


@pytest.mark.parametrize("tool", ["delete_task", "complete_task"])
@pytest.mark.parametrize("query", ["", "   ", "a"])
def test_destructive_tools_reject_blank_or_tiny_query(test_config, test_db, tool, query):
    agent = AIAgent(config=test_config, db=test_db)
    _seed(test_db, "Alpha", "Beta")

    res = agent._execute_tool(tool, {"task_query": query})

    assert res.startswith("Error")
    tasks = test_db.list_tasks(include_completed=True)
    assert len(tasks) == 2 and not any(t["is_completed"] for t in tasks)


@pytest.mark.parametrize("tool", ["delete_task", "complete_task"])
def test_destructive_tools_refuse_ambiguous_match(test_config, test_db, tool):
    agent = AIAgent(config=test_config, db=test_db)
    _seed(test_db, "Report draft", "Report final")

    res = agent._execute_tool(tool, {"task_query": "report"})

    assert res.startswith("Error") and "matches 2 tasks" in res
    tasks = test_db.list_tasks(include_completed=True)
    assert len(tasks) == 2 and not any(t["is_completed"] for t in tasks)


def test_add_task_refuses_unparseable_due_date(test_config, test_db):
    agent = AIAgent(config=test_config, db=test_db)

    res = agent._execute_tool("add_task", {"title": "Report", "due_date": "whenever you like"})

    assert res.startswith("Error") and "whenever you like" in res
    assert test_db.list_tasks(include_completed=True) == []


def test_add_task_without_due_date_still_defaults(test_config, test_db):
    agent = AIAgent(config=test_config, db=test_db)
    res = agent._execute_tool("add_task", {"title": "Report"})
    assert "Successfully added task" in res
