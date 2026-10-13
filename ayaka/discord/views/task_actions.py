"""Task Action View for Discord reminder and task notifications.

The "Mark Complete" button is a persistent DynamicItem: its custom_id encodes the task
ID, so it keeps working on old DMs after the bot restarts (register it with
``bot.add_dynamic_items(CompleteTaskButton)``).
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, TYPE_CHECKING

import discord

from ayaka.discord.safe import safe_http_url

if TYPE_CHECKING:
    from ayaka.storage.db import Database
    from ayaka.dialogue import DialogueManager

logger = logging.getLogger("ayaka.discord.views.task_actions")

COMPLETE_PREFIX = "ayaka:complete:"
MAX_CUSTOM_ID_LEN = 100


class CompleteTaskButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"ayaka:complete:(?P<task_id>.+)",
):
    """Persistent "Mark Complete" button bound to one task ID."""

    def __init__(self, task_id: str) -> None:
        super().__init__(
            discord.ui.Button(
                label="Mark Complete",
                style=discord.ButtonStyle.success,
                emoji="✅",
                custom_id=f"{COMPLETE_PREFIX}{task_id}"[:MAX_CUSTOM_ID_LEN],
            )
        )
        self.task_id = task_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> "CompleteTaskButton":
        return cls(match["task_id"])

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        bot = interaction.client
        is_owner = getattr(bot, "is_owner_id", None)
        if is_owner is not None and not is_owner(interaction.user.id):
            await interaction.response.send_message("Only Master can do that. (｡•́︿•̀｡)", ephemeral=True)
            return False
        return True

    async def callback(self, interaction: discord.Interaction) -> None:
        bot = interaction.client
        db = bot.db
        task = await asyncio.to_thread(db.get_task, self.task_id)
        real_id = task["id"] if task else self.task_id

        success = await asyncio.to_thread(db.mark_task_completed, real_id)
        if not success:
            await interaction.response.send_message(
                "Unable to update task status in database (it may have been removed).", ephemeral=True
            )
            return

        google_sync = getattr(bot, "google_sync", None)
        if google_sync:
            try:
                await asyncio.to_thread(google_sync.mark_completed_in_google, real_id)
            except Exception as e:
                logger.error(f"Error updating Google Tasks: {e}")

        # Rebuild the view from the live message so this works after restarts, then disable our button.
        view = discord.ui.View.from_message(interaction.message, timeout=None)
        for child in view.children:
            if getattr(child, "custom_id", None) == self.item.custom_id:
                child.disabled = True
                child.label = "Completed"
                child.emoji = "🌸"
                child.style = discord.ButtonStyle.secondary

        title = (task or {}).get("title", "assignment")
        char_reply = bot.dialogue_mgr.get_dialogue("task_completed", title=title)

        await interaction.response.edit_message(view=view)
        await interaction.followup.send(
            f">>> *\"{char_reply}\"*\n\n-# Task `{real_id}` has been cleared from your active obligations.",
            ephemeral=True,
        )


class TaskActionView(discord.ui.View):
    """Interactive action buttons attached to reminder embeds."""

    def __init__(
        self,
        task: dict[str, Any],
        db: Database,
        dialogue_mgr: DialogueManager,
        google_sync: Any = None,
    ):
        super().__init__(timeout=None)
        self.task = task
        self.task_id = task["id"]
        self.db = db
        self.dialogue_mgr = dialogue_mgr
        self.google_sync = google_sync

        # If assignment has a valid web link, add an external Link Button
        task_url = safe_http_url(task.get("url"))
        if task_url:
            self.add_item(
                discord.ui.Button(
                    label="Open Assignment",
                    url=task_url,
                    emoji="🔗",
                    style=discord.ButtonStyle.link,
                )
            )

        self.add_item(CompleteTaskButton(self.task_id))
