"""Base repository definition for Ayaka storage layer."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ayaka.storage.connection import ConnectionManager


class BaseRepository:
    """Abstract base repository holding a shared ConnectionManager."""

    def __init__(self, conn_mgr: ConnectionManager) -> None:
        self.conn_mgr = conn_mgr
