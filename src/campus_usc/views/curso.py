"""One course: its page, its downloadable materials, downloading them, opening it.

* ``curso``      the course page like Moodle shows it (sections and activities);
* ``materiales`` only the files and folders, with the numbers ``descargar aed 3 5`` takes;
* ``descargar``  downloads them, keeping the confirmation of ``mcp-usc descargar``:
  with a session Moodle records that each new material was opened, so we ask first;
* ``abrir``      opens the course or a Campus page in the browser.

Only the standard library and ``campus_usc`` are imported at module level: the
service (and httpx, bs4…) load inside ``descargar`` alone.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .. import sources, store
from ..auth import SessionExpired, run_with_session
from ..courses import CourseNotFound, course_year, current, find
from ..style import (
    AMBER,
    BLUE,
    GRAY,
    GREEN,
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
    CAMPUS_URL,
    activity_icon,
    block,
    countdown,
    course_alias,
    course_chip,
    course_code,
    course_color,
    course_title,
    day_label,
    empty,
    long_day,
    navbar,
    out,
    parse_moment,
)
from . import Command, fail, show
from .cronograma import item_lines
from .cursos import alias_command, card

_TAGS = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"\s+")
_YES = {"s", "si", "sí", "y", "yes"}
_PENDING_DAYS = 30
_PENDING_ROWS = 6
_LABEL_ROWS = 4

# What ``campus abrir <destino>`` knows: the Campus's own pages.
PAGES: dict[str, tuple[str, str]] = {
    "taboleiro": ("/my/", "Taboleiro"),
    "cursos": ("/my/courses.php", "Os meus cursos"),
    "calendario": ("/calendar/view.php?view=month", "Calendario"),
    "notas": ("/grade/report/overview/index.php", "Cualificacións"),
    "mensaxes": ("/message/index.php", "Mensaxes"),
}
_PAGE_ALIASES = {
    "inicio": "taboleiro",
    "dashboard": "taboleiro",
    "home": "taboleiro",
    "calificaciones": "notas",
    "cualificacions": "notas",
    "mensajes": "mensaxes",
    "mensaxe": "mensaxes",
    "calendar": "calendario",
}


# --- resolving the course ---------------------------------------------------------------


def _report_not_found(error: CourseNotFound, courses: list[dict[str, Any]]) -> None:
    """The error plus the candidates (or, when nothing matched, every current course)."""

    fail(str(error))
    options = error.options or current(courses)
    if not error.options:
        sys.stderr.write(muted("  Tus asignaturas de este curso:") + "\n")
    for course in sorted(options, key=lambda item: str(item.get("full_name"))):
        alias = course_alias(course.get("full_name")) or str(course.get("id"))
        code = course_code(course.get("full_name")) or ""
        year = course_year(course) or ""
        sys.stderr.write(
            f"  {course_chip(course.get('id'), course.get('full_name'))}  "
            + muted(f"{code} {year}".strip())
            + "  →  "
            + muted("campus curso ")
            + paint(alias, BLUE, bold=True)
            + muted(f"   (o {course.get('id')})")
            + "\n"
        )


def resolve_course(query: str) -> dict[str, Any] | None:
    """The course ``query`` names, from the cached «Os meus cursos»; reports and returns
    None when it cannot be told."""

    cursos = sources.load(["cursos"]).get("cursos")
    if cursos is None or not cursos.ok:
        fail(
            (cursos.error if cursos else None)
            or "No pude leer tus asignaturas del Campus. Prueba `campus actualizar`."
        )
        return None
    try:
        return find(cursos.data, query)
    except CourseNotFound as exc:
        _report_not_found(exc, cursos.data)
        return None


def _course_url(course: dict[str, Any]) -> str:
    return str(course.get("url") or f"{CAMPUS_URL}/course/view.php?id={course.get('id')}")


# --- sections and activities --------------------------------------------------------------


def clean_text(value: Any) -> str:
    return _SPACES.sub(" ", _TAGS.sub(" ", str(value or ""))).strip()


def sections_of(items: list[dict[str, Any]]) -> list[tuple[int | None, str, list[dict[str, Any]]]]:
    """Activities grouped by section, in the order the course lists them."""

    groups: dict[Any, list[dict[str, Any]]] = {}
    names: dict[Any, str] = {}
    for item in items:
        key = (
            item.get("section_id")
            if item.get("section_id") is not None
            else (item.get("section_number"))
        )
        groups.setdefault(key, []).append(item)
        names.setdefault(key, clean_text(item.get("section_name")))
    result = []
    for key, members in groups.items():
        number = members[0].get("section_number")
        name = names[key] or (f"Sección {number}" if number is not None else "Sen sección")
        result.append((number, name, members))
    return result


def pick_sections(
    sections: list[tuple[int | None, str, list[dict[str, Any]]]], query: str | None
) -> list[tuple[int | None, str, list[dict[str, Any]]]]:
    """``campus curso aed 2``: a section number, else words of the section's name."""

    if not query:
        return sections
    text = query.strip()
    if text.isdigit():
        wanted = [entry for entry in sections if entry[0] == int(text)]
        if wanted:
            return wanted
    from ..ui import fold

    needle = fold(text)
    return [entry for entry in sections if needle in fold(entry[1])]


