"""Thread-safe SQLite connection manager for Ayaka.

Provides persistent thread-local connections with WAL mode and busy timeouts
to eliminate connection churn during high-frequency sync cycles.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Generator


class ConnectionManager:
    """Manages persistent thread-local SQLite connections.

    Eliminates connection churn (handshakes & PRAGMA roundtrips) by reusing
    one connection per thread while maintaining thread isolation.
    """

    def __init__(self, db_path: str = "ayaka_state.db") -> None:
        self.db_path = str(db_path)
        self._ensure_dir()
        self._local = threading.local()

    def _ensure_dir(self) -> None:
        path = Path(self.db_path)
        if path.parent and not path.parent.exists():
            path.parent.mkdir(parents=True, exist_ok=True)

    def get_connection(self) -> sqlite3.Connection:
        """Get or initialize the persistent SQLite connection for the current thread."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.db_path, timeout=10.0, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA busy_timeout=5000;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            self._local.conn = conn
        return conn

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager yielding the thread connection inside an automatic transaction."""
        conn = self.get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def close(self) -> None:
        """Close current thread's connection if active."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            self._local.conn = None
