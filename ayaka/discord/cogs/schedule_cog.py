"""Schedule Cog for Ayaka Discord bot.

Handles university lecture schedule views from Google Calendar.
"""

from __future__ import annotations

import asyncio
from typing import Optional, TYPE_CHECKING
import discord
from discord import app_commands
from discord.ext import commands

from ayaka.discord.formatters import build_schedule_embed

if TYPE_CHECKING:
    from ayaka.discord.bot import AyakaBot


class ScheduleCog(commands.Cog, name="Schedule"):
    """Commands for inspecting lecture schedules and classes."""

    def __init__(self, bot: "AyakaBot") -> None:
        self.bot = bot

    @app_commands.command(name="schedule", description="View your university lecture schedule from Google Calendar")
    @app_commands.describe(period="Schedule period to display (today, tomorrow, week)")
    @app_commands.choices(period=[
        app_commands.Choice(name="today", value="today"),
        app_commands.Choice(name="tomorrow", value="tomorrow"),
        app_commands.Choice(name="week", value="week"),
    ])
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.allowed_installs(guilds=True, users=True)
    async def slash_schedule(
        self,
        interaction: discord.Interaction,
        period: Optional[app_commands.Choice[str]] = None,
    ) -> None:
        period_val = period.value if period else "today"
        # Calendar + lazy SIX lookups are blocking network calls; defer and run in a thread.
        await interaction.response.defer(thinking=True)
        embed = await asyncio.to_thread(
            build_schedule_embed,
            schedule_service=self.bot.schedule_service,
            author_icon=self.bot.get_author_icon(),
            period=period_val,
        )
        await interaction.followup.send(embed=embed)

    @commands.command(name="schedule", aliases=["classes"])
    async def cmd_schedule(self, ctx: commands.Context, period: str = "today") -> None:
        embed = await asyncio.to_thread(
            build_schedule_embed,
            schedule_service=self.bot.schedule_service,
            author_icon=self.bot.get_author_icon(),
            period=period,
        )
        await ctx.send(embed=embed)


async def setup(bot: "AyakaBot") -> None:
    """Extension entry point for ScheduleCog."""
    await bot.add_cog(ScheduleCog(bot))
