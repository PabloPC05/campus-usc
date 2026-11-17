"""Private on-disk cache of what the Campus answered, so commands render instantly.

One JSON file per key (``pendientes``, ``horario/2026-11-16``…) in the user's cache
folder, readable only by them. Writes are atomic; a corrupt or foreign file reads as a
miss. Nothing secret is stored: no cookies, tokens or session keys.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

FORMAT = 1
_SAFE = re.compile(r"[^0-9A-Za-z_.-]+")


def cache_dir() -> Path:
    override = os.environ.get("MCP_USC_CACHE_DIR")
    if override:
        return Path(override).expanduser()
    shared = os.environ.get("USC_CACHE_DIR", "").strip()  # the engine's disk caches' root
    if shared:
        return Path(shared).expanduser() / "campus"
    home = Path.home()
    if sys.platform == "darwin":
        base = home / "Library" / "Caches"
    elif os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or home / ".cache")
    return base / "mcp-usc" / "campus"


def _path(key: str) -> Path:
    return cache_dir() / f"{_SAFE.sub('_', key)}.json"


def read(key: str) -> tuple[Any, float] | None:
    """``(data, age_seconds)`` for ``key``, or None when missing or unreadable."""

    try:
        raw = _path(key).read_bytes()
        entry = json.loads(raw)
    except (OSError, ValueError):
        return None
    if not isinstance(entry, dict) or entry.get("v") != FORMAT or "data" not in entry:
        return None
    saved_at = entry.get("saved_at")
    if not isinstance(saved_at, (int, float)):
        return None
    return entry["data"], max(0.0, time.time() - saved_at)


def write(key: str, data: Any) -> None:
    import tempfile

    folder = cache_dir()
    folder.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(folder, 0o700)
    payload = json.dumps(
        {"v": FORMAT, "key": key, "saved_at": time.time(), "data": data},
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    descriptor, temporary = tempfile.mkstemp(dir=folder, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.chmod(temporary, 0o600)
        os.replace(temporary, _path(key))
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


def clear() -> int:
    """Delete every cached answer; returns how many files went."""

    removed = 0
    folder = cache_dir()
    if not folder.is_dir():
        return 0
    for item in folder.iterdir():
        if item.suffix in {".json", ".lock"}:
            try:
                item.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def claim_refresh(key: str, seconds: float = 120.0) -> bool:
    """True if no other process started refreshing ``key`` in the last ``seconds``."""

    folder = cache_dir()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        lock = folder / f"{_SAFE.sub('_', key)}.lock"
        try:
            if time.time() - lock.stat().st_mtime < seconds:
                return False
        except FileNotFoundError:
            pass
        lock.write_text(str(os.getpid()), encoding="utf-8")
        return True
    except OSError:
        return False


def release_refresh(key: str) -> None:
    with contextlib.suppress(OSError):
        (cache_dir() / f"{_SAFE.sub('_', key)}.lock").unlink()
