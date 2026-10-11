"""Ayaka Main Application Runner.

Launches the background 24/7 daemon on VPS with Discord Bot,
scheduler loops, Google Workspace synchronization, and Gmail monitor.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from ayaka.config import Config
from ayaka.scheduler import (
    academic_sync_loop,
    gmail_loop,
    reminder_loop,
    run_sync_cycle,
    schedule_reminder_loop,
)
from ayaka.services.discord_bot import AyakaBot
from ayaka.services.google_sync import GoogleSyncService
from ayaka.services.schedule_service import ScheduleService
from ayaka.storage.db import Database


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


class DaemonBot(AyakaBot):
    """AyakaBot augmented with lifecycle scheduler tasks for 24/7 VPS operation."""

    async def setup_hook(self) -> None:
        await super().setup_hook()
        # Spawn concurrent background loops
        self.loop.create_task(reminder_loop(self, self.db))
        self.loop.create_task(gmail_loop(self, self.config, self.db, self.google_sync))
        self.loop.create_task(academic_sync_loop(self, self.config, self.db, self.google_sync))
        if self.schedule_service:
            self.loop.create_task(schedule_reminder_loop(self, self.schedule_service, self.db))


def main() -> None:
    setup_logging()
    logger = logging.getLogger("ayaka.main")

    parser = argparse.ArgumentParser(description="Ayaka: ITB Academic Assistant & Notification Bot")
    parser.add_argument("--sync-only", action="store_true", help="Execute single fetch cycle and exit")
    parser.add_argument("--platform", default="all", help="Target platform for --sync-only (edunex, six, omnicampus, all)")
    args = parser.parse_args()

    config = Config.load()
    db = Database(config.database_path)
    google_sync = GoogleSyncService(config, db)

    # Attempt early Google authentication if credentials exist
    if config.google.has_credentials:
        logger.info("Initializing Google Workspace connection...")
        google_sync.authenticate()

    if args.sync_only:
        logger.info("Running single sync cycle...")
        stats = run_sync_cycle(config, db, platform=args.platform, google_sync=google_sync)
        print(f"Completed: {stats['new_tasks']} new tasks, {stats['updated_tasks']} tasks updated.")
        return

    # Daemon / Bot Mode
    if not config.discord.is_configured:
        logger.error(
            "DISCORD_BOT_TOKEN or DISCORD_USER_ID is not configured in .env! "
            "Please populate your .env file before starting the daemon."
        )
        sys.exit(1)

    schedule_service = ScheduleService(config, db, google_sync)

    logger.info("Starting Ayaka Daemon Bot...")
    bot = DaemonBot(config, db, google_sync, schedule_service)
    bot.run(config.discord.bot_token)


if __name__ == "__main__":
    main()
