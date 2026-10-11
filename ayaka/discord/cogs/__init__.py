"""Discord Cogs package for Ayaka bot."""

from ayaka.discord.cogs.academic_cog import AcademicCog
from ayaka.discord.cogs.admin_cog import AdminCog
from ayaka.discord.cogs.ai_cog import AICog
from ayaka.discord.cogs.schedule_cog import ScheduleCog

__all__ = [
    "AcademicCog",
    "AdminCog",
    "AICog",
    "ScheduleCog",
]
