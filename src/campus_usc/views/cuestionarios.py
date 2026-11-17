"""«Cuestionarios»: your quizzes, when they open and close, and how you did.

* ``campus cuestionarios``          this year's quizzes, by course (from the course pages);
* ``campus cuestionarios ia``       one course's quizzes, numbered;
* ``campus cuestionarios ia 2``     quiz 2: dates, time limit, attempts allowed, each of your
                                    attempts and your grade.

The detail opens the quiz's page once, as on the web (Moodle logs the visit; no attempt is
ever started). Quizzes are answered on the web: ``campus abrir`` takes you there.
"""

from __future__ import annotations

import argparse
import re
from typing import Any

from .. import sources, store
from ..courses import current
from ..style import (
    GREEN,
    RED,
    WHITE,
    bold,
    clip,
    link,
    muted,
    pad,
    paint,
    term_width,
    truncate,
    width,
)
from ..ui import activity_icon, block, course_alias, course_chip, course_title, empty
from . import Command, fail, show
from .curso import _pending_badge, pending_by_module, resolve_course


def quizzes_of(contents: dict[str, Any] | None) -> list[dict[str, Any]]:
    items = (contents or {}).get("items") or []
    return [item for item in items if item.get("module_type") == "quiz"]


def _list(courses: list[dict[str, Any]], numbered: bool) -> Any:
    keys = [f"contenidos/{course['id']}" for course in courses]

    def render(results: dict[str, sources.Result], args: argparse.Namespace) -> list[str]:
        cells = term_width()
        cached = store.read("pendientes")
        pending = pending_by_module(cached[0] if cached else None)
        total = 0
        lines = [block("Cuestionarios", "", cells)]
        for course, key in zip(courses, keys, strict=True):
            quizzes = quizzes_of(results[key].data)
            if not quizzes:
                continue
            total += len(quizzes)
            alias = course_alias(course.get("full_name")) or str(course["id"])
            lines += ["", " " + course_chip(course["id"], course.get("full_name"))]
            for number, quiz in enumerate(quizzes, start=1):
                tag = _pending_badge(pending.get(int(quiz.get("module_id") or 0)))
                if not tag and quiz.get("visible") is False:
                    tag = muted("non dispoñible")
                head = f"  {muted(f'{number:>3}')}  " if numbered else "     "
                name = truncate(str(quiz.get("name") or ""), cells - width(head) - width(tag) - 6)
                row = f"{head}{activity_icon('quiz')} {link(bold(name), quiz.get('activity_url'))}"
                lines.append(row + " " * max(2, cells - width(row) - width(tag)) + tag)
            if not numbered:
                lines.append(muted(f"     campus cuestionarios {alias} <número> para o detalle"))
        if not total:
            lines += ["", empty("Non hai cuestionarios.")]
        return lines

    return keys, render


_SCORE = re.compile(r"(\d+(?:[,.]\d+)?)\s*/\s*(\d+(?:[,.]\d+)?)")


def detail_lines(data: dict[str, Any], cells: int) -> list[str]:
    lines: list[str] = [""]
    rows = {**(data.get("dates") or {}), **(data.get("info") or {})}
    label_cells = max((width(label) for label in rows), default=0) + 1
    for label, value in rows.items():
        head = pad(muted(label + ":"), label_cells)
        lines.append(clip(f"  {head}  {value}", cells))
    grade = str(data.get("final_grade") or "")
    if grade:
        score = _SCORE.search(grade)
        shown = f"{score.group(1)} / {score.group(2)}" if score else grade
        lines += ["", "  " + paint(" Cualificación ", WHITE, GREEN, bold=True) + "  " + bold(shown)]
    attempts = data.get("attempts") or []
    if attempts:
        lines += ["", "  " + bold("Os teus intentos")]
        for number, attempt in enumerate(attempts, start=1):
            state = attempt.get("Estado") or attempt.get("State") or ""
            mark = attempt.get("Cualificación") or attempt.get("Puntuacións") or ""
            mark = re.sub(r"\(\s+", "(", mark)
            when = attempt.get("Completada en") or attempt.get("Iniciado o") or ""
            row = f"   {muted(f'{number}.')} {state}  {bold(mark)}"
            lines.append(truncate_row(row, when, cells))
    elif not grade:
        lines += ["", empty("Aínda non fixeches ningún intento.")]
    lines.append("")
    if data.get("can_attempt"):
        lines.append("  " + paint("● Podes facelo agora", GREEN, bold=True) + muted(" · na web"))
    else:
        lines.append("  " + paint("● Non se pode intentar agora", RED))
    return lines


def truncate_row(row: str, right: str, cells: int) -> str:
    from ..style import clip

    right = muted(right)
    return (
        clip(row, cells - width(right) - 2)
        + " " * max(2, cells - width(row) - width(right))
        + right
    )


def run(args: argparse.Namespace) -> int:
    if not args.curso:
        loaded = sources.load(["cursos"]).get("cursos")
        courses = current(loaded.data or []) if loaded and loaded.ok else []
        keys, render = _list(courses, numbered=False)
        return show(args, keys, render, ["Cuestionarios"])
    course = resolve_course(args.curso)
    if course is None:
        return 1
    title = course_title(course.get("full_name"))
    if args.numero is None:
        keys, render = _list([course], numbered=True)
        return show(args, keys, render, ["Os meus cursos", title, "Cuestionarios"])
    key = f"contenidos/{course['id']}"
    contents = sources.load([key])[key]
    quizzes = quizzes_of(contents.data if contents.ok else None)
    quiz = next((item for item in quizzes if item.get("module_id") == args.numero), None)
    if quiz is None and 1 <= args.numero <= len(quizzes):
        quiz = quizzes[args.numero - 1]
    if quiz is None:
        alias = course_alias(course.get("full_name")) or str(course["id"])
        return fail(
            f"No hay cuestionario {args.numero}: mira la lista con campus cuestionarios {alias}."
        )
    detail_key = f"cuestionario/{quiz['module_id']}"

    def render_detail(results: dict[str, sources.Result], args: argparse.Namespace) -> list[str]:
        cells = term_width()
        data = results[detail_key].data or {}
        name = data.get("name") or quiz.get("name") or "Cuestionario"
        lines = [block(truncate(str(name), cells // 2), truncate(title, cells // 3), cells)]
        lines += detail_lines(data, cells)
        url = quiz.get("activity_url")
        if url:
            lines.append("  " + link(muted(str(url)), str(url)))
        return lines

    return show(args, [detail_key], render_detail, ["Os meus cursos", title, "Cuestionarios"])


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("curso", nargs="?", help="Solo esta asignatura (ia, redes…)")
    parser.add_argument("numero", nargs="?", type=int, metavar="NÚMERO", help="Ese cuestionario")


COMMANDS = [
    Command(
        "cuestionarios",
        "Cuestionarios: fechas, intentos y tu nota",
        run,
        configure,
        aliases=("tests", "quiz"),
    )
]

__all__ = ["COMMANDS", "detail_lines", "quizzes_of"]