def _kind_tag(item: dict[str, Any]) -> str:
    parts = [muted(str(item.get("module_type_label") or item.get("module_type") or ""))]
    files = len(item.get("files") or [])
    if files:
        parts.append(muted(f"{files} {'ficheiro' if files == 1 else 'ficheiros'}"))
    if item.get("visible") is False:
        parts.append(paint("oculto", AMBER))
    return muted(" · ").join(part for part in parts if part)


_CMID = re.compile(r"[?&]id=(\d+)")


def pending_by_module(events: list[dict[str, Any]] | None) -> dict[int, dict[str, Any]]:
    """The Cronograma entry of each activity that still asks something of you."""

    found: dict[int, dict[str, Any]] = {}
    for event in events or []:
        match = _CMID.search(str(event.get("url") or event.get("action_url") or ""))
        if match:
            found.setdefault(int(match.group(1)), event)
    return found


def _pending_badge(event: dict[str, Any] | None, now: datetime | None = None) -> str:
    """«Pendente · en 2 días», «Atrasada», «Pechada»… like the Campus marks it."""

    if not event:
        return ""
    now = now or datetime.now()
    moment = parse_moment(event.get("sort_at") or event.get("starts_at"))
    if moment is None:
        return ""
    if moment < now:
        if not event.get("actionable"):
            return muted("pechada")
        return paint(" Atrasada ", WHITE, RED, bold=True)
    if not event.get("actionable"):
        return muted("aínda non aberta")
    left, tone = countdown(moment, now)
    return paint(" Pendente ", WHITE, BLUE, bold=True) + " " + paint(left, tone)


def graded_by_module(report: dict[str, Any] | None) -> dict[int, tuple[str, str | None]]:
    """``{cmid: (grade, range)}`` from a cached «Cualificacións» report of the course."""

    found: dict[int, tuple[str, str | None]] = {}
    for item in (report or {}).get("items") or []:
        grade = item.get("grade")
        match = _CMID.search(str(item.get("url") or ""))
        if item.get("kind") == "item" and match and grade not in (None, "", "-"):
            found[int(match.group(1))] = (str(grade), item.get("range"))
    return found


def _grade_badge(graded: tuple[str, str | None] | None) -> str:
    if not graded:
        return ""
    from .notas import grade_text

    grade, top = graded
    maximum = str(top or "").replace("–", "-").split("-")[-1].strip()
    return grade_text(grade, top) + (muted(f" / {maximum}") if maximum else "")


