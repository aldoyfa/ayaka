"""Tests for DialogueManager, template formatting, and Discord UI helpers."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from ayaka.dialogue import DialogueManager, format_discord_timestamp, generate_progress_bar


def test_dialogue_manager_loading(tmp_path):
    mgr = DialogueManager(str(Path(__file__).resolve().parent.parent / "dialogues.json"))
    assert mgr.data is not None

    # Test H-3 scenario dialogue
    dialogue = mgr.get_dialogue("h3_reminder", course="IF2110", title="List ADT")
    assert isinstance(dialogue, str)
    assert len(dialogue) > 10
    # Should contain replaced course or title
    assert "IF2110" in dialogue or "List ADT" in dialogue or "Master" in dialogue

    # Test title and color
    title = mgr.get_title("h3_reminder")
    assert "3 Days" in title

    color = mgr.get_color("h3_reminder")
    assert color == 0x5DADE2


def test_progress_bar_generation():
    now = datetime.now(timezone.utc)

    # 1. Past due
    past_due = now - timedelta(hours=1)
    bar_past = generate_progress_bar(past_due, now)
    assert "100%" in bar_past

    # 2. Approaching due (e.g. 6 hours left in 72h window)
    approaching = now + timedelta(hours=6)
    bar_approaching = generate_progress_bar(approaching, now, total_span_hours=72.0)
    assert "elapsed" in bar_approaching
    assert "▰" in bar_approaching


def test_discord_timestamp_format():
    dt = datetime(2026, 10, 15, 23, 59, 0, tzinfo=timezone.utc)
    rel_ts, full_ts = format_discord_timestamp(dt)
    assert rel_ts.startswith("<t:")
    assert rel_ts.endswith(":R>")
    assert full_ts.startswith("<t:")
    assert full_ts.endswith(":F>")
