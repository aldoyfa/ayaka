"""Schedule and Lecture Embed Formatters for Ayaka Discord bot."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
import discord

from ayaka.discord.safe import clip


def format_meeting_field_value(ev: dict[str, Any], include_links: bool = True) -> str:
    """Format rich modal details of a lecture meeting for Discord embed fields."""
    st = ev["start_dt"].strftime("%H:%M")
    et = ev["end_dt"].strftime("%H:%M")
    lines = [f"⏰ **{st} - {et} WIB**"]

    detail = ev.get("meeting_detail") or {}

    # Room / Location
    room = detail.get("room") or ev.get("location")
    if room:
        lines.append(f"📍 **Ruang:** `{room.strip()}`")

    # Activity Type / Mode (e.g. Kuliah - Tatap Muka, UTS - Tatap Muka)
    act_type = detail.get("activity_type")
    if act_type:
        clean_act = re.sub(r"\s+", " ", act_type).strip()
        lines.append(f"🏷️ **Tipe:** {clean_act}")

    # Lecturer
    lecturer = detail.get("lecturer")
    if lecturer and lecturer.strip() not in ("-", ""):
        lines.append(f"👨‍🏫 **Dosen:** {lecturer.strip()}")

    # Topic
    topic = detail.get("topic")
    if topic and topic.strip() not in ("-", ""):
        lines.append(f"📖 **Topik:** {topic.strip()}")

    # Attendance Window
    att_win = detail.get("attendance_window")
    if att_win and att_win.strip() not in ("-", ""):
        lines.append(f"📝 **Presensi:** {att_win.strip()}")

    # Notes
    notes = detail.get("notes")
    if notes and notes.strip() not in ("-", ""):
        lines.append(f"💬 **Catatan:** {notes.strip()}")

    # Direct Links
    if include_links:
        link_parts = []
        edunex_url = detail.get("edunex_url")
        if edunex_url and edunex_url.startswith("http"):
            link_parts.append(f"[Edunex]({edunex_url})")

        teams_url = detail.get("teams_url")
        if teams_url:
            if teams_url.startswith("/"):
                teams_url = f"https://six.itb.ac.id{teams_url}"
            if teams_url.startswith("http"):
                link_parts.append(f"[MS Teams]({teams_url})")

        raw_durl = detail.get("detail_url") or ""
        if raw_durl:
            if raw_durl.startswith("/"):
                raw_durl = f"https://six.itb.ac.id{raw_durl}"
            clean_durl = raw_durl.split("?returnTo=")[0]
            if clean_durl.startswith("http"):
                link_parts.append(f"[Detail SIX]({clean_durl})")

        if link_parts:
            lines.append("🔗 " + " • ".join(link_parts))

    return clip("\n".join(lines))


def build_schedule_embed(
    schedule_service: Any,
    author_icon: str,
    period: str = "today",
) -> discord.Embed:
    """Construct rich embed for lecture schedule based on requested period."""
    if not schedule_service:
        embed = discord.Embed(
            title="📅 Lecture Schedule",
            description="Lecture schedule service is not initialized or Google Calendar is not connected.",
            color=0xE74C3C,
        )
        embed.set_author(name="Ayaka ✨", icon_url=author_icon)
        return embed

    tz = schedule_service.timezone_obj
    now = datetime.now(tz)
    today = now.date()

    if period in ("tomorrow", "besok"):
        target_date = today + timedelta(days=1)
        title = f"📅 Tomorrow's Lecture Schedule — {target_date.strftime('%A, %d %B %Y')}"
        events = schedule_service.get_events_for_date(target_date)
    elif period in ("week", "minggu", "minggu ini"):
        target_date = today
        end_week = today + timedelta(days=7)
        title = f"📅 Lecture Schedule (Next 7 Days: {today.strftime('%d %b')} - {end_week.strftime('%d %b')})"
        events = schedule_service.get_events_for_range(today, end_week)
    else:
        target_date = today
        title = f"📅 Today's Lecture Schedule — {target_date.strftime('%A, %d %B %Y')}"
        events = schedule_service.get_events_for_date(target_date)

    embed = discord.Embed(
        title=title,
        color=0x5DADE2,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_author(name="Ayaka ✨", icon_url=author_icon)

    if not events:
        embed.description = "🎉 **No lecture classes scheduled** for this period! Time to relax or study at your own leisure! 🌸"
        embed.set_footer(text="Google Calendar • Semester 7")
        return embed

    if period in ("week", "minggu", "minggu ini"):
        by_day: dict[date, list[Any]] = {}
        for ev in events:
            d = ev["start_dt"].date()
            by_day.setdefault(d, []).append(ev)

        for d, d_events in by_day.items():
            day_name = d.strftime("%A, %d %B %Y")
            lines = []
            for ev in d_events:
                st = ev["start_dt"].strftime("%H:%M")
                et = ev["end_dt"].strftime("%H:%M")
                detail = ev.get("meeting_detail") or {}
                act = f" • `{detail['activity_type']}`" if detail.get("activity_type") else ""
                room = detail.get("room") or ev.get("location")
                loc = f" • 📍 `{room}`" if room else ""
                lect = f"\n  └ 👨‍🏫 {detail['lecturer']}" if detail.get("lecturer") else ""
                lines.append(f"• **{st} - {et} WIB**: **{ev['summary']}**{act}{loc}{lect}")
            embed.add_field(name=f"🗓️ {day_name}", value="\n".join(lines), inline=False)
    else:
        for idx, ev in enumerate(events, 1):
            val = format_meeting_field_value(ev, include_links=True)
            embed.add_field(name=f"{idx}. {ev['summary']}", value=val, inline=False)

    embed.set_footer(text="Automated reminders active: 05:00 Briefing • Class Start • 10m Attendance Alert 💖")
    return embed
