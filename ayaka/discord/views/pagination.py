"""Task Pagination View for Discord quest board navigation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, TYPE_CHECKING
import discord

from ayaka.dialogue import format_discord_timestamp

if TYPE_CHECKING:
    from ayaka.discord.bot import AyakaBot


class TaskPaginationView(discord.ui.View):
    """Interactive pagination view for navigating through academic tasks."""

    def __init__(
        self,
        bot: "AyakaBot",
        tasks: list[dict[str, Any]],
        author_id: int,
        all_tasks: bool = False,
        per_page: int = 5,
        timeout: float = 300.0,
    ):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.tasks = tasks
        self.author_id = author_id
        self.all_tasks = all_tasks
        self.per_page = per_page
        self.current_page = 0
        self.total_pages = max(1, (len(tasks) + per_page - 1) // per_page)
        self.message: Optional[discord.Message] = None
        self._update_buttons()

    def _update_buttons(self) -> None:
        self.prev_button.disabled = (self.current_page <= 0)
        self.next_button.disabled = (self.current_page >= self.total_pages - 1)
        self.indicator_button.label = f"Page {self.current_page + 1}/{self.total_pages}"

    def build_embed(self) -> discord.Embed:
        start_idx = self.current_page * self.per_page
        end_idx = min(start_idx + self.per_page, len(self.tasks))
        page_tasks = self.tasks[start_idx:end_idx]

        header_quote = self.bot.dialogue_mgr.get_dialogue("task_list_header")
        header_title = self.bot.dialogue_mgr.get_title("task_list_header", default="Ayaka's Academic Quest Board")

        embed = discord.Embed(
            title=f"🌸 {header_title} ✨",
            description=f">>> *\"{header_quote}\"*",
            color=0x5DADE2,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(name="Ayaka ✨", icon_url=self.bot.get_author_icon())

        for t in page_tasks:
            course = t.get("course_name") or t.get("course_id") or "General"
            try:
                due_dt = datetime.fromisoformat(t["due_date"])
                if due_dt.tzinfo is None:
                    due_dt = due_dt.replace(tzinfo=timezone.utc)
                rel_ts, full_ts = format_discord_timestamp(due_dt)
                due_display = f"{rel_ts} ({full_ts})"
            except Exception:
                due_display = t.get("due_date", "-")

            status_icon = "✅" if t.get("is_completed") else "⏳"
            embed.add_field(
                name=f"{status_icon} [{t['platform'].upper()}] {t['title']}",
                value=f"• **Course:** {course}\n• **Due:** {due_display}\n• **ID:** `{t['id']}`",
                inline=False,
            )

        embed.set_footer(
            text=f"Page {self.current_page + 1} of {self.total_pages} • Total: {len(self.tasks)} tasks • Use /complete <id> to finish"
        )
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.author_id and interaction.user.id != self.author_id:
            await interaction.response.send_message(
                ">>> *\"Umm, Master, these pages belong to someone else! (｡•́︿•̀｡) Please use `/tasks` to open your own quest board! 🌸\"*",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="◀️ Previous", style=discord.ButtonStyle.primary, custom_id="task_nav_prev")
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            self._update_buttons()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Page 1/1", style=discord.ButtonStyle.secondary, disabled=True, custom_id="task_nav_indicator")
    async def indicator_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(label="Next ▶️", style=discord.ButtonStyle.primary, custom_id="task_nav_next")
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self._update_buttons()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        try:
            if self.message:
                await self.message.edit(view=self)
        except Exception:
            pass
