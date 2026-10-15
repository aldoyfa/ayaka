"""Dialogue and UI Presentation Manager for Ayaka.

Manages anime-style conversational responses, dialogue mapping from dialogues.json,
and aesthetic UI element generation (Discord timestamps, visual progress bars).
"""

from __future__ import annotations

import json
import logging
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("ayaka.dialogue")


class DialogueManager:
    """Loads and formats character dialogues from a dedicated JSON configuration."""

    DEFAULT_FALLBACKS = {
        "h3_reminder": {
            "title": "❄️ Ayaka's Gentle Reminder — 3 Days Remaining",
            "color": "0x5DADE2",
            "dialogues": ["Greetings, Master. A gentle reminder that {course} is due in three days."],
        },
        "h1_reminder": {
            "title": "🌸 Ayaka's Notice — Due Tomorrow",
            "color": "0xF39C12",
            "dialogues": ["Tomorrow is the deadline for {title}. Please take care and prepare well."],
        },
        "j6_reminder": {
            "title": "⚡ Ayaka's Vigil — 6 Hours Remaining",
            "color": "0xE67E22",
            "dialogues": ["Only 6 hours remain for {title}! Please ensure your submission is underway."],
        },
        "j1_reminder": {
            "title": "🚨 Urgent Submission Alert — 1 Hour Left!",
            "color": "0xE74C3C",
            "dialogues": ["Only 1 hour remains for {title}! Please submit right now, Master!"],
        },
        "due_reminder": {
            "title": "⏳ The Due Hour Has Arrived",
            "color": "0x992D22",
            "dialogues": ["The deadline for {title} has arrived. Rest well if you have submitted."],
        },
        "task_completed": {
            "dialogues": ["Splendid work, Master! I have marked {title} as completed. 🍵"],
        },
        "gmail_alert": {
            "title": "📬 Urgent Correspondence Received",
            "color": "0x9B59B6",
            "dialogues": ["An important academic message from {sender} requires your attention, Master."],
        },
        "no_tasks": {
            "dialogues": ["Your schedule is free of pending tasks right now, Master! 🌸"],
        },
        "task_list_header": {
            "title": "📜 Ayaka's Academic Ledger",
            "dialogues": ["Here is the ledger of your ongoing commitments, Master:"],
        },
        "task_added": {
            "dialogues": ["I have recorded {title} into our ledger, Master."],
        },
        "session_expired": {
            "title": "⚠️ Access Interruption Notice",
            "dialogues": ["My access to {platform} has expired. Please refresh your session credentials."],
        },
        "greetings": {
            "title": "👋 Hello, Master!",
            "dialogues": ["Ayaka is ready to assist your academic journey, Master!"],
        },
    }

    def __init__(self, config_file: str = "dialogues.json", active_personality: Optional[str] = None):
        self.config_path = Path(config_file)
        self.preferred_personality = active_personality
        self.data: dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        """Load dialogues from file, falling back gracefully if missing or invalid."""
        if not self.config_path.is_file():
            # Check parent directory fallback
            alt_path = Path(__file__).resolve().parent.parent / "dialogues.json"
            if alt_path.is_file():
                self.config_path = alt_path

        if self.config_path.is_file():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
                logger.info(f"Loaded multi-personality dialogues from {self.config_path}")
                return
            except Exception as e:
                logger.error(f"Error reading dialogues from {self.config_path}: {e}")

        logger.warning("Using built-in default dialogues fallback.")
        self.data = {
            "active_personality": "deredere",
            "personalities": {"deredere": {"scenarios": self.DEFAULT_FALLBACKS}},
        }

    @property
    def current_personality_key(self) -> str:
        """Get the active personality key (e.g. 'deredere', 'tsundere', etc.)."""
        if self.preferred_personality:
            return self.preferred_personality.strip().lower()
        return self.data.get("active_personality", "deredere").strip().lower()

    def set_personality(self, personality_key: str) -> None:
        """Dynamically switch character personality."""
        self.preferred_personality = personality_key.strip().lower()

    def list_personalities(self) -> list[str]:
        """List all available personality keys."""
        personalities = self.data.get("personalities", {})
        if personalities:
            return sorted(list(personalities.keys()))
        if "scenarios" in self.data:
            return ["deredere"]
        return ["deredere"]

    def _get_active_scenarios(self) -> dict[str, Any]:
        """Get the scenario dictionary for the currently active personality."""
        personalities = self.data.get("personalities", {})
        active_key = self.current_personality_key

        p_obj = personalities.get(active_key)
        if not p_obj and "deredere" in personalities:
            p_obj = personalities["deredere"]
        elif not p_obj and personalities:
            # Fallback to first available personality
            p_obj = next(iter(personalities.values()))

        if p_obj and isinstance(p_obj, dict) and "scenarios" in p_obj:
            return p_obj["scenarios"]

        # Support backward-compatible flat scenarios structure
        if "scenarios" in self.data and isinstance(self.data["scenarios"], dict):
            return self.data["scenarios"]

        # Final fallback to built-in defaults
        return self.DEFAULT_FALLBACKS

    def get_personality_meta(self, personality_key: Optional[str] = None) -> dict[str, Any]:
        """Get display name, description, and avatar URL for specified or active personality."""
        active_key = (personality_key or self.current_personality_key).strip().lower()
        p_obj = self.data.get("personalities", {}).get(active_key, {})
        return {
            "key": active_key,
            "display_name": p_obj.get("display_name", f"Ayaka ({active_key.title()})"),
            "description": p_obj.get("description", ""),
            "avatar_url": p_obj.get("avatar_url", self.data.get("avatar_url", "")),
        }

    def get_scenario(self, scenario_key: str) -> dict[str, Any]:
        scenarios = self._get_active_scenarios()
        return scenarios.get(scenario_key, self.DEFAULT_FALLBACKS.get(scenario_key, {}))

    def get_dialogue(self, scenario_key: str, **kwargs) -> str:
        """Get a dialogue line with template variable substitution."""
        scenario = self.get_scenario(scenario_key)
        dialogues = scenario.get("dialogues", [])
        if not dialogues:
            dialogues = self.DEFAULT_FALLBACKS.get(scenario_key, {}).get("dialogues", ["..."])

        selected = random.choice(dialogues)
        try:
            return selected.format(**kwargs)
        except Exception:
            return selected

    def get_title(self, scenario_key: str, default: str = "Notice") -> str:
        scenario = self.get_scenario(scenario_key)
        return scenario.get("title", default)

    def get_color(self, scenario_key: str, default_color: int = 0x5DADE2) -> int:
        scenario = self.get_scenario(scenario_key)
        raw_color = scenario.get("color")
        if not raw_color:
            return default_color
        try:
            if isinstance(raw_color, str) and raw_color.startswith("0x"):
                return int(raw_color, 16)
            return int(raw_color)
        except Exception:
            return default_color


def generate_progress_bar(due_dt: datetime, now_dt: datetime, total_span_hours: float = 72.0) -> str:
    """Generate a clean visual ASCII progress bar showing elapsed time window.

    Example: `[▰▰▰▰▰▰▱▱▱▱] 60% elapsed`
    """
    remaining_hours = (due_dt - now_dt).total_seconds() / 3600.0
    if remaining_hours <= 0:
        return "`[▰▰▰▰▰▰▰▰▰▰]` **100% (Deadline Arrived)**"

    elapsed_hours = max(0.0, total_span_hours - remaining_hours)
    progress_ratio = min(1.0, max(0.0, elapsed_hours / total_span_hours))
    total_blocks = 10
    filled = int(round(progress_ratio * total_blocks))
    unfilled = total_blocks - filled

    bar = "▰" * filled + "▱" * unfilled
    pct = int(progress_ratio * 100)
    return f"`[{bar}]` **{pct}% elapsed**"


def format_discord_timestamp(dt: datetime) -> tuple[str, str]:
    """Return tuple of (Relative '<t:unix:R>', Full DateTime '<t:unix:F>')."""
    unix_ts = int(dt.timestamp())
    return f"<t:{unix_ts}:R>", f"<t:{unix_ts}:F>"
