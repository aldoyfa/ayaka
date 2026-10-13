"""Academic Sync embed formatter for Ayaka Discord bot."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import discord

from ayaka.dialogue import format_discord_timestamp
from ayaka.discord.safe import join_lines_limited


def build_sync_embed(platform: str, stats: dict[str, Any], author_icon: str) -> discord.Embed:
    """Construct detailed sync result embed with itemized changelog."""
    has_expired = bool(stats.get("expired_sessions"))
    embed = discord.Embed(
        title=f"🌸 Academic Sync Complete ({platform.upper()})! ✨",
        color=0xF39C12 if has_expired else 0x5DADE2,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_author(name="Ayaka ✨", icon_url=author_icon)

    added = stats.get("added_items", [])
    updated = stats.get("updated_items", [])
    completed = stats.get("completed_items", [])
    expired = stats.get("expired_sessions", [])

    has_changes = bool(added or updated or completed or expired)

    if not has_changes:
        embed.description = (
            ">>> *\"Master, I have thoroughly checked all configured platforms! "
            "All assignments are completely up-to-date with no new changes detected! (ﾉ´ヮ`)ﾉ*: ･ﾟ 🌸\"*"
        )
        embed.add_field(
            name="📊 Activity Log",
            value="✨ **Everything is up-to-date!**\n• 🆕 New tasks: `0`\n• 🔄 Updated: `0`\n• ✅ Newly Completed: `0`",
            inline=False,
        )
    else:
        embed.description = ">>> *\"Here is the detailed change log from our sync check! (๑•̀ㅂ•́)و✧\"*"

        if completed:
            comp_lines = []
            for it in completed[:10]:
                course_tag = f"[{it.get('course')}] " if it.get("course") else ""
                comp_lines.append(f"• ✅ **[{it['platform'].upper()}]** {course_tag}{it['title']} (`{it['id']}`)")
            if len(completed) > 10:
                comp_lines.append(f"• ...and {len(completed) - 10} more completed tasks")
            embed.add_field(
                name=f"🎉 Newly Completed Tasks ({len(completed)})",
                value=join_lines_limited(comp_lines, more_label="more"),
                inline=False,
            )

        if added:
            add_lines = []
            for it in added[:10]:
                due_str = ""
                if it.get("due_date"):
                    try:
                        dt = datetime.fromisoformat(it["due_date"])
                        rel_ts, _ = format_discord_timestamp(dt)
                        due_str = f" — {rel_ts}"
                    except Exception:
                        due_str = f" — `{it['due_date']}`"
                course_tag = f"[{it.get('course')}] " if it.get("course") else ""
                add_lines.append(f"• 🆕 **[{it['platform'].upper()}]** {course_tag}{it['title']}{due_str}")
            if len(added) > 10:
                add_lines.append(f"• ...and {len(added) - 10} more new tasks")
            embed.add_field(
                name=f"📋 Newly Discovered Tasks ({len(added)})",
                value=join_lines_limited(add_lines, more_label="more"),
                inline=False,
            )

        if updated:
            upd_lines = []
            for it in updated[:10]:
                due_str = ""
                if it.get("due_date"):
                    try:
                        dt = datetime.fromisoformat(it["due_date"])
                        rel_ts, _ = format_discord_timestamp(dt)
                        due_str = f" — {rel_ts}"
                    except Exception:
                        due_str = f" — `{it['due_date']}`"
                course_tag = f"[{it.get('course')}] " if it.get("course") else ""
                upd_lines.append(f"• 🔄 **[{it['platform'].upper()}]** {course_tag}{it['title']}{due_str}")
            if len(updated) > 10:
                upd_lines.append(f"• ...and {len(updated) - 10} more updated tasks")
            embed.add_field(
                name=f"🔄 Updated Deadlines / Tasks ({len(updated)})",
                value=join_lines_limited(upd_lines, more_label="more"),
                inline=False,
            )

        if expired:
            exp_names = ", ".join([f"`{p.upper()}`" for p in expired])
            embed.add_field(
                name="⚠️ Expired Sessions Detected",
                value=f"Session expired for {exp_names}! Please update credentials via `/session <platform>`.",
                inline=False,
            )

    new_cnt = stats.get("new_tasks", len(added))
    upd_cnt = stats.get("updated_tasks", len(updated))
    cmp_cnt = stats.get("completed_tasks", len(completed))
    embed.set_footer(text=f"Summary: {new_cnt} new • {upd_cnt} updated • {cmp_cnt} completed ✨")
    return embed
