"""Task Action View for Discord reminder and task notifications."""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from ayaka.storage.db import Database
    from ayaka.dialogue import DialogueManager

logger = logging.getLogger("ayaka.discord.views.task_actions")


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
        task_url = task.get("url")
        if task_url and task_url.startswith("http"):
            self.add_item(
                discord.ui.Button(
                    label="Open Assignment",
                    url=task_url,
                    emoji="🔗",
                    style=discord.ButtonStyle.link,
                )
            )

    @discord.ui.button(label="Mark Complete", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm_complete(self, interaction: discord.Interaction, button: discord.ui.Button):
        success = self.db.mark_task_completed(self.task_id)
        if success:
            if self.google_sync:
                try:
                    self.google_sync.mark_completed_in_google(self.task_id)
                except Exception as e:
                    logger.error(f"Error updating Google Tasks: {e}")

            # Disable button and update label
            button.disabled = True
            button.label = "Completed"
            button.emoji = "🌸"
            button.style = discord.ButtonStyle.secondary

            # Get in-character congratulatory response
            char_reply = self.dialogue_mgr.get_dialogue(
                "task_completed",
                title=self.task.get("title", "assignment"),
            )

            # Update existing message with disabled view
            await interaction.response.edit_message(view=self)
            # Send character feedback in ephemeral message
            await interaction.followup.send(
                f">>> *\"{char_reply}\"*\n\n-# Task `{self.task_id}` has been cleared from your active obligations.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "Unable to update task status in database.", ephemeral=True
            )
