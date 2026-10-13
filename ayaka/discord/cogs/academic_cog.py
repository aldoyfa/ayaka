"""Academic Cog for Ayaka Discord bot.

Handles tasks listing, addition, completion, blacklisting, upcoming deadlines, and synchronization.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING
import discord
from discord import app_commands
from discord.ext import commands

from ayaka.core.time import parse_user_due_date
from ayaka.dialogue import format_discord_timestamp
from ayaka.discord.formatters import build_sync_embed, build_upcoming_embed
from ayaka.discord.views import TaskPaginationView
from ayaka.task_filters import TaskFilters

if TYPE_CHECKING:
    from ayaka.discord.bot import AyakaBot

logger = logging.getLogger("ayaka.discord.cogs.academic")


class AcademicCog(commands.Cog, name="Academic"):
    """Commands for managing academic tasks, deadlines, and platform sync."""

    def __init__(self, bot: "AyakaBot") -> None:
        self.bot = bot

    # ----------------- SLASH COMMANDS -----------------

    @app_commands.command(name="tasks", description="List your pending academic tasks and upcoming deadlines")
    @app_commands.describe(
        all_tasks="Show all tasks including completed ones (default: False)",
        platform="Filter tasks by platform (default: all)",
    )
    @app_commands.choices(platform=[
        app_commands.Choice(name="All Platforms", value="all"),
        app_commands.Choice(name="Omnicampus", value="omnicampus"),
        app_commands.Choice(name="Edunex ITB", value="edunex"),
        app_commands.Choice(name="SIX ITB", value="six"),
        app_commands.Choice(name="Manual Tasks", value="manual"),
    ])
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.allowed_installs(guilds=True, users=True)
    async def slash_tasks(
        self,
        interaction: discord.Interaction,
        all_tasks: bool = False,
        platform: Optional[app_commands.Choice[str]] = None,
    ) -> None:
        plat_val = platform.value if platform else None
        plat_filter = plat_val if plat_val and plat_val != "all" else None
        tasks = self.bot.db.list_tasks(include_completed=all_tasks, platform=plat_filter)
        if not all_tasks:
            try:
                filters = TaskFilters.load_from_file(self.bot.config.task_filters_file)
                tasks = [
                    t for t in tasks
                    if not filters.is_task_blacklisted(t["id"], t.get("title", ""), t.get("course_id", ""))
                ]
            except Exception as e:
                logger.debug(f"Task filter blacklist check skipped: {e}")

        if not tasks:
            empty_msg = self.bot.dialogue_mgr.get_dialogue("no_tasks")
            await interaction.response.send_message(f">>> *\"{empty_msg}\"*")
            return

        view = TaskPaginationView(
            bot=self.bot,
            tasks=tasks,
            author_id=interaction.user.id,
            all_tasks=all_tasks,
            per_page=5,
        )
        embed = view.build_embed()
        if view.total_pages > 1:
            await interaction.response.send_message(embed=embed, view=view)
            try:
                view.message = await interaction.original_response()
            except Exception:
                pass
        else:
            await interaction.response.send_message(embed=embed)

    @app_commands.command(name="complete", description="Mark an academic assignment as completed")
    @app_commands.describe(task_id="The ID of the assignment to complete (e.g. from /tasks)")
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.allowed_installs(guilds=True, users=True)
    async def slash_complete(self, interaction: discord.Interaction, task_id: str) -> None:
        existing = self.bot.db.get_task(task_id)
        if not existing:
            await interaction.response.send_message(
                f"Umm, Master, I couldn't locate any task with ID `{task_id}` in our ledger! (｡•́︿•̀｡)",
                ephemeral=True,
            )
            return

        real_id = existing["id"]
        success = self.bot.db.mark_task_completed(real_id)
        if success:
            if self.bot.google_sync:
                try:
                    self.bot.google_sync.mark_completed_in_google(real_id)
                except Exception as e:
                    logger.error(f"Error updating Google Tasks: {e}")

            reply = self.bot.dialogue_mgr.get_dialogue("task_completed", title=existing["title"])
            embed = discord.Embed(
                title="🎉 Task Completed!",
                description=f">>> *\"{reply}\"*",
                color=0x2ECC71,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_author(name="Ayaka ✨", icon_url=self.bot.get_author_icon())
            embed.add_field(name="📌 Finished Assignment", value=f"**{existing['title']}** (`{task_id}`)", inline=False)
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message(
                f"I encountered a little hiccup trying to update task `{task_id}`. (｡•́︿•̀｡)",
                ephemeral=True,
            )

    @app_commands.command(name="add", description="Add a manual assignment or custom academic deadline")
    @app_commands.describe(
        title="Assignment or task title",
        due_date="Deadline format: YYYY-MM-DD HH:MM (e.g. 2026-10-15 23:59)",
        course="Course name or code (optional)",
        description="Additional details or instructions (optional)",
    )
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.allowed_installs(guilds=True, users=True)
    async def slash_add(
        self,
        interaction: discord.Interaction,
        title: str,
        due_date: str,
        course: Optional[str] = None,
        description: Optional[str] = None,
    ) -> None:
        due_dt = parse_user_due_date(due_date, self.bot.config.timezone)
        if not due_dt:
            await interaction.response.send_message(
                ">>> *\"Umm, Master, I couldn't understand that due date format! (｡•́︿•̀｡)\\n"
                "Please use `YYYY-MM-DD HH:MM` (e.g., `2026-10-15 23:59`) or `YYYY-MM-DD`! 🌸\"*",
                ephemeral=True,
            )
            return

        task_id = f"manual:{uuid.uuid4().hex[:8]}"
        course_name = course.strip() if course else "Personal / Custom"
        task_dict = {
            "id": task_id,
            "platform": "manual",
            "course_id": course.strip() if course else "MANUAL",
            "course_name": course_name,
            "title": title.strip(),
            "description": description.strip() if description else "",
            "due_date": due_dt.isoformat(),
            "url": "",
            "is_completed": 0,
        }

        task, is_new = self.bot.db.upsert_task(task_dict)
        if self.bot.google_sync:
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self.bot.google_sync.sync_task, task)
            except Exception as e:
                logger.error(f"Error syncing manual task to Google: {e}")

        rel_ts, full_ts = format_discord_timestamp(due_dt)
        embed = discord.Embed(
            title="🌸 Assignment Added Successfully! ✨",
            description=(
                f">>> *\"Master! I have added **{title.strip()}** to your study queue! "
                f"I'll keep a careful eye on it and remind you as the deadline approaches! (๑•̀ㅂ•́)و✧ 💖\"*"
            ),
            color=0x2ECC71,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(name="Ayaka ✨", icon_url=self.bot.get_author_icon())
        embed.add_field(name="📌 Assignment", value=f"**{title.strip()}**", inline=False)
        embed.add_field(name="📚 Course", value=course_name, inline=True)
        embed.add_field(name="⏰ Deadline", value=f"{rel_ts}\n`{full_ts}`", inline=True)
        embed.add_field(name="🆔 Task ID", value=f"`{task_id}`", inline=False)
        embed.set_footer(text="Ayaka Academic Assistant • Use /complete to finish ✨")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="blacklist", description="Blacklist and ignore an assignment by ID")
    @app_commands.describe(
        task_id="Task ID to ignore (e.g. 61962, edunex:61962, or manual:abc12345)",
        reason="Optional reason for blacklisting this assignment",
    )
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.allowed_installs(guilds=True, users=True)
    async def slash_blacklist(
        self,
        interaction: discord.Interaction,
        task_id: str,
        reason: Optional[str] = "Ignored via Discord command",
    ) -> None:
        raw_id = task_id.strip()
        reason_text = reason.strip() if reason else "Ignored via Discord command"

        existing = self.bot.db.get_task(raw_id)
        real_id = existing["id"] if existing else raw_id

        # Filters key on the numeric LMS id, i.e. the last ':' segment of "edunex:task:61962"
        num_part = real_id.rsplit(":", 1)[-1]
        saved_to_filters = False
        if num_part.isdigit():
            saved_to_filters = TaskFilters.add_task_to_blacklist(
                self.bot.config.task_filters_file,
                int(num_part),
                reason=reason_text,
            )

        # Close the Google task before deleting locally (the lookup needs the row).
        if self.bot.google_sync and existing:
            try:
                self.bot.google_sync.mark_completed_in_google(real_id)
            except Exception as e:
                logger.error(f"Error updating Google Tasks for blacklisted task: {e}")

        deleted = self.bot.db.delete_task(real_id)

        embed = discord.Embed(
            title="🚫 Assignment Blacklisted! 🌸",
            description=(
                f">>> *\"Understood, Master! I have blacklisted task `{raw_id}` so it won't clutter your quest board "
                f"or trigger any more notifications! ٩(ˊᗜˋ*)و ✨\"*"
            ),
            color=0xE74C3C,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(name="Ayaka ✨", icon_url=self.bot.get_author_icon())
        embed.add_field(name="🆔 Target ID", value=f"`{raw_id}`", inline=True)
        embed.add_field(name="📝 Reason", value=reason_text, inline=True)
        if saved_to_filters:
            embed.add_field(name="📁 Filters Configuration", value="Saved to `task_filters.json`", inline=False)
        embed.set_footer(text="Ayaka will ignore this assignment in future sync cycles ✨")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="upcoming", description="View upcoming assignment deadlines within N days")
    @app_commands.describe(days="Number of days to look ahead (default: 7)")
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.allowed_installs(guilds=True, users=True)
    async def slash_upcoming(self, interaction: discord.Interaction, days: Optional[int] = 7) -> None:
        num_days = max(1, min(days or 7, 60))
        embed = build_upcoming_embed(self.bot.db, self.bot.get_author_icon(), days=num_days)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="sync", description="Trigger an immediate sync cycle from ITB LMS & Google")
    @app_commands.describe(platform="Specific platform to sync")
    @app_commands.choices(platform=[
        app_commands.Choice(name="All Platforms", value="all"),
        app_commands.Choice(name="Edunex ITB", value="edunex"),
        app_commands.Choice(name="SIX ITB", value="six"),
        app_commands.Choice(name="Omnicampus", value="omnicampus"),
    ])
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.allowed_installs(guilds=True, users=True)
    async def slash_sync(self, interaction: discord.Interaction, platform: Optional[app_commands.Choice[str]] = None) -> None:
        plat_val = platform.value if platform else "all"
        await interaction.response.defer(thinking=True)

        from ayaka.scheduler import run_sync_cycle_async
        stats = await run_sync_cycle_async(self.bot.config, self.bot.db, plat_val, self.bot.google_sync)

        embed = build_sync_embed(plat_val, stats, self.bot.get_author_icon())
        await interaction.followup.send(embed=embed)

    # ----------------- PREFIX COMMANDS (FALLBACK) -----------------

    @commands.command(name="tasks", aliases=["list", "tugas"])
    async def cmd_tasks(self, ctx: commands.Context, platform: Optional[str] = None) -> None:
        plat_filter = platform if platform and platform != "all" else None
        tasks = self.bot.db.list_tasks(include_completed=False, platform=plat_filter)
        try:
            filters = TaskFilters.load_from_file(self.bot.config.task_filters_file)
            tasks = [
                t for t in tasks
                if not filters.is_task_blacklisted(t["id"], t.get("title", ""), t.get("course_id", ""))
            ]
        except Exception as e:
            logger.debug(f"Task filter blacklist check skipped: {e}")

        if not tasks:
            empty_msg = self.bot.dialogue_mgr.get_dialogue("no_tasks")
            await ctx.send(f">>> *\"{empty_msg}\"*")
            return

        view = TaskPaginationView(
            bot=self.bot,
            tasks=tasks,
            author_id=ctx.author.id,
            all_tasks=False,
            per_page=5,
        )
        embed = view.build_embed()
        if view.total_pages > 1:
            msg = await ctx.send(embed=embed, view=view)
            view.message = msg
        else:
            await ctx.send(embed=embed)

    @commands.command(name="complete", aliases=["selesai"])
    async def cmd_complete(self, ctx: commands.Context, task_id: str) -> None:
        existing = self.bot.db.get_task(task_id)
        if not existing:
            await ctx.send(f"Umm, Master, I couldn't locate any task with ID `{task_id}` in our ledger! (｡•́︿•̀｡)")
            return

        real_id = existing["id"]
        success = self.bot.db.mark_task_completed(real_id)
        if success:
            if self.bot.google_sync:
                try:
                    self.bot.google_sync.mark_completed_in_google(real_id)
                except Exception as e:
                    logger.error(f"Error updating Google Tasks: {e}")

            reply = self.bot.dialogue_mgr.get_dialogue("task_completed", title=existing["title"])
            await ctx.send(f">>> *\"{reply}\"*\n\n-# Task `{real_id}` has been cleared from your active obligations.")
        else:
            await ctx.send(f"I encountered a difficulty trying to update task `{task_id}`.")

    @commands.command(name="add")
    async def cmd_add(self, ctx: commands.Context, title: str, due_date: str, course: Optional[str] = None) -> None:
        due_dt = parse_user_due_date(due_date, self.bot.config.timezone)
        if not due_dt:
            await ctx.send(">>> *\"Master, please provide the due date in `YYYY-MM-DD HH:MM` format! (｡•́︿•̀｡)\"*")
            return
        task_id = f"manual:{uuid.uuid4().hex[:8]}"
        course_name = course or "Personal / Custom"
        task_dict = {
            "id": task_id,
            "platform": "manual",
            "course_id": course or "MANUAL",
            "course_name": course_name,
            "title": title,
            "description": "",
            "due_date": due_dt.isoformat(),
            "url": "",
            "is_completed": 0,
        }
        task, _ = self.bot.db.upsert_task(task_dict)
        if self.bot.google_sync:
            try:
                self.bot.google_sync.sync_task(task)
            except Exception:
                pass
        await ctx.send(f"🌸 Added assignment **{title}** (`{task_id}`) due {due_dt.strftime('%Y-%m-%d %H:%M')}!")

    @commands.command(name="blacklist", aliases=["ignore"])
    async def cmd_blacklist(self, ctx: commands.Context, task_id: str, *, reason: str = "Ignored via command") -> None:
        existing = self.bot.db.get_task(task_id.strip())
        real_id = existing["id"] if existing else task_id.strip()
        num_part = real_id.rsplit(":", 1)[-1]
        if num_part.isdigit():
            TaskFilters.add_task_to_blacklist(self.bot.config.task_filters_file, int(num_part), reason=reason)
        if existing and self.bot.google_sync:
            try:
                self.bot.google_sync.mark_completed_in_google(real_id)
            except Exception as e:
                logger.error(f"Error updating Google Tasks for blacklisted task: {e}")
        self.bot.db.delete_task(real_id)
        await ctx.send(f"🚫 Task `{task_id}` has been blacklisted and removed from active tracking!")

    @commands.command(name="upcoming")
    async def cmd_upcoming(self, ctx: commands.Context, days: int = 7) -> None:
        embed = build_upcoming_embed(self.bot.db, self.bot.get_author_icon(), days=days)
        await ctx.send(embed=embed)

    @commands.command(name="sync")
    async def cmd_sync(self, ctx: commands.Context, platform: str = "all") -> None:
        from ayaka.scheduler import run_sync_cycle_async
        stats = await run_sync_cycle_async(self.bot.config, self.bot.db, platform, self.bot.google_sync)
        embed = build_sync_embed(platform, stats, self.bot.get_author_icon())
        await ctx.send(embed=embed)


async def setup(bot: "AyakaBot") -> None:
    """Extension entry point for AcademicCog."""
    await bot.add_cog(AcademicCog(bot))
