"""«Notificacións»: the Campus notifications popover, as a numbered list, and each one in full.

* ``campus notificaciones``      the list, newest first, each with its number;
* ``campus notificaciones 3``    notification 3 in full (its whole message and its link);
* ``… 3 --marcar-leida``         also marks it as read in the Campus, like opening it on the web.

Reading never changes anything by itself: only ``--marcar-leida`` does, and it goes through
mcp-usc's one-time confirmation like every other write.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import textwrap
import time
from datetime import datetime
from typing import Any

from .. import sources, store
from ..style import BLUE, GREEN, bold, link, muted, paint, term_width, truncate, width
from ..ui import ACTIVITY, MONTHS, activity_icon, block, empty, fold, long_day, navbar, out
from . import Command, fail, show

_TAGS = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"\s+")
_MARK_READ = "core_message_mark_notification_read"


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
    year = "" if moment.year == datetime.now().year else f" {moment.year}"
    return f"{moment.day} {MONTHS[moment.month - 1][:3]}.{year}"


def notification_module(component: Any) -> str:
    """The activity icon for a Moodle component: ``mod_assign`` → ``assign``."""

    name = str(component or "")
    if name.startswith("mod_") and name[4:] in ACTIVITY:
        return name[4:]
    return "site"


def clean(value: Any) -> str:
    return _SPACES.sub(" ", _TAGS.sub(" ", str(value or ""))).strip()


def notification_lines(
    item: dict[str, Any], cells: int, *, now: float | None = None, number: int | None = None
) -> list[str]:
    unread = not item.get("read")
    dot = paint("●", BLUE, bold=True) if unread else muted("○")
    when = relative_time(item.get("timecreated"), now)
    when_text = paint(when, BLUE) if unread else muted(when)
    subject = clean(item.get("subject")) or "(sen asunto)"
    tag = muted(f"{number:>3}") if number is not None else ""
    prefix = f"{tag} {dot} {activity_icon(notification_module(item.get('component')))} "
    room = max(8, cells - width(prefix) - width(when) - 2)
    first = prefix + link(bold(truncate(subject, room)), item.get("contexturl"))
    first += " " * max(2, cells - width(first) - width(when)) + when_text
    lines = [first]
    small = clean(item.get("smallmessage"))
    indent = width(prefix)
    if small and not _same(small, subject):
        lines.append(" " * indent + muted(truncate(small, cells - indent - 2)))
    return lines


def _same(left: str, right: str) -> bool:
    a, b = fold(left), fold(right)
    return a == b or a.startswith(b) or b.startswith(a)


def numbered(data: dict[str, Any] | None, *, unread_only: bool) -> list[tuple[int, dict]]:
    """``(number, notification)``: numbers stay those of the full list, also when filtered."""

    items = list(enumerate((data or {}).get("items") or [], start=1))
    return [(n, item) for n, item in items if not item.get("read")] if unread_only else items


def select(data: dict[str, Any] | None, *, unread_only: bool) -> list[dict[str, Any]]:
    return [item for _, item in numbered(data, unread_only=unread_only)]


def _render(results: dict[str, sources.Result], args: argparse.Namespace) -> list[str]:
    cells = term_width()
    result = results["notificaciones"]
    unread = int((result.data or {}).get("unread") or 0)
    right = f"{unread} sen ler" if unread else "Todo ao día"
    lines = [block("Notificacións", right, cells)]
    if not result.ok:
        return lines
    items = numbered(result.data, unread_only=args.sin_leer)
    lines.append("")
    if not items:
        lines.append(
            empty("Non tes notificacións novas." if args.sin_leer else "Non hai notificacións.")
        )
    for number, item in items:
        lines.extend(notification_lines(item, cells, number=number))
    lines.append("")
    hint = f"  campus notificaciones {items[0][0]}  para leer una entera" if items else ""
    lines.append(
        muted(hint or "  Nada se marca como leído al mirar la lista.")
        + (muted("  ·  --sin-leer") if items and not args.sin_leer else "")
    )
    return lines


# --- one notification -------------------------------------------------------------------------


def _moment(item: dict[str, Any]) -> str:
    try:
        moment = datetime.fromtimestamp(float(item.get("timecreated")))
    except (TypeError, ValueError, OSError):
        return ""
    return f"{long_day(moment.date())} · {moment:%H:%M}"


def detail_lines(item: dict[str, Any], number: int, cells: int) -> list[str]:
    unread = not item.get("read")
    lines = [block(f"Notificación {number}", relative_time(item.get("timecreated")), cells), ""]
    icon = activity_icon(notification_module(item.get("component")))
    dot = paint("●", BLUE, bold=True) if unread else muted("○")
    subject = clean(item.get("subject")) or "(sen asunto)"
    wrap = max(20, cells - 6)
    for index, row in enumerate(textwrap.wrap(subject, wrap) or [subject]):
        lines.append((f" {dot} {icon} " if index == 0 else "     ") + bold(row))
    status = paint("sen ler", BLUE) if unread else muted("lida")
    lines.append("     " + muted(_moment(item)) + muted("  ·  ") + status)
    lines.append("")
    text = str(item.get("text") or "").strip() or clean(item.get("smallmessage"))
    if not text:
        lines.append(empty("A notificación non trae máis texto."))
    for paragraph in text.split("\n"):
        if not paragraph.strip():
            lines.append("")
            continue
        lines.extend("     " + row for row in textwrap.wrap(paragraph, wrap) or [""])
    url = item.get("contexturl")
    if url:
        label = clean(item.get("contexturlname")) or "Abrir no Campus"
        lines.append("")
        lines.append(
            f"     {paint('↗', BLUE, bold=True)} {link(bold(truncate(label, wrap - 2)), url)}"
        )
        lines.append("       " + muted(truncate(str(url), wrap - 2)))
    return lines


def _new_service() -> Any:
    from mcp_usc.service import UscService  # heavy: only when marking as read

    return UscService()


async def mark_read(notification_id: int) -> dict[str, Any]:
    """Marks one notification as read through the engine's confirmed student action."""

    service = _new_service()
    arguments = {"notificationid": int(notification_id)}
    preview = await service.student_action(_MARK_READ, arguments, None)
    return await service.student_action(_MARK_READ, arguments, preview["confirmation_token"])