def activity_lines(
    item: dict[str, Any],
    cells: int,
    pending: dict[str, Any] | None = None,
    graded: tuple[str, str | None] | None = None,
) -> list[str]:
    module = item.get("module_type")
    icon = activity_icon(module)
    if module == "label":
        # The teacher's own text, as the course page shows it (up to four lines here).
        import textwrap

        text = clean_text(item.get("description")) or clean_text(item.get("name"))
        rows = textwrap.wrap(text, max(20, cells - 8)) or [""]
        if len(rows) > _LABEL_ROWS:
            rows = rows[:_LABEL_ROWS]
            rows[-1] = truncate(rows[-1] + " …", cells - 8)
        return ["  " + icon + " " + muted(rows[0])] + ["     " + muted(row) for row in rows[1:]]
    # A graded task shows its grade, even when its deadline (and the action) is past.
    closed = bool(pending) and not pending.get("actionable")
    tag = (
        (_grade_badge(graded) if closed else "")
        or _pending_badge(pending)
        or _grade_badge(graded)
        or _kind_tag(item)
    )
    name = clean_text(item.get("name")) or "(sen nome)"
    name_cells = max(8, cells - 2 - 3 - 1 - width(tag) - 2)
    shown = link(bold(truncate(name, name_cells)), item.get("activity_url") or item.get("url"))
    first = "  " + icon + " " + shown
    first += " " * max(2, cells - width(first) - width(tag)) + tag
    lines = [first]
    note = clean_text(item.get("availability"))
    if note:
        lines.append(" " * 7 + muted("↳ " + truncate(note, cells - 11)))
    return lines


def section_heading(
    name: str,
    count: int,
    color: str,
    cells: int,
    noun: tuple[str, str] = ("actividade", "actividades"),
) -> str:
    left = paint("▌", color) + " " + bold(truncate(name, cells - 24))
    right = muted(f"{count} {noun[0] if count == 1 else noun[1]}")
    rule = max(2, cells - width(left) - width(right) - 4)
    return " " + left + " " + paint("─" * rule, GRAY) + " " + right


# --- the course page --------------------------------------------------------------------------


def header_card(course: dict[str, Any], cells: int, verbs: tuple[str, ...]) -> list[str]:
    inner = cells - 4
    title = link(bold(truncate(course_title(course.get("full_name")), inner)), _course_url(course))
    year = course_year(course)
    code = " · ".join(
        filter(None, [course_code(course.get("full_name")), year and f"curso {year}"])
    )
    commands = muted("  ·  ").join(alias_command(course, verb) for verb in verbs)
    open_link = link(paint("Abrir no Campus ↗", BLUE, bold=True), _course_url(course))
    gap = max(2, inner - width(code) - width("Abrir no Campus ↗"))
    return card(
        course,
        cells,
        [title, muted(code) + " " * gap + open_link, commands],
    )


def pending_lines(
    events: list[dict[str, Any]] | None, course_id: int, cells: int, now: datetime | None = None
) -> list[str]:
    """«Pendente»: this course's slice of the Cronograma, upcoming first."""

    now = now or datetime.now()
    mine = [event for event in events or [] if event.get("course_id") == course_id]
    upcoming, overdue = [], 0
    for event in sorted(mine, key=lambda item: str(item.get("sort_at"))):
        moment = parse_moment(event.get("sort_at") or event.get("starts_at"))
        if moment is None:
            continue
        if moment < now:
            overdue += 1 if event.get("actionable") else 0
        elif (moment - now).days <= _PENDING_DAYS:
            upcoming.append((moment, event))
    lines = [block("Pendente", f"Próximos {_PENDING_DAYS} días", cells)]
    if not upcoming and not overdue:
        return lines + ["", empty("Non hai actividades que requiran accións.")]
    today = now.date()
    seen: date | None = None
    for moment, event in upcoming[:_PENDING_ROWS]:
        if moment.date() != seen:
            seen = moment.date()
            label = day_label(seen, today)
            if label in {"Hoxe", "Mañá"}:
                label += " · " + long_day(seen)
            lines += ["", " " + paint(label, RED if seen <= today else BLUE, bold=True)]
        lines.append(item_lines(event, cells, now=now)[0])
    if len(upcoming) > _PENDING_ROWS:
        lines += ["", muted(f"  … e {len(upcoming) - _PENDING_ROWS} máis")]
    if overdue:
        lines.append("")
        lines.append(
            "  "
            + paint(f" {overdue} ", WHITE, RED, bold=True)
            + paint(f" {'atrasada' if overdue == 1 else 'atrasadas'} sen entregar", RED)
            + muted("  ·  campus pendientes -a")
        )
    return lines


