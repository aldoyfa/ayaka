"""Ayaka Scheduler Engine.

Orchestrates periodic background tasks:
1. Polling academic platforms (Edunex, SIX, Omnicampus)
2. Syncing tasks to Google Calendar & Google Tasks
3. Scanning Gmail for important announcements (Option C)
4. Dispatching timed milestone reminders (H-3, H-1, J-6, J-1, Due) to Discord DM
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from ayaka.config import Config
from ayaka.fetchers.base import SessionExpiredException
from ayaka.fetchers.edunex import EdunexFetcher
from ayaka.fetchers.gmail_reader import GmailReader
from ayaka.fetchers.omnicampus import OmnicampusFetcher
from ayaka.fetchers.six import SixFetcher
from ayaka.services.discord_bot import AyakaBot
from ayaka.services.google_sync import GoogleSyncService
from ayaka.storage.db import Database

logger = logging.getLogger("ayaka.scheduler")


def _apply_platform_result(
    db: Database,
    google_sync: Optional[GoogleSyncService],
    stats: dict[str, Any],
    plat_name: str,
    tasks: list[Any],
    meetings: list[Any],
    exc: Optional[Exception],
) -> None:
    """Persist one platform's fetch result and push changes to Google (blocking; run in a thread)."""
    if exc:
        if isinstance(exc, SessionExpiredException):
            logger.warning(f"Session expired for {plat_name}: {exc}")
            db.log_sync(plat_name, "expired", str(exc))
            stats["expired_sessions"].append(plat_name)
        else:
            logger.error(f"Error fetching from {plat_name}: {exc}")
            db.log_sync(plat_name, "error", str(exc))
        return

    logger.info(f"Fetched {len(tasks)} items from {plat_name}.")

    if meetings:
        for m in meetings:
            saved_m, is_new_m, was_upd_m = db.upsert_lecture_meeting(m)
            if was_upd_m and saved_m.get("_topic_changed"):
                stats["updated_tasks"] += 1
                stats["updated_items"].append({
                    "id": saved_m["id"],
                    "title": f"Topik: {saved_m['topic']}",
                    "platform": "six",
                    "course": f"{saved_m['course_code']} ({saved_m['meeting_date']})",
                    "due_date": "",
                })
        logger.info(f"Synchronized {len(meetings)} upcoming lecture meetings from SIX ITB.")

    for t in tasks:
        t_dict = t.to_dict() if hasattr(t, "to_dict") else t
        saved_task, is_new = db.upsert_task(t_dict)

        item_info = {
            "id": saved_task["id"],
            "title": saved_task.get("title", ""),
            "platform": saved_task.get("platform", plat_name),
            "course": saved_task.get("course_name") or saved_task.get("course_id") or "",
            "due_date": saved_task.get("due_date", ""),
        }

        if saved_task.get("_is_newly_completed"):
            stats["completed_tasks"] += 1
            stats["completed_items"].append(item_info)
        elif is_new:
            if saved_task.get("is_completed") == 1:
                stats["completed_tasks"] += 1
                stats["completed_items"].append(item_info)
            else:
                stats["new_tasks"] += 1
                stats["added_items"].append(item_info)
        elif saved_task.get("_due_date_changed") or saved_task.get("_title_changed"):
            stats["updated_tasks"] += 1
            stats["updated_items"].append(item_info)

        # Sync to Google if service enabled
        if google_sync:
            try:
                if saved_task.get("is_completed") == 1:
                    if saved_task.get("google_tasks_task_id"):
                        google_sync.mark_completed_in_google(saved_task["id"])
                    elif is_new:
                        google_sync.sync_task(saved_task)
                else:
                    google_sync.sync_task(saved_task)
            except Exception as e:
                logger.error(f"Failed to sync task {saved_task['id']} to Google: {e}")

    db.log_sync(plat_name, "success", f"Fetched {len(tasks)} items.")
    db.clear_session_alert(plat_name)


