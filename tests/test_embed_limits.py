"""Embeds built from untrusted/long data must stay within Discord's hard limits."""

from ayaka.discord.formatters import build_sync_embed
from ayaka.discord.safe import escape_text, join_lines_limited


def test_sync_embed_fields_fit_with_long_titles():
    items = [
        {"id": f"edunex:task:{i}", "platform": "edunex", "course": "Pemrosesan Bahasa Alami Lanjut",
         "title": "Tugas Besar Implementasi dan Analisis Model Transformer " * 2, "due_date": ""}
        for i in range(25)
    ]
    embed = build_sync_embed("all", {"added_items": items, "new_tasks": 25}, "https://x/icon.png")

    assert all(len(f.value) <= 1024 for f in embed.fields)
    assert "more" in embed.fields[0].value
    assert len(embed) <= 6000


def test_join_lines_limited_reports_cut_count():
    lines = ["x" * 100 for _ in range(30)]
    out = join_lines_limited(lines, 1024)
    assert len(out) <= 1024
    assert out.rstrip().endswith("more")


def test_escape_text_neutralizes_links_and_mentions():
    out = escape_text("[Login](https://evil.example) **now** @everyone")
    assert "](" not in out.replace("\\]\\(", "")
    assert "@everyone" not in out
