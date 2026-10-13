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

        self.add_item(CheckInButton())


class CheckInButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"ayaka:checkin",
):
    """Persistent "Checked In" acknowledgement; survives bot restarts."""

    def __init__(self) -> None:
        super().__init__(
            discord.ui.Button(
                label="Checked In",
                style=discord.ButtonStyle.success,
                emoji="✅",
                custom_id="ayaka:checkin",
            )
        )

    @classmethod
    async def from_custom_id(cls, interaction, item, match) -> "CheckInButton":
        return cls()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        is_owner = getattr(interaction.client, "is_owner_id", None)
        if is_owner is not None and not is_owner(interaction.user.id):
            await interaction.response.send_message("Only Master can do that. (｡•́︿•̀｡)", ephemeral=True)
            return False
        return True

    async def callback(self, interaction: discord.Interaction) -> None:
        view = discord.ui.View.from_message(interaction.message, timeout=None)
        for child in view.children:
            if getattr(child, "custom_id", None) == "ayaka:checkin":
                child.disabled = True
                child.label = "Checked In! 🌸"
                child.style = discord.ButtonStyle.secondary
        await interaction.response.edit_message(view=view)
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