def _contents(results: dict[str, sources.Result], course: dict[str, Any]) -> sources.Result:
    return results[f"contenidos/{course['id']}"]


def render_course(
    course: dict[str, Any],
    results: dict[str, sources.Result],
    seccion: str | None,
    cells: int | None = None,
) -> list[str]:
    cells = cells or term_width()
    color = course_color(course["id"])
    lines = [""] + header_card(course, cells, ("materiales", "abrir"))
    pendientes = results.get("pendientes")
    if pendientes is not None and pendientes.ok:
        lines += pending_lines(pendientes.data, int(course["id"]), cells)
    contents = _contents(results, course)
    lines.append(block("Contido do curso", "", cells))
    if not contents.ok:
        return lines
    items = list((contents.data or {}).get("items") or [])
    sections = sections_of(items)
    chosen = pick_sections(sections, seccion)
    if not items:
        return lines + ["", empty("Este curso aínda non ten contido.")]
    if not chosen:
        names = ", ".join(f"{number}: {name}" for number, name, _ in sections)
        return lines + [
            "",
            empty(f"Ningunha sección coincide con «{seccion}»."),
            muted("  " + truncate(f"Seccións: {names}", cells - 2)),
        ]
    by_module = pending_by_module(pendientes.data if pendientes is not None else None)
    report = store.read(f"notas/{course['id']}")  # only if you already looked at its grades
    graded = graded_by_module(report[0] if report else None)
    for _, name, members in chosen:
        lines += ["", section_heading(name, len(members), color, cells)]
        for item in members:
            module_id = item.get("module_id")
            lines.extend(
                activity_lines(item, cells, by_module.get(module_id), graded.get(module_id))
            )
    data = contents.data or {}
    if data.get("has_more"):
        lines += [
            "",
            muted(f"  Só se mostran {len(items)} de {data.get('total_count')} actividades."),
        ]
    return lines


def run_curso(args: argparse.Namespace) -> int:
    words = getattr(args, "seccion", None)
    if isinstance(words, list):  # campus curso aed tema 2 → «tema 2»
        args.seccion = " ".join(words) or getattr(args, "seccion_opcion", None)
    course = resolve_course(args.asignatura)
    if course is None:
        return 1
    key = f"contenidos/{course['id']}"
    title = course_title(course.get("full_name"))
    failed = {"contents": False}

    def render(results: dict[str, sources.Result], parsed: argparse.Namespace) -> list[str]:
        failed["contents"] = not results[key].ok
        return render_course(course, results, parsed.seccion)

    def payload(results: dict[str, sources.Result]) -> Any:
        events = results["pendientes"].data if results["pendientes"].ok else []
        data = dict(results[key].data or {})
        items = data.get("items") or []
        data["items"] = [
            i for _, _, m in pick_sections(sections_of(items), args.seccion) for i in m
        ]
        return {
            "curso": course,
            "pendientes": [e for e in events or [] if e.get("course_id") == course["id"]],
            "contenidos": data,
        }

    code = show(
        args,
        ["cursos", "pendientes", key],
        render,
        ["Os meus cursos", title],
        json_payload=payload,
    )
    return code or (1 if failed["contents"] else 0)


def configure_curso(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "asignatura", help="Alias, código G, número o parte del nombre (ia, redes…)"
    )
    parser.add_argument(
        "seccion", nargs="*", help="Solo esta sección: su número o parte de su nombre"
    )
    # the old spelling, still accepted: campus curso aed -s 2
    parser.add_argument("-s", "--seccion", dest="seccion_opcion", help=argparse.SUPPRESS)


# --- materiales ---------------------------------------------------------------------------------


def downloadable(item: dict[str, Any]) -> bool:
    return item.get("module_type") in {"resource", "folder"} or bool(item.get("downloadable"))


def numbered_materials(items: list[dict[str, Any]]) -> list[tuple[int, dict[str, Any]]]:
    """The downloadable materials in the order `campus materiales` shows them, from 1.

    That number is what `campus descargar aed 3 5` takes: no Moodle ids to copy.
    """

    files = [item for item in items if downloadable(item)]
    ordered = [item for _, _, members in sections_of(files) for item in members]
    return list(enumerate(ordered, start=1))


