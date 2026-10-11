"""Base Fetcher and Data Contracts for Academic Platforms.

Provides the common abstraction, error contracts, and session lifecycle
tracking for Edunex, SIX ITB, and Omnicampus fetchers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, List, Optional

from ayaka.config import Config


class SessionExpiredException(Exception):
    """Raised when an academic platform returns 401, 403, or redirects to login."""
    def __init__(self, platform: str, message: str = "Session cookie/token expired"):
        super().__init__(f"[{platform}] {message}")
        self.platform = platform


@dataclass
class AcademicTask:
    """Standardized representation of an academic assignment, exam, or quiz."""
    id: str
    platform: str
    course_id: str
    course_name: str
    title: str
    due_date: str  # ISO 8601
    description: str = ""
    url: str = ""
    is_completed: int = 0
    google_calendar_event_id: Optional[str] = None
    google_tasks_task_id: Optional[str] = None

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "platform": self.platform,
            "course_id": self.course_id,
            "course_name": self.course_name,
            "title": self.title,
            "description": self.description,
            "due_date": self.due_date,
            "url": self.url,
            "is_completed": self.is_completed,
            "google_calendar_event_id": self.google_calendar_event_id,
            "google_tasks_task_id": self.google_tasks_task_id,
        }



import asyncio
import concurrent.futures
from typing import Coroutine, TypeVar

T = TypeVar("T")


def run_coro_sync(coro: Coroutine[Any, Any, T]) -> T:
    """Safely execute a coroutine from synchronous code, even if an event loop is running."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(lambda: asyncio.run(coro)).result()
    else:
        return asyncio.run(coro)


class BaseFetcher(ABC):
    """Abstract base class for all campus LMS fetchers."""

    platform_name: str = "generic"

    def __init__(self, config: Config):
        self.config = config
        self.session_valid: bool = True
        self.last_sync_time: Optional[datetime] = None
        self.last_error: Optional[str] = None

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True if required tokens or cookies are populated."""
        pass

    def fetch_tasks(self) -> List[dict[str, Any]]:
        """Fetch pending assignments, exams, and academic tasks from platform."""
        return run_coro_sync(self.fetch_tasks_async())

    async def fetch_tasks_async(self) -> List[dict[str, Any]]:
        """Fetch pending assignments asynchronously using httpx.AsyncClient."""
        raise NotImplementedError("Subclasses must implement fetch_tasks_async or override fetch_tasks")
