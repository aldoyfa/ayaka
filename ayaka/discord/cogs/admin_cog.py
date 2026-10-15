"""Admin & System Cog for Ayaka Discord bot.

Handles credentials management, session updates, system health status, and help guides.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, TYPE_CHECKING
import discord
from discord import app_commands
from discord.ext import commands
import httpx

from ayaka.config import is_safe_env_value, update_env_variable
from ayaka.core.time import format_uptime
from ayaka.dialogue import format_discord_timestamp

if TYPE_CHECKING:
    from ayaka.discord.bot import AyakaBot

logger = logging.getLogger("ayaka.discord.cogs.admin")


def is_jwt_expired(token_str: str) -> bool:
    """Check if a JWT token string has expired based on its 'exp' claim."""
    if not token_str:
        return False
    try:
        clean = token_str.replace("Bearer ", "").strip()
        parts = clean.split(".")
        if len(parts) >= 2:
            payload_b64 = parts[1] + "=="
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))
            exp = payload.get("exp")
            if exp and time.time() >= exp:
                return True
    except Exception:
        pass
    return False


class AdminCog(commands.Cog, name="Admin"):
    """Commands for bot monitoring, credentials, and configuration."""

    def __init__(self, bot: "AyakaBot") -> None:
        self.bot = bot

    # ----------------- SLASH COMMANDS -----------------

    @app_commands.command(name="status", description="Check Ayaka system, sync, and platform connections")
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.allowed_installs(guilds=True, users=True)
    async def slash_status(self, interaction: discord.Interaction) -> None:
        tasks = self.bot.db.list_tasks(include_completed=True)
        pending = sum(1 for t in tasks if not t.get("is_completed"))
        completed = sum(1 for t in tasks if t.get("is_completed"))

        uptime_str = format_uptime(datetime.now(timezone.utc) - self.bot.start_time)
        last_sync = self.bot.db.get_last_sync_status()

        # Session alert statuses
        alerted_platforms: set[str] = set()
        with self.bot.db._conn() as conn:
            rows = conn.execute("SELECT platform, last_alerted_at FROM session_alerts").fetchall()
            for r in rows:
                alerted_platforms.add(r["platform"].lower())

        def _platform_status(plat_key: str, is_configured: bool) -> str:
            if not is_configured:
                return "🔴 Not configured"

            if plat_key == "omnicampus" and self.bot.config.academic.omnicampus_token:
                if is_jwt_expired(self.bot.config.academic.omnicampus_token):
                    return "⚠️ Session Expired (use `/session`)"

            if plat_key in alerted_platforms:
                return "⚠️ Session Expired (use `/session`)"

            info = last_sync.get(plat_key)
            if info:
                status = info.get("status")
                ts = info.get("timestamp", "")
                try:
                    sync_dt = datetime.fromisoformat(ts)
                    rel_ts, _ = format_discord_timestamp(sync_dt)
                    time_str = f" ({rel_ts})"
                except Exception:
                    time_str = ""
                if status == "expired":
                    return f"⚠️ Session Expired{time_str} (use `/session`)"
                elif status == "success":
                    return f"🟢 Healthy{time_str}"
                else:
                    return f"🟡 Warn{time_str}"
            return "🟢 Configured"

        embed = discord.Embed(
            title="🌸 Ayaka Companion Status ✨",
            description=f">>> *\"Ayaka is actively on duty and watching over your academic success! Master has been studying hard! (๑•̀ㅂ•́)و✧\"*\n\n⏱️ **Uptime:** `{uptime_str}`",
            color=0x5DADE2,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(name="Ayaka ✨", icon_url=self.bot.get_author_icon())
        embed.add_field(name="🏫 Edunex ITB", value=_platform_status("edunex", self.bot.config.academic.has_edunex), inline=True)
        embed.add_field(name="🎓 SIX ITB", value=_platform_status("six", self.bot.config.academic.has_six), inline=True)
        embed.add_field(name="🌐 Omnicampus", value=_platform_status("omnicampus", self.bot.config.academic.has_omnicampus), inline=True)
        embed.add_field(name="📅 Google Workspace", value="🟢 Connected" if (self.bot.google_sync and self.bot.google_sync.creds) else "⚪ Standby", inline=True)
        embed.add_field(
            name="🤖 AI Intelligence",
            value=f"🟢 Active (`{self.bot.ai_agent._get_model_name()}`)" if self.bot.ai_agent.is_configured else "🔴 Not configured",
            inline=True,
        )
        embed.add_field(name="📚 Active Tasks", value=f"**{pending}** pending / **{completed}** finished", inline=True)
        pers_meta = self.bot.dialogue_mgr.get_personality_meta()
        embed.add_field(name="🎭 Personality", value=pers_meta["display_name"], inline=True)
        embed.add_field(name="⏰ Timezone", value=self.bot.config.timezone, inline=True)
        embed.set_footer(text="Ayaka Academic Assistant • System Status ✨")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="session", description="Update academic platform session cookie/token securely")
    @app_commands.describe(
        platform="Academic platform to update",
        credential="New token or cookie string",
    )
    @app_commands.choices(platform=[
        app_commands.Choice(name="Omnicampus (Bearer Token)", value="omnicampus"),
        app_commands.Choice(name="Edunex ITB (Cookie / Bearer)", value="edunex"),
        app_commands.Choice(name="SIX ITB (Cookie / Session)", value="six"),
    ])
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.allowed_installs(guilds=True, users=True)
    async def slash_session(
        self,
        interaction: discord.Interaction,
        platform: app_commands.Choice[str],
        credential: str,
    ) -> None:
        if self.bot.config.discord.user_id and interaction.user.id != self.bot.config.discord.user_id:
            await interaction.response.send_message(
                ">>> *\"Master's private chambers! Only Master is authorized to configure credentials. (｡•́︿•̀｡)\"*",
                ephemeral=True,
            )
            return

        clean_cred = credential.strip().strip("'\"")
        if not clean_cred or not is_safe_env_value(clean_cred):
            await interaction.response.send_message(
                "That credential is empty or contains line breaks, so I did not save it. (｡•́︿•̀｡)",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        plat_val = platform.value
        if plat_val == "omnicampus" and clean_cred.lower().startswith("bearer "):
            clean_cred = clean_cred[7:].strip()

        env_key_map = {
            "omnicampus": "OMNICAMPUS_TOKEN",
            "edunex": "EDUNEX_COOKIE",
            "six": "SIX_COOKIE",
        }
        env_key = env_key_map[plat_val]
        persisted = update_env_variable(env_key, clean_cred)

        if plat_val == "omnicampus":
            self.bot.config.academic.omnicampus_token = clean_cred
        elif plat_val == "edunex":
            self.bot.config.academic.edunex_cookie = clean_cred
        elif plat_val == "six":
            self.bot.config.academic.six_cookie = clean_cred

        with self.bot.db._conn() as conn:
            conn.execute("DELETE FROM session_alerts WHERE platform = ?", (plat_val,))

        verified = False
        verif_msg = ""
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                if plat_val == "omnicampus":
                    test_headers = {"Authorization": f"Bearer {clean_cred}", "Accept": "application/json"}
                    r = await client.get(f"{self.bot.config.academic.endpoints.omnicampus_base_url}/api/v3/courses/170", headers=test_headers)
                    if r.status_code == 200:
                        verified = True
                        verif_msg = "🟢 Connected & verified! Course data accessible."
                    else:
                        verif_msg = f"🟡 Saved to `.env`, but test request returned HTTP {r.status_code}."
                elif plat_val == "edunex":
                    test_headers = {"Cookie": clean_cred}
                    r = await client.get(f"{self.bot.config.academic.endpoints.edunex_base_url}/", headers=test_headers)
                    verified = (r.status_code in (200, 302))
                    verif_msg = "🟢 Saved to `.env` & active!"
                elif plat_val == "six":
                    six_cookie = f"khongguan={clean_cred}" if "=" not in clean_cred else clean_cred
                    test_headers = {"Cookie": six_cookie}
                    r = await client.get(f"{self.bot.config.academic.endpoints.six_base_url}/home", headers=test_headers)
                    verified = (r.status_code in (200, 302))
                    verif_msg = "🟢 Saved to `.env` & active!"
            except Exception as e:
                verif_msg = f"🟡 Saved to `.env`, but the test request failed ({type(e).__name__})."

        from ayaka.scheduler import run_sync_cycle_async
        asyncio.create_task(run_sync_cycle_async(self.bot.config, self.bot.db, plat_val, self.bot.google_sync))

        embed = discord.Embed(
            title=f"🌸 {platform.name} Session Refreshed! ✨",
            description=(
                f">>> *\"Splendid, Master! I have safely updated the credentials for **{platform.value.upper()}** "
                f"in `.env` and refreshed our active connection! (≧◡ŋ) 💕\"*\n\n"
                f"**Verification Status:**\n{verif_msg}\n\n"
                + ("" if persisted else "⚠️ Could not write `.env`; active until restart only.\n\n") +
                f"-# Background synchronization cycle for `{platform.value.upper()}` has been started automatically."
            ),
            color=0x2ECC71 if verified else 0xF39C12,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(name="Ayaka ✨", icon_url=self.bot.get_author_icon())
        embed.set_footer(text="Your secret credential remains private and secure.")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="personality", description="View or switch Ayaka's anime personality archetype")
    @app_commands.describe(
        archetype="Select personality archetype (leave blank to view current personality)"
    )
    @app_commands.choices(archetype=[
        app_commands.Choice(name="Deredere (Energetic, Cheerful & Loving)", value="deredere"),
        app_commands.Choice(name="Tsundere (Prickly & Feisty on the outside, deeply caring inside)", value="tsundere"),
        app_commands.Choice(name="Kuudere (Cool, Calm, Analytical & Stoic loyalty)", value="kuudere"),
        app_commands.Choice(name="Yandere (Devoted, Possessive & Chillingly affectionate)", value="yandere"),
    ])
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.allowed_installs(guilds=True, users=True)
    async def slash_personality(
        self,
        interaction: discord.Interaction,
        archetype: Optional[app_commands.Choice[str]] = None,
    ) -> None:
        if archetype is None:
            current_meta = self.bot.dialogue_mgr.get_personality_meta()
            curr_key = current_meta["key"]
            embed = discord.Embed(
                title=f"🎭 Ayaka Personality Profile: {current_meta['display_name']}",
                description=f">>> *\"{current_meta.get('description', '')}\"*",
                color=0x5DADE2 if curr_key == "deredere" else 0xE74C3C if curr_key == "tsundere" else 0x34495E if curr_key == "kuudere" else 0x884EA0,
                timestamp=datetime.now(timezone.utc),
            )
            if current_meta.get("avatar_url"):
                embed.set_thumbnail(url=current_meta["avatar_url"])

            all_archetypes = self.bot.dialogue_mgr.list_personalities()
            archetypes_desc = []
            for p in all_archetypes:
                meta = self.bot.dialogue_mgr.get_personality_meta(p)
                marker = "👉 **[ACTIVE]** " if p == curr_key else "• "
                archetypes_desc.append(f"{marker}**{meta['display_name']}** — {meta.get('description', '')}")

            embed.add_field(name="Available Archetypes", value="\n".join(archetypes_desc), inline=False)
            embed.set_footer(text="Switch personality anytime using /personality <archetype>")
            await interaction.response.send_message(embed=embed)
            return

        target_key = archetype.value.strip().lower()
        self.bot.dialogue_mgr.set_personality(target_key)
        if hasattr(self.bot.config, "personality"):
            self.bot.config.personality.active = target_key

        try:
            cfg_path = Path(self.bot.config.dialogue_file).resolve().parent / "config.json"
            if cfg_path.is_file():
                with open(cfg_path, "r", encoding="utf-8") as f:
                    c_data = json.load(f)
                if not isinstance(c_data.get("personality"), dict):
                    c_data["personality"] = {}
                c_data["personality"]["active"] = target_key
                with open(cfg_path, "w", encoding="utf-8") as f:
                    json.dump(c_data, f, indent=2, ensure_ascii=False)
                    f.write("\n")
        except Exception as e:
            logger.warning(f"Could not persist personality to config.json: {e}")

        meta = self.bot.dialogue_mgr.get_personality_meta(target_key)

        if target_key == "tsundere":
            voice_line = "H-Hmph! Don't get the wrong idea, okay?! I only switched to this because you told me to, baka! Don't expect me to be all sweet and soft on your assignments! 💢"
            color = 0xE74C3C
        elif target_key == "kuudere":
            voice_line = "Recalibration complete. Persona switched to Kuudere. Efficiency parameters and stoic academic monitoring active. ❄️"
            color = 0x34495E
        elif target_key == "yandere":
            voice_line = "Aha... ahahaha! Now you're all mine, Master... I will watch over your tasks, your screen, and every single second of your life. Forever... 🖤🩸"
            color = 0x884EA0
        else:
            voice_line = "Yaaay! Deredere Ayaka is here and super pumped to cheer you on with all my love and energy! Let's do our absolute best together, Master! 🌸✨"
            color = 0x5DADE2

        embed = discord.Embed(
            title=f"✨ Switched Personality to {meta['display_name']}!",
            description=f">>> *\"{voice_line}\"*",
            color=color,
            timestamp=datetime.now(timezone.utc),
        )
        if meta.get("avatar_url"):
            embed.set_thumbnail(url=meta["avatar_url"])
        embed.set_footer(text="Task reminders & /chat will now reflect this personality!")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="help", description="Show all available Ayaka slash commands and features")
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.allowed_installs(guilds=True, users=True)
    async def slash_help(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="🌸 Ayaka Study Companion Guide ✨",
            description="Here are all the ways I can help keep your studies organized and stress-free!",
            color=0x5DADE2,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(name="Ayaka ✨", icon_url=self.bot.get_author_icon())
        embed.add_field(name="📋 `/tasks`", value="View pending assignments and countdowns.", inline=False)
        embed.add_field(name="⏳ `/upcoming [days]`", value="View assignment deadlines within N days (default: 7).", inline=False)
        embed.add_field(name="➕ `/add <title> <due_date> [course]`", value="Add a manual assignment or custom academic deadline.", inline=False)
        embed.add_field(name="✅ `/complete <id>`", value="Mark an assignment finished and sync to Google.", inline=False)
        embed.add_field(name="🚫 `/blacklist <id> [reason]`", value="Ignore an assignment permanently from future sync cycles.", inline=False)
        embed.add_field(name="📅 `/schedule [period]`", value="View lecture schedule (`today`, `tomorrow`, or `week`).", inline=False)
        embed.add_field(name="🔄 `/sync [platform]`", value="Trigger an immediate sync across all campus LMS platforms.", inline=False)
        embed.add_field(name="📊 `/status`", value="Check bot uptime, LMS sync timestamps, and session health.", inline=False)
        embed.add_field(name="🎭 `/personality [archetype]`", value="View or switch Ayaka's anime personality (Deredere, Tsundere, Kuudere, Yandere).", inline=False)
        embed.add_field(name="💬 `/chat <message>`", value="Talk with Ayaka or ask her to create/finish tasks with AI natural language.", inline=False)
        embed.add_field(name="💡 Milestone Reminders", value="Proactive reminders arrive at **H-3, H-1, J-6, J-1, and Due** directly in your DMs!", inline=False)
        embed.add_field(name="🔔 Automated Class Reminders", value="05:00 AM daily briefing, class start alerts, and attendance alerts 10 minutes before class ends ✨", inline=False)
        embed.set_footer(text="Ayaka Academic Assistant • Always by your side 💖")
        await interaction.response.send_message(embed=embed)

    # ----------------- PREFIX COMMANDS (FALLBACK) -----------------

    @commands.command(name="status")
    async def cmd_status(self, ctx: commands.Context) -> None:
        tasks = self.bot.db.list_tasks(include_completed=True)
        pending = sum(1 for t in tasks if not t.get("is_completed"))
        completed = sum(1 for t in tasks if t.get("is_completed"))
        uptime_str = format_uptime(datetime.now(timezone.utc) - self.bot.start_time)
        last_sync = self.bot.db.get_last_sync_status()

        alerted_platforms: set[str] = set()
        with self.bot.db._conn() as conn:
            rows = conn.execute("SELECT platform, last_alerted_at FROM session_alerts").fetchall()
            for r in rows:
                alerted_platforms.add(r["platform"].lower())

        def _quick_st(plat_key: str, is_configured: bool) -> str:
            if not is_configured:
                return "🔴 Off"
            if plat_key == "omnicampus" and self.bot.config.academic.omnicampus_token and is_jwt_expired(self.bot.config.academic.omnicampus_token):
                return "⚠️ Expired"
            if plat_key in alerted_platforms or last_sync.get(plat_key, {}).get("status") == "expired":
                return "⚠️ Expired"
            if last_sync.get(plat_key, {}).get("status") == "success":
                return "🟢 Healthy"
            return "🟢 Configured"

        pers_meta = self.bot.dialogue_mgr.get_personality_meta()
        await ctx.send(
            f"🌸 **Ayaka Status:** Uptime: `{uptime_str}` • Tasks: {pending} pending / {completed} finished\n"
            f"🎭 **Personality:** {pers_meta['display_name']} | "
            f"🏫 **Edunex:** {_quick_st('edunex', self.bot.config.academic.has_edunex)} | "
            f"🎓 **SIX:** {_quick_st('six', self.bot.config.academic.has_six)} | "
            f"🌐 **Omnicampus:** {_quick_st('omnicampus', self.bot.config.academic.has_omnicampus)} | "
            f"🤖 **AI:** {'🟢 Active' if self.bot.ai_agent.is_configured else '🔴 Off'}"
        )

    @commands.command(name="session")
    async def cmd_session(self, ctx: commands.Context, platform: str, *, credential: str) -> None:
        if ctx.guild:
            try:
                await ctx.message.delete()
            except Exception:
                pass

        if self.bot.config.discord.user_id and ctx.author.id != self.bot.config.discord.user_id:
            try:
                await ctx.author.send("Only Master is authorized to configure credentials! (｡•́︿•̀｡)")
            except Exception:
                pass
            return

        plat_val = platform.strip().lower()
        clean_cred = credential.strip().strip("'\"")
        if plat_val == "omnicampus" and clean_cred.lower().startswith("bearer "):
            clean_cred = clean_cred[7:].strip()

        env_key_map = {
            "omnicampus": "OMNICAMPUS_TOKEN",
            "edunex": "EDUNEX_COOKIE",
            "six": "SIX_COOKIE",
        }
        if plat_val not in env_key_map or not clean_cred or not is_safe_env_value(clean_cred):
            try:
                await ctx.author.send("Unknown platform (use omnicampus, edunex or six) or an unsafe/empty credential.")
            except Exception:
                pass
            return
        env_key = env_key_map[plat_val]
        update_env_variable(env_key, clean_cred)

        if plat_val == "omnicampus":
            self.bot.config.academic.omnicampus_token = clean_cred
        elif plat_val == "edunex":
            self.bot.config.academic.edunex_cookie = clean_cred
        elif plat_val == "six":
            self.bot.config.academic.six_cookie = clean_cred

        with self.bot.db._conn() as conn:
            conn.execute("DELETE FROM session_alerts WHERE platform = ?", (plat_val,))

        from ayaka.scheduler import run_sync_cycle_async
        asyncio.create_task(run_sync_cycle_async(self.bot.config, self.bot.db, plat_val, self.bot.google_sync))

        reply = f"🌸 Master, session for `{plat_val.upper()}` has been updated in `.env` and active memory! ✨"
        try:
            await ctx.author.send(reply)
        except Exception:
            await ctx.send(reply)

    @commands.command(name="personality")
    async def cmd_personality(self, ctx: commands.Context, archetype: Optional[str] = None) -> None:
        if not archetype:
            current_meta = self.bot.dialogue_mgr.get_personality_meta()
            all_archetypes = self.bot.dialogue_mgr.list_personalities()
            archetype_list_str = ", ".join(f"`{p}`" for p in all_archetypes)
            await ctx.send(
                f"🎭 **Active Personality:** {current_meta['display_name']}\n"
                f"_{current_meta.get('description', '')}_\n\n"
                f"**Available Archetypes:** {archetype_list_str}\n"
                f"👉 Use `!personality <name>` to switch!"
            )
            return

        target_key = archetype.strip().lower()
        valid_keys = self.bot.dialogue_mgr.list_personalities()
        if target_key not in valid_keys:
            await ctx.send(f"⚠️ Unknown archetype `{target_key}`. Available options: {', '.join(f'`{k}`' for k in valid_keys)}")
            return

        self.bot.dialogue_mgr.set_personality(target_key)
        if hasattr(self.bot.config, "personality"):
            self.bot.config.personality.active = target_key

        try:
            cfg_path = Path(self.bot.config.dialogue_file).resolve().parent / "config.json"
            if cfg_path.is_file():
                with open(cfg_path, "r", encoding="utf-8") as f:
                    c_data = json.load(f)
                if not isinstance(c_data.get("personality"), dict):
                    c_data["personality"] = {}
                c_data["personality"]["active"] = target_key
                with open(cfg_path, "w", encoding="utf-8") as f:
                    json.dump(c_data, f, indent=2, ensure_ascii=False)
                    f.write("\n")
        except Exception as e:
            logger.warning(f"Could not persist personality to config.json: {e}")

        meta = self.bot.dialogue_mgr.get_personality_meta(target_key)
        if target_key == "tsundere":
            reply = f"😤 **{meta['display_name']}:** H-Hmph! Don't get the wrong idea! I only switched because you asked, baka! 💢"
        elif target_key == "kuudere":
            reply = f"❄️ **{meta['display_name']}:** Persona updated to Kuudere. Efficiency parameters applied."
        elif target_key == "yandere":
            reply = f"🖤 **{meta['display_name']}:** Hehehe... You're all mine now, Master. I will never let you go... 🩸"
        else:
            reply = f"🌸 **{meta['display_name']}:** Yaaay! Deredere Ayaka is here and super excited to support you, Master! ✨"

        await ctx.send(reply)


async def setup(bot: "AyakaBot") -> None:
    """Extension entry point for AdminCog."""
    await bot.add_cog(AdminCog(bot))
