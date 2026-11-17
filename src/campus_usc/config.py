"""Small per-user preferences of the `campus` CLI (e.g. your class groups).

Stored as JSON next to the mcp-usc academic profile (``campus.json``); missing or
broken files read as empty preferences.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def config_path() -> Path:
    override = os.environ.get("MCP_USC_CLI_CONFIG")
    if override:
        return Path(override).expanduser()
    home = Path.home()
    if sys.platform == "darwin":
        base = home / "Library" / "Application Support"
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    return base / "mcp-usc" / "campus.json"


def load() -> dict[str, Any]:
    try:
        value = json.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def get(name: str, default: Any = None) -> Any:
    return load().get(name, default)


def set_value(name: str, value: Any) -> None:
    data = load()
    if value is None:
        data.pop(name, None)
    else:
        data[name] = value
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