def _remember_read(data: dict[str, Any], notification_id: Any) -> None:
    """The cache says it is read at once; a background refresh brings the Campus's view."""

    for item in data.get("items") or []:
        if item.get("id") == notification_id and not item.get("read"):
            item["read"] = True
            data["unread"] = max(0, int(data.get("unread") or 0) - 1)
    store.write("notificaciones", data)
    sources.refresh_in_background(["notificaciones"])


def run_one(args: argparse.Namespace) -> int:
    import asyncio

    loaded = sources.load(["notificaciones"], force=args.fresco)["notificaciones"]
    if not loaded.ok:
        return fail(loaded.error or "No pude leer las notificaciones del Campus.")
    items = list((loaded.data or {}).get("items") or [])
    number = args.numero
    if not 1 <= number <= len(items):
        return fail(
            f"No hay notificación {number}: la lista tiene {len(items)}. "
            "Mira los números con `campus notificaciones`."
        )
    item = items[number - 1]
    marked: dict[str, Any] | None = None
    if args.marcar_leida and not item.get("read"):
        from mcp_usc.campus import AuthenticationRequired, CampusError

        from ..auth import SessionExpired, run_with_session

        outcome: dict[str, Any] = {}

        def attempt() -> int:
            try:
                outcome["marked"] = asyncio.run(mark_read(item["id"]))
            except AuthenticationRequired:
                raise SessionExpired from None
            return 0

        try:
            if run_with_session(attempt, interactive=sys.stdin.isatty() and not args.json):
                return 1
        except (CampusError, ValueError, KeyError) as exc:
            return fail(f"No pude marcarla como leída: {exc}")
        marked = outcome["marked"]
        if marked.get("outcome") == "reported_by_moodle":
            _remember_read(loaded.data, item.get("id"))
            item = {**item, "read": True}
    if args.json:
        payload = {"numero": number, **item}
        if marked is not None:
            payload["marcada_leida"] = marked.get("outcome") == "reported_by_moodle"
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return 0
    cells = term_width()
    user = ((store.read("perfil") or ({}, 0))[0] or {}).get("fullname")
    subject = clean(item.get("subject")) or "(sen asunto)"
    lines = [navbar(["Notificacións", truncate(subject, 40)], user, cells)]
    lines.extend(detail_lines(item, number, cells))
    lines.append("")
    if marked is not None and marked.get("outcome") == "reported_by_moodle":
        lines.append("  " + paint("✓ Marcada como lida no Campus", GREEN, bold=True))
    elif marked is not None:
        lines.append(
            "  " + muted("Moodle no confirmó la marca; mira el Campus antes de repetirlo.")
        )
    elif not item.get("read"):
        lines.append(muted("  Sigue sin leer en el Campus · --marcar-leida para marcarla"))
    out(lines)
    return 0


def run(args: argparse.Namespace) -> int:
    if args.numero is not None:
        return run_one(args)
    if args.marcar_leida:
        return fail("Indica qué notificación marcar: campus notificaciones 3 --marcar-leida")
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
    parser.add_argument(
        "numero", nargs="?", type=int, metavar="NÚMERO", help="Lee esa notificación entera"
    )
    parser.add_argument("--sin-leer", action="store_true", help="Solo las no leídas")
    parser.add_argument(
        "-m",
        "--marcar-leida",
        action="store_true",
        help="Márcala como leída en el Campus (como al abrirla en la web)",
    )


COMMANDS = [
    Command(
        "notificaciones",
        "Notificacións del Campus; con un número, la lee entera",
        run,
        configure,
        aliases=("n", "notificacions"),
    )
]

__all__ = ["COMMANDS", "detail_lines", "mark_read", "notification_lines", "relative_time"]
