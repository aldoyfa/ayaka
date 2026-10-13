"""Omnicampus Data Fetcher.

Fetches course activities, assignments, reports, and questionnaires from edu.omnicamp.us
using Bearer token or session cookies.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, List
import httpx

from ayaka.config import Config
from ayaka.fetchers.base import AcademicTask, BaseFetcher, SessionExpiredException, run_coro_sync
from ayaka.task_filters import TaskFilters

logger = logging.getLogger("ayaka.fetchers.omnicampus")


class OmnicampusFetcher(BaseFetcher):
    platform_name = "omnicampus"
    BASE_URL = "https://edu.omnicamp.us"

    def __init__(self, config: Config):
        super().__init__(config)
        self.token = config.academic.omnicampus_token
        self.cookie = config.academic.omnicampus_cookie
        self.course_ids = getattr(config.academic, "omnicampus_course_ids", [170])
        self.base_url = (
            config.academic.endpoints.omnicampus_base_url
            if hasattr(config.academic, "endpoints")
            else self.BASE_URL
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.token or self.cookie)

    def _get_headers(self) -> dict[str, str]:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
        }
        if self.token:
            clean_token = self.token.replace("Bearer ", "").strip()
            headers["Authorization"] = f"Bearer {clean_token}"
            headers["X-Auth-Token"] = f"Bearer {clean_token}"
        if self.cookie:
            headers["Cookie"] = self.cookie if "=" in self.cookie else f"appSession={self.cookie}"
        return headers

    def fetch_tasks(self) -> List[AcademicTask]:
        """Fetch tasks synchronously (wrapper for fetch_tasks_async)."""
        return run_coro_sync(self.fetch_tasks_async())

    async def fetch_tasks_async(self) -> List[AcademicTask]:
        """Fetch tasks, reports, and questionnaires from Omnicampus API asynchronously."""
        if not self.is_configured:
            logger.info("Omnicampus token/cookie not configured. Skipping.")
            return []

        headers = self._get_headers()
        filters = TaskFilters.load_from_file(self.config.task_filters_file)

        async with httpx.AsyncClient(headers=headers, timeout=20.0, follow_redirects=True) as client:
            async def _fetch_course_data(cid: int) -> list[AcademicTask]:
                course_tasks: list[AcademicTask] = []
                course_name = f"Course {cid}"

                # 1. Course Metadata
                try:
                    c_resp = await client.get(f"{self.base_url}/api/v3/courses/{cid}")
                    if c_resp.status_code == 200:
                        course_name = c_resp.json().get("name", course_name)
                    elif c_resp.status_code in (401, 403):
                        raise SessionExpiredException("omnicampus", f"HTTP {c_resp.status_code}")
                except SessionExpiredException:
                    raise
                except Exception as e:
                    logger.debug(f"Error fetching course {cid} metadata: {e}")

                # 2. Homework / Assignments
                try:
                    a_resp = await client.get(f"{self.base_url}/api/v6/student/courses/{cid}/assignments")
                    if a_resp.status_code == 200:
                        assignments = a_resp.json().get("assignments", [])
                        for item in assignments:
                            aid = str(item.get("assignmentId", ""))
                            if not aid:
                                continue
                            due = item.get("dueDate")
                            if not due:
                                continue
                            title = item.get("title", f"Homework {aid}")
                            if filters.is_task_blacklisted(task_id=aid, title=title):
                                logger.info(f"Omnicampus assignment {aid} ({title}) is blacklisted. Skipping.")
                                continue
                            is_submitted = bool(item.get("submittedAtLeastOnce", False))
                            course_tasks.append(
                                AcademicTask(
                                    id=f"omnicampus:assignment:{aid}",
                                    platform="omnicampus",
                                    course_id=str(cid),
                                    course_name=course_name,
                                    title=title,
                                    description="Omnicampus Course Assignment / Homework",
                                    due_date=due,
                                    url=f"{self.base_url}/en/courses/{cid}/assignments/{aid}/",
                                    is_completed=1 if is_submitted else 0,
                                )
                            )
                    elif a_resp.status_code in (401, 403):
                        raise SessionExpiredException("omnicampus", f"HTTP {a_resp.status_code}")
                except SessionExpiredException:
                    raise
                except Exception as e:
                    logger.debug(f"Error fetching assignments for course {cid}: {e}")

                # 3. Reports
                try:
                    r_resp = await client.get(f"{self.base_url}/api/v4/courses/{cid}/user-reports")
                    if r_resp.status_code == 200:
                        reports_data = r_resp.json()
                        if isinstance(reports_data, list):
                            for r_item in reports_data:
                                rep = r_item.get("report", {})
                                rid = str(rep.get("id", ""))
                                if not rid:
                                    continue
                                due = rep.get("endAt")
                                if not due:
                                    continue
                                title = rep.get("displayName", f"Report {rid}")
                                if filters.is_task_blacklisted(task_id=rid, title=title):
                                    logger.info(f"Omnicampus report {rid} ({title}) is blacklisted. Skipping.")
                                    continue
                                is_submitted = bool(r_item.get("submittedAt"))
                                course_tasks.append(
                                    AcademicTask(
                                        id=f"omnicampus:report:{rid}",
                                        platform="omnicampus",
                                        course_id=str(cid),
                                        course_name=course_name,
                                        title=title,
                                        description=rep.get("description", "Course Final Report"),
                                        due_date=due,
                                        url=f"{self.base_url}/en/courses/{cid}/reports/{rid}/",
                                        is_completed=1 if is_submitted else 0,
                                    )
                                )
                    elif r_resp.status_code in (401, 403):
                        raise SessionExpiredException("omnicampus", f"HTTP {r_resp.status_code}")
                except SessionExpiredException:
                    raise
                except Exception as e:
                    logger.debug(f"Error fetching reports for course {cid}: {e}")

                # 4. Questionnaires
                try:
                    q_resp = await client.get(f"{self.base_url}/api/v4/courses/{cid}/user-questionnaires")
                    if q_resp.status_code == 200:
                        q_data = q_resp.json()
                        if isinstance(q_data, list):
                            for q_item in q_data:
                                qid = str(q_item.get("questionnaireId", ""))
                                if not qid:
                                    continue
                                due = q_item.get("endAt")
                                if not due:
                                    continue
                                title = f"Questionnaire: {q_item.get('displayName', qid)}"
                                if filters.is_task_blacklisted(task_id=qid, title=title):
                                    logger.info(f"Omnicampus questionnaire {qid} ({title}) is blacklisted. Skipping.")
                                    continue
                                is_answered = bool(q_item.get("answers"))
                                course_tasks.append(
                                    AcademicTask(
                                        id=f"omnicampus:questionnaire:{qid}",
                                        platform="omnicampus",
                                        course_id=str(cid),
                                        course_name=course_name,
                                        title=title,
                                        description="Session Attendance & Feedback Questionnaire",
                                        due_date=due,
                                        url=f"{self.base_url}/en/courses/{cid}/questionnaires/{qid}/",
                                        is_completed=1 if is_answered else 0,
                                    )
                                )
                    elif q_resp.status_code in (401, 403):
                        raise SessionExpiredException("omnicampus", f"HTTP {q_resp.status_code}")
                except SessionExpiredException:
                    raise
                except Exception as e:
                    logger.debug(f"Error fetching questionnaires for course {cid}: {e}")

                return course_tasks

            results = await asyncio.gather(*[_fetch_course_data(cid) for cid in self.course_ids])
            all_tasks: list[AcademicTask] = []
            for r in results:
                all_tasks.extend(r)
            return all_tasks
