"""Unit tests for Phase 4 Async Fetchers and Concurrency."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from ayaka.config import Config
from ayaka.fetchers.base import AcademicTask, SessionExpiredException
from ayaka.fetchers.edunex import EdunexFetcher
from ayaka.fetchers.six import SixFetcher
from ayaka.fetchers.omnicampus import OmnicampusFetcher
from ayaka.scheduler import run_sync_cycle_async
from ayaka.storage.db import Database


@pytest.mark.anyio
async def test_edunex_fetcher_async(monkeypatch):
    config = Config.load()
    config.academic.edunex_cookie = "test_cookie"
    config.academic.edunex_period_id = 99
    fetcher = EdunexFetcher(config)
    assert fetcher.period_id == 99

    courses_response = {
        "data": [
            {
                "id": 1001,
                "attributes": {"code": "IF5152", "name": "Visi Komputer"},
            }
        ]
    }
    tasks_response = {
        "data": [
            {
                "id": 5001,
                "attributes": {
                    "name": "Tugas 1 Segmentasi",
                    "end_at": "2026-10-20T23:59:00+07:00",
                    "open_status": "open",
                    "is_lateable": False,
                    "answers": [],
                },
            }
        ]
    }

    async def mock_get(url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        if "courses" in url:
            resp.json.return_value = courses_response
        elif "tasks/5001" in url:
            resp.json.return_value = {"data": tasks_response["data"][0]}
        elif "course_id][is]=1001" in url:
            resp.json.return_value = tasks_response
        else:
            resp.json.return_value = {"data": []}
        return resp

    with patch("httpx.AsyncClient.get", side_effect=mock_get):
        tasks = await fetcher.fetch_tasks_async()
        assert len(tasks) >= 1
        assert any(t["id"] == "edunex:task:5001" for t in tasks)
        target = next(t for t in tasks if t["id"] == "edunex:task:5001")
        assert target["title"] == "Tugas 1 Segmentasi"
        assert target["course_id"] == "IF5152"


@pytest.mark.anyio
async def test_six_fetcher_async_dynamic_config():
    config = Config.load()
    config.academic.six_cookie = "test_cookie"
    config.academic.six_student_id = "13521099"
    config.academic.six_semester_code = "2027-1"
    fetcher = SixFetcher(config)

    assert fetcher.student_id == "13521099"
    assert fetcher.semester_code == "2027-1"

    calendar_html = """
    <table class="table-bordered">
        <tr><th>Senin</th></tr>
        <tr>
            <td>
                <div>15 Oktober 2027</div>
                <a class="linkpertemuan" data-url="/kelas/pertemuan/999/mhs/1" data-kuliah="IF5152 Visi Komputer">
                    (Kuliah 7609) 09:00-11:00
                </a>
            </td>
        </tr>
    </table>
    """
    modal_html = """
    <dl>
        <dt>Kuliah Tatap Muka</dt>
        <dt>Dosen Pengampu</dt>
        <dd>Dr. Jane Doe</dd>
        <dt>Topik Materi</dt>
        <dd>Object Detection</dd>
    </dl>
    """

    async def mock_get(url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        if "jadwal" in url:
            resp.text = calendar_html
        elif "pertemuan" in url:
            resp.text = modal_html
        else:
            resp.text = ""
        return resp

    with patch("httpx.AsyncClient.get", side_effect=mock_get):
        meetings = await fetcher.fetch_lecture_meetings_async(fetch_modals=True, future_only=False)
        assert len(meetings) == 1
        m = meetings[0]
        assert m["id"] == "six:meeting:999"
        assert m["meeting_date"] == "2027-10-15"
        assert m["lecturer"] == "Dr. Jane Doe"
        assert m["topic"] == "Object Detection"


@pytest.mark.anyio
async def test_omnicampus_fetcher_async_dynamic_courses():
    config = Config.load()
    config.academic.omnicampus_token = "valid_token"
    config.academic.omnicampus_course_ids = [201, 202]
    fetcher = OmnicampusFetcher(config)

    assert fetcher.course_ids == [201, 202]

    async def mock_get(url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        if "assignments" in url:
            resp.json.return_value = {
                "assignments": [
                    {
                        "assignmentId": "301",
                        "title": "HW 1 Deep Learning",
                        "dueDate": "2026-11-01T23:59:00Z",
                        "submittedAtLeastOnce": False,
                    }
                ]
            }
        elif "user-reports" in url:
            resp.json.return_value = []
        elif "user-questionnaires" in url:
            resp.json.return_value = []
        else:
            resp.json.return_value = {"name": "Test Omnicampus Course"}
        return resp

    with patch("httpx.AsyncClient.get", side_effect=mock_get):
        tasks = await fetcher.fetch_tasks_async()
        # 2 courses * 1 assignment each = 2 tasks
        assert len(tasks) == 2
        assert all(isinstance(t, AcademicTask) for t in tasks)
        assert tasks[0].title == "HW 1 Deep Learning"


@pytest.mark.anyio
async def test_run_sync_cycle_async_orchestration(tmp_path):
    db_file = tmp_path / "test_async_sync.db"
    db = Database(str(db_file))

    config = Config.load()
    config.academic.edunex_cookie = "test_cookie"
    config.academic.six_cookie = "test_cookie"
    config.academic.omnicampus_token = "test_token"

    mock_edunex_task = {
        "id": "edunex:task:1",
        "platform": "edunex",
        "course_id": "IF5152",
        "course_name": "Visi Komputer",
        "title": "Tugas Asinkron Edunex",
        "due_date": "2026-10-30T23:59:00",
        "is_completed": 0,
    }
    mock_six_meeting = {
        "id": "six:meeting:2",
        "meeting_date": "2026-10-30",
        "course_code": "IF5152",
        "course_name": "Visi Komputer",
        "start_time": "09:00",
        "end_time": "11:00",
        "topic": "Neural Radiance Fields",
    }

    with patch("ayaka.fetchers.edunex.EdunexFetcher.fetch_tasks_async", new_callable=AsyncMock) as m_edu, \
         patch("ayaka.fetchers.six.SixFetcher.fetch_tasks_async", new_callable=AsyncMock) as m_six_t, \
         patch("ayaka.fetchers.six.SixFetcher.fetch_lecture_meetings_async", new_callable=AsyncMock) as m_six_m, \
         patch("ayaka.fetchers.omnicampus.OmnicampusFetcher.fetch_tasks_async", new_callable=AsyncMock) as m_omni:

        m_edu.return_value = [mock_edunex_task]
        m_six_t.return_value = []
        m_six_m.return_value = [mock_six_meeting]
        m_omni.return_value = []

        stats = await run_sync_cycle_async(config, db, platform="all")

        assert stats["new_tasks"] == 1
        assert len(stats["added_items"]) == 1
        assert stats["added_items"][0]["id"] == "edunex:task:1"

        # Verify DB persisted the meeting
        meeting = db.get_lecture_meeting("2026-10-30", course_code="IF5152")
        assert meeting is not None
        assert meeting["topic"] == "Neural Radiance Fields"
