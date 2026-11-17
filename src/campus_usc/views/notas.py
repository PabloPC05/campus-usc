"""«Cualificacións»: your grades, as the Campus's grade reports show them.

* ``campus notas``          every course of this year with its total (``--todos``: all years);
* ``campus notas redes``    that course's report: categories, each item with its grade,
                            range, percentage and the teacher's feedback.

The USC has no AJAX function for grades, so this opens the report page once, like clicking
«Cualificacións» on the web (Moodle logs that visit). The cache keeps it for an hour.
"""

from __future__ import annotations

import argparse
import textwrap
from typing import Any

from .. import sources, store
from ..courses import course_year, current
from ..style import AMBER, BLUE, GREEN, RED, bold, link, muted, paint, term_width, truncate, width
from ..ui import (
    activity_icon,
    block,
    course_alias,
    course_chip,
    course_code,
    course_title,
    empty,
    fold,
)
from . import Command, show
from .curso import resolve_course

# The module label the report prints above each item → the Campus's activity icon.
_MODULES = {
    "tarefa": "assign",
    "tarea": "assign",
    "cuestionario": "quiz",
    "foro": "forum",
    "obradoiro": "workshop",
    "taller": "workshop",
    "leccion": "lesson",
    "consulta": "choice",
    "h5p": "h5pactivity",
}


def _number(grade: str | None) -> float | None:
    try:
        return float(str(grade).replace(",", ".").split()[0])
    except (ValueError, IndexError):
        return None


def _maximum(range_text: str | None) -> float | None:
    parts = str(range_text or "").replace(",", ".").replace("–", "-").split("-")
    try:
        return float(parts[-1])
    except ValueError:
        return None


def grade_text(grade: str | None, range_text: str | None = None) -> str:
    """The grade coloured like the Campus: green from half the range up, red below."""

    if grade in (None, "", "-"):
        return muted("–")
    value, top = _number(grade), _maximum(range_text) or 10.0
    color = None if value is None else (GREEN if value >= top / 2 else RED)
    return paint(str(grade), color, bold=True)


# --- every course ---------------------------------------------------------------------------


def _overview(results: dict[str, sources.Result], args: argparse.Namespace) -> list[str]:
    cells = term_width()
    result = results["notas"]
    lines = [block("Cualificacións", "Informe xeral", cells)]
    if not result.ok:
        return lines
    rows = list((result.data or {}).get("courses") or [])
    cached = store.read("cursos")
    known = {int(course["id"]): course for course in (cached[0] if cached else None) or []}
    if not args.todos:
        this_year = {int(course["id"]) for course in current(list(known.values()))}
        rows = [row for row in rows if row.get("course_id") in this_year] or rows
    lines.append("")
    if not rows:
        lines.append(empty("O Campus non mostra cualificacións."))
    for row in rows:
        course = known.get(int(row.get("course_id") or 0)) or {
            "id": row.get("course_id"),
            "full_name": row.get("course_name"),
        }
        grade = grade_text(row.get("grade"))
        chip = course_chip(course.get("id"), course.get("full_name"), max(16, cells - 30))
        alias = muted(course_alias(course.get("full_name")) or "")
        line = f"  {chip}  {alias}"
        line += " " * max(2, cells - width(line) - width(grade) - 2) + grade
        lines.append(line)
    lines.append("")
    lines.append(
        muted("  campus notas <alias> para o detalle")
        + ("" if args.todos else muted("  ·  --todos inclúe outros cursos"))
    )
    return lines


# --- one course ------------------------------------------------------------------------------


def _icon(item: dict[str, Any]) -> str:
    return activity_icon(_MODULES.get(fold(str(item.get("module") or "")), "site"))


def report_lines(report: dict[str, Any], cells: int) -> list[str]:
    items = list(report.get("items") or [])
    lines: list[str] = []
    total = report.get("course_total")
    total_range = next(
        (item.get("range") for item in items if item["kind"] == "total" and item["level"] == 1),
        None,
    )
    lines.append("")
    lines.append(
        "  "
        + paint(" Total do curso ", "#ffffff", "#000066", bold=True)
        + "  "
        + grade_text(total, total_range)
        + (muted(f" / {_maximum(total_range):g}") if _maximum(total_range) else "")
    )
    for item in items:
        level = max(1, int(item.get("level") or 1))
        if item["kind"] == "category":
            if level == 1:
                continue  # the course itself, already in the header
            lines.append("")
            indent = "  " * (level - 1)
            lines.append(f"{indent}{paint('▌', BLUE)} {bold(truncate(item['name'], cells - 8))}")
            continue
        indent = "  " * level
        right = grade_text(item.get("grade"), item.get("range"))
        if item.get("range"):
            right += muted(f"  {item['range']}")
        if item["kind"] == "total":
            name = muted(truncate(item["name"], cells - width(indent) - width(right) - 4))
            line = f"{indent}  {name}"
        else:
            name = truncate(item["name"], cells - width(indent) - width(right) - 6)
            line = f"{indent}{_icon(item)} {link(bold(name), item.get('url'))}"
        line += " " * max(2, cells - width(line) - width(right)) + right
        lines.append(line)
        feedback = str(item.get("feedback") or "").strip()
        if feedback:
            wrap = max(20, cells - width(indent) - 6)
            rows = textwrap.wrap(feedback, wrap)
            for number, row in enumerate(rows[:3]):
                mark = paint("❝ ", AMBER) if number == 0 else "  "
                lines.append(f"{indent}   {mark}{muted(row)}")
            if len(rows) > 3:
                lines.append(f"{indent}     {muted('…')}")
    return lines


def _course(course: dict[str, Any]) -> Any:
    key = f"notas/{course['id']}"

    def render(results: dict[str, sources.Result], args: argparse.Namespace) -> list[str]:
        cells = term_width()
        title = course_title(course.get("full_name"))
        info = " · ".join(filter(None, [course_code(course.get("full_name")), course_year(course)]))
        lines = [block("Cualificacións", truncate(title, cells // 2), cells)]
        lines.append("")
        lines.append(f"  {course_chip(course['id'], course.get('full_name'))}  {muted(info)}")
        result = results[key]
        if result.ok:
            lines += report_lines(result.data or {}, cells)
        return lines

    return key, render


def run(args: argparse.Namespace) -> int:
    if not args.curso:
        return show(args, ["notas"], _overview, ["Cualificacións"])
    course = resolve_course(args.curso)
    if course is None:
        return 1
    key, render = _course(course)
    return show(args, [key], render, ["Cualificacións", course_title(course.get("full_name"))])


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("curso", nargs="?", help="Una asignatura: su informe con el detalle")
    parser.add_argument("--todos", action="store_true", help="Incluye cursos de otros años")


COMMANDS = [
    Command(
        "notas",
        "Tus notas; con una asignatura, el detalle",
        run,
        configure,
        aliases=("cualificacions", "calificaciones"),
    )
]

__all__ = ["COMMANDS", "grade_text", "report_lines"]
