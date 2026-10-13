"""Task and Reminder Embed Formatters for Ayaka Discord bot."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, TYPE_CHECKING
import discord

from ayaka.dialogue import format_discord_timestamp, generate_progress_bar
from ayaka.discord.safe import clip, defang_code_block

if TYPE_CHECKING:
    from ayaka.dialogue import DialogueManager
    from ayaka.storage.db import Database


def build_reminder_embed(
    task: dict[str, Any],
    milestone: str,
    dialogue_mgr: DialogueManager,
    author_icon: str,
) -> discord.Embed:
    """Create a modern, aesthetic anime-themed reminder embed."""
    scenario_key = f"{milestone.lower()}_reminder"
    title = dialogue_mgr.get_title(scenario_key, default="Academic Reminder")
    color = dialogue_mgr.get_color(scenario_key, default_color=0x5DADE2)

    course_name = task.get("course_name") or task.get("course_id") or "General Course"
    task_title = task.get("title", "Assignment")

    # In-character dialogue line with template substitutions
    dialogue = dialogue_mgr.get_dialogue(
        scenario_key,
        course=course_name,
        title=task_title,
    )

    embed = discord.Embed(
        title=title,
        description=f">>> *\"{dialogue}\"*",
        color=color,
        timestamp=datetime.now(timezone.utc),
    )

    embed.set_author(
        name="Ayaka • Academic Companion ✨",
        icon_url=author_icon,
    )

    # Structured course and platform info
    embed.add_field(name="📚 Course", value=clip(f"**{course_name}**"), inline=True)
    embed.add_field(name="🌐 Platform", value=f"`{task.get('platform', '').upper()}`", inline=True)
    embed.add_field(name="📌 Assignment", value=clip(f"**{task_title}**"), inline=False)

    # Discord timestamp and visual progress bar
    now_utc = datetime.now(timezone.utc)
    try:
        due_dt = datetime.fromisoformat(task["due_date"])
        if due_dt.tzinfo is None:
            due_dt = due_dt.replace(tzinfo=timezone.utc)

        rel_ts, full_ts = format_discord_timestamp(due_dt)
        embed.add_field(
            name="⏰ Deadline",
            value=f"{full_ts}\n**Remaining:** {rel_ts}",
            inline=False,
        )

        progress_bar = generate_progress_bar(due_dt, now_utc)
        embed.add_field(name="⏳ Time Elapsed", value=progress_bar, inline=False)
    except Exception:
        embed.add_field(name="⏰ Deadline", value=task.get("due_date", "-"), inline=False)

    if task.get("description"):
        desc_snip = defang_code_block(task["description"][:280]) + ("..." if len(task["description"]) > 280 else "")
        embed.add_field(name="📝 Notes", value=f"```{desc_snip}```", inline=False)

    embed.set_footer(
        text=f"Task ID: {task['id']} • Click 'Mark Complete' once finished"
    )
    return embed


def build_upcoming_embed(
    db: Database,
    author_icon: str,
    days: int = 7,
) -> discord.Embed:
    """Construct an aesthetic timeline embed of upcoming tasks within N days."""
    now = datetime.now(timezone.utc)
    target_limit = now + timedelta(days=days)
    tasks = db.list_tasks(include_completed=False)
    upcoming: list[tuple[datetime, dict[str, Any]]] = []

    for t in tasks:
        try:
            due_dt = datetime.fromisoformat(t["due_date"])
            if due_dt.tzinfo is None:
                due_dt = due_dt.replace(tzinfo=timezone.utc)
            if now <= due_dt <= target_limit:
                upcoming.append((due_dt, t))
        except Exception:
            continue

    upcoming.sort(key=lambda x: x[0])

    embed = discord.Embed(
        title=f"⏳ Upcoming Academic Deadlines (Next {days} Days) ✨",
        color=0x5DADE2,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_author(name="Ayaka ✨", icon_url=author_icon)

    if not upcoming:
        embed.description = f"🎉 *\"You have no assignments due within the next {days} days, Master! Keep relaxing or working steadily ahead! (ﾉ´ヮ`)ﾉ*: ･ﾟ 🌸\"*"
        return embed

    embed.description = f">>> *\"Here is your study roadmap for the next {days} days ({len(upcoming)} pending tasks). Let's take them step by step together! (๑•̀ㅂ•́)و✧\"*"

    for due_dt, t in upcoming[:10]:
        course = t.get("course_name") or t.get("course_id") or "General"
        rel_ts, full_ts = format_discord_timestamp(due_dt)
        embed.add_field(
            name=clip(f"📌 [{t['platform'].upper()}] {t['title']}", 256),
            value=clip(f"• **Course:** {course}\n• **Deadline:** {rel_ts} ({full_ts})\n• **ID:** `{t['id']}`"),
            inline=False,
        )

    embed.set_footer(text=f"Total: {len(upcoming)} upcoming • Use /complete <id> to finish")
    return embed
