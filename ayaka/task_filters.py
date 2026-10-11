"""Academic task filtering and blacklist configuration manager.

Loads rules from task_filters.json:
- Criteria for fetching tasks (future deadlines, unsubmitted open/lateable, max past days)
- Blacklists by task ID, keywords, or course codes
- Fallback/configured active courses
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, List, Optional, Set

logger = logging.getLogger("ayaka.task_filters")


@dataclass
class FilterCriteria:
    include_future_deadlines: bool = True
    include_unsubmitted_open: bool = True
    include_unsubmitted_lateable: bool = True
    max_past_deadline_days: int = 60


@dataclass
class TaskFilters:
    criteria: FilterCriteria = field(default_factory=FilterCriteria)
    excluded_task_ids: Set[int] = field(default_factory=set)
    excluded_keywords: List[str] = field(default_factory=list)
    excluded_courses: List[str] = field(default_factory=list)
    courses: List[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def load_from_file(cls, file_path: str | Path) -> "TaskFilters":
        """Load task filters from JSON file. Returns default filters if file missing or invalid."""
        path = Path(file_path)
        if not path.is_file():
            logger.warning(f"Task filter file '{path}' not found. Using defaults.")
            return cls()

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            crit_data = data.get("criteria", {})
            criteria = FilterCriteria(
                include_future_deadlines=bool(crit_data.get("include_future_deadlines", True)),
                include_unsubmitted_open=bool(crit_data.get("include_unsubmitted_open", True)),
                include_unsubmitted_lateable=bool(crit_data.get("include_unsubmitted_lateable", True)),
                max_past_deadline_days=int(crit_data.get("max_past_deadline_days", 60)),
            )

            bl_data = data.get("blacklist", {})
            raw_ids = bl_data.get("task_ids", [])
            excluded_ids: set[int] = set()
            for item in raw_ids:
                if isinstance(item, dict) and "id" in item:
                    try:
                        excluded_ids.add(int(item["id"]))
                    except (ValueError, TypeError):
                        pass
                elif isinstance(item, (int, str)):
                    try:
                        excluded_ids.add(int(item))
                    except (ValueError, TypeError):
                        pass

            raw_keywords = bl_data.get("keywords", [])
            excluded_keywords = [
                str(k).strip().lower() for k in raw_keywords if str(k).strip()
            ]

            raw_courses = bl_data.get("courses", [])
            excluded_courses = [
                str(c).strip().upper() for c in raw_courses if str(c).strip()
            ]

            courses_list = data.get("courses", [])

            return cls(
                criteria=criteria,
                excluded_task_ids=excluded_ids,
                excluded_keywords=excluded_keywords,
                excluded_courses=excluded_courses,
                courses=courses_list,
            )
        except Exception as e:
            logger.error(f"Error parsing task filter file '{path}': {e}")
            return cls()

    def is_task_blacklisted(
        self,
        task_id: int | str,
        title: str = "",
        course_code: str = "",
    ) -> bool:
        """Check if task is excluded by ID, title keyword, or course code."""
        try:
            tid = int(str(task_id).split(":")[-1])
            if tid in self.excluded_task_ids:
                return True
        except (ValueError, TypeError):
            pass

        if course_code and course_code.strip().upper() in self.excluded_courses:
            return True

        if title and self.excluded_keywords:
            title_lower = title.lower()
            if any(kw in title_lower for kw in self.excluded_keywords):
                return True

        return False

    def should_include_task(
        self,
        due_dt: Optional[datetime],
        now: datetime,
        open_status: str,
        is_lateable: bool,
        has_submitted: bool,
    ) -> bool:
        """Evaluate if task passes acceptance criteria."""
        if has_submitted:
            return False

        is_future = due_dt is not None and due_dt > now
        if is_future:
            return self.criteria.include_future_deadlines

        # For past deadlines:
        # Check max past days threshold
        if self.criteria.max_past_deadline_days > 0 and due_dt is not None:
            max_past_delta = timedelta(days=self.criteria.max_past_deadline_days)
            if (now - due_dt) > max_past_delta:
                return False

        can_submit_open = self.criteria.include_unsubmitted_open and (open_status == "open")
        can_submit_late = self.criteria.include_unsubmitted_lateable and is_lateable

        return can_submit_open or can_submit_late

    @classmethod
    def add_task_to_blacklist(
        cls,
        file_path: str | Path,
        task_id: int | str,
        reason: str = "",
    ) -> bool:
        """Add a task ID to task_filters.json blacklist and persist to disk."""
        path = Path(file_path)
        try:
            tid = int(task_id)
        except (ValueError, TypeError):
            logger.error(f"Invalid task_id '{task_id}' for blacklist.")
            return False

        data: dict[str, Any] = {}
        if path.is_file():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                logger.error(f"Error reading {path}: {e}")

        blacklist = data.setdefault("blacklist", {})
        task_ids = blacklist.setdefault("task_ids", [])

        # Check if already in list
        for item in task_ids:
            if isinstance(item, dict) and item.get("id") == tid:
                return True
            elif item == tid:
                return True

        entry = {"id": tid}
        if reason:
            entry["reason"] = reason
        task_ids.append(entry)

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            return True
        except Exception as e:
            logger.error(f"Failed to save {path}: {e}")
            return False
