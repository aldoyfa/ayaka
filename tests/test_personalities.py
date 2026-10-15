"""Unit and integration tests for multi-personality anime archetypes.

Tests:
- Loading dialogues.json with 4 archetypes (deredere, tsundere, kuudere, yandere)
- Switching personalities dynamically via DialogueManager
- Metadata extraction (display_name, description, avatar_url)
- Backward compatibility with legacy flat scenarios
- Built-in fallback when config is missing
- Config loader parsing personality from config.json and env
- AIAgent system prompt persona adaptation across all 4 archetypes
- Discord cog commands for /personality and !personality
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from ayaka.config import Config, PersonalityConfig
from ayaka.dialogue import DialogueManager
from ayaka.discord.cogs.admin_cog import AdminCog
from ayaka.services.ai_agent import AIAgent


def test_dialogue_manager_loads_all_four_personalities():
    """Verify that the loaded dialogues.json contains all 4 archetypes."""
    dialogues_path = Path(__file__).resolve().parent.parent / "dialogues.json"
    mgr = DialogueManager(str(dialogues_path))

    personalities = mgr.list_personalities()
    assert set(personalities) == {"deredere", "tsundere", "kuudere", "yandere"}


def test_personality_metadata_and_distinct_voices():
    """Verify metadata and distinct voice lines for each personality."""
    dialogues_path = Path(__file__).resolve().parent.parent / "dialogues.json"
    mgr = DialogueManager(str(dialogues_path))

    # 1. Deredere (Default)
    assert mgr.current_personality_key == "deredere"
    dere_meta = mgr.get_personality_meta("deredere")
    assert "Deredere" in dere_meta["display_name"]
    assert "twemoji" in dere_meta["avatar_url"]
    dere_title = mgr.get_title("h3_reminder")
    assert "✨" in dere_title or "Friendly" in dere_title

    # 2. Tsundere
    mgr.set_personality("tsundere")
    assert mgr.current_personality_key == "tsundere"
    tsun_meta = mgr.get_personality_meta("tsundere")
    assert "Tsundere" in tsun_meta["display_name"]
    tsun_title = mgr.get_title("h3_reminder")
    assert "Hmph" in tsun_title or "💢" in tsun_title
    tsun_line = mgr.get_dialogue("h3_reminder", course="IF2110", title="List ADT")
    assert any(w in tsun_line.lower() for w in ["baka", "wrong idea", "care", "hmph", "fail", "dummy"])

    # 3. Kuudere
    mgr.set_personality("kuudere")
    assert mgr.current_personality_key == "kuudere"
    kuu_meta = mgr.get_personality_meta("kuudere")
    assert "Kuudere" in kuu_meta["display_name"]
    kuu_title = mgr.get_title("h3_reminder")
    assert "Status Assessment" in kuu_title or "❄️" in kuu_title
    kuu_line = mgr.get_dialogue("h3_reminder", course="IF2110", title="List ADT")
    assert "Notice" in kuu_line or "Observation" in kuu_line or "72 hours" in kuu_line or "monitoring" in kuu_line

    # 4. Yandere
    mgr.set_personality("yandere")
    assert mgr.current_personality_key == "yandere"
    yan_meta = mgr.get_personality_meta("yandere")
    assert "Yandere" in yan_meta["display_name"]
    yan_title = mgr.get_title("h3_reminder")
    assert "Watching" in yan_title or "🖤" in yan_title or "🩸" in yan_title
    yan_line = mgr.get_dialogue("h3_reminder", course="IF2110", title="List ADT")
    assert "focus entirely on me" in yan_line.lower() or "alone" in yan_line.lower() or "master" in yan_line.lower()


def test_dialogue_manager_backward_compatibility(tmp_path):
    """Ensure older flat scenarios schema continues to function cleanly."""
    legacy_json = tmp_path / "legacy_dialogues.json"
    legacy_data = {
        "character_name": "Ayaka",
        "scenarios": {
            "h3_reminder": {
                "title": "Legacy Reminder",
                "color": "0x5DADE2",
                "dialogues": ["Legacy test line for {title}."],
            }
        }
    }
    legacy_json.write_text(json.dumps(legacy_data), encoding="utf-8")

    mgr = DialogueManager(str(legacy_json))
    assert mgr.list_personalities() == ["deredere"]
    assert mgr.get_title("h3_reminder") == "Legacy Reminder"
    assert "Legacy test line" in mgr.get_dialogue("h3_reminder", title="Task 1")


def test_dialogue_manager_missing_file_fallback(tmp_path):
    """Ensure nonexistent file falls back to built-in defaults without crashing."""
    nonexistent = tmp_path / "missing.json"
    mgr = DialogueManager(str(nonexistent))
    assert mgr.current_personality_key == "deredere"
    assert mgr.get_title("h3_reminder") != ""
    assert mgr.get_dialogue("h3_reminder", course="IF1010", title="Test") != ""


def test_config_personality_parsing(tmp_path, monkeypatch):
    """Verify Config.load() properly ingests personality settings."""
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({
        "personality": {
            "active": "tsundere"
        }
    }), encoding="utf-8")

    cfg = Config.load(base_dir=tmp_path)
    assert isinstance(cfg.personality, PersonalityConfig)
    assert cfg.personality.active == "tsundere"

    # Test environment variable override
    monkeypatch.setenv("ACTIVE_PERSONALITY", "kuudere")
    cfg_env = Config.load(base_dir=tmp_path)
    assert cfg_env.personality.active == "kuudere"


def test_ai_agent_adapts_persona_to_active_personality():
    """Verify that AIAgent's dynamic system prompt matches the active archetype."""
    config = Config.load()
    db = MagicMock()
    dialogue_mgr = DialogueManager()

    agent = AIAgent(config=config, db=db, dialogue_mgr=dialogue_mgr)

    # 1. Deredere
    dialogue_mgr.set_personality("deredere")
    prompt_dere = agent._build_system_prompt()
    assert "Ayaka (Deredere)" in prompt_dere
    assert "Sweet, caring, polite, diligent, energetic" in prompt_dere

    # 2. Tsundere
    dialogue_mgr.set_personality("tsundere")
    prompt_tsun = agent._build_system_prompt()
    assert "Ayaka (Tsundere)" in prompt_tsun
    assert "Prickly, easily flustered" in prompt_tsun
    assert "baka" in prompt_tsun.lower()

    # 3. Kuudere
    dialogue_mgr.set_personality("kuudere")
    prompt_kuu = agent._build_system_prompt()
    assert "Ayaka (Kuudere)" in prompt_kuu
    assert "Cool, calm, analytical, stoic" in prompt_kuu

    # 4. Yandere
    dialogue_mgr.set_personality("yandere")
    prompt_yan = agent._build_system_prompt()
    assert "Ayaka (Yandere)" in prompt_yan
    assert "Intensely possessive, obsessively devoted" in prompt_yan


