"""Blocking SQLite/Google work must run off the Discord event loop thread."""

import threading
from unittest.mock import MagicMock, patch

import pytest

from ayaka.config import Config
from ayaka.storage.db import Database


class _FakeFetcher:
    def __init__(self, config):
        pass

    async def fetch_tasks_async(self):
        return [{
            "id": "edunex:task:1", "platform": "edunex", "course_id": "IF1",
            "title": "HW", "due_date": "2026-12-01T10:00:00+07:00",
        }]


@pytest.mark.anyio
async def test_sync_cycle_runs_google_and_db_in_worker_thread(tmp_path):
    from ayaka import scheduler

    main_thread = threading.get_ident()
    seen: dict[str, int] = {}

    google = MagicMock()
    google.sync_task.side_effect = lambda task: seen.__setitem__("google", threading.get_ident())

    db = Database(str(tmp_path / "loop.db"))
    real_upsert = db.upsert_task

    def spy_upsert(task):
        seen["db"] = threading.get_ident()
        return real_upsert(task)

    db.upsert_task = spy_upsert

    with patch.object(scheduler, "EdunexFetcher", _FakeFetcher), \
         patch.object(scheduler, "SixFetcher", _FakeFetcher), \
         patch.object(scheduler, "OmnicampusFetcher", _FakeFetcher):
        stats = await scheduler.run_sync_cycle_async(Config.load(), db, "edunex", google)

    assert stats["new_tasks"] == 1
    assert seen["google"] != main_thread
    assert seen["db"] != main_thread


@pytest.mark.anyio
async def test_ai_tools_run_in_worker_thread(tmp_path):
    from unittest.mock import AsyncMock
    from ayaka.services.ai_agent import AIAgent

    config = Config.load()
    config.ai.api_key = "k"
    agent = AIAgent(config, Database(str(tmp_path / "ai.db")))
    main_thread = threading.get_ident()
    seen = {}

    def fake_tool(name, args):
        seen["thread"] = threading.get_ident()
        return "ok"

    agent._execute_tool = fake_tool

    tool_resp = MagicMock(status_code=200)
    tool_resp.json.return_value = {"choices": [{"message": {"tool_calls": [
        {"id": "1", "function": {"name": "list_tasks", "arguments": "{}"}}]}}]}
    final_resp = MagicMock(status_code=200)
    final_resp.json.return_value = {"choices": [{"message": {"content": "done"}}]}

    with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=[tool_resp, final_resp])):
        reply = await agent.chat("1", "list my tasks")

    assert reply == "done"
    assert seen["thread"] != main_thread


def test_google_sync_calls_are_serialized(tmp_path):
    """Two threads must never be inside the Google client at the same time."""
    import time
    from concurrent.futures import ThreadPoolExecutor
    from ayaka.services.google_sync import GoogleSyncService

    svc = GoogleSyncService(Config.load(), Database(str(tmp_path / "g.db")))
    svc._calendar_service = MagicMock()
    svc._tasks_service = MagicMock()
    svc.db.upsert_task({"id": "t:1", "platform": "x", "title": "T", "due_date": "2026-12-01",
                        "google_tasks_task_id": "g1"})

    active = 0
    overlap = False

    def slow_patch(**kwargs):
        nonlocal active, overlap
        active += 1
        overlap = overlap or active > 1
        time.sleep(0.05)
        active -= 1
        return MagicMock()

    svc._tasks_service.tasks.return_value.patch.side_effect = slow_patch

    with ThreadPoolExecutor(4) as pool:
        list(pool.map(lambda _: svc.mark_completed_in_google("t:1"), range(4)))

    assert overlap is False


def test_overlapping_syncs_do_not_duplicate_google_task(tmp_path):
    """Two syncs holding the same stale (ID-less) row must insert once, then patch."""
    from concurrent.futures import ThreadPoolExecutor
    from ayaka.services.google_sync import GoogleSyncService

    svc = GoogleSyncService(Config.load(), Database(str(tmp_path / "g.db")))
    svc._calendar_service = MagicMock()
    svc.config.google.sync_calendar = False
    tasks_api = MagicMock()
    tasks_api.tasks().insert().execute.return_value = {"id": "g-new"}
    tasks_api.tasks().patch().execute.return_value = {"id": "g-new"}
    tasks_api.reset_mock()
    svc._tasks_service = tasks_api

    stale, _ = svc.db.upsert_task({"id": "t:1", "platform": "x", "title": "T", "due_date": "2026-12-01"})
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(svc.sync_task, [dict(stale), dict(stale)]))

    assert tasks_api.tasks().insert.call_count == 1
    assert svc.db.get_task("t:1")["google_tasks_task_id"] == "g-new"
