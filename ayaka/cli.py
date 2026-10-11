"""Command Line Interface for Ayaka.

Allows managing tasks, checking synchronization status, triggering manual fetches,
and running the bot service directly from the terminal or conversational assistant.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from ayaka.config import Config
from ayaka.storage.db import Database


def _format_table(headers: list[str], rows: list[list[str]]) -> str:
    """Simple ANSI-free text table formatter."""
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(cell))

    header_line = " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    separator = "-+-".join("-" * col_widths[i] for i in range(len(headers)))
    data_lines = [
        " | ".join(cell.ljust(col_widths[i]) for i, cell in enumerate(row))
        for row in rows
    ]
    return f"{header_line}\n{separator}\n" + "\n".join(data_lines)


def cmd_status(config: Config, db: Database) -> int:
    """Print system and configuration status."""
    summary = config.summary()
    print("=== Ayaka Status ===")
    print(f"Timezone:             {config.timezone}")
    print(f"Database Path:        {config.database_path}")
    print(f"Discord Configured:   {'[YES]' if summary['discord_configured'] else '[NO]'}")
    print(f"Google Credentials:   {'[YES]' if summary['google_credentials_found'] else '[NO]'}")
    print(f"Edunex Configured:    {'[YES]' if summary['edunex_configured'] else '[NO]'}")
    print(f"SIX ITB Configured:   {'[YES]' if summary['six_configured'] else '[NO]'}")
    print(f"Omnicampus Configured:{'[YES]' if summary['omnicampus_configured'] else '[NO]'}")

    tasks = db.list_tasks(include_completed=True)
    pending_count = sum(1 for t in tasks if not t["is_completed"])
    completed_count = sum(1 for t in tasks if t["is_completed"])
    print(f"\nTotal Tasks:          {len(tasks)} (Pending: {pending_count}, Completed: {completed_count})")
    return 0


def cmd_list(db: Database, all_tasks: bool = False, platform: Optional[str] = None) -> int:
    """List pending or all academic tasks."""
    tasks = db.list_tasks(include_completed=all_tasks, platform=platform)
    if not tasks:
        state_label = "recorded" if all_tasks else "pending"
        print(f"No {state_label} academic tasks found.")
        return 0

    headers = ["Task ID", "Platform", "Course", "Title", "Due Date", "Status"]
    rows = []
    for t in tasks:
        status_str = "COMPLETED" if t["is_completed"] else "PENDING"
        course_str = t.get("course_id") or t.get("course_name") or "-"
        due_raw = t.get("due_date", "-")
        rows.append([
            t["id"],
            t.get("platform", "-"),
            course_str[:12],
            t.get("title", "-")[:35],
            due_raw[:16].replace("T", " "),
            status_str,
        ])

    print(_format_table(headers, rows))
    return 0


def cmd_complete(db: Database, task_id: str) -> int:
    """Mark a task as completed."""
    existing = db.get_task(task_id)
    if not existing:
        print(f"Error: Task with ID '{task_id}' was not found in database.")
        return 1

    success = db.mark_task_completed(task_id)
    if success:
        print(f"Success: Task '{existing['title']}' ({task_id}) marked as COMPLETED.")
        print("Upcoming milestone reminders for this task are now halted.")
        return 0
    else:
        print(f"Error: Failed to update status for task '{task_id}'.")
        return 1


def cmd_add(
    db: Database,
    title: str,
    due_date: str,
    course: str = "",
    description: str = "",
    platform: str = "manual",
) -> int:
    """Manually add a task or deadline."""
    try:
        dt = datetime.fromisoformat(due_date)
        due_iso = dt.isoformat()
    except Exception:
        print(f"Error: Invalid date format '{due_date}'. Use ISO 8601 format (YYYY-MM-DDTHH:MM:SS).")
        return 1

    import uuid
    task_id = f"manual:{uuid.uuid4().hex[:8]}"

    task_data = {
        "id": task_id,
        "platform": platform,
        "course_id": course,
        "course_name": course,
        "title": title,
        "description": description,
        "due_date": due_iso,
    }
    _, is_new = db.upsert_task(task_data)
    print(f"Success: Task '{title}' ({task_id}) created. Due: {due_iso}")
    return 0


def cmd_auth_google(config: Config, db: Database) -> int:
    """Run interactive Google OAuth authentication to generate token.json."""
    import os
    import shutil

    # Prioritize Brave browser if available on the system
    brave_bin = shutil.which("brave") or shutil.which("brave-browser")
    if brave_bin and "BROWSER" not in os.environ:
        os.environ["BROWSER"] = brave_bin

    from ayaka.services.google_sync import GoogleSyncService
    print("Initiating Google OAuth authentication flow...")
    target_browser = "Brave" if brave_bin else "default browser"
    print(f"Opening {target_browser}... Please log in with your Google account and grant permissions.")
    svc = GoogleSyncService(config, db)
    if svc.authenticate():
        print(f"Success: Google OAuth authenticated! Token saved to: {config.google.token_file}")
        return 0
    else:
        print("Error: Google OAuth authentication failed. Please verify credentials.json and console logs.")
        return 1


def cmd_test_dm(config: Config, db: Database) -> int:
    """Send a test greeting DM via Discord to verify bot token and user ID."""
    import asyncio
    from ayaka.services.discord_bot import send_test_greeting
    print(f"Connecting to Discord as Ayaka to send a greeting DM to user ID {config.discord.user_id}...")
    success = asyncio.run(send_test_greeting(config, db))
    if success:
        print("Success! Test greeting DM sent to your Discord. Check your Discord DMs!")
        return 0
    else:
        print("Error: Failed to send DM. Please verify DISCORD_BOT_TOKEN and DISCORD_USER_ID, and ensure you allow DMs from server members.")
        return 1


def main(argv: list[str] | None = None) -> None:
    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        prog="ayaka",
        description="Ayaka: ITB Academic Assistant & Notification Bot",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # Status
    subparsers.add_parser("status", help="Check system, credentials, and database status")

    # List
    parser_list = subparsers.add_parser("list", help="List academic tasks and deadlines")
    parser_list.add_argument("--all", action="store_true", help="Include completed tasks")
    parser_list.add_argument("--platform", type=str, default=None, help="Filter by platform (edunex, six, omnicampus, manual)")

    # Complete
    parser_comp = subparsers.add_parser("complete", help="Mark a task as completed")
    parser_comp.add_argument("task_id", type=str, help="ID of the task to complete")

    # Add
    parser_add = subparsers.add_parser("add", help="Manually insert an assignment or event deadline")
    parser_add.add_argument("title", type=str, help="Task title")
    parser_add.add_argument("due_date", type=str, help="Deadline in ISO format (e.g. 2026-10-15T23:59:00)")
    parser_add.add_argument("--course", type=str, default="", help="Course code or name")
    parser_add.add_argument("--desc", type=str, default="", help="Task description")

    # Auth Google
    subparsers.add_parser("auth-google", help="Authenticate with Google Workspace (Calendar, Tasks, Gmail)")

    # Test DM
    subparsers.add_parser("test-dm", help="Send a test greeting DM via Discord to verify credentials")

    # Bot
    parser_bot = subparsers.add_parser("bot", help="Launch the Discord Bot service with 24/7 background scheduler")
    parser_bot.add_argument("--standalone", action="store_true", help="Launch bot only without background scheduler loops")

    # Sync / Fetch
    parser_sync = subparsers.add_parser("sync", help="Trigger on-demand fetch and sync cycle")
    parser_sync.add_argument("--platform", type=str, default="all", help="Platform to fetch (edunex, six, omnicampus, gmail, all)")

    args = parser.parse_args(argv)

    if not args.subcommand:
        parser.print_help()
        sys.exit(0)

    config = Config.load()
    db = Database(config.database_path)

    if args.subcommand == "status":
        sys.exit(cmd_status(config, db))
    elif args.subcommand == "auth-google":
        sys.exit(cmd_auth_google(config, db))
    elif args.subcommand == "test-dm":
        sys.exit(cmd_test_dm(config, db))
    elif args.subcommand == "list":
        sys.exit(cmd_list(db, all_tasks=args.all, platform=args.platform))
    elif args.subcommand == "complete":
        sys.exit(cmd_complete(db, args.task_id))
    elif args.subcommand == "add":
        sys.exit(cmd_add(db, args.title, args.due_date, course=args.course, description=args.desc))
    elif args.subcommand == "bot":
        from ayaka.services.discord_bot import run_bot
        run_bot(config, db, daemon=not args.standalone)
    elif args.subcommand == "sync":
        from ayaka.scheduler import run_sync_cycle
        run_sync_cycle(config, db, platform=args.platform)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