def render_materiales(
    course: dict[str, Any], results: dict[str, sources.Result], cells: int | None = None
) -> list[str]:
    cells = cells or term_width()
    color = course_color(course["id"])
    contents = _contents(results, course)
    lines = [block("Materiais", course_title(course.get("full_name")), cells)]
    if not contents.ok:
        return lines
    items = list((contents.data or {}).get("items") or [])
    files = [item for item in items if downloadable(item)]
    if not files:
        return lines + ["", empty("Este curso non ten ficheiros nin cartafoles descargables.")]
    position = {id(item): n for n, item in numbered_materials(items)}
    for _, name, members in sections_of(files):
        lines += ["", section_heading(name, len(members), color, cells, ("material", "materiais"))]
        for item in members:
            number = muted(f"{position[id(item)]:>3}")
            kind = muted(str(item.get("module_type_label") or item.get("module_type")))
            title = clean_text(item.get("name")) or "(sen nome)"
            room = max(8, cells - 2 - 3 - 2 - 3 - 1 - width(kind) - 2)
            left = f"  {number}  {activity_icon(item.get('module_type'))} " + link(
                bold(truncate(title, room)), item.get("activity_url") or item.get("url")
            )
            lines.append(left + " " * max(2, cells - width(left) - width(kind)) + kind)
    others = Counter(
        str(item.get("module_type_label") or item.get("module_type"))
        for item in items
        if not downloadable(item) and item.get("module_type") != "label"
    )
    lines.append("")
    lines.append(
        muted(f"  {len(files)} materiales  ·  campus descargar ")
        + paint(course_alias(course.get("full_name")) or str(course["id"]), BLUE, bold=True)
        + muted("  <números>  para elegir")
    )
    if others:
        text = ", ".join(f"{count} {kind}" for kind, count in others.most_common())
        lines.append(muted(truncate("  No descargables: " + text, cells)))
    return lines


def run_materiales(args: argparse.Namespace) -> int:
    course = resolve_course(args.asignatura)
    if course is None:
        return 1
    key = f"contenidos/{course['id']}"
    title = course_title(course.get("full_name"))
    failed = {"contents": False}

    def render(results: dict[str, sources.Result], _parsed: argparse.Namespace) -> list[str]:
        failed["contents"] = not results[key].ok
        return ["", *render_materiales(course, results)]

    def payload(results: dict[str, sources.Result]) -> Any:
        items = (results[key].data or {}).get("items") or []
        return [
            {
                "numero": number,
                "module_id": item.get("module_id"),
                "module_type": item.get("module_type"),
                "name": item.get("name"),
                "section_name": item.get("section_name"),
                "url": item.get("activity_url"),
            }
            for number, item in numbered_materials(items)
        ]

    code = show(
        args,
        ["cursos", key],
        render,
        ["Os meus cursos", title, "Materiais"],
        json_payload=payload,
    )
    return code or (1 if failed["contents"] else 0)


def configure_materiales(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "asignatura", help="Alias, código G, número o parte del nombre (ia, redes…)"
    )


# --- descargar ------------------------------------------------------------------------------------


def _new_service() -> Any:
    from campus_usc_core.service import UscService  # heavy: only when really downloading

    return UscService()


def _interactive() -> bool:
    return sys.stdin.isatty()


def _ask(prompt: str) -> str:
    return input(prompt)


def progress_bar(done: int, total: int, color: str, cells: int = 12) -> str:
    filled = round(cells * done / total) if total else 0
    return (
        paint("▕", GRAY)
        + paint("█" * filled, color)
        + paint("░" * (cells - filled), GRAY)
        + paint("▏", GRAY)
    )


_OUTCOMES = {
    "descargado": ("✓", GREEN, "descargado"),
    "ya estaba": ("●", GRAY, "ya estaba"),
    "error": ("✗", RED, "error"),
}


