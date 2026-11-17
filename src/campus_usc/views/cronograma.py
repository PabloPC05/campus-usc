"""«Cronograma»: the Campus timeline block, in the terminal.

Same filters as the block on the Taboleiro (Próximos 7/30 días, Atrasada, Ordenar por
datas/cursos). One cached fetch (60 days plus this year's overdue work) serves every
filter, so changing the filter never touches the network.
"""

from __future__ import annotations

import argparse
import re
from datetime import date, datetime, timedelta
from typing import Any

from .. import sources
from ..courses import CourseNotFound, find
from ..style import (
    BLUE,
    RED,
    WHITE,
    bold,
    link,
    muted,
    paint,
    term_width,
    truncate,
    width,
)
from ..ui import (
    activity_icon,
    block,
    countdown,
    course_chip,
    course_title,
    day_label,
    empty,
    long_day,
    parse_moment,
)
from . import Command, show

_DUE_SUFFIX = re.compile(
    r"\s+(?:pendente de entrega|está pendiente|is due|vence|debe entregarse|péchase|closes)$",
    re.IGNORECASE,
)
_KIND = {
    "assign": "Tarefa",
    "quiz": "Cuestionario",
    "forum": "Foro",
    "choice": "Consulta",
    "workshop": "Obradoiro",
    "lesson": "Lección",
    "feedback": "Enquisa",
}


def activity_name(item: dict[str, Any]) -> str:
    return _DUE_SUFFIX.sub("", str(item.get("name") or "")).strip()


def items_in_window(
    data: list[dict[str, Any]] | None,
    *,
    days: int,
    overdue: bool,
    now: datetime | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Events inside the filter and how many overdue ones the filter hid."""

    now = now or datetime.now()
    limit = now + timedelta(days=days)
    shown, hidden_overdue = [], 0
    for item in data or []:
        moment = parse_moment(item.get("sort_at") or item.get("starts_at"))
        if moment is None:
            continue
        if moment < now:
            if overdue:
                shown.append(item)
            else:
                hidden_overdue += 1
            continue
        if moment <= limit:
            shown.append(item)
    shown.sort(key=lambda item: str(item.get("sort_at") or ""))
    return shown, hidden_overdue


def item_lines(item: dict[str, Any], cells: int, *, now: datetime | None = None) -> list[str]:
    """Two lines per activity, as the timeline block draws them."""

    moment = parse_moment(item.get("sort_at") or item.get("starts_at"))
    clock = f"{moment:%H:%M}" if moment else "--:--"
    left_text, color = countdown(moment, now) if moment else ("", None)
    tag = paint(left_text, color, bold=color in {RED}) if color else muted(left_text)
    name_cells = cells - 8 - 4 - width(tag) - 2
    name = link(bold(truncate(activity_name(item), max(8, name_cells))), item.get("url"))
    first = f"  {muted(clock)}  {activity_icon(item.get('module'))} {name}"
    first += " " * max(1, cells - width(first) - width(tag)) + tag
    kind = _KIND.get(str(item.get("module") or ""), "Actividade")
    action = item.get("action_name") if item.get("actionable") else None
    detail = course_chip(item.get("course_id"), item.get("course_name"), 40)
    detail += muted(f" · {kind}")
    if action:
        detail += "  " + link(paint(f" {action} ", BLUE, bold=True), item.get("action_url"))
    return [first, " " * 13 + detail]


def render_timeline(
    items: list[dict[str, Any]],
    cells: int,
    *,
    by_course: bool = False,
    today: date | None = None,
    now: datetime | None = None,
) -> list[str]:
    today = today or date.today()
    lines: list[str] = []
    if by_course:
        groups: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            groups.setdefault(course_title(item.get("course_name")) or "—", []).append(item)
        for title in sorted(groups):
            first = groups[title][0]
            lines.append("")
            lines.append(" " + course_chip(first.get("course_id"), first.get("course_name")))
            for item in groups[title]:
                moment = parse_moment(item.get("sort_at"))
                when = muted(f"{long_day(moment.date())}") if moment else ""
                lines.extend(item_lines(item, cells, now=now)[:1])
                lines.append(" " * 13 + when)
        return lines
    current: date | None = None
    for item in items:
        moment = parse_moment(item.get("sort_at") or item.get("starts_at"))
        day = moment.date() if moment else None
        if day != current:
            current = day
            if day is None:
                label = "Sen data"
            elif day < today:
                label = "Atrasada · " + long_day(day)
            else:
                label = day_label(day, today)
                if label in {"Hoxe", "Mañá"}:
                    label += " · " + long_day(day)
            color = RED if day is not None and day <= today else BLUE
            lines.append("")
            lines.append(" " + paint(label, color, bold=True))
        lines.extend(item_lines(item, cells, now=now))
    return lines


def _render(results: dict[str, sources.Result], args: argparse.Namespace) -> list[str]:
    result = results["pendientes"]
    cells = term_width()
    items, hidden = items_in_window(result.data, days=args.dias, overdue=args.atrasadas)
    if args.curso:
        try:
            wanted = find(_courses_from(result.data), args.curso)
        except CourseNotFound as exc:
            return ["", empty(str(exc))]
        items = [item for item in items if item.get("course_id") == wanted["id"]]
    window = "Atrasada e próximos" if args.atrasadas else f"Próximos {args.dias} días"
    order = "Ordenar por cursos" if args.por_cursos else "Ordenar por datas"
    lines = [block("Cronograma", f"{window} · {order}", cells)]
    if not result.ok:
        return lines
    if not items:
        lines.append("")
        lines.append(empty("Non hai actividades que requiran accións."))
    else:
        lines.extend(render_timeline(items, cells, by_course=args.por_cursos))
    if hidden and not args.atrasadas:
        lines.append("")
        lines.append(
            "  "
            + paint(f" {hidden} ", WHITE, RED, bold=True)
            + paint(f" {'atrasada' if hidden == 1 else 'atrasadas'} sin entregar", RED)
            + muted("  ·  campus pendientes -a")
        )
    return lines


def _courses_from(events: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Courses to match a filter against: cached «Os meus cursos», else the events' own.

    Never touches the network: filtering a cached timeline must stay instant.
    """

    from .. import store

    cached = store.read("cursos")
    if cached is not None and cached[0]:
        return list(cached[0])
    seen: dict[int, dict[str, Any]] = {}
    for event in events or []:
        if event.get("course_id"):
            seen[event["course_id"]] = {
                "id": event["course_id"],
                "full_name": event.get("course_name"),
            }
    return list(seen.values())


def run(args: argparse.Namespace) -> int:
    def payload(results: dict[str, sources.Result]) -> Any:
        items, _ = items_in_window(
            results["pendientes"].data, days=args.dias, overdue=args.atrasadas
        )
        return items

    return show(args, ["pendientes"], _render, ["Taboleiro", "Cronograma"], json_payload=payload)


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("curso", nargs="?", help="Solo esta asignatura (ia, redes, soi…)")
    parser.add_argument("-d", "--dias", type=int, default=7, help="Días hacia delante (7)")
    parser.add_argument("-a", "--atrasadas", action="store_true", help="Incluye lo atrasado")
    parser.add_argument("-c", "--por-cursos", action="store_true", help="Agrupa por asignatura")


COMMANDS = [
    Command(
        "pendientes",
        "Cronograma: entregas y cuestionarios que vencen",
        run,
        configure,
        aliases=("cronograma", "p"),
    )
]

__all__ = ["COMMANDS", "activity_name", "items_in_window", "item_lines", "render_timeline"]