@pytest.mark.anyio
async def test_admin_cog_personality_commands(tmp_path):
    """Test /personality and !personality command responses and switching."""
    mock_bot = MagicMock()
    mock_bot.config = Config.load()
    mock_bot.config.dialogue_file = str(tmp_path / "dialogues.json")
    mock_bot.dialogue_mgr = DialogueManager()

    cog = AdminCog(mock_bot)

    # 1. View current personality via slash command
    mock_interaction = MagicMock()
    mock_interaction.response.send_message = AsyncMock()

    await cog.slash_personality.callback(cog, mock_interaction, archetype=None)
    mock_interaction.response.send_message.assert_called_once()
    call_kwargs = mock_interaction.response.send_message.call_args.kwargs
    embed = call_kwargs.get("embed")
    assert embed is not None
    assert "Ayaka (Deredere)" in embed.title

    # 2. Switch personality via slash command
    mock_interaction.response.send_message.reset_mock()
    choice_tsun = MagicMock()
    choice_tsun.value = "tsundere"

    await cog.slash_personality.callback(cog, mock_interaction, archetype=choice_tsun)
    assert mock_bot.dialogue_mgr.current_personality_key == "tsundere"
    assert mock_bot.config.personality.active == "tsundere"
    mock_interaction.response.send_message.assert_called_once()
    switched_embed = mock_interaction.response.send_message.call_args.kwargs.get("embed")
    assert "Tsundere" in switched_embed.title
    assert "baka" in switched_embed.description.lower() or "hmph" in switched_embed.description.lower()

    # 3. View personality via prefix command
    mock_ctx = MagicMock()
    mock_ctx.send = AsyncMock()
    await cog.cmd_personality.callback(cog, mock_ctx, archetype=None)
    mock_ctx.send.assert_called_once()
    msg = mock_ctx.send.call_args.args[0]
    assert "Tsundere" in msg

    # 4. Switch personality via prefix command
    mock_ctx.send.reset_mock()
    await cog.cmd_personality.callback(cog, mock_ctx, archetype="yandere")
    assert mock_bot.dialogue_mgr.current_personality_key == "yandere"
    mock_ctx.send.assert_called_once()
    yandere_reply = mock_ctx.send.call_args.args[0]
    assert "Yandere" in yandere_reply
