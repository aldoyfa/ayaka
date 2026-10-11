"""Edunex ITB Scraper & API Fetcher.

Fetches active courses, assignments, quizzes, and submission deadlines
from api-edunex.cognisia.id using browser session cookies or bearer tokens.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, List, Optional
import zoneinfo
import httpx
from bs4 import BeautifulSoup

from ayaka.config import Config
from ayaka.fetchers.base import BaseFetcher, SessionExpiredException, run_coro_sync
from ayaka.task_filters import TaskFilters

logger = logging.getLogger("ayaka.fetchers.edunex")


class EdunexFetcher(BaseFetcher):
    platform_name = "edunex"
    BASE_WEB_URL = "https://edunex.itb.ac.id"
    BASE_API_URL = "https://api-edunex.cognisia.id"

    def __init__(self, config: Config):
        super().__init__(config)
        self.cookie = config.academic.edunex_cookie
        self.bearer = config.academic.edunex_bearer_token
        self.period_id = getattr(config.academic, "edunex_period_id", 26)
        self.base_url = (
            config.academic.endpoints.edunex_base_url
            if hasattr(config.academic, "endpoints")
            else self.BASE_WEB_URL
        )

    def _get_headers(self) -> dict[str, str]:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/html, */*",
        }
        if self.cookie:
            headers["Cookie"] = self.cookie
        if self.bearer:
            headers["Authorization"] = f"Bearer {self.bearer}"
        return headers

    def is_configured(self) -> bool:
        return bool(self.cookie or self.bearer)

    def fetch_tasks(self) -> List[dict[str, Any]]:
        """Fetch active/open assignments synchronously (wrapper for fetch_tasks_async)."""
        return run_coro_sync(self.fetch_tasks_async())

    async def fetch_tasks_async(self) -> List[dict[str, Any]]:
        """Fetch active/open assignments asynchronously according to rules in task_filters.json."""
        if not self.is_configured():
            logger.info("Edunex cookie/bearer not configured. Skipping.")
            return []

        filters = TaskFilters.load_from_file(self.config.task_filters_file)
        headers = self._get_headers()

        try:
            tz = zoneinfo.ZoneInfo(self.config.timezone)
        except Exception:
            tz = timezone.utc

        now = datetime.now(tz)
        sem = asyncio.Semaphore(10)

        async with httpx.AsyncClient(headers=headers, timeout=20.0, follow_redirects=True) as client:
            courses_to_scan: list[tuple[int, str, str]] = []
            for c in filters.courses:
                try:
                    courses_to_scan.append((int(c["id"]), str(c.get("code", "")), str(c.get("name", ""))))
                except (KeyError, ValueError, TypeError):
                    pass

            # Discover additional courses dynamically for configured period_id
            try:
                r_courses = await client.get(f"{self.BASE_API_URL}/course/courses?filter[period_id][is]={self.period_id}&limit=100")
                if r_courses.status_code in (401, 403):
                    self.session_valid = False
                    self.last_error = f"HTTP {r_courses.status_code} Unauthorized"
                    raise SessionExpiredException("edunex", f"HTTP {r_courses.status_code} - session cookie expired")

                if r_courses.status_code == 200:
                    data = r_courses.json().get("data", [])
                    known_cids = {c[0] for c in courses_to_scan}
                    for item in data:
                        cid = int(item.get("id"))
                        if cid not in known_cids:
                            attr = item.get("attributes", {})
                            code = attr.get("code", "")
                            name = attr.get("name", "")
                            if code.startswith(("IF", "II")) and not filters.is_task_blacklisted(0, course_code=code):
                                courses_to_scan.append((cid, code, name))
                                known_cids.add(cid)
            except SessionExpiredException:
                raise
            except Exception as e:
                logger.debug(f"Dynamic course discovery skipped: {e}")

            # Fetch tasks concurrently across all courses
            async def _fetch_course_tasks(cid: int, code: str, course_name: str) -> list[dict[str, Any]]:
                if filters.is_task_blacklisted(0, course_code=code):
                    return []

                course_tasks: list[dict[str, Any]] = []
                async with sem:
                    try:
                        r_tasks = await client.get(f"{self.BASE_API_URL}/course/tasks?filter[course_id][is]={cid}&limit=100")
                        if r_tasks.status_code != 200:
                            return []
                        items = r_tasks.json().get("data", [])
                    except Exception as err:
                        logger.error(f"Error fetching tasks for course {code} ({cid}): {err}")
                        return []

                # Detail fetcher for individual task
                async def _fetch_task_detail(item: dict[str, Any]) -> Optional[dict[str, Any]]:
                    tid_raw = item.get("id")
                    if not tid_raw:
                        return None
                    tid = int(tid_raw)

                    attr = item.get("attributes", {})
                    async with sem:
                        try:
                            r_det = await client.get(f"{self.BASE_API_URL}/course/tasks/{tid}", timeout=10.0)
                            if r_det.status_code == 200:
                                attr = r_det.json().get("data", {}).get("attributes", {})
                        except Exception:
                            pass

                    name = attr.get("name", "Unnamed Task")
                    end_at_str = attr.get("end_at")
                    open_status = attr.get("open_status", "unknown")
                    is_lateable = bool(attr.get("is_lateable", False))
                    answers = attr.get("answers", [])
                    has_submitted = len(answers) > 0

                    if filters.is_task_blacklisted(task_id=tid, title=name, course_code=code):
                        logger.info(f"Task {tid} ({name}) is blacklisted. Skipping.")
                        return None

                    due_dt = None
                    if end_at_str:
                        try:
                            due_dt = datetime.fromisoformat(end_at_str)
                            if due_dt.tzinfo is None:
                                due_dt = due_dt.replace(tzinfo=tz)
                        except Exception:
                            due_dt = None

                    raw_desc = attr.get("description", "") or ""
                    clean_desc = ""
                    if raw_desc:
                        soup = BeautifulSoup(raw_desc, "html.parser")
                        clean_desc = soup.get_text(separator=" ").strip()

                    if has_submitted:
                        max_past_days = filters.criteria.max_past_deadline_days
                        is_recent = True
                        if due_dt and max_past_days > 0:
                            if (now - due_dt) > timedelta(days=max_past_days):
                                is_recent = False

                        if is_recent:
                            return {
                                "id": f"edunex:task:{tid}",
                                "platform": "edunex",
                                "course_id": code,
                                "course_name": course_name,
                                "title": name,
                                "description": clean_desc,
                                "due_date": due_dt.isoformat() if due_dt else "",
                                "url": f"{self.BASE_WEB_URL}/courses/{cid}",
                                "is_completed": 1,
                            }
                    elif filters.should_include_task(
                        due_dt=due_dt,
                        now=now,
                        open_status=open_status,
                        is_lateable=is_lateable,
                        has_submitted=False,
                    ):
                        return {
                            "id": f"edunex:task:{tid}",
                            "platform": "edunex",
                            "course_id": code,
                            "course_name": course_name,
                            "title": name,
                            "description": clean_desc,
                            "due_date": due_dt.isoformat() if due_dt else "",
                            "url": f"{self.BASE_WEB_URL}/courses/{cid}",
                            "is_completed": 0,
                        }
                    return None

                task_results = await asyncio.gather(*[_fetch_task_detail(it) for it in items])
                for res in task_results:
                    if res:
                        course_tasks.append(res)
                return course_tasks

            course_results = await asyncio.gather(
                *[_fetch_course_tasks(cid, code, cname) for cid, code, cname in courses_to_scan]
            )

            all_tasks: list[dict[str, Any]] = []
            seen_ids = set()
            for cr in course_results:
                for t in cr:
                    tid = t["id"]
                    if tid not in seen_ids:
                        seen_ids.add(tid)
                        all_tasks.append(t)

        all_tasks.sort(key=lambda t: t.get("due_date") or "9999-12-31")
        return all_tasks

