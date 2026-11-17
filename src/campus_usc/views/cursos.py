"""«Os meus cursos»: the Campus course overview as cards in the terminal.

Each card imitates a Moodle course card: a strip in the colour Moodle paints that
course's card (``ui.course_color``), the title as a link, the subject code, the alias
the other commands accept and the pending work from the cached timeline.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from typing import Any

from .. import sources
from ..courses import course_year, current
from ..style import (
    AMBER,
    BLUE,
    GRAY,
    RED,
    bold,
    link,
    muted,
    pad,
    paint,
    term_width,
    truncate,
    width,
)
from ..ui import (
    block,
    countdown,
    course_alias,
    course_chip,
    course_code,
    course_color,
    course_title,
    empty,
    fold,
    parse_moment,
)
from . import Command, show

TWO_COLUMNS_FROM = 90
_GAP = 2
_SHADES = "░▒▓"


# --- pending work per course --------------------------------------------------------


def pending_by_course(
    events: list[dict[str, Any]] | None, now: datetime | None = None
) -> dict[int, dict[str, Any]]:
    """``{course_id: {overdue, upcoming, soon, next}}`` from the cached timeline."""

    now = now or datetime.now()
    found: dict[int, dict[str, Any]] = {}
    for event in events or []:
        course_id = event.get("course_id")
        moment = parse_moment(event.get("sort_at") or event.get("starts_at"))
        if not course_id or moment is None:
            continue
        entry = found.setdefault(
            int(course_id), {"overdue": 0, "upcoming": 0, "soon": 0, "next": None}
        )
        if moment < now:
            if event.get("actionable"):  # still takes the late work
                entry["overdue"] += 1
            continue
        entry["upcoming"] += 1
        if (moment - now).total_seconds() <= 3 * 86400:
            entry["soon"] += 1
        if entry["next"] is None or moment < entry["next"]:
            entry["next"] = moment
    return found


def pending_segments(entry: dict[str, Any] | None, now: datetime | None = None) -> list[str]:
    """Styled pieces of the «pending» summary, most important first."""

    if not entry or not (entry["overdue"] or entry["upcoming"]):
        return [muted("Sen entregas pendentes")]
    parts: list[str] = []
    if entry["overdue"]:
        word = "atrasada" if entry["overdue"] == 1 else "atrasadas"
        parts.append(paint(f"● {entry['overdue']} {word}", RED, bold=True))
    if entry["upcoming"]:
        word = "pendente" if entry["upcoming"] == 1 else "pendentes"
        text = f"{entry['upcoming']} {word}"
        parts.append(paint(text, AMBER, bold=True) if entry["soon"] else text)
        if entry["next"] is not None:
            parts.append(muted(countdown(entry["next"], now)[0]))
    return parts


def _fit(parts: list[str], cells: int, sep: str = "  ") -> str:
    """Join ``parts`` and drop trailing ones until the line fits ``cells``."""

    while len(parts) > 1 and width(sep.join(parts)) > cells:
        parts = parts[:-1]
    return sep.join(parts)


# --- the card -----------------------------------------------------------------------


def _shade(color: str, factor: float) -> str:
    value = color.lstrip("#")
    channels = [int(int(value[i : i + 2], 16) * factor) for i in (0, 2, 4)]
    return "#" + "".join(f"{channel:02x}" for channel in channels)


def course_strip(course_id: int | None, cells: int) -> str:
    """The card's «image»: a deterministic shaded pattern in the course colour."""

    seed = (int(course_id or 0) * 2654435761 + 12345) & 0xFFFFFFFF
    level = seed % len(_SHADES)
    out: list[str] = []
    for _ in range(cells):
        seed = (seed * 1103515245 + 12345) & 0x7FFFFFFF
        step = (seed >> 16) % 4  # a random walk: smooth like Moodle's generated patterns
        if step == 0:
            level = max(0, level - 1)
        elif step == 1:
            level = min(len(_SHADES) - 1, level + 1)
        out.append(_SHADES[level])
    color = course_color(course_id)
    return paint("".join(out), _shade(color, 0.72), color)


def card(course: dict[str, Any], cells: int, body: list[str]) -> list[str]:
    """A rounded card: the course strip on top, ``body`` lines below."""

    inner = cells - 4
    edge = paint("│", GRAY)
    lines = [
        paint("╭" + "─" * (cells - 2) + "╮", GRAY),
        edge + course_strip(course.get("id"), cells - 2) + edge,
    ]
    lines.extend(edge + " " + pad(line, inner) + " " + edge for line in body)
    lines.append(paint("╰" + "─" * (cells - 2) + "╯", GRAY))
    return lines


def alias_command(course: dict[str, Any], verb: str = "curso") -> str:
    alias = course_alias(course.get("full_name")) or str(course.get("id"))
    return muted(f"campus {verb} ") + paint(alias, BLUE, bold=True)


