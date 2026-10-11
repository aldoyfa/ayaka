"""Meeting and class action views for Discord schedule reminders."""

from __future__ import annotations

from typing import Optional
import discord


class AttendanceActionView(discord.ui.View):
    """Interactive action buttons for class attendance reminder."""

    def __init__(
        self,
        six_url: str = "https://six.itb.ac.id",
        edunex_url: str = "https://edunex.itb.ac.id",
        teams_url: Optional[str] = None,
    ):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                label="Open SIX",
                url=six_url,
                emoji="🎓",
                style=discord.ButtonStyle.link,
            )
        )
        self.add_item(
            discord.ui.Button(
                label="Open Edunex",
                url=edunex_url,
                emoji="🏫",
                style=discord.ButtonStyle.link,
            )
        )
        if teams_url:
            self.add_item(
                discord.ui.Button(
                    label="MS Teams",
                    url=teams_url,
                    emoji="💬",
                    style=discord.ButtonStyle.link,
                )
            )

    @discord.ui.button(label="Checked In", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm_check_in(self, interaction: discord.Interaction, button: discord.ui.Button):
        button.disabled = True
        button.label = "Checked In! 🌸"
        button.style = discord.ButtonStyle.secondary
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(
            ">>> *\"Splendid, Master! Your attendance has been marked! Keep up the brilliant focus! (≧◡≦) 💖\"*",
            ephemeral=True,
        )


class ClassStartActionView(discord.ui.View):
    """Quick action buttons for class start reminder."""

    def __init__(
        self,
        edunex_url: Optional[str] = None,
        teams_url: Optional[str] = None,
        six_url: str = "https://six.itb.ac.id",
    ):
        super().__init__(timeout=None)
        if edunex_url:
            self.add_item(
                discord.ui.Button(
                    label="Open Edunex",
                    url=edunex_url,
                    emoji="🏫",
                    style=discord.ButtonStyle.link,
                )
            )
        if teams_url:
            self.add_item(
                discord.ui.Button(
                    label="Join Teams",
                    url=teams_url,
                    emoji="💬",
                    style=discord.ButtonStyle.link,
                )
            )
        self.add_item(
            discord.ui.Button(
                label="Open SIX",
                url=six_url,
                emoji="🎓",
                style=discord.ButtonStyle.link,
            )
        )
