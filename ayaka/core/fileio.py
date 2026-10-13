"""Small file helpers for persisting config and credential files safely."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write_text(path: str | Path, text: str, default_mode: int = 0o600) -> None:
    """Write text so a crash or error never leaves a truncated file.

    Writes to a temp file in the same directory, then renames over the target.
    Keeps the existing file's permissions (new files get ``default_mode``).
    Falls back to an in-place write when rename is impossible (e.g. a single
    file bind-mounted into a Docker container); the content is fully built
    before either path runs.
    """
    target = Path(path)
    try:
        mode = target.stat().st_mode & 0o777
    except OSError:
        mode = default_mode

    fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp_name, mode)
        try:
            os.replace(tmp_name, target)
            return
        except OSError:
            pass  # e.g. EBUSY on bind-mounted file; fall through to in-place write
        with open(target, "w", encoding="utf-8") as f:
            f.write(text)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
