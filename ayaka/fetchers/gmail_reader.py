"""Gmail Reader for Academic Announcements.

Monitors incoming Gmail messages using Google Gmail API.
Filters emails according to Option C:
- Originates from ITB campus domain OR marked Important/Starred
- Contains academic priority keywords (tugas, ujian, deadline, dosen, pengumuman, etc.)
- Only unread/unprocessed messages are surfaced for Discord DM alerts.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional
from pathlib import Path

from ayaka.config import Config

logger = logging.getLogger("ayaka.fetchers.gmail")


class GmailReader:
    def __init__(self, config: Config, google_creds: Any = None):
        self.config = config
        self.creds = google_creds

    def is_configured(self) -> bool:
        return self.creds is not None or self.config.google.has_credentials

    def _build_query(self) -> str:
        """Construct search query based on Option C."""
        domains = self.config.gmail.domains
        keywords = self.config.gmail.keywords

        # Domain part: from:itb.ac.id OR from:mahasiswa.itb.ac.id
        from_parts = " OR ".join([f"from:{d}" for d in domains])
        domain_or_important = f"({from_parts} OR is:important OR is:starred)"

        # Keyword part
        keyword_parts = " OR ".join(keywords)
        keyword_clause = f"({keyword_parts})"

        # Only check unread messages to prevent flooding historical emails
        query = f"{domain_or_important} AND {keyword_clause} is:unread"
        return query

    def fetch_important_messages(self) -> List[dict[str, Any]]:
        """Fetch list of important unread academic messages."""
        if not self.is_configured():
            logger.info("Gmail credentials not loaded. Skipping Gmail check.")
            return []

        try:
            from googleapiclient.discovery import build
            service = build("gmail", "v1", credentials=self.creds, cache_discovery=False)
        except Exception as e:
            logger.error(f"Failed to initialize Gmail API service: {e}")
            return []

        query = self._build_query()
        logger.debug(f"Querying Gmail with: {query}")

        messages: list[dict[str, Any]] = []
        try:
            results = (
                service.users()
                .messages()
                .list(userId="me", q=query, maxResults=self.config.gmail.max_results)
                .execute()
            )
            raw_msgs = results.get("messages", [])

            for m in raw_msgs:
                msg_id = m["id"]
                detail = (
                    service.users()
                    .messages()
                    .get(userId="me", id=msg_id, format="metadata", metadataHeaders=["Subject", "From", "Date"])
                    .execute()
                )

                headers = {h["name"]: h["value"] for h in detail.get("payload", {}).get("headers", [])}
                subject = headers.get("Subject", "(No Subject)")
                sender = headers.get("From", "Unknown Sender")
                date_str = headers.get("Date", "")
                snippet = detail.get("snippet", "")

                messages.append({
                    "id": msg_id,
                    "subject": subject,
                    "sender": sender,
                    "date": date_str,
                    "snippet": snippet,
                })
        except Exception as e:
            logger.error(f"Error fetching Gmail messages: {e}")

        return messages
