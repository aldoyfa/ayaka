"""AI Conversational Cog for Ayaka Discord bot.

Handles natural language interactions, /chat slash command, and mention/DM listeners.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
import discord
from discord import app_commands
from discord.ext import commands

if TYPE_CHECKING:
    from ayaka.discord.bot import AyakaBot

logger = logging.getLogger("ayaka.discord.cogs.ai")


class AICog(commands.Cog, name="AI"):
    """Commands and listeners for casual natural language chat and AI tool management."""

    def __init__(self, bot: "AyakaBot") -> None:
        self.bot = bot

    @app_commands.command(name="chat", description="Chat casually with Ayaka and let her manage your academic duties")
    @app_commands.describe(message="What would you like to say or tell Ayaka to do?")
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.allowed_installs(guilds=True, users=True)
    async def slash_chat(self, interaction: discord.Interaction, message: str) -> None:
        if not self.bot.ai_agent.is_configured:
            await interaction.response.send_message(
                "Master, my AI intelligence core is currently resting! Please configure `AI_API_KEY` in `.env` first. (｡•́︿•̀｡)",
                ephemeral=True,
            )
            return

        if message.strip().lower() in ("reset", "clear", "reset chat"):
            self.bot.ai_agent.clear_history(str(interaction.user.id))
            await interaction.response.send_message(
                "Master, I have refreshed our conversation memory! Let's start anew with a fresh cup of tea! (´｡• ᵕ •｡`) 🌸✨"
            )
            return

        await interaction.response.defer(thinking=True)
        reply = await self.bot.ai_agent.chat(str(interaction.user.id), message)
        if not reply or not reply.strip():
            reply = "Master, I have carried out your request and updated our records! (๑•̀ㅂ•́)و✧ 🌸✨"
        if len(reply) <= 2000:
            await interaction.followup.send(reply)
        else:
            for chunk in [reply[i:i + 1950] for i in range(0, len(reply), 1950)]:
                await interaction.followup.send(chunk)

    @app_commands.command(name="reset", description="Reset your AI conversation history with Ayaka")
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.allowed_installs(guilds=True, users=True)
    async def slash_reset(self, interaction: discord.Interaction) -> None:
        self.bot.ai_agent.clear_history(str(interaction.user.id))
        await interaction.response.send_message(
            "Master, I have refreshed our conversation memory! Let's start anew with a fresh cup of tea! (´｡• ᵕ •｡`) 🌸✨"
        )

    @commands.command(name="chat", aliases=["ask", "tanya"])
    async def cmd_chat(self, ctx: commands.Context, *, message: str) -> None:
        if not self.bot.ai_agent.is_configured:
            await ctx.send("Master, my AI intelligence core is currently resting! Please configure `AI_API_KEY` in `.env` first. (｡•́︿•̀｡)")
            return
        if message.strip().lower() in ("reset", "clear", "reset chat"):
            self.bot.ai_agent.clear_history(str(ctx.author.id))
            await ctx.reply("Master, I have refreshed our conversation memory! Let's start anew with a fresh cup of tea! (´｡• ᵕ •｡`) 🌸✨")
            return
        async with ctx.typing():
            reply = await self.bot.ai_agent.chat(str(ctx.author.id), message)
            if not reply or not reply.strip():
                reply = "Master, I have carried out your request and updated our records! (๑•̀ㅂ•́)و✧ 🌸✨"
            if len(reply) <= 2000:
                await ctx.reply(reply)
            else:
                for chunk in [reply[i:i + 1950] for i in range(0, len(reply), 1950)]:
                    await ctx.reply(chunk)

    @commands.command(name="reset", aliases=["clear", "reset_chat"])
    async def cmd_reset(self, ctx: commands.Context) -> None:
        self.bot.ai_agent.clear_history(str(ctx.author.id))
        await ctx.reply("Master, I have refreshed our conversation memory! Let's start anew with a fresh cup of tea! (´｡• ᵕ •｡`) 🌸✨")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author == self.bot.user or not self.bot.is_owner_id(message.author.id):
            return

        is_dm = isinstance(message.channel, discord.DMChannel)
        is_mention = self.bot.user in message.mentions and not message.mention_everyone

        if (is_mention or is_dm) and not message.content.strip().startswith("!"):
            clean_content = message.content.replace(f"<@{self.bot.user.id}>", "").replace(f"<@!{self.bot.user.id}>", "").strip()
            if clean_content and self.bot.ai_agent.is_configured:
                async with message.channel.typing():
                    reply = await self.bot.ai_agent.chat(str(message.author.id), clean_content)
                    if not reply or not reply.strip():
                        reply = "Master, I have carried out your request and updated our records! (๑•̀ㅂ•́)و✧ 🌸✨"
                    if len(reply) <= 2000:
                        await message.reply(reply)
                    else:
                        for chunk in [reply[i:i + 1950] for i in range(0, len(reply), 1950)]:
                            await message.reply(chunk)


async def setup(bot: "AyakaBot") -> None:
    """Extension entry point for AICog."""
    await bot.add_cog(AICog(bot))
