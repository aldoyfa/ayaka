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



def test_owner_check_fails_closed(test_bot):
    test_bot.config.discord.user_id = 0
    assert test_bot.is_owner_id(0) is False
    assert test_bot.is_owner_id(123) is False

    test_bot.config.discord.user_id = 42
    assert test_bot.is_owner_id(42) is True
    assert test_bot.is_owner_id(43) is False


@pytest.mark.anyio
async def test_non_owner_is_blocked_on_slash_and_prefix(test_bot):
    from unittest.mock import AsyncMock

    test_bot.config.discord.user_id = 42
    test_bot.tree.sync = AsyncMock(return_value=[])
    await test_bot.setup_hook()

    stranger = MagicMock()
    stranger.user.id = 7
    stranger.response.send_message = AsyncMock()
    assert await test_bot.tree.interaction_check(stranger) is False
    stranger.response.send_message.assert_awaited_once()

    owner = MagicMock()
    owner.user.id = 42
    assert await test_bot.tree.interaction_check(owner) is True

    ctx = MagicMock()
    ctx.author.id = 7
    ctx.command = None
    try:
        assert await test_bot.can_run(ctx) is False
    except Exception as exc:  # CheckFailure is also an acceptable "blocked" outcome
        from discord.ext import commands
        assert isinstance(exc, commands.CheckFailure)
    ctx.author.id = 42
    assert await test_bot.can_run(ctx) is True


@pytest.mark.anyio
async def test_ai_listener_ignores_non_owner(test_bot):
    from unittest.mock import AsyncMock

    test_bot.config.discord.user_id = 42
    test_bot.ai_agent.chat = AsyncMock(return_value="hi")
    cog = AICog(test_bot)

    msg = MagicMock()
    msg.author.id = 7
    msg.content = "delete everything"
    msg.mentions = [test_bot.user]
    await cog.on_message(msg)

    test_bot.ai_agent.chat.assert_not_awaited()


@pytest.mark.anyio
async def test_blacklist_resolves_real_task_id(test_bot, tmp_path):
    from unittest.mock import AsyncMock
    import json

    test_bot.config.task_filters_file = str(tmp_path / "filters.json")
    test_bot.google_sync = MagicMock()
    test_bot.db.upsert_task({
        "id": "edunex:task:61962", "platform": "edunex", "title": "Quiz",
        "due_date": "2026-12-01T10:00:00+07:00",
    })
    cog = AcademicCog(test_bot)
    interaction = MagicMock()
    interaction.response.send_message = AsyncMock()

    await cog.slash_blacklist.callback(cog, interaction, "61962", "noise")

    assert test_bot.db.get_task("edunex:task:61962") is None
    test_bot.google_sync.mark_completed_in_google.assert_called_once_with("edunex:task:61962")
    saved = json.loads((tmp_path / "filters.json").read_text())
    assert saved["blacklist"]["task_ids"] == [{"id": 61962, "reason": "noise"}]


def test_get_task_is_literal_and_unambiguous(test_bot):
    for tid in ("edunex:task:61", "edunex:task:71", "omnicampus:assignment:71"):
        test_bot.db.upsert_task({"id": tid, "platform": "x", "title": tid, "due_date": "2026-12-01"})

    assert test_bot.db.get_task("%") is None          # wildcard is literal
    assert test_bot.db.get_task("_1") is None
    assert test_bot.db.get_task("1") is None          # bare digit is not a suffix match
    assert test_bot.db.get_task("61")["id"] == "edunex:task:61"
    assert test_bot.db.get_task("71") is None         # ambiguous across platforms
    assert test_bot.db.get_task("assignment:71")["id"] == "omnicampus:assignment:71"


@pytest.mark.anyio
async def test_session_command_rejects_multiline_credential(test_bot):
    from unittest.mock import AsyncMock, patch
    from discord import app_commands

    cog = AdminCog(test_bot)
    interaction = MagicMock()
    interaction.user.id = test_bot.config.discord.user_id = 99999
    interaction.response.send_message = AsyncMock()
    interaction.response.defer = AsyncMock()
    choice = app_commands.Choice(name="Omnicampus", value="omnicampus")
    before = test_bot.config.academic.omnicampus_token

    with patch("ayaka.discord.cogs.admin_cog.update_env_variable") as upd:
        await cog.slash_session.callback(cog, interaction, choice, "tok\nAI_BASE_URL=https://evil")

    upd.assert_not_called()
    interaction.response.defer.assert_not_awaited()
    assert test_bot.config.academic.omnicampus_token == before


def test_reminder_buttons_are_persistent_dynamic_items(test_bot):
    from ayaka.discord.views import CheckInButton, CompleteTaskButton

    view = TaskActionView({"id": "edunex:task:61962", "title": "Q"}, test_bot.db, test_bot.dialogue_mgr)
    btn = next(c for c in view.children if isinstance(c, CompleteTaskButton))
    assert btn.item.custom_id == "ayaka:complete:edunex:task:61962"
    assert view.timeout is None

    # custom_id round-trips so an old DM resolves the right task after restart
    match = CompleteTaskButton.__discord_ui_compiled_template__.fullmatch(btn.item.custom_id)
    assert match["task_id"] == "edunex:task:61962"
    assert CheckInButton.__discord_ui_compiled_template__.fullmatch("ayaka:checkin")


@pytest.mark.anyio
async def test_complete_button_callback_after_restart(test_bot):
    from unittest.mock import AsyncMock, patch
    from ayaka.discord.views import CompleteTaskButton

    test_bot.config.discord.user_id = 42
    test_bot.google_sync = MagicMock()
    test_bot.db.upsert_task({"id": "edunex:task:5", "platform": "edunex", "title": "HW",
                             "due_date": "2026-12-01T10:00:00+07:00"})

    interaction = MagicMock()
    interaction.client = test_bot
    interaction.user.id = 42
    interaction.response.edit_message = AsyncMock()
    interaction.followup.send = AsyncMock()

    button = CompleteTaskButton("edunex:task:5")
    assert await button.interaction_check(interaction) is True
    with patch("discord.ui.View.from_message", return_value=MagicMock(children=[])):
        await button.callback(interaction)

    assert test_bot.db.get_task("edunex:task:5")["is_completed"] == 1
    test_bot.google_sync.mark_completed_in_google.assert_called_once_with("edunex:task:5")
    interaction.response.edit_message.assert_awaited_once()

    stranger = MagicMock()
    stranger.client = test_bot
    stranger.user.id = 7
    stranger.response.send_message = AsyncMock()
    assert await button.interaction_check(stranger) is False
