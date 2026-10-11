"""Discord Bot Service Facade for Ayaka.

Backward-compatibility proxy redirecting to modular ayaka.discord package.
"""

from __future__ import annotations

from ayaka.core.time import format_uptime as _format_uptime, parse_user_due_date as _parse_user_due_date
from ayaka.discord.bot import AyakaBot, run_bot, send_test_greeting
from ayaka.discord.constants import CHECK_ICON_PNG, DEFAULT_ICON_PNG, MAIL_ICON_PNG
from ayaka.discord.views import (
    AttendanceActionView,
    ClassStartActionView,
    TaskActionView,
    TaskPaginationView,
)

__all__ = [
    "AttendanceActionView",
    "AyakaBot",
    "CHECK_ICON_PNG",
    "ClassStartActionView",
    "DEFAULT_ICON_PNG",
    "MAIL_ICON_PNG",
    "TaskActionView",
    "TaskPaginationView",
    "_format_uptime",
    "_parse_user_due_date",
    "run_bot",
    "send_test_greeting",
]
