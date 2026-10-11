"""Ayaka Discord Package.

Modular Discord bot architecture comprising Cogs, UI Views, Formatters, and Core Bot.
"""

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
    "run_bot",
    "send_test_greeting",
]