async def run_sync_cycle_async(
    config: Config,
    db: Database,
    platform: str = "all",
    google_sync: Optional[GoogleSyncService] = None,
) -> dict[str, Any]:
    """Execute concurrent asynchronous fetch and Google sync cycle across platforms."""
    stats: dict[str, Any] = {
        "new_tasks": 0,
        "updated_tasks": 0,
        "completed_tasks": 0,
        "expired_sessions": [],
        "added_items": [],
        "updated_items": [],
        "completed_items": [],
    }

    async def _fetch_platform(plat_name: str, fetcher: Any) -> tuple[str, list[Any], list[Any], Optional[Exception]]:
        try:
            tasks = await fetcher.fetch_tasks_async()
            meetings = []
            if plat_name == "six" and hasattr(fetcher, "fetch_lecture_meetings_async"):
                try:
                    meetings = await fetcher.fetch_lecture_meetings_async(fetch_modals=True, future_only=True)
                except Exception as me:
                    logger.warning(f"Error updating lecture meetings from SIX: {me}")
            return (plat_name, tasks, meetings, None)
        except Exception as e:
            return (plat_name, [], [], e)

    fetch_coroutines = []
    if platform in ("all", "edunex"):
        fetch_coroutines.append(_fetch_platform("edunex", EdunexFetcher(config)))
    if platform in ("all", "six"):
        fetch_coroutines.append(_fetch_platform("six", SixFetcher(config)))
    if platform in ("all", "omnicampus"):
        fetch_coroutines.append(_fetch_platform("omnicampus", OmnicampusFetcher(config)))

    results = await asyncio.gather(*fetch_coroutines)

    for plat_name, tasks, meetings, exc in results:
        # SQLite + Google API calls are blocking; keep them off the Discord event loop.
        await asyncio.to_thread(_apply_platform_result, db, google_sync, stats, plat_name, tasks, meetings, exc)

    return stats


def run_sync_cycle(
    config: Config,
    db: Database,
    platform: str = "all",
    google_sync: Optional[GoogleSyncService] = None,
) -> dict[str, Any]:
    """Execute a single synchronous fetch and Google sync cycle."""
    from ayaka.fetchers.base import run_coro_sync
    return run_coro_sync(run_sync_cycle_async(config, db, platform, google_sync))



async def reminder_loop(
    bot: AyakaBot,
    db: Database,
    interval_seconds: int = 60,
    config: Optional[Config] = None,
) -> None:
    """Continuously evaluates and sends reminder milestones configured in config.json."""
    await bot.wait_until_ready()
    logger.info("Ayaka reminder loop started.")

    cfg: Optional[Config] = config or getattr(bot, "config", None)

    while not bot.is_closed():
        try:
            if cfg and not cfg.reminders.tasks.enabled:
                await asyncio.sleep(interval_seconds)
                continue

            milestones = cfg.reminders.tasks.milestones if cfg else None
            now_utc = datetime.now(timezone.utc)
            needing = await asyncio.to_thread(db.get_tasks_needing_reminders, now_utc, milestones)
            for task, milestone in needing:
                logger.info(f"Triggering reminder [{milestone}] for task {task['id']} - {task['title']}")
                try:
                    sent = await bot.send_task_reminder(task, milestone)
                    if sent:
                        await asyncio.to_thread(db.mark_reminder_sent, task["id"], milestone)
                except Exception as task_err:
                    logger.error(f"Reminder [{milestone}] failed for task {task['id']}: {task_err}")
        except Exception as e:
            logger.error(f"Error in reminder loop: {e}")

        await asyncio.sleep(interval_seconds)