def course_card(
    course: dict[str, Any],
    cells: int,
    pending: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> list[str]:
    inner = cells - 4
    title = link(bold(truncate(course_title(course.get("full_name")), inner)), course.get("url"))
    code = course_code(course.get("full_name")) or ""
    command = alias_command(course)
    if width(code) + 3 + width(command) > inner:
        command = ""
    second = muted(code) + " " * max(1, inner - width(code) - width(command)) + command
    return card(course, cells, [title, second, _fit(pending_segments(pending, now), inner)])


def _grid(cards: list[list[str]], cells: int) -> list[str]:
    columns = 2 if cells >= TWO_COLUMNS_FROM else 1
    lines: list[str] = []
    for start in range(0, len(cards), columns):
        row = cards[start : start + columns]
        for parts in zip(*row, strict=False):
            lines.append((" " * _GAP).join(parts).rstrip())
    return lines


def _sorted(courses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(courses, key=lambda course: fold(course_title(course.get("full_name"))))


def visible_courses(courses: list[dict[str, Any]], *, todos: bool = False) -> list[dict[str, Any]]:
    """Courses the overview shows: this academic year, minus those hidden from the view."""

    if todos:
        return list(courses)
    return [course for course in current(courses) if not course.get("dashboard_hidden")]


# --- compact list for the dashboard ---------------------------------------------------


def compact_courses(
    cursos_result: sources.Result | None,
    pendientes_result: sources.Result | None,
    cells: int,
) -> list[str]:
    """One line per current course: chip, title, alias and pending counts."""

    if cursos_result is None or not cursos_result.ok:
        return []
    courses = _sorted(visible_courses(cursos_result.data))
    if not courses:
        return []
    pending = pending_by_course(
        pendientes_result.data if pendientes_result is not None and pendientes_result.ok else None
    )
    commands = [alias_command(course) for course in courses]
    command_cells = max(width(command) for command in commands)
    lines = []
    for course, command in zip(courses, commands, strict=True):
        parts = _fit(pending_segments(pending.get(int(course["id"]))), 28)
        tail = width(parts)
        title_cells = max(10, cells - command_cells - tail - 8)
        chip = course_chip(course["id"], course.get("full_name"), title_cells)
        chip = link(chip, course.get("url"))
        line = " " + pad(chip, title_cells) + "  " + pad(command, command_cells) + "  " + parts
        lines.append(line)
    return lines


# --- screen ---------------------------------------------------------------------------


def _group_by_year(courses: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    now_year = sources.academic_year()
    groups: dict[str, list[dict[str, Any]]] = {}
    for course in courses:
        groups.setdefault(course_year(course) or now_year, []).append(course)
    return [(year, _sorted(groups[year])) for year in sorted(groups, reverse=True)]


def _render(results: dict[str, sources.Result], args: argparse.Namespace) -> list[str]:
    cells = term_width()
    year = sources.academic_year()
    right = "Todos" if args.todos else f"En curso · {year}"
    lines = [block("Os meus cursos", right, cells)]
    cursos = results["cursos"]
    if not cursos.ok:
        return lines
    courses = visible_courses(cursos.data, todos=args.todos)
    if not courses:
        lines += ["", empty("Non hai cursos para mostrar.")]
        return lines
    pendientes = results.get("pendientes")
    pending = pending_by_course(pendientes.data if pendientes and pendientes.ok else None)
    columns = 2 if cells >= TWO_COLUMNS_FROM else 1
    card_cells = (cells - _GAP * (columns - 1)) // columns
    groups = _group_by_year(courses) if args.todos else [("", _sorted(courses))]
    for group_year, group in groups:
        if args.todos:
            label = f"Curso {group_year}" + ("  · en curso" if group_year == year else "")
            lines += ["", " " + paint(label, BLUE, bold=True)]
        lines.append("")
        cards = [
            course_card(course, card_cells, pending.get(int(course["id"]))) for course in group
        ]
        lines.extend(_grid(cards, cells))
    lines.append("")
    hints = ["campus materiales <alias>", "campus abrir <alias>", "--todos: cursos anteriores"]
    hint = muted("  campus curso ") + paint("<alias>", BLUE)
    for extra in hints:  # as many as fit the terminal
        candidate = hint + muted(f"  ·  {extra}")
        if width(candidate) > cells:
            break
        hint = candidate
    lines.append(hint)
    return lines


def _payload(results: dict[str, sources.Result], args: argparse.Namespace) -> Any:
    cursos = results["cursos"]
    courses = visible_courses(cursos.data or [], todos=args.todos)
    pendientes = results.get("pendientes")
    pending = pending_by_course(pendientes.data if pendientes and pendientes.ok else None)
    return [
        {
            **course,
            "alias": course_alias(course.get("full_name")),
            "atrasadas": pending.get(int(course["id"]), {}).get("overdue", 0),
            "pendientes": pending.get(int(course["id"]), {}).get("upcoming", 0),
        }
        for course in _sorted(courses)
    ]


def run(args: argparse.Namespace) -> int:
    return show(
        args,
        ["cursos", "pendientes"],
        _render,
        ["Os meus cursos"],
        json_payload=lambda results: _payload(results, args),
    )


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--todos", action="store_true", help="Incluye cursos de años anteriores")


COMMANDS = [
    Command(
        "cursos",
        "Os meus cursos: tus asignaturas como en el Campus",
        run,
        configure,
        aliases=("c", "os-meus-cursos"),
    )
]

__all__ = [
    "COMMANDS",
    "card",
    "compact_courses",
    "course_card",
    "course_strip",
    "pending_by_course",
    "pending_segments",
    "visible_courses",
]