def progress_line(
    item: Any, outcome: str, done: int, total: int, color: str, cells: int | None = None
) -> str:
    cells = cells or term_width()
    mark, tone, label = _OUTCOMES.get(outcome, ("•", None, outcome))
    counter = f"{done:>{len(str(total))}}/{total}"
    prefix = (
        f"  {progress_bar(done, total, color)} {muted(counter)}  {paint(mark, tone, bold=True)} "
    )
    status = paint(label.ljust(10), tone) + " "
    room = max(8, cells - width(prefix) - width(status))
    return prefix + status + truncate(clean_text(getattr(item, "name", "")), room)


def _folder_link(folder: Any) -> str:
    path = Path(str(folder))
    try:
        url = path.resolve().as_uri()
    except (ValueError, OSError):
        url = None
    return link(str(path), url)


async def _download(course: dict[str, Any], args: argparse.Namespace) -> int:
    from campus_usc_core.campus import AuthenticationRequired, CampusError

    json_mode = bool(args.json)
    say = (lambda text: sys.stderr.write(text + "\n")) if json_mode else out
    cells = term_width()
    color = course_color(course["id"])
    title = course_title(course.get("full_name"))
    service = _new_service()
    try:
        plan = await service.course_download_plan(course["id"], args.module_ids or None)
    except AuthenticationRequired:
        raise SessionExpired from None  # nothing downloaded yet: renew and start again
    except (CampusError, ValueError) as exc:
        return fail(str(exc))
    folder = Path(args.carpeta).expanduser() if args.carpeta else plan["folder"]
    items = list(plan["items"])
    total = len(items)
    user = ((store.read("perfil") or ({}, 0))[0] or {}).get("fullname")
    say(navbar(["Os meus cursos", title, "Descargar"], user, cells))
    say(block("Descargar", title, cells))
    say("")
    say(
        f"  {course_chip(course['id'], course.get('full_name'))}  "
        + muted(f"{total} ficheiros e cartafoles →")
        + f" {folder}"
    )
    if not total:
        say("")
        say(empty("Non hai materiais descargables."))
        return 0
    if plan["records_views"] and not args.si:
        say("")
        say(
            paint(" ! ", WHITE, AMBER, bold=True)
            + " Con tu sesión de alumno, Moodle solo entrega cada archivo al abrirlo: quedará "
            "registrado que abriste cada material nuevo, igual que al hacer clic en la web."
        )
        if not _interactive():
            return fail("Confirma con --si para descargar sin preguntar.")
        if _ask("¿Descargar? [s/N] ").strip().casefold() not in _YES:
            say("No se ha descargado nada.")
            return 0
    say("")
    live = not json_mode and sys.stdout.isatty()
    state = {"done": 0}

    def upcoming() -> None:
        if live and state["done"] < total:
            name = clean_text(items[state["done"]].name)
            sys.stdout.write(muted("  " + truncate(f"descargando {name}…", cells - 2)) + "\r")
            sys.stdout.flush()

    def progress(item: Any, outcome: str) -> None:
        state["done"] += 1
        if json_mode:
            return
        if live:
            sys.stdout.write("\x1b[K")
        out(progress_line(item, outcome, state["done"], total, color, cells))
        upcoming()

    upcoming()
    try:
        result = await service.download_course_files_now(
            plan, folder=folder, force=args.forzar, progress=progress
        )
    except AuthenticationRequired:
        return fail("La sesión del Campus caducó: escribe `campus entrar`.")
    except (CampusError, ValueError) as exc:
        return fail(str(exc))
    if live:
        sys.stdout.write("\x1b[K")
    if json_mode:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 1 if result.get("failed") else 0
    failed = result.get("failed") or []
    say("")
    say(
        "  "
        + paint(f"✓ {len(result.get('downloaded') or [])} descargados", GREEN, bold=True)
        + "   "
        + muted(f"● {len(result.get('already_downloaded') or [])} ya estaban")
        + "   "
        + (paint(f"✗ {len(failed)} fallidos", RED, bold=True) if failed else muted("✗ 0 fallidos"))
    )
    for failure in failed:
        say(paint("  ✗ ", RED) + truncate(f"{failure['name']}: {failure['error']}", cells - 4))
    say("  " + muted("Carpeta ") + _folder_link(result.get("folder") or folder))
    return 1 if failed else 0