async def gmail_loop(bot: AyakaBot, config: Config, db: Database, google_sync: GoogleSyncService) -> None:
    """Continuously polls Gmail for Option C urgent academic messages."""
    await bot.wait_until_ready()
    logger.info("Ayaka Gmail monitoring loop started.")

    gmail_reader = GmailReader(config, google_creds=google_sync.creds)
    poll_sec = max(60, config.gmail.poll_interval_minutes * 60)

    while not bot.is_closed():
        try:
            if not gmail_reader.creds and google_sync.creds:
                gmail_reader.creds = google_sync.creds

            if gmail_reader.is_configured():
                messages = await asyncio.to_thread(gmail_reader.fetch_important_messages)
                for msg in messages:
                    if not await asyncio.to_thread(db.is_gmail_processed, msg["id"]):
                        sent = await bot.send_gmail_alert(msg)
                        if sent:
                            await asyncio.to_thread(
                                db.record_gmail_message,
                                message_id=msg["id"],
                                subject=msg.get("subject", ""),
                                sender=msg.get("sender", ""),
                                snippet=msg.get("snippet", ""),
                                received_at=msg.get("date", ""),
                            )
        except Exception as e:
            logger.error(f"Error in Gmail monitoring loop: {e}")

        await asyncio.sleep(poll_sec)


async def academic_sync_loop(
    bot: AyakaBot,
    config: Config,
    db: Database,
    google_sync: GoogleSyncService,
) -> None:
    """Periodically fetches updates from Edunex, SIX, and Omnicampus."""
    await bot.wait_until_ready()
    logger.info("Ayaka academic sync loop started.")

    interval_sec = max(300, config.sync_interval_minutes * 60)

    while not bot.is_closed():
        try:
            stats = await run_sync_cycle_async(config, db, "all", google_sync)
            await asyncio.to_thread(db.prune_ai_history)
            for plat_name in stats.get("expired_sessions", []):
                if await asyncio.to_thread(db.should_alert_session_expired, plat_name):
                    sent = await bot.send_session_expired_alert(plat_name)
                    if sent:
                        await asyncio.to_thread(db.record_session_alert, plat_name)
        except Exception as e:
            logger.error(f"Error in academic sync loop: {e}")

        await asyncio.sleep(interval_sec)


