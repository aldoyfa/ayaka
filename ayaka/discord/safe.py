"""Helpers that keep scraped/untrusted text from breaking Discord payloads."""

from __future__ import annotations

from typing import Optional
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
