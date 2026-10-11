"""Ayaka Configuration Loader.

Separates operational settings (config.json) from private credentials (.env).
- config.json: Gmail keywords, domains, intervals, platform URLs, timezone, and dialogue mapping.
- .env: Discord bot token, user ID, academic session cookies, and Google OAuth credentials.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List

from dotenv import load_dotenv


def update_env_variable(key: str, value: str, env_path: Path | None = None) -> bool:
    """Safely update or append a key=value pair in the .env file and update os.environ."""
    if env_path is None:
        env_path = Path(__file__).resolve().parent.parent / ".env"

    os.environ[key] = value

    lines = []
    found = False
    if env_path.is_file():
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped.startswith(f"{key}=") or stripped.startswith(f"{key} ="):
                        lines.append(f"{key}={value}\n")
                        found = True
                    else:
                        lines.append(line)
        except Exception:
            pass

    if not found:
        lines.append(f"{key}={value}\n")

    try:
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        return True
    except Exception:
        return False


@dataclass
class DiscordConfig:
    bot_token: str = ""
    user_id: int = 0

    @property
    def is_configured(self) -> bool:
        return bool(self.bot_token and self.user_id)


@dataclass
class GoogleConfig:
    credentials_file: str = "credentials.json"
    token_file: str = "token.json"
    calendar_id: str = "primary"
    tasks_list_id: str = "@default"
    schedule_calendar_id: str = "5fcc5f6e8055f705bee196c5f2edb626badfee2551ca19995ca4663e2a93c3b4@group.calendar.google.com"
    sync_calendar: bool = False
    sync_tasks: bool = True

    @property
    def has_credentials(self) -> bool:
        return Path(self.credentials_file).is_file() or Path(self.token_file).is_file()


@dataclass
class GmailConfig:
    domains: List[str] = field(default_factory=lambda: ["itb.ac.id", "mahasiswa.itb.ac.id"])
    keywords: List[str] = field(default_factory=list)
    max_results: int = 15
    poll_interval_minutes: int = 5


@dataclass
class PlatformEndpoints:
    edunex_base_url: str = "https://edunex.itb.ac.id"
    six_base_url: str = "https://six.itb.ac.id"
    omnicampus_base_url: str = "https://edu.omnicamp.us"


@dataclass
class AcademicConfig:
    edunex_cookie: str = ""
    edunex_bearer_token: str = ""
    six_cookie: str = ""
    omnicampus_token: str = ""
    omnicampus_cookie: str = ""
    edunex_period_id: int = 26
    six_student_id: str = "18223113"
    six_semester_code: str = "2026-1"
    omnicampus_course_ids: List[int] = field(default_factory=lambda: [170])
    endpoints: PlatformEndpoints = field(default_factory=PlatformEndpoints)

    @property
    def has_edunex(self) -> bool:
        return bool(self.edunex_cookie or self.edunex_bearer_token)

    @property
    def has_six(self) -> bool:
        return bool(self.six_cookie)

    @property
    def has_omnicampus(self) -> bool:
        return bool(self.omnicampus_token or self.omnicampus_cookie)


@dataclass
class SchedulerConfig:
    sync_interval_minutes: int = 30
    reminder_poll_interval_seconds: int = 60


@dataclass
class TaskMilestoneConfig:
    key: str
    label: str = ""
    hours: float = 0.0


@dataclass
class TaskRemindersConfig:
    enabled: bool = True
    milestones: List[TaskMilestoneConfig] = field(default_factory=lambda: [
        TaskMilestoneConfig(key="h3", label="H-3 (3 hari sebelum)", hours=72.0),
        TaskMilestoneConfig(key="h1", label="H-1 (24 jam sebelum)", hours=24.0),
        TaskMilestoneConfig(key="j6", label="J-6 (6 jam sebelum)", hours=6.0),
        TaskMilestoneConfig(key="j1", label="J-1 (1 jam sebelum)", hours=1.0),
        TaskMilestoneConfig(key="due", label="Due (Batas waktu tiba)", hours=0.0),
    ])


@dataclass
class LectureRemindersConfig:
    enabled: bool = True
    morning_briefing_enabled: bool = True
    morning_briefing_hour: int = 5
    morning_briefing_tasks_lookahead_hours: float = 36.0
    advance_reminder_enabled: bool = True
    advance_reminder_minutes_before: int = 15
    class_start_reminder_enabled: bool = True
    class_start_reminder_minutes_before: int = 0
    attendance_reminder_enabled: bool = True
    attendance_reminder_minutes_before_end: int = 10


@dataclass
class RemindersConfig:
    tasks: TaskRemindersConfig = field(default_factory=TaskRemindersConfig)
    lectures: LectureRemindersConfig = field(default_factory=LectureRemindersConfig)


@dataclass
class AIConfig:
    api_key: str = ""
    provider: str = "gemini"
    model: str = "gemini-3.5-flash"
    base_url: str = ""

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)


@dataclass
class Config:
    discord: DiscordConfig
    google: GoogleConfig
    gmail: GmailConfig
    academic: AcademicConfig
    scheduler: SchedulerConfig
    ai: AIConfig
    reminders: RemindersConfig = field(default_factory=RemindersConfig)
    database_path: str = "data/ayaka_state.db"
    dialogue_file: str = "dialogues.json"
    task_filters_file: str = "task_filters.json"
    timezone: str = "Asia/Jakarta"

    @property
    def sync_interval_minutes(self) -> int:
        """Backward compatibility helper."""
        return self.scheduler.sync_interval_minutes

    @classmethod
    def load(cls, base_dir: Path | None = None) -> Config:
        if base_dir is None:
            base_dir = Path(__file__).resolve().parent.parent

        # 1. Load operational settings from config.json
        config_json_path = base_dir / "config.json"
        c_data: dict[str, Any] = {}
        if config_json_path.is_file():
            try:
                with open(config_json_path, "r", encoding="utf-8") as f:
                    c_data = json.load(f)
            except Exception:
                c_data = {}

        system_data = c_data.get("system", {})
        gmail_data = c_data.get("gmail", {})
        sched_data = c_data.get("scheduler", {})
        plat_data = c_data.get("platforms", {})
        google_data = c_data.get("google", {})

        # 2. Load private credentials from .env
        env_file = base_dir / ".env"
        load_dotenv(env_file)

        raw_user_id = os.getenv("DISCORD_USER_ID", "").strip()
        user_id = int(raw_user_id) if raw_user_id.isdigit() else 0

        # System paths & timezone
        timezone_val = os.getenv("TZ", system_data.get("timezone", "Asia/Jakarta")).strip()
        db_path = os.getenv("DATABASE_PATH", system_data.get("database_path", "data/ayaka_state.db")).strip()
        if not os.path.isabs(db_path):
            db_path = str(base_dir / db_path)

        dialogue_file = os.getenv("DIALOGUE_FILE", system_data.get("dialogue_file", "dialogues.json")).strip()
        if not os.path.isabs(dialogue_file):
            dialogue_file = str(base_dir / dialogue_file)

        task_filters_file = os.getenv("TASK_FILTERS_FILE", system_data.get("task_filters_file", "task_filters.json")).strip()
        if not os.path.isabs(task_filters_file):
            task_filters_file = str(base_dir / task_filters_file)

        # Google files
        cred_file = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json").strip()
        if not os.path.isabs(cred_file):
            cred_file = str(base_dir / cred_file)

        tok_file = os.getenv("GOOGLE_TOKEN_FILE", "token.json").strip()
        if not os.path.isabs(tok_file):
            tok_file = str(base_dir / tok_file)

        # Gmail configuration
        domains = gmail_data.get("monitor_domains") or ["itb.ac.id", "mahasiswa.itb.ac.id"]
        keywords = gmail_data.get("important_keywords") or [
            "assignment", "exam", "midterm", "final", "deadline", "announcement",
            "lecture", "grade", "score", "lecturer", "quiz", "practicum", "schedule",
            "tugas", "ujian", "uts", "uas", "pengumuman", "kuliah", "nilai",
            "dosen", "asistensi", "kuis", "praktikum", "revisi", "batal", "jadwal",
        ]
        max_results = int(gmail_data.get("max_results", 15))
        poll_min = int(gmail_data.get("poll_interval_minutes", 5))

        # Scheduler
        sync_interval = int(sched_data.get("academic_sync_interval_minutes", 30))
        rem_poll_sec = int(sched_data.get("reminder_poll_interval_seconds", 60))

        # Academic platforms dynamic settings
        edunex_cfg = plat_data.get("edunex", {})
        six_cfg = plat_data.get("six", {})
        omni_cfg = plat_data.get("omnicampus", {})

        raw_period = os.getenv("EDUNEX_PERIOD_ID", "").strip()
        period_id = int(raw_period) if raw_period.isdigit() else int(edunex_cfg.get("period_id", 26))

        six_student_id = os.getenv("SIX_STUDENT_ID", str(six_cfg.get("student_id", "18223113"))).strip()
        six_semester_code = os.getenv("SIX_SEMESTER_CODE", str(six_cfg.get("semester_code", "2026-1"))).strip()

        raw_omni_courses = os.getenv("OMNICAMPUS_COURSE_IDS", "").strip()
        if raw_omni_courses:
            try:
                omni_cids = [int(x.strip()) for x in raw_omni_courses.split(",") if x.strip()]
            except Exception:
                omni_cids = [170]
        else:
            raw_json_cids = omni_cfg.get("course_ids", [170])
            omni_cids = [int(x) for x in raw_json_cids] if isinstance(raw_json_cids, list) else [170]

        # Endpoints
        endpoints = PlatformEndpoints(
            edunex_base_url=edunex_cfg.get("base_url", "https://edunex.itb.ac.id"),
            six_base_url=six_cfg.get("base_url", "https://six.itb.ac.id"),
            omnicampus_base_url=omni_cfg.get("base_url", "https://edu.omnicamp.us"),
        )

        # Reminders configuration
        rem_data = c_data.get("reminders", {})
        task_rem_data = rem_data.get("tasks", {})
        raw_milestones = task_rem_data.get("milestones", [])
        milestones_list: list[TaskMilestoneConfig] = []
        if isinstance(raw_milestones, list):
            for m in raw_milestones:
                if isinstance(m, dict) and "key" in m:
                    milestones_list.append(
                        TaskMilestoneConfig(
                            key=str(m["key"]).strip().lower(),
                            label=str(m.get("label", m["key"])),
                            hours=float(m.get("hours", 0)),
                        )
                    )
        if not milestones_list:
            milestones_list = [
                TaskMilestoneConfig(key="h3", label="H-3 (3 hari sebelum)", hours=72.0),
                TaskMilestoneConfig(key="h1", label="H-1 (24 jam sebelum)", hours=24.0),
                TaskMilestoneConfig(key="j6", label="J-6 (6 jam sebelum)", hours=6.0),
                TaskMilestoneConfig(key="j1", label="J-1 (1 jam sebelum)", hours=1.0),
                TaskMilestoneConfig(key="due", label="Due (Batas waktu tiba)", hours=0.0),
            ]

        task_rem_cfg = TaskRemindersConfig(
            enabled=bool(task_rem_data.get("enabled", True)),
            milestones=milestones_list,
        )

        lec_rem_data = rem_data.get("lectures", {})
        mb_data = lec_rem_data.get("morning_briefing") if isinstance(lec_rem_data.get("morning_briefing"), dict) else {}
        adv_data = lec_rem_data.get("advance_reminder") if isinstance(lec_rem_data.get("advance_reminder"), dict) else {}
        cs_data = lec_rem_data.get("class_start") if isinstance(lec_rem_data.get("class_start"), dict) else {}
        att_data = lec_rem_data.get("attendance") if isinstance(lec_rem_data.get("attendance"), dict) else {}

        lec_rem_cfg = LectureRemindersConfig(
            enabled=bool(lec_rem_data.get("enabled", True)),
            morning_briefing_enabled=bool(mb_data.get("enabled", lec_rem_data.get("morning_briefing_enabled", True))),
            morning_briefing_hour=int(mb_data.get("hour", lec_rem_data.get("morning_briefing_hour", 5))),
            morning_briefing_tasks_lookahead_hours=float(
                mb_data.get("tasks_lookahead_hours", lec_rem_data.get("morning_briefing_tasks_lookahead_hours", 36.0))
            ),
            advance_reminder_enabled=bool(adv_data.get("enabled", lec_rem_data.get("advance_reminder_enabled", True))),
            advance_reminder_minutes_before=int(
                adv_data.get("minutes_before", lec_rem_data.get("advance_reminder_minutes_before", 15))
            ),
            class_start_reminder_enabled=bool(cs_data.get("enabled", lec_rem_data.get("class_start_reminder_enabled", True))),
            class_start_reminder_minutes_before=int(
                cs_data.get("minutes_before", lec_rem_data.get("class_start_reminder_minutes_before", 0))
            ),
            attendance_reminder_enabled=bool(att_data.get("enabled", lec_rem_data.get("attendance_reminder_enabled", True))),
            attendance_reminder_minutes_before_end=int(
                att_data.get("minutes_before_end", lec_rem_data.get("attendance_reminder_minutes_before_end", 10))
            ),
        )

        reminders_cfg = RemindersConfig(
            tasks=task_rem_cfg,
            lectures=lec_rem_cfg,
        )

        return cls(
            discord=DiscordConfig(
                bot_token=os.getenv("DISCORD_BOT_TOKEN", "").strip(),
                user_id=user_id,
            ),
            google=GoogleConfig(
                credentials_file=cred_file,
                token_file=tok_file,
                calendar_id=os.getenv("GOOGLE_CALENDAR_ID", google_data.get("calendar_id", "primary")).strip(),
                tasks_list_id=os.getenv("GOOGLE_TASKS_LIST_ID", google_data.get("tasks_list_id", "@default")).strip(),
                schedule_calendar_id=os.getenv(
                    "GOOGLE_SCHEDULE_CALENDAR_ID",
                    google_data.get("schedule_calendar_id", "5fcc5f6e8055f705bee196c5f2edb626badfee2551ca19995ca4663e2a93c3b4@group.calendar.google.com"),
                ).strip(),
                sync_calendar=bool(str(os.getenv("GOOGLE_SYNC_CALENDAR", google_data.get("sync_calendar", False))).lower() in ("true", "1", "yes")),
                sync_tasks=bool(str(os.getenv("GOOGLE_SYNC_TASKS", google_data.get("sync_tasks", True))).lower() in ("true", "1", "yes")),
            ),
            gmail=GmailConfig(
                domains=[d.strip().lower() for d in domains],
                keywords=[k.strip().lower() for k in keywords],
                max_results=max_results,
                poll_interval_minutes=poll_min,
            ),
            academic=AcademicConfig(
                edunex_cookie=os.getenv("EDUNEX_COOKIE", "").strip(),
                edunex_bearer_token=os.getenv("EDUNEX_BEARER_TOKEN", "").strip(),
                six_cookie=os.getenv("SIX_COOKIE", "").strip(),
                omnicampus_token=os.getenv("OMNICAMPUS_TOKEN", "").strip(),
                omnicampus_cookie=os.getenv("OMNICAMPUS_COOKIE", "").strip(),
                edunex_period_id=period_id,
                six_student_id=six_student_id,
                six_semester_code=six_semester_code,
                omnicampus_course_ids=omni_cids,
                endpoints=endpoints,
            ),
            scheduler=SchedulerConfig(
                sync_interval_minutes=sync_interval,
                reminder_poll_interval_seconds=rem_poll_sec,
            ),
            ai=AIConfig(
                api_key=(os.getenv("AI_API_KEY") or os.getenv("GEMINI_API_KEY", "")).strip(),
                provider=os.getenv("AI_PROVIDER", "gemini").strip().lower(),
                model=(os.getenv("AI_MODEL") or os.getenv("GEMINI_MODEL") or "gemini-3.5-flash").strip(),
                base_url=os.getenv("AI_BASE_URL", "").strip(),
            ),
            reminders=reminders_cfg,
            database_path=db_path,
            dialogue_file=dialogue_file,
            task_filters_file=task_filters_file,
            timezone=timezone_val,
        )

    def summary(self) -> dict[str, bool]:
        """Safe overview of configured services without revealing secrets."""
        return {
            "discord_configured": self.discord.is_configured,
            "google_credentials_found": self.google.has_credentials,
            "edunex_configured": self.academic.has_edunex,
            "six_configured": self.academic.has_six,
            "omnicampus_configured": self.academic.has_omnicampus,
            "ai_configured": self.ai.is_configured,
        }

