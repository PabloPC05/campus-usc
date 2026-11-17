"""«Próximas entregas»: the assignments you still have to hand in, soonest first.

The Cronograma's data (Moodle only lists what still needs an action from you), narrowed to
assignments, each with the exact ``campus entregar`` that hands it in. Late ones that still
accept a submission are counted apart and shown with ``-a``; closed ones are left out.
"""

from __future__ import annotations

import argparse
import re
from datetime import datetime, timedelta
from typing import Any

from .. import sources
from ..courses import CourseNotFound, find
from ..style import BLUE, RED, WHITE, bold, link, muted, paint, term_width, truncate, width
from ..ui import (
    WEEKDAYS_SHORT,
    activity_icon,
    block,
    countdown,
    course_chip,
    empty,
    parse_moment,
)
from . import Command, add_max, show, words_as_flags
from .cronograma import _courses_from, activity_name

_CMID = re.compile(r"[?&]id=(\d+)")


def module_id(item: dict[str, Any]) -> int | None:
    match = _CMID.search(str(item.get("url") or item.get("action_url") or ""))
    return int(match.group(1)) if match else None


def numbered(
    data: list[dict[str, Any]] | None, now: datetime | None = None
) -> list[tuple[int, dict[str, Any]]]:
    """Every assignment you can still hand in, with a number that does not depend on the view.

    Upcoming ones first (soonest = 1), then late ones that still take work. ``campus entregar
    3 practica.pdf`` hands in number 3 of this list.
    """

    soon, late = upcoming(data, days=3650, now=now)
    return list(enumerate(soon + late, start=1))


def hand_in_command(number: int) -> str:
    return f"campus entregar {number}"


def upcoming(
    data: list[dict[str, Any]] | None, *, days: int, now: datetime | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(assignments due within ``days``, late ones that still take a submission)."""

    now = now or datetime.now()
    limit = now + timedelta(days=days)
    soon: list[dict[str, Any]] = []
    late: list[dict[str, Any]] = []
    for item in data or []:
        if item.get("module") != "assign":
            continue
        moment = parse_moment(item.get("sort_at") or item.get("starts_at"))
        if moment is None:
            continue
        if moment < now:
            if item.get("actionable"):  # Moodle still offers «Engadir entrega»
                late.append(item)
        elif moment <= limit:
            soon.append(item)
    key = lambda item: str(item.get("sort_at") or "")  # noqa: E731
    return sorted(soon, key=key), sorted(late, key=key)


def _when(moment: datetime, now: datetime) -> str:
    today = now.date()
    if moment.date() == today:
        day = "Hoxe"
    elif moment.date() == today + timedelta(days=1):
        day = "Mañá"
    else:
        day = f"{WEEKDAYS_SHORT[moment.weekday()]} {moment.day:>2}"
    return f"{day:<6} {moment:%H:%M}"


def entry_lines(
    item: dict[str, Any], cells: int, now: datetime, number: int | None = None
) -> list[str]:
    moment = parse_moment(item.get("sort_at") or item.get("starts_at"))
    when = _when(moment, now) if moment else "sen data"
    left, tone = countdown(moment, now) if moment else ("", None)
    tag = paint(left, tone, bold=tone == RED) if tone else muted(left)
    opens_later = not item.get("actionable") and moment is not None and moment >= now
    if opens_later:
        tag = muted("aínda non aberta")
    tag_number = muted(f"{number:>3}") if number is not None else "   "
    prefix = (
        f"{tag_number}  {paint(when, RED if moment and moment.date() <= now.date() else BLUE)}  "
    )
    prefix += activity_icon("assign") + " "
    room = max(8, cells - width(prefix) - width(tag) - 2)
    name = link(bold(truncate(activity_name(item), room)), item.get("url"))
    first = prefix + name
    first += " " * max(2, cells - width(first) - width(tag)) + tag
    indent = " " * 18
    chip = course_chip(item.get("course_id"), item.get("course_name"), max(16, cells - 20))
    return [first, indent + chip]


def _render(results: dict[str, sources.Result], args: argparse.Namespace) -> list[str]:
    cells = term_width()
    now = datetime.now()
    result = results["pendientes"]
    soon, late = upcoming(result.data, days=args.dias, now=now)
    numbers = {id(item): number for number, item in numbered(result.data, now)}
    if args.curso:
        try:
            wanted = find(_courses_from(result.data), args.curso)["id"]
        except CourseNotFound as exc:
            return ["", empty(str(exc))]
        soon = [item for item in soon if item.get("course_id") == wanted]
        late = [item for item in late if item.get("course_id") == wanted]
    lines = [block("Próximas entregas", f"{len(soon)} nos próximos {args.dias} días", cells)]
    if not result.ok:
        return lines
    if args.atrasadas and late:
        lines.append("")
        lines.append(" " + paint("Atrasadas · aínda admiten entrega", RED, bold=True))
        for item in late:
            lines.extend(entry_lines(item, cells, now, numbers.get(id(item))))
    lines.append("")
    if not soon:
        lines.append(empty(f"Non tes entregas nos próximos {args.dias} días."))
    shown = soon[: args.max] if args.max else soon
    for item in shown:
        lines.extend(entry_lines(item, cells, now, numbers.get(id(item))))
    if len(shown) < len(soon):
        lines.append(muted(f"  … e {len(soon) - len(shown)} máis · sin -n para velas todas"))
    if late and not args.atrasadas:
        lines.append("")
        lines.append(
            "  "
            + paint(f" {len(late)} ", WHITE, RED, bold=True)
            + paint(" atrasadas que aínda admiten entrega", RED)
            + muted("  ·  campus entregas atrasadas")
        )
    if soon or (late and args.atrasadas):
        lines.append("")
        lines.append(muted("  Para entregar unha: campus entregar <número> ficheiro.pdf"))
    return lines


def run(args: argparse.Namespace) -> int:
    words_as_flags(args, "curso", {"atrasadas": {"atrasadas", "atrasada", "atrasados", "atrasado"}})

    def payload(results: dict[str, sources.Result]) -> Any:
        data = results["pendientes"].data
        soon, late = upcoming(data, days=args.dias)
        wanted = {id(item) for item in (late + soon if args.atrasadas else soon)}
        return [
            {
                **item,
                "numero": number,
                "module_id": module_id(item),
                "atrasada": item in late,
                "entregar": hand_in_command(number),
            }
            for number, item in numbered(data)
            if id(item) in wanted
        ]

    return show(args, ["pendientes"], _render, ["Taboleiro", "Entregas"], json_payload=payload)


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "curso",
        nargs="*",
        help="Solo esta asignatura (ia, redes…); «atrasadas» añade las que aún admiten entrega",
    )
    parser.add_argument("-d", "--dias", type=int, default=30, help="Días hacia delante (30)")
    parser.add_argument(
        "-a", "--atrasadas", action="store_true", help="Incluye las atrasadas aún abiertas"
    )
    add_max(parser, None, "mostrar")


COMMANDS = [
    Command(
        "entregas",
        "Tus próximas entregas, numeradas para entregarlas",
        run,
        configure,
        aliases=("proximas", "próximas", "e2"),
    )
]

__all__ = ["COMMANDS", "hand_in_command", "module_id", "numbered", "upcoming"]