async def schedule_reminder_loop(
    bot: AyakaBot,
    schedule_service: Any,
    db: Database,
    interval_seconds: int = 60,
    config: Optional[Config] = None,
) -> None:
    """Continuously evaluates and sends lecture schedule reminders based on config.json:
    1. Daily morning briefing (configurable hour in config.json, default 05:00 WIB)
    2. Class start proactive reminder (configurable offset before start in config.json)
    3. Attendance proactive reminder (configurable offset before end in config.json)
    """
    await bot.wait_until_ready()
    logger.info("Ayaka lecture schedule reminder loop started.")

    cfg: Optional[Config] = config or getattr(bot, "config", None)

    cached_date: Optional[date] = None
    cached_events: list[dict[str, Any]] = []
    last_fetch_time: Optional[datetime] = None

    while not bot.is_closed():
        try:
            if cfg and not cfg.reminders.lectures.enabled:
                await asyncio.sleep(interval_seconds)
                continue

            tz = schedule_service.timezone_obj
            now_local = datetime.now(tz)
            today = now_local.date()
            today_str = today.strftime("%Y-%m-%d")

            # Dynamic parameters from config.json
            morning_enabled = cfg.reminders.lectures.morning_briefing_enabled if cfg else True
            morning_hour = cfg.reminders.lectures.morning_briefing_hour if cfg else 5
            tasks_lookahead = cfg.reminders.lectures.morning_briefing_tasks_lookahead_hours if cfg else 36.0

            adv_enabled = cfg.reminders.lectures.advance_reminder_enabled if cfg else True
            adv_offset_min = cfg.reminders.lectures.advance_reminder_minutes_before if cfg else 15

            start_enabled = cfg.reminders.lectures.class_start_reminder_enabled if cfg else True
            start_offset_min = cfg.reminders.lectures.class_start_reminder_minutes_before if cfg else 0

            attend_enabled = cfg.reminders.lectures.attendance_reminder_enabled if cfg else True
            attend_offset_min = cfg.reminders.lectures.attendance_reminder_minutes_before_end if cfg else 10

            # Refresh today's events if date changed or cache older than 10 minutes
            if (
                cached_date != today
                or last_fetch_time is None
                or (now_local - last_fetch_time).total_seconds() > 600
            ):
                cached_events = await asyncio.to_thread(schedule_service.get_events_for_date, today)
                cached_date = today
                last_fetch_time = now_local

            # 1. Daily morning briefing
            if morning_enabled and now_local.hour >= morning_hour:
                morning_rem_id = f"morning:{today_str}"
                if not await asyncio.to_thread(db.is_schedule_reminder_sent, morning_rem_id):
                    logger.info(f"Triggering morning lecture briefing for {today_str} at hour {now_local.hour} ({len(cached_events)} classes)")
                    tasks_due_soon = await asyncio.to_thread(db.get_tasks_due_soon, tasks_lookahead)
                    sent = await bot.send_schedule_morning_briefing(today, cached_events, tasks_due_soon)
                    if sent:
                        await asyncio.to_thread(
                            db.record_schedule_reminder,
                            reminder_id=morning_rem_id,
                            reminder_type="morning",
                            scheduled_for=today_str,
                        )

            # 2. Evaluate class-specific reminders for today's classes
            for ev in cached_events:
                ev_id = ev["id"]
                start_dt = ev["start_dt"]
                end_dt = ev["end_dt"]

                # A. Advance Preparation Reminder (e.g. 15 minutes before start)
                if adv_enabled and adv_offset_min > 0:
                    target_adv = start_dt - timedelta(minutes=adv_offset_min)
                    diff_adv = (now_local - target_adv).total_seconds()
                    if -120 <= diff_adv <= 300 and now_local < end_dt:
                        adv_rem_id = f"advance:{ev_id}:{today_str}"
                        if not await asyncio.to_thread(db.is_schedule_reminder_sent, adv_rem_id):
                            logger.info(f"Triggering advance class reminder for {ev['summary']} ({adv_rem_id})")
                            sent = await bot.send_class_advance_reminder(ev, adv_offset_min)
                            if sent:
                                await asyncio.to_thread(
                                    db.record_schedule_reminder,
                                    reminder_id=adv_rem_id,
                                    reminder_type="advance",
                                    event_id=ev_id,
                                    event_title=ev["summary"],
                                    scheduled_for=target_adv.isoformat(),
                                )

                # B. Class Start Reminder (target_start = start_dt - offset)
                if start_enabled:
                    target_start = start_dt - timedelta(minutes=start_offset_min)
                    diff_start = (now_local - target_start).total_seconds()
                    if -120 <= diff_start <= 300 and now_local < end_dt:
                        start_rem_id = f"start:{ev_id}:{today_str}"
                        if not await asyncio.to_thread(db.is_schedule_reminder_sent, start_rem_id):
                            logger.info(f"Triggering class start reminder for {ev['summary']} ({start_rem_id})")
                            sent = await bot.send_class_start_reminder(ev)
                            if sent:
                                await asyncio.to_thread(
                                    db.record_schedule_reminder,
                                    reminder_id=start_rem_id,
                                    reminder_type="start",
                                    event_id=ev_id,
                                    event_title=ev["summary"],
                                    scheduled_for=target_start.isoformat(),
                                )

                # C. Attendance / Presensi Reminder (target_attend = end_dt - offset)
                if attend_enabled:
                    attend_dt = end_dt - timedelta(minutes=attend_offset_min)
                    diff_attend = (now_local - attend_dt).total_seconds()
                    if -120 <= diff_attend <= 300 and now_local < end_dt:
                        attend_rem_id = f"attendance:{ev_id}:{today_str}"
                        if not await asyncio.to_thread(db.is_schedule_reminder_sent, attend_rem_id):
                            logger.info(f"Triggering attendance reminder for {ev['summary']} ({attend_rem_id})")
                            sent = await bot.send_class_attendance_reminder(ev)
                            if sent:
                                await asyncio.to_thread(
                                    db.record_schedule_reminder,
                                    reminder_id=attend_rem_id,
                                    reminder_type="attendance",
                                    event_id=ev_id,
                                    event_title=ev["summary"],
                                    scheduled_for=attend_dt.isoformat(),
                                )

        except Exception as e:
            logger.error(f"Error in lecture schedule reminder loop: {e}")

        await asyncio.sleep(interval_seconds)

