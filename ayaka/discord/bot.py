"""Ayaka Discord Bot Core Client.

Modular client implementation with Discord Cogs, interactive views,
embed formatters, and global error handling.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Optional

import discord
from discord import app_commands
from discord.ext import commands

from ayaka.config import Config
from ayaka.dialogue import DialogueManager, format_discord_timestamp
from ayaka.discord.cogs import AcademicCog, AdminCog, AICog, ScheduleCog
from ayaka.discord.constants import DEFAULT_ICON_PNG, MAIL_ICON_PNG
from ayaka.discord.formatters import (
    build_reminder_embed,
    build_schedule_embed,
    build_sync_embed,
    build_upcoming_embed,
    format_meeting_field_value,
)
from ayaka.discord.views import (
    AttendanceActionView,
    ClassStartActionView,
    TaskActionView,
    TaskPaginationView,
)
from ayaka.services.ai_agent import AIAgent
from ayaka.storage.db import Database
from ayaka.task_filters import TaskFilters

logger = logging.getLogger("ayaka.discord.bot")


class AyakaBot(commands.Bot):
    """Main Discord bot client for Ayaka academic assistant."""

    def __init__(
        self,
        config: Config,
        db: Database,
        google_sync: Any = None,
        schedule_service: Any = None,
    ) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

        self.config = config
        self.db = db
        self.google_sync = google_sync
        self.schedule_service = schedule_service
        self.dialogue_mgr = DialogueManager(config.dialogue_file)
        self.ai_agent = AIAgent(
            config=config,
            db=db,
            google_sync=google_sync,
            schedule_service=schedule_service,
        )
        self.start_time = datetime.now(timezone.utc)

    def is_owner_id(self, user_id: int) -> bool:
        """True only for the configured owner. Fails closed when DISCORD_USER_ID is unset."""
        owner_id = self.config.discord.user_id
        return bool(owner_id) and user_id == owner_id

    def get_author_icon(self) -> str:
        """Return the bot's actual profile avatar or high-quality PNG fallback."""
        if self.user and self.user.display_avatar:
            return self.user.display_avatar.url
        return DEFAULT_ICON_PNG

    async def setup_hook(self) -> None:
        """Initialize extensions, error handlers, and sync slash commands."""
        # Load Cogs
        await self.add_cog(AcademicCog(self))
        await self.add_cog(ScheduleCog(self))
        await self.add_cog(AdminCog(self))
        await self.add_cog(AICog(self))

        # Register global app command tree error handler
        async def on_tree_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
            logger.error(f"Slash command error on /{interaction.command.name if interaction.command else 'unknown'}: {error}", exc_info=True)
            msg = f">>> *\"Umm, Master, I encountered an unexpected error while executing that command! (｡•́︿•̀｡)\\n`{str(error)}`\"*"
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(msg, ephemeral=True)
                else:
                    await interaction.response.send_message(msg, ephemeral=True)
            except Exception:
                pass

        self.tree.on_error = on_tree_error

        # Owner-only gate for every slash and prefix command
        async def owner_only_interaction(interaction: discord.Interaction) -> bool:
            if self.is_owner_id(interaction.user.id):
                return True
            try:
                await interaction.response.send_message(
                    "Sorry, Ayaka only serves her Master. (｡•́︿•̀｡)", ephemeral=True
                )
            except Exception:
                pass
            return False

        self.tree.interaction_check = owner_only_interaction

        async def owner_only_prefix(ctx: commands.Context) -> bool:
            return self.is_owner_id(ctx.author.id)

        self.add_check(owner_only_prefix)

        # Sync slash commands globally
        logger.info("Ayaka Discord Bot syncing application slash commands globally...")
        try:
            synced = await self.tree.sync()
            logger.info(f"Successfully synced {len(synced)} global slash commands.")
        except Exception as e:
            logger.error(f"Failed to sync slash commands globally: {e}")

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        if isinstance(error, commands.CheckFailure):
            return  # non-owner attempt; stay silent
        logger.error(f"Prefix command error: {error}", exc_info=error)

    async def on_ready(self) -> None:
        """Called when the client is done preparing the data received from Discord."""
        logger.info(f"Ayaka Bot logged in as {self.user} (ID: {self.user.id})")
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="over your studies! 🌸",
            )
        )
        for guild in self.guilds:
            try:
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                logger.info(f"Instant slash commands synced to guild: {guild.name} ({guild.id})")
            except Exception as e:
                logger.warning(f"Could not instant-sync commands to guild {guild.id}: {e}")

    # ----------------- PROACTIVE NOTIFICATION DISPATCHERS -----------------

    async def send_task_reminder(self, task: dict[str, Any], milestone: str) -> bool:
        """Send modern aesthetic reminder embed directly to user's DM."""
        user_id = self.config.discord.user_id
        if not user_id:
            logger.warning("DISCORD_USER_ID is not configured.")
            return False

        try:
            user = await self.fetch_user(user_id)
            if not user:
                logger.error(f"Could not find Discord user with ID {user_id}")
                return False

            embed = self._build_reminder_embed(task, milestone)
            view = TaskActionView(
                task=task,
                db=self.db,
                dialogue_mgr=self.dialogue_mgr,
                google_sync=self.google_sync,
            )
            await user.send(embed=embed, view=view)
            return True
        except Exception as e:
            logger.error(f"Failed to send DM reminder to {user_id}: {e}")
            return False

    async def send_gmail_alert(self, email_data: dict[str, Any]) -> bool:
        """Send aesthetic urgent Gmail alert embed directly to user's DM."""
        user_id = self.config.discord.user_id
        if not user_id:
            return False

        try:
            user = await self.fetch_user(user_id)
            if not user:
                return False

            sender = email_data.get("sender", "University Academic Office")
            subject = email_data.get("subject", "(No Subject)")

            dialogue = self.dialogue_mgr.get_dialogue("gmail_alert", sender=sender)
            title = self.dialogue_mgr.get_title("gmail_alert", default="Urgent Correspondence")
            color = self.dialogue_mgr.get_color("gmail_alert", default_color=0x9B59B6)

            embed = discord.Embed(
                title=title,
                description=f">>> *\"{dialogue}\"*",
                color=color,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_author(
                name="Ayaka • Mail Courier",
                icon_url=MAIL_ICON_PNG,
            )
            embed.add_field(name="📬 Subject", value=f"**{subject}**", inline=False)
            embed.add_field(name="👤 Sender", value=f"`{sender}`", inline=True)
            embed.add_field(name="📅 Received", value=email_data.get("date", "-"), inline=True)

            snippet = email_data.get("snippet", "")
            if snippet:
                embed.add_field(name="📄 Message Preview", value=f"```{snippet[:450]}```", inline=False)

            embed.set_footer(text="Gmail Priority Monitor • Please verify in your inbox")
            await user.send(embed=embed)
            return True
        except Exception as e:
            logger.error(f"Failed to send Gmail alert to {user_id}: {e}")
            return False

    async def send_greeting(self) -> bool:
        """Send a test greeting DM embed directly to user's DM."""
        user_id = self.config.discord.user_id
        if not user_id:
            logger.error("No DISCORD_USER_ID configured.")
            return False

        try:
            user = await self.fetch_user(user_id)
            if not user:
                logger.error(f"Could not find Discord user with ID {user_id}")
                return False

            dialogue = self.dialogue_mgr.get_dialogue("greetings")
            title = self.dialogue_mgr.get_title("greetings", default="☀️ Yay! Hello there, Master! 💖")
            color = self.dialogue_mgr.get_color("greetings", default_color=0x5DADE2)

            embed = discord.Embed(
                title=title,
                description=f">>> *\"{dialogue}\"*",
                color=color,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_author(
                name="Ayaka • Academic Companion ✨",
                icon_url=self.get_author_icon(),
            )
            embed.add_field(
                name="🌸 System Status",
                value="• **Google Workspace:** Synchronized\n• **LMS Fetchers:** Active\n• **Milestone Tracker:** Ready",
                inline=False,
            )
            embed.set_footer(text="Ayaka Academic Assistant • Ready for duty!")
            await user.send(embed=embed)
            return True
        except Exception as e:
            logger.error(f"Failed to send greeting to {user_id}: {e}")
            return False

    async def send_schedule_morning_briefing(
        self,
        target_date: date,
        events: list[dict[str, Any]],
        tasks_due_soon: Optional[list[dict[str, Any]]] = None,
    ) -> bool:
        """Send 05:00 AM daily briefing for today's classes & imminent deadlines to user's DM."""
        user_id = self.config.discord.user_id
        if not user_id:
            return False

        try:
            user = await self.fetch_user(user_id)
            if not user:
                return False

            date_str = target_date.strftime("%A, %d %B %Y")

            embed = discord.Embed(
                title=f"🌅 Morning Academic Briefing — {date_str} ✨",
                color=0x5DADE2,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_author(name="Ayaka ✨", icon_url=self.get_author_icon())

            if events:
                count_str = f"{len(events)} class" if len(events) == 1 else f"{len(events)} classes"
                embed.description = (
                    f">>> *\"Good morning, Master! ☀️ Here is your academic schedule for today ({count_str}). "
                    f"Don't forget to have breakfast and stay hydrated! Ayaka is always cheering for you! ٩(ˊᗜˋ*)و 🌸\"*"
                )
                for idx, ev in enumerate(events, 1):
                    val = self._format_meeting_field_value(ev, include_links=True)
                    embed.add_field(
                        name=f"{idx}. {ev['summary']}",
                        value=val,
                        inline=False,
                    )
            else:
                embed.description = (
                    ">>> *\"Good morning, Master! ☀️ You have **no classes scheduled for today**! 🎉 "
                    "Enjoy your rest or make steady progress on your personal goals! Have a wonderful day! (ﾉ´ヮ`)ﾉ*: ･ﾟ 💖\"*"
                )

            if tasks_due_soon:
                task_lines = []
                for t in tasks_due_soon[:5]:
                    course = t.get("course_name") or t.get("course_id") or "General"
                    try:
                        due_dt = datetime.fromisoformat(t["due_date"])
                        rel_ts, _ = format_discord_timestamp(due_dt)
                    except Exception:
                        rel_ts = t.get("due_date", "")
                    task_lines.append(f"• **[{course}]** {t['title']} — Due {rel_ts}")

                embed.add_field(
                    name=f"⏳ Imminent Deadlines ({len(tasks_due_soon)})",
                    value="\n".join(task_lines),
                    inline=False,
                )

            embed.set_footer(text="Daily Morning Briefing • Ayaka Academic Companion 💖")
            await user.send(embed=embed)
            return True
        except Exception as e:
            logger.error(f"Failed to send schedule morning briefing to {user_id}: {e}")
            return False

    async def send_class_start_reminder(self, event: dict[str, Any]) -> bool:
        """Send proactive reminder when a lecture/class starts to user's DM."""
        user_id = self.config.discord.user_id
        if not user_id:
            return False

        try:
            user = await self.fetch_user(user_id)
            if not user:
                return False

            detail = event.get("meeting_detail") or {}
            start_str = event["start_dt"].strftime("%H:%M")
            end_str = event["end_dt"].strftime("%H:%M")

            embed = discord.Embed(
                title=f"🔔 Class Starting: {event['summary']} 📚✨",
                description=(
                    f">>> *\"Master! Your class **{event['summary']}** is starting right now! ({start_str} - {end_str} WIB). "
                    f"Let's join the lecture hall or open the classroom stream and dive into today's lesson! (๑•̀ㅂ•́)و✧ 🔥\"*"
                ),
                color=0x2ECC71,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_author(name="Ayaka ✨", icon_url=self.get_author_icon())
            embed.add_field(name="⏰ Lecture Time", value=f"**{start_str} - {end_str} WIB**", inline=True)
            room = detail.get("room") or event.get("location")
            if room:
                embed.add_field(name="📍 Room / Location", value=f"`{room}`", inline=True)
            if detail.get("activity_type"):
                embed.add_field(name="🏷️ Activity Type", value=f"`{detail['activity_type']}`", inline=True)
            if detail.get("lecturer"):
                embed.add_field(name="👨‍🏫 Lecturer", value=detail["lecturer"], inline=False)
            if detail.get("topic"):
                embed.add_field(name="📖 Topic", value=detail["topic"], inline=False)
            if detail.get("attendance_window"):
                embed.add_field(name="📝 Attendance Info", value=detail["attendance_window"], inline=False)
            if detail.get("notes"):
                embed.add_field(name="💬 Notes", value=detail["notes"], inline=False)

            raw_durl = detail.get("detail_url") or ""
            if raw_durl.startswith("/"):
                raw_durl = f"https://six.itb.ac.id{raw_durl}"
            clean_durl = raw_durl.split("?returnTo=")[0]
            six_btn_url = clean_durl or "https://six.itb.ac.id"

            embed.set_footer(text="Ayaka will remind you about attendance 10 minutes before class ends ✨")
            view = ClassStartActionView(
                edunex_url=detail.get("edunex_url"),
                teams_url=detail.get("teams_url"),
                six_url=six_btn_url,
            )
            await user.send(embed=embed, view=view)
            return True
        except Exception as e:
            logger.error(f"Failed to send class start reminder to {user_id}: {e}")
            return False

    async def send_class_advance_reminder(self, event: dict[str, Any], minutes_before: int = 15) -> bool:
        """Send proactive advance preparation reminder before class starts."""
        user_id = self.config.discord.user_id
        if not user_id:
            return False

        try:
            user = await self.fetch_user(user_id)
            if not user:
                return False

            detail = event.get("meeting_detail") or {}
            start_str = event["start_dt"].strftime("%H:%M")
            end_str = event["end_dt"].strftime("%H:%M")

            embed = discord.Embed(
                title=f"⏳ Upcoming Class: {event['summary']} (in {minutes_before} min) 🎒✨",
                description=(
                    f">>> *\"Master! Heads up! 📢 Your class **{event['summary']}** starts in **{minutes_before} minutes** "
                    f"({start_str} - {end_str} WIB). "
                    f"Please prepare your notes and head to class or open your lecture window! (´｡• ᵕ •｡`) ♡ 🌸\"*"
                ),
                color=0x3498DB,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_author(name="Ayaka ✨", icon_url=self.get_author_icon())
            embed.add_field(name="⏰ Lecture Time", value=f"**{start_str} - {end_str} WIB**", inline=True)
            room = detail.get("room") or event.get("location")
            if room:
                embed.add_field(name="📍 Room / Location", value=f"`{room}`", inline=True)
            if detail.get("activity_type"):
                embed.add_field(name="🏷️ Activity Type", value=f"`{detail['activity_type']}`", inline=True)
            if detail.get("lecturer"):
                embed.add_field(name="👨‍🏫 Lecturer", value=detail["lecturer"], inline=False)
            if detail.get("topic"):
                embed.add_field(name="📖 Topic", value=detail["topic"], inline=False)

            raw_durl = detail.get("detail_url") or ""
            if raw_durl.startswith("/"):
                raw_durl = f"https://six.itb.ac.id{raw_durl}"
            clean_durl = raw_durl.split("?returnTo=")[0]
            six_btn_url = clean_durl or "https://six.itb.ac.id"

            embed.set_footer(text=f"Advance reminder {minutes_before}m before class • Ayaka ✨")
            view = ClassStartActionView(
                edunex_url=detail.get("edunex_url"),
                teams_url=detail.get("teams_url"),
                six_url=six_btn_url,
            )
            await user.send(embed=embed, view=view)
            return True
        except Exception as e:
            logger.error(f"Failed to send advance class reminder to {user_id}: {e}")
            return False

    async def send_class_attendance_reminder(self, event: dict[str, Any]) -> bool:
        """Send proactive attendance reminder 10 minutes before class ends with quick actions."""
        user_id = self.config.discord.user_id
        if not user_id:
            return False

        try:
            user = await self.fetch_user(user_id)
            if not user:
                return False

            detail = event.get("meeting_detail") or {}
            end_str = event["end_dt"].strftime("%H:%M")

            embed = discord.Embed(
                title=f"⏰ Attendance Reminder: {event['summary']}! 📝✨",
                description=(
                    f">>> *\"Master, heads up! 📢 Your class **{event['summary']}** will conclude in **10 minutes** "
                    f"(at **{end_str} WIB**)!\n\n"
                    f"Please submit your attendance/presensi right now before the session portal closes! 🏃‍♀️💨💖\"*"
                ),
                color=0xF39C12,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_author(name="Ayaka ✨", icon_url=self.get_author_icon())

            att_win = detail.get("attendance_window")
            att_text = f"**{att_win}**\n\nEnsure your attendance is recorded on SIX / Edunex before the class concludes!" if att_win else "Ensure your attendance is recorded on SIX / Edunex / lecturer's form before the class concludes!"
            embed.add_field(
                name="⚠️ Attendance Check",
                value=att_text,
                inline=False,
            )
            if detail.get("lecturer"):
                embed.add_field(name="👨‍🏫 Lecturer", value=detail["lecturer"], inline=True)
            room = detail.get("room") or event.get("location")
            if room:
                embed.add_field(name="📍 Room", value=f"`{room}`", inline=True)

            raw_durl = detail.get("detail_url") or ""
            if raw_durl.startswith("/"):
                raw_durl = f"https://six.itb.ac.id{raw_durl}"
            clean_durl = raw_durl.split("?returnTo=")[0]
            six_btn_url = clean_durl or "https://six.itb.ac.id"

            embed.set_footer(text="Attendance check 10 minutes before class conclusion • Ayaka ✨")
            view = AttendanceActionView(
                six_url=six_btn_url,
                edunex_url=detail.get("edunex_url") or "https://edunex.itb.ac.id",
                teams_url=detail.get("teams_url"),
            )
            await user.send(embed=embed, view=view)
            return True
        except Exception as e:
            logger.error(f"Failed to send class attendance reminder to {user_id}: {e}")
            return False

    async def send_session_expired_alert(self, platform: str) -> bool:
        """Send urgent notification when an academic session cookie expires."""
        user_id = self.config.discord.user_id
        if not user_id:
            return False

        try:
            user = await self.fetch_user(user_id)
            if not user:
                return False

            embed = discord.Embed(
                title=f"⚠️ Session Expired: {platform.upper()} ITB! 🥺",
                description=(
                    f">>> *\"Master! My access session to **{platform.upper()}** has expired! (｡•́︿•̀｡)\\n\\n"
                    f"Please update your `{platform.upper()}_COOKIE` in `.env` so I can continue watching over your coursework! 🌸\"*"
                ),
                color=0xE74C3C,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_author(name="Ayaka ✨", icon_url=self.get_author_icon())
            embed.set_footer(text="Session Health Alert • Ayaka Academic Assistant ✨")
            await user.send(embed=embed)
            return True
        except Exception as e:
            logger.error(f"Failed to send session expired alert to {user_id}: {e}")
            return False

    # ----------------- BACKWARDS-COMPATIBLE FORMATTER HELPERS -----------------

    def _build_reminder_embed(self, task: dict[str, Any], milestone: str) -> discord.Embed:
        return build_reminder_embed(task, milestone, self.dialogue_mgr, self.get_author_icon())

    def _format_meeting_field_value(self, ev: dict[str, Any], include_links: bool = True) -> str:
        return format_meeting_field_value(ev, include_links=include_links)

    def _build_schedule_embed(self, period: str = "today") -> discord.Embed:
        return build_schedule_embed(self.schedule_service, self.get_author_icon(), period=period)

    def _build_tasks_embed(self, all_tasks: bool = False, platform: Optional[str] = None) -> tuple[Optional[discord.Embed], Optional[str]]:
        plat_filter = platform if platform and platform != "all" else None
        tasks = self.db.list_tasks(include_completed=all_tasks, platform=plat_filter)
        if not all_tasks:
            try:
                filters = TaskFilters.load_from_file(self.config.task_filters_file)
                tasks = [
                    t for t in tasks
                    if not filters.is_task_blacklisted(t["id"], t.get("title", ""), t.get("course_id", ""))
                ]
            except Exception as e:
                logger.debug(f"Task filter blacklist check skipped: {e}")

        if not tasks:
            empty_msg = self.dialogue_mgr.get_dialogue("no_tasks")
            return None, empty_msg

        view = TaskPaginationView(self, tasks, author_id=0, all_tasks=all_tasks, per_page=5)
        return view.build_embed(), None

    def _build_sync_embed(self, platform: str, stats: dict[str, Any]) -> discord.Embed:
        return build_sync_embed(platform, stats, self.get_author_icon())

    def _build_upcoming_embed(self, days: int = 7) -> discord.Embed:
        return build_upcoming_embed(self.db, self.get_author_icon(), days=days)


async def send_test_greeting(config: Config, db: Database) -> bool:
    """Connect briefly to Discord, send a greeting DM, and close."""
    if not config.discord.is_configured:
        logger.error("Discord token or user ID is not configured.")
        return False

    bot = AyakaBot(config, db)
    sent_status = False

    @bot.event
    async def on_ready():
        nonlocal sent_status
        sent_status = await bot.send_greeting()
        await bot.close()

    try:
        await bot.start(config.discord.bot_token)
    except Exception as e:
        logger.error(f"Error during test greeting: {e}")
        return False
    return sent_status


def run_bot(config: Config, db: Database, google_sync: Any = None, daemon: bool = True) -> None:
    """Entry point to launch Discord bot with optional background daemon loops."""
    if not config.discord.is_configured:
        print("Error: DISCORD_BOT_TOKEN or DISCORD_USER_ID is missing in .env")
        return

    if daemon:
        from ayaka.main import DaemonBot
        from ayaka.services.schedule_service import ScheduleService
        if google_sync is None and config.google.has_credentials:
            from ayaka.services.google_sync import GoogleSyncService
            google_sync = GoogleSyncService(config, db)
            try:
                google_sync.authenticate()
            except Exception:
                pass
        schedule_service = ScheduleService(config, db, google_sync)
        bot = DaemonBot(config, db, google_sync, schedule_service)
    else:
        bot = AyakaBot(config, db, google_sync)

    bot.run(config.discord.bot_token)
