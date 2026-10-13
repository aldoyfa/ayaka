"""Scraped/untrusted text must never make a Discord payload invalid."""

import pytest

from ayaka.discord.safe import clip, defang_code_block, safe_http_url
from ayaka.discord.views import AttendanceActionView, ClassStartActionView, TaskActionView
from ayaka.fetchers.six import SixFetcher
from ayaka.config import Config


@pytest.mark.parametrize("bad", [
    "javascript:alert(1)", "/relative/path", "ftp://x.y", "http://", "https://a b",
    "https://" + "a" * 600 + ".com", "", None,
])
def test_safe_http_url_rejects(bad):
    assert safe_http_url(bad) is None
    assert safe_http_url(bad, "https://fallback") == "https://fallback"


def test_safe_http_url_accepts_https():
    assert safe_http_url("https://teams.microsoft.com/l/meetup-join/1") == "https://teams.microsoft.com/l/meetup-join/1"


def test_views_survive_hostile_urls():
    att = AttendanceActionView(six_url="javascript:x", edunex_url="/rel", teams_url="ftp://t")
    labels = [getattr(c, "item", c).label for c in att.children]
    assert "Open SIX" in labels and "Open Edunex" in labels and "MS Teams" not in labels

    start = ClassStartActionView(edunex_url="//evil", teams_url="data:text/html,x", six_url="")
    assert [c.label for c in start.children] == ["Open SIX"]

    task = TaskActionView({"id": "t", "url": "javascript:x"}, None, None)
    assert len(task.children) == 1  # only the Complete button, no link


def test_clip_and_defang():
    assert len(clip("x" * 5000)) == 1024
    assert clip("short") == "short"
    assert "```" not in defang_code_block("a```b")


def test_modal_parser_absolutizes_links_and_bounds_attendance():
    fetcher = SixFetcher(Config.load())
    page = (
        "<dl><dt>Link</dt><dd>"
        '<a href="/edunex/course/1">Edunex</a>'
        '<a href="javascript:alert(1)">Teams</a>'
        '<a href="https://teams.microsoft.com/l/1">Teams</a>'
        "</dd></dl>"
        + "<div>" + "x" * 5000 + " Presensi dibuka 08:00 &amp; ditutup 10:00 " + "y" * 5000 + "</div>"
    )
    data = fetcher.parse_modal_details(page)

    assert data["edunex_url"] == "https://six.itb.ac.id/edunex/course/1"
    assert data["teams_url"] == "https://teams.microsoft.com/l/1"
    assert len(data["attendance_window"]) <= 200
    assert "Presensi dibuka 08:00 & ditutup" in data["attendance_window"]
