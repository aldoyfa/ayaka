"""Helpers that keep scraped/untrusted text from breaking Discord payloads."""

from __future__ import annotations

import re
from typing import Iterable, Optional
from urllib.parse import urlsplit

MAX_LINK_URL = 512      # Discord link-button limit
MAX_FIELD_VALUE = 1024  # Discord embed field value limit


def safe_http_url(url: Optional[str], default: Optional[str] = None) -> Optional[str]:
    """Return ``url`` only if it is a plain http(s) URL Discord will accept, else ``default``."""
    if not url:
        return default
    url = url.strip()
    if len(url) > MAX_LINK_URL or any(c in url for c in " \t\r\n"):
        return default
    try:
        parts = urlsplit(url)
    except ValueError:
        return default
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return default
    return url


def clip(text: object, limit: int = MAX_FIELD_VALUE) -> str:
    """Truncate to ``limit`` characters with an ellipsis so embeds are never rejected."""
    value = str(text)
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def defang_code_block(text: str) -> str:
    """Prevent untrusted text from closing a surrounding ``` block."""
    return text.replace("```", "'''")


_MD_SPECIAL = re.compile(r"([\\*_`~|>\[\]()])")


def escape_text(text: object, limit: int = MAX_FIELD_VALUE) -> str:
    """Neutralize Discord markdown/links/mentions in untrusted text (email subjects, senders)."""
    value = _MD_SPECIAL.sub(r"\\\1", str(text))
    value = value.replace("@", "@\u200b")
    return clip(value, limit)


def join_lines_limited(lines: Iterable[str], limit: int = MAX_FIELD_VALUE, more_label: str = "more") -> str:
    """Join lines for an embed field without exceeding ``limit``; summarize what was cut."""
    lines = [clip(line, 200) for line in lines]
    out: list[str] = []
    used = 0
    for i, line in enumerate(lines):
        remaining = len(lines) - i
        reserve = len(f"\n• ...and {remaining} {more_label}") if remaining > 1 else 0
        if used + len(line) + 1 + reserve > limit and out:
            out.append(f"• ...and {remaining} {more_label}")
            break
        out.append(line)
        used += len(line) + 1
    return "\n".join(out)
