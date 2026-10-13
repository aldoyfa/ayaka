"""SIX ITB Scraper & Data Fetcher.

Fetches academic schedules, exam dates (UTS/UAS), and announcements
from six.itb.ac.id using browser session cookies.
"""

from __future__ import annotations

import asyncio
import logging
import html as html_lib
import re
from datetime import date, datetime, timezone
from typing import Any, List, Optional, Union
import zoneinfo
from urllib.parse import urljoin
import httpx
from bs4 import BeautifulSoup

from ayaka.config import Config
from ayaka.core.time import parse_user_due_date
from ayaka.fetchers.base import BaseFetcher, SessionExpiredException, run_coro_sync

logger = logging.getLogger("ayaka.fetchers.six")


class SixFetcher(BaseFetcher):
    platform_name = "six"
    BASE_URL = "https://six.itb.ac.id"

    def __init__(self, config: Config):
        super().__init__(config)
        self.cookie = config.academic.six_cookie
        self.student_id = getattr(config.academic, "six_student_id", "")
        self.semester_code = getattr(config.academic, "six_semester_code", "2026-1")
        self.base_url = (
            config.academic.endpoints.six_base_url
            if hasattr(config.academic, "endpoints")
            else self.BASE_URL
        )

    def is_configured(self) -> bool:
        return bool(self.cookie)

    def _get_headers(self) -> dict[str, str]:
        c = self.cookie or ""
        if c and "=" not in c:
            c = f"khongguan={c}"
        return {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
            ),
            "Cookie": c,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

    def fetch_tasks(self) -> List[dict[str, Any]]:
        """Fetch exam schedules (UTS/UAS) synchronously (wrapper for fetch_tasks_async)."""
        return run_coro_sync(self.fetch_tasks_async())

    async def fetch_tasks_async(self) -> List[dict[str, Any]]:
        """Fetch exam schedules (UTS/UAS) asynchronously from SIX ITB."""
        if not self.is_configured():
            logger.info("SIX ITB cookie not configured. Skipping.")
            return []

        tasks: list[dict[str, Any]] = []
        headers = self._get_headers()

        async with httpx.AsyncClient(headers=headers, timeout=20.0, follow_redirects=True) as client:
            try:
                resp = await client.get(f"{self.BASE_URL}/ujian")
                if resp.status_code in (401, 403) or "login" in str(resp.url).lower():
                    self.session_valid = False
                    self.last_error = "Session cookie expired or redirected to login"
                    logger.warning("SIX ITB session expired! Please update SIX_COOKIE.")
                    raise SessionExpiredException("six", "Session cookie expired or redirected to login")

                if resp.status_code == 200:
                    exam_tasks = self._parse_exam_table(resp.text)
                    tasks.extend(exam_tasks)
                    self.session_valid = True
                    self.last_sync_time = datetime.now(timezone.utc)
            except SessionExpiredException:
                raise
            except Exception as e:
                logger.error(f"Error fetching exam schedules from SIX: {e}")

        return tasks

    def _parse_exam_table(self, html: str) -> List[dict[str, Any]]:
        """Parse exam schedule tables from SIX ITB."""
        soup = BeautifulSoup(html, "html.parser")
        tasks: list[dict[str, Any]] = []

        # Find tables with course and exam date columns
        tables = soup.find_all("table")
        for table in tables:
            rows = table.find_all("tr")
            for row in rows:
                cols = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
                if len(cols) < 4:
                    continue

                # Header detection
                if any("mata kuliah" in c.lower() or "kode" in c.lower() for c in cols):
                    continue

                # Typical columns: No | Kode | Nama MK | Kelas | Tanggal & Waktu | Ruang
                course_code = cols[1] if len(cols) > 1 else ""
                course_name = cols[2] if len(cols) > 2 else ""
                datetime_str = cols[4] if len(cols) > 4 else cols[3]

                if not course_code or not datetime_str:
                    continue

                # Never invent a deadline: a moving "now" resets reminder flags on every sync.
                due_dt = parse_user_due_date(datetime_str, self.config.timezone)
                task_id = f"six:exam:{re.sub(r'[^a-zA-Z0-9]', '', course_code).lower()}"
                tasks.append({
                    "id": task_id,
                    "platform": "six",
                    "course_id": course_code,
                    "course_name": course_name,
                    "title": f"Exam: {course_name} ({course_code})",
                    "description": f"Exam schedule from SIX ITB. Room / Info: {' '.join(cols[3:])}",
                    "due_date": due_dt.isoformat() if due_dt else "",
                    "url": f"{self.BASE_URL}/ujian",
                })

        return tasks

    def parse_modal_details(self, html: str) -> dict[str, str]:
        """Parse modal detail HTML from /kelas/pertemuan/<id>/mhs/<id>."""
        soup = BeautifulSoup(html, "html.parser")
        dl = soup.find("dl")
        data = {
            "activity_type": "",
            "lecturer": "",
            "edunex_url": "",
            "teams_url": "",
            "topic": "",
            "notes": "",
            "attendance_window": "",
        }
        if dl:
            curr_key = None
            for elem in dl.find_all(["dt", "dd"]):
                if elem.name == "dt":
                    text = re.sub(r"\s+", " ", elem.get_text(" ", strip=True)).strip()
                    curr_key = text.lower()
                    if any(w in curr_key for w in ("kuliah", "uts", "uas", "praktikum")):
                        data["activity_type"] = text
                elif elem.name == "dd" and curr_key:
                    txt = elem.get_text(" ", strip=True)
                    if "dosen" in curr_key:
                        data["lecturer"] = txt
                    elif "topik" in curr_key:
                        if txt != "-":
                            data["topic"] = txt
                    elif "catatan" in curr_key:
                        if txt != "-":
                            data["notes"] = txt
                    elif "link" in curr_key:
                        for a in elem.find_all("a"):
                            href = urljoin(self.BASE_URL + "/", a.get("href", "").strip())
                            if not href.lower().startswith(("http://", "https://")):
                                continue
                            a_txt = a.get_text(" ", strip=True).lower()
                            if "edunex" in a_txt or "edunex" in href.lower():
                                data["edunex_url"] = href
                            elif "teams" in a_txt or "teams" in href.lower():
                                data["teams_url"] = href

        for line in html.splitlines():
            line = line.strip()
            if "presensi" in line.lower():
                text = html_lib.unescape(re.sub(r"<[^>]+>", " ", line))
                text = re.sub(r"\s+", " ", text).strip()
                # Minified pages put everything on one line; keep a bounded window around the keyword.
                pos = text.lower().find("presensi")
                start = max(0, pos - 40)
                data["attendance_window"] = text[start:start + 200].strip()
                break

        return data

    def fetch_lecture_meetings(
        self,
        fetch_modals: bool = True,
        future_only: bool = True,
        from_date: Optional[Union[date, str]] = None,
    ) -> List[dict[str, Any]]:
        """Scrape lecture schedule calendar synchronously (wrapper for fetch_lecture_meetings_async)."""
        return run_coro_sync(
            self.fetch_lecture_meetings_async(
                fetch_modals=fetch_modals,
                future_only=future_only,
                from_date=from_date,
            )
        )

    async def fetch_lecture_meetings_async(
        self,
        fetch_modals: bool = True,
        future_only: bool = True,
        from_date: Optional[Union[date, str]] = None,
    ) -> List[dict[str, Any]]:
        """Scrape lecture schedule calendar from SIX ITB and fetch detailed meeting modals asynchronously."""
        if not self.is_configured():
            logger.info("SIX ITB cookie not configured. Skipping lecture schedule scrape.")
            return []

        if not self.student_id or not self.semester_code:
            logger.warning("SIX student_id/semester_code not configured; skipping lecture schedule scrape.")
            return []

        headers = self._get_headers()
        schedule_url = f"{self.BASE_URL}/app/mahasiswa:{self.student_id}+{self.semester_code}/kelas/jadwal/mahasiswa"

        meetings: list[dict[str, Any]] = []

        async with httpx.AsyncClient(headers=headers, timeout=25.0, follow_redirects=True) as client:
            try:
                resp = await client.get(schedule_url)
                if resp.status_code in (401, 403) or "login" in str(resp.url).lower():
                    self.session_valid = False
                    logger.warning("SIX ITB session expired when accessing schedule calendar.")
                    raise SessionExpiredException("six", "Session cookie expired or redirected to login")

                if resp.status_code != 200:
                    logger.warning(f"Failed to fetch SIX schedule calendar: HTTP {resp.status_code}")
                    return []

                self.session_valid = True
                self.last_sync_time = datetime.now(timezone.utc)
                soup = BeautifulSoup(resp.text, "html.parser")
                table = soup.find("table", class_="table-bordered")
                if not table:
                    return []

                rows = table.find_all("tr")
                months = {
                    "januari": 1, "februari": 2, "maret": 3, "april": 4, "mei": 5, "juni": 6,
                    "juli": 7, "agustus": 8, "september": 9, "oktober": 10, "november": 11, "desember": 12
                }
                try:
                    local_now = datetime.now(zoneinfo.ZoneInfo(getattr(self.config, "timezone", "Asia/Jakarta")))
                except Exception:
                    local_now = datetime.now(timezone.utc)
                # Fallbacks only: cells normally carry "<day> <month> <year>".
                current_month = local_now.month
                try:
                    current_year = int(self.semester_code.split("-")[0])
                    if self.semester_code.split("-")[1].strip() == "2":
                        current_year += 1  # even semester runs Jan-Jun of the following year
                except Exception:
                    current_year = local_now.year

                for r in rows[1:]:
                    for td in r.find_all("td"):
                        first_div = td.find("div")
                        if not first_div:
                            continue
                        parts = first_div.get_text(" ", strip=True).split()
                        if not parts:
                            continue
                        try:
                            day_num = int(parts[0])
                        except ValueError:
                            continue
                        if len(parts) > 1 and parts[1].lower() in months:
                            new_month = months[parts[1].lower()]
                            if len(parts) > 2 and parts[2].isdigit() and len(parts[2]) == 4:
                                current_year = int(parts[2])
                            elif new_month < current_month:
                                current_year += 1  # no explicit year and the month wrapped (Dec -> Jan)
                            current_month = new_month
                        if not 1 <= day_num <= 31:
                            continue

                        date_str = f"{current_year:04d}-{current_month:02d}-{day_num:02d}"

                        for a in td.find_all("a", class_="linkpertemuan"):
                            full_text = a.get_text(" ", strip=True)
                            url = a.get("data-url", "")
                            kuliah = a.get("data-kuliah", "").strip()

                            code_match = re.match(r"^([A-Z0-9]{5,8})\s*(.*)", kuliah)
                            if code_match:
                                course_code = code_match.group(1).strip()
                                course_name = code_match.group(2).strip()
                            else:
                                course_code = kuliah[:6].strip()
                                course_name = kuliah[6:].strip()

                            time_match = re.search(r"([0-9]{2}:[0-9]{2})-([0-9]{2}:[0-9]{2})", full_text)
                            st = time_match.group(1) if time_match else ""
                            et = time_match.group(2) if time_match else ""

                            room_match = re.search(r"\(([^)]+)\)", full_text)
                            type_and_room = room_match.group(1).strip() if room_match else ""
                            parts_tr = type_and_room.split(None, 1)
                            act_type = parts_tr[0] if parts_tr else "Kuliah"
                            room = parts_tr[1] if len(parts_tr) > 1 else ""

                            pid_match = re.search(r"/pertemuan/([0-9]+)/", url)
                            pid = pid_match.group(1) if pid_match else ""
                            if not pid:
                                # Stable fallback so meetings without a numeric id don't overwrite each other
                                pid = "x" + re.sub(r"[^a-z0-9]", "", f"{date_str}{course_code}{st}".lower())

                            clean_durl = url.split("?returnTo=")[0]
                            if clean_durl.startswith("/"):
                                clean_durl = f"{self.BASE_URL}{clean_durl}"

                            meeting_item = {
                                "id": f"six:meeting:{pid}",
                                "meeting_date": date_str,
                                "course_code": course_code,
                                "course_name": course_name,
                                "start_time": st,
                                "end_time": et,
                                "activity_type": act_type,
                                "room": room,
                                "lecturer": "",
                                "topic": "",
                                "notes": "",
                                "edunex_url": "",
                                "teams_url": "",
                                "attendance_window": "",
                                "detail_url": clean_durl,
                            }
                            meetings.append(meeting_item)

                if future_only:
                    try:
                        tz = zoneinfo.ZoneInfo(getattr(self.config, "timezone", "Asia/Jakarta"))
                    except Exception:
                        tz = timezone.utc

                    if from_date:
                        cutoff = from_date if isinstance(from_date, str) else from_date.strftime("%Y-%m-%d")
                    else:
                        cutoff = datetime.now(tz).strftime("%Y-%m-%d")

                    meetings = [m for m in meetings if m.get("meeting_date", "") >= cutoff]
                    logger.info(
                        f"Filtered lecture meetings to {len(meetings)} upcoming sessions (on/after {cutoff})."
                    )

                if fetch_modals:
                    sem = asyncio.Semaphore(8)

                    async def _fetch_modal(m: dict[str, Any]) -> None:
                        d_url = m.get("detail_url")
                        if not d_url:
                            return
                        full_modal_url = self.BASE_URL + d_url if d_url.startswith("/") else d_url
                        async with sem:
                            try:
                                m_resp = await client.get(full_modal_url, timeout=10.0)
                                if m_resp.status_code == 200:
                                    modal_data = self.parse_modal_details(m_resp.text)
                                    if modal_data.get("activity_type"):
                                        m["activity_type"] = modal_data["activity_type"]
                                    if modal_data.get("lecturer"):
                                        m["lecturer"] = modal_data["lecturer"]
                                    if modal_data.get("topic"):
                                        m["topic"] = modal_data["topic"]
                                    if modal_data.get("notes"):
                                        m["notes"] = modal_data["notes"]
                                    if modal_data.get("edunex_url"):
                                        m["edunex_url"] = modal_data["edunex_url"]
                                    if modal_data.get("teams_url"):
                                        m["teams_url"] = modal_data["teams_url"]
                                    if modal_data.get("attendance_window"):
                                        m["attendance_window"] = modal_data["attendance_window"]
                            except Exception as me:
                                logger.debug(f"Failed to fetch modal for {m.get('id')}: {me}")

                    await asyncio.gather(*[_fetch_modal(m) for m in meetings])

            except SessionExpiredException:
                raise
            except Exception as e:
                logger.error(f"Error fetching lecture meetings from SIX: {e}")

        return meetings

