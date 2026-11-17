"""«Notificacións»: the Campus notifications popover, as a list.

Read-only: nothing is ever marked as read from here (reading a notification in
Moodle changes its state for the account, and the terminal must not do that quietly).
"""

from __future__ import annotations

import argparse
import re
import time
from datetime import datetime
from typing import Any

from .. import sources
from ..style import BLUE, bold, link, muted, paint, term_width, truncate, width
from ..ui import ACTIVITY, MONTHS, activity_icon, block, empty, fold
from . import Command, show

_TAGS = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"\s+")


def relative_time(created: Any, now: float | None = None) -> str:
    """«hai 3 h», «hai 2 días»: how long ago, in Galician."""

    try:
        stamp = float(created)
    except (TypeError, ValueError):
        return ""
    seconds = (now if now is not None else time.time()) - stamp
    if seconds < 60:
        return "agora mesmo"
    minutes = seconds / 60
    if minutes < 60:
        return f"hai {int(minutes)} min"
    hours = minutes / 60
    if hours < 24:
        return f"hai {int(hours)} h"
    days = int(hours / 24)
    if days < 30:
        return f"hai {days} {'día' if days == 1 else 'días'}"
    moment = datetime.fromtimestamp(stamp)
    return f"{moment.day} {MONTHS[moment.month - 1][:3]}."


def notification_module(component: Any) -> str:
    """The activity icon for a Moodle component: ``mod_assign`` → ``assign``."""

    name = str(component or "")
    if name.startswith("mod_") and name[4:] in ACTIVITY:
        return name[4:]
    return "site"


def clean(value: Any) -> str:
    return _SPACES.sub(" ", _TAGS.sub(" ", str(value or ""))).strip()


def notification_lines(item: dict[str, Any], cells: int, *, now: float | None = None) -> list[str]:
    unread = not item.get("read")
    dot = paint("●", BLUE, bold=True) if unread else muted("○")
    when = relative_time(item.get("timecreated"), now)
    when_text = paint(when, BLUE) if unread else muted(when)
    subject = clean(item.get("subject")) or "(sen asunto)"
    prefix = f" {dot} {activity_icon(notification_module(item.get('component')))} "
    room = max(8, cells - width(prefix) - width(when) - 2)
    first = prefix + link(bold(truncate(subject, room)), item.get("contexturl"))
    first += " " * max(2, cells - width(first) - width(when)) + when_text
    lines = [first]
    small = clean(item.get("smallmessage"))
    if small and not _same(small, subject):
        lines.append(" " * 8 + muted(truncate(small, cells - 10)))
    return lines


def _same(left: str, right: str) -> bool:
    a, b = fold(left), fold(right)
    return a == b or a.startswith(b) or b.startswith(a)


def select(data: dict[str, Any] | None, *, unread_only: bool) -> list[dict[str, Any]]:
    items = list((data or {}).get("items") or [])
    return [item for item in items if not item.get("read")] if unread_only else items


def _render(results: dict[str, sources.Result], args: argparse.Namespace) -> list[str]:
    cells = term_width()
    result = results["notificaciones"]
    unread = int((result.data or {}).get("unread") or 0)
    right = f"{unread} sen ler" if unread else "Todo ao día"
    lines = [block("Notificacións", right, cells)]
    if not result.ok:
        return lines
    items = select(result.data, unread_only=args.sin_leer)
    lines.append("")
    if not items:
        lines.append(
            empty("Non tes notificacións novas." if args.sin_leer else "Non hai notificacións.")
        )
    for item in items:
        lines.extend(notification_lines(item, cells))
    lines.append("")
    lines.append(
        muted("  Só lectura: non se marca nada como lido.")
        + (muted("  ·  campus notificaciones --sin-leer") if not args.sin_leer else "")
    )
    return lines


def run(args: argparse.Namespace) -> int:
    return show(
        args,
        ["notificaciones"],
        _render,
        ["Notificacións"],
        json_payload=lambda results: {
            **(results["notificaciones"].data or {}),
            "items": select(results["notificaciones"].data, unread_only=args.sin_leer),
        },
    )


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--sin-leer", action="store_true", help="Solo las no leídas")


COMMANDS = [
    Command(
        "notificaciones",
        "Notificacións del Campus (solo lectura)",
        run,
        configure,
        aliases=("n", "notificacions"),
    )
]

__all__ = ["COMMANDS", "notification_lines", "relative_time"]