def _material_ids(course: dict[str, Any], numbers: list[int]) -> list[int] | int:
    """Numbers of `campus materiales` → Moodle ids. A Moodle id itself still works."""

    key = f"contenidos/{course['id']}"
    contents = sources.load([key])[key]
    items = list((contents.data or {}).get("items") or []) if contents.ok else []
    by_number = {n: int(item["module_id"]) for n, item in numbered_materials(items)}
    known = set(by_number.values())
    alias = course_alias(course.get("full_name")) or str(course["id"])
    found: list[int] = []
    for number in numbers:
        if number in by_number:
            found.append(by_number[number])
        elif number in known:  # the old way: the Moodle id
            found.append(number)
        else:
            return fail(
                f"No hay material número {number}: mira la lista con campus materiales {alias}."
            )
    return found


def run_descargar(args: argparse.Namespace) -> int:
    import asyncio

    course = resolve_course(args.asignatura)
    if course is None:
        return 1
    wanted = list(args.numeros or []) + list(args.solo or [])
    ids = _material_ids(course, wanted) if wanted else []
    if isinstance(ids, int):
        return ids
    args.module_ids = ids
    try:
        return run_with_session(
            lambda: asyncio.run(_download(course, args)),
            interactive=_interactive() and not args.json,
        )
    except KeyboardInterrupt:
        fail("Descarga interrumpida; lo ya bajado queda en la carpeta.")
        return 130


def configure_descargar(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "asignatura", help="Alias, código G, número o parte del nombre (ia, redes…)"
    )
    parser.add_argument(
        "numeros", nargs="*", type=int, metavar="NÚMERO", help="Solo estos materiales (sus números)"
    )
    parser.add_argument("--carpeta", help="Carpeta de destino de esta asignatura")
    # the old spelling, still accepted: campus descargar aed --solo 3 5
    parser.add_argument("--solo", type=int, nargs="+", help=argparse.SUPPRESS)
    parser.add_argument("--forzar", action="store_true", help="Vuelve a bajar lo ya descargado")
    parser.add_argument("--si", action="store_true", help="No preguntes antes de descargar")


# --- abrir ---------------------------------------------------------------------------------------


def run_abrir(args: argparse.Namespace) -> int:
    from ..ui import fold

    target = (args.destino or "taboleiro").strip()
    page = _PAGE_ALIASES.get(fold(target), fold(target))
    if page in PAGES:
        path, label = PAGES[page]
        url = CAMPUS_URL + path
        chip = paint("▌", BLUE) + " " + label
    else:
        course = resolve_course(target)
        if course is None:
            return 1
        url = _course_url(course)
        chip = course_chip(course["id"], course.get("full_name"))
    import webbrowser

    opened = webbrowser.open(url)
    if args.json:
        print(json.dumps({"url": url, "abierto": bool(opened)}, ensure_ascii=False))
        return 0 if opened else 1
    if not opened:
        return fail(f"No pude abrir el navegador. Abre esto a mano: {url}")
    out(f"  {paint('↗', BLUE, bold=True)} Abrindo {chip}  {link(muted(url), url)}")
    return 0


def configure_abrir(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "destino",
        nargs="?",
        help="Asignatura (ia, redes…) o taboleiro, cursos, calendario, notas, mensaxes",
    )


COMMANDS = [
    Command(
        "curso",
        "Una asignatura por dentro: campus curso aed",
        run_curso,
        configure_curso,
        aliases=("ver",),
    ),
    Command(
        "materiales",
        "Los archivos de una asignatura, numerados",
        run_materiales,
        configure_materiales,
    ),
    Command(
        "descargar",
        "Descarga sus archivos: campus descargar aed (o aed 3 5)",
        run_descargar,
        configure_descargar,
    ),
    Command(
        "abrir",
        "Abre una asignatura o página del Campus en el navegador",
        run_abrir,
        configure_abrir,
        aliases=("open",),
    ),
]

__all__ = ["COMMANDS", "PAGES", "render_course", "render_materiales", "resolve_course"]
