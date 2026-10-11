"""Tests for Ayaka modular Discord bot and Cogs architecture."""

from unittest.mock import MagicMock
import pytest

from ayaka.config import Config
from ayaka.discord.bot import AyakaBot
from ayaka.discord.cogs import AcademicCog, AdminCog, AICog, ScheduleCog
from ayaka.discord.formatters import (
    build_reminder_embed,
    build_schedule_embed,
    build_sync_embed,
    build_upcoming_embed,
    format_meeting_field_value,
)
from ayaka.discord.views import (
    AttendanceActionView,
    ClassStartActionView,
    TaskActionView,
    TaskPaginationView,
)
from ayaka.storage.db import Database


@pytest.fixture
def test_bot(tmp_path):
    db_file = tmp_path / "test_ayaka_cogs.db"
    db = Database(str(db_file))
    config = Config.load()
    config.database_path = str(db_file)
    mock_google = MagicMock()
    mock_sched = MagicMock()
    return AyakaBot(config, db, mock_google, mock_sched)


@pytest.mark.anyio
async def test_bot_setup_hook_loads_cogs(test_bot):
    # Mock tree sync so we don't make real Discord API network calls during test
    test_bot.tree.sync = MagicMock()
    test_bot.tree.sync.return_value = []

    # Run setup_hook
    await test_bot.setup_hook()

    # Verify all 4 cogs are loaded
    assert test_bot.get_cog("Academic") is not None
    assert test_bot.get_cog("Schedule") is not None
    assert test_bot.get_cog("Admin") is not None
    assert test_bot.get_cog("AI") is not None

    assert isinstance(test_bot.get_cog("Academic"), AcademicCog)
    assert isinstance(test_bot.get_cog("Schedule"), ScheduleCog)
    assert isinstance(test_bot.get_cog("Admin"), AdminCog)
    assert isinstance(test_bot.get_cog("AI"), AICog)


def test_views_initialization(test_bot):
    task = {
        "id": "t1",
        "title": "Assignment NLP",
        "due_date": "2026-10-15T23:59:00",
        "platform": "edunex",
        "url": "https://edunex.itb.ac.id/task/1",
    }
    task_view = TaskActionView(task, test_bot.db, test_bot.dialogue_mgr)
    assert len(task_view.children) >= 2  # Link button + Complete button

    att_view = AttendanceActionView(teams_url="https://teams.microsoft.com/meet/1")
    assert len(att_view.children) >= 3

    class_view = ClassStartActionView(edunex_url="https://edunex.itb.ac.id", teams_url="https://teams.microsoft.com")
    assert len(class_view.children) >= 3

    page_view = TaskPaginationView(test_bot, [task], author_id=123)
    embed = page_view.build_embed()
    assert "Assignment NLP" in embed.fields[0].name


@pytest.mark.anyio
async def test_admin_cog_slash_session(test_bot, monkeypatch):
    from unittest.mock import AsyncMock, patch
    from discord import app_commands

    admin_cog = AdminCog(test_bot)

    interaction = MagicMock()
    interaction.user.id = test_bot.config.discord.user_id = 99999
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()

    choice = app_commands.Choice(name="Omnicampus (Bearer Token)", value="omnicampus")

    with patch("ayaka.config.update_env_variable", return_value=True), \
         patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
         patch("ayaka.scheduler.run_sync_cycle_async", new_callable=AsyncMock) as mock_sync:
        
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        # Should execute cleanly without TypeError (a coroutine was expected)
        await admin_cog.slash_session.callback(admin_cog, interaction, choice, "Bearer my_new_token_123")

        assert test_bot.config.academic.omnicampus_token == "my_new_token_123"
        interaction.response.defer.assert_awaited_once()
        interaction.followup.send.assert_awaited_once()

