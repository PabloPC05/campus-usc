"""«Engadir entrega»: handing in files to an assignment, from the terminal.

    campus entregar <asignatura>                   its assignments, numbered
    campus entregar <asignatura> <tarea>           that submission: open?, files, limits
    campus entregar <asignatura> <tarea> FILE…     hands FILE… in (asks first)
    campus entregar <asignatura> <tarea> --retirar takes the submission back (asks first)

Every step goes through mcp-usc and its one-time confirmations:

1. the assignment is found among the course's activities (from the cache);
2. its submission page is opened once (what «Engadir entrega» opens on the web) to learn
   whether it is open, whether it takes files, how many, and what is already there;
3. what will happen is shown and confirmed (``--si`` skips the question; without a
   terminal it is required);
4. the files replace the submission's files through Moodle's own file manager, sending
   exactly the bytes whose sha256 was confirmed;
5. the page is opened again to check which files Moodle holds now.

``--enviar`` then also sends it for grading, for assignments that ask for that final step
(usually it cannot be changed afterwards).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from .. import sources, store
from ..style import AMBER, BLUE, GREEN, RED, WHITE, bold, muted, paint, term_width, truncate
from ..ui import (
    activity_icon,
    block,
    countdown,
    course_alias,
    course_chip,
    course_title,
    empty,
    fold,
    long_day,
    navbar,
    out,
    parse_moment,
)
from . import Command, fail
from .curso import _ask, _interactive, clean_text, resolve_course

_YES = {"s", "si", "sí", "y", "yes"}
_WORDS = re.compile(r"\w+")


class TaskNotFound(ValueError):
    def __init__(self, message: str, options: list[dict[str, Any]]) -> None:
        super().__init__(message)
        self.options = options


# --- finding the assignment ---------------------------------------------------------------


def assignments(contents: dict[str, Any] | None) -> list[dict[str, Any]]:
    items = (contents or {}).get("items") or []
    return [item for item in items if item.get("module_type") == "assign"]


def _matches(query: list[str], name: list[str]) -> bool:
    """Every query word is a word of the name (numbers exactly, words also as prefixes)."""

    def one(word: str) -> bool:
        if word.isdigit():
            return word in name
        return any(token == word or (len(word) >= 3 and token.startswith(word)) for token in name)

    return all(one(word) for word in query)


def find_task(tasks: list[dict[str, Any]], query: str) -> dict[str, Any]:
    """By its number in the list, its Moodle id or the words of its name."""

    text = query.strip()
    if text.isdigit():
        number = int(text)
        for task in tasks:
            if task.get("module_id") == number:
                return task
        if 1 <= number <= len(tasks):
            return tasks[number - 1]
    wanted = fold(text)
    exact = [task for task in tasks if fold(clean_text(task.get("name"))) == wanted]
    if len(exact) == 1:
        return exact[0]
    words = _WORDS.findall(wanted)
    found = [
        task
        for task in tasks
        if _matches(words, _WORDS.findall(fold(clean_text(task.get("name")))))
    ]
    if len(found) == 1:
        return found[0]
    if found:
        raise TaskNotFound(f"«{query}» coincide con varias tareas:", found)
    raise TaskNotFound(f"No encuentro la tarea «{query}» en esta asignatura.", tasks)


def task_lines(tasks: list[dict[str, Any]], cells: int) -> list[str]:
    lines = []
    for number, task in enumerate(tasks, start=1):
        available = task.get("visible", True)
        name = truncate(clean_text(task.get("name")), cells - (14 if available else 31))
        row = f"  {muted(f'{number:>3}')}  {activity_icon('assign')} "
        lines.append(row + (name if available else muted(f"{name} (non dispoñible)")))
    return lines


def _due(cmid: int) -> dict[str, Any] | None:
    """The Cronograma entry for this assignment, if it has one (cache only)."""

    cached = store.read("pendientes")
    pattern = re.compile(rf"[?&]id={cmid}(?!\d)")
    for item in (cached[0] if cached else None) or []:
        if pattern.search(str(item.get("url") or item.get("action_url") or "")):
            return item
    return None


def _size(count: int) -> str:
    if count < 1024:
        return f"{count} B"
    if count < 1024 * 1024:
        return f"{count / 1024:.0f} KB"
    return f"{count / 1024 / 1024:.1f} MB"


# --- talking to the Campus ----------------------------------------------------------------


def _new_service(upload_root: Path | None = None) -> Any:
    from dataclasses import replace

    from mcp_usc.service import UscService  # heavy: only when really handing in
    from mcp_usc.settings import Settings

    settings = Settings.from_env()
    if upload_root is not None:
        # You typed these paths yourself: their folder is what this upload may read.
        settings = replace(settings, upload_root=upload_root)
    return UscService(settings)


async def inspect(service: Any, cmid: int) -> dict[str, Any]:
    """Opens the submission page once (the engine asks for a confirmation even to read it)."""

    preview = await service.inspect_submission_status(cmid, None)
    return await service.inspect_submission_status(cmid, preview["confirmation_token"])


def _state(inspected: dict[str, Any]) -> dict[str, Any]:
    page = inspected.get("inspection") or {}
    manager = page.get("filemanager") or {}
    status = inspected.get("submission_status") or {}
    return {
        "open": bool(inspected.get("editable")),
        "takes_files": bool(manager.get("supported")),
        "files": [item.get("filename") for item in manager.get("current_files") or []],
        "max_files": manager.get("max_files"),
        "max_bytes": manager.get("max_bytes"),
        "status": dict(status.get("rows") or {}),
        "submit_step": bool(status.get("submit_for_grading_available")),
        "unknown": inspected.get("outcome") == "unknown",
    }


# The rows of «Estado da entrega» worth showing, in whatever language the Campus speaks.
_STATUS_ROWS = (
    ("estado da entrega", "estado de la entrega", "submission status"),
    ("estado das cualificacions", "estado de la calificacion", "grading status"),
    ("data limite", "fecha de entrega", "due date"),
    ("tempo restante", "tiempo restante", "time remaining"),
)


def status_lines(state: dict[str, Any], cells: int) -> list[str]:
    rows = state.get("status") or {}
    lines = []
    for names in _STATUS_ROWS:
        for label, value in rows.items():
            if any(name in fold(label) for name in names):
                text = f"{label}: "
                tone = AMBER if "borrador" in fold(value) or "atrasad" in fold(value) else None
                lines.append(
                    "  " + muted(text) + paint(truncate(value, cells - len(text) - 4), tone)
                )
                break
    return lines


# --- the screen ---------------------------------------------------------------------------


def _check_files(paths: list[str]) -> tuple[list[Path], str | None]:
    files: list[Path] = []
    names: set[str] = set()
    for raw in paths:
        path = Path(raw).expanduser()
        if not path.is_file():
            return [], f"No encuentro el archivo {raw}."
        resolved = path.resolve()
        if resolved.name.casefold() in names:
            return [], f"Hay dos archivos llamados {resolved.name}: Moodle no lo permite."
        names.add(resolved.name.casefold())
        files.append(resolved)
    if len(files) > 20:
        return [], "Como mucho 20 archivos por entrega."
    return files, None


def _warn(text: str) -> str:
    return paint(" ! ", WHITE, AMBER, bold=True) + " " + text


async def _withdraw(
    service: Any, cmid: int, before: dict[str, Any], args: argparse.Namespace, say: Any, cells: int
) -> int:
    """«Retirar a entrega»: Moodle's own removal, after the same kind of confirmation."""

    from mcp_usc.campus import AuthenticationRequired, CampusError

    if not before["files"]:
        say("")
        say(muted("  No tienes nada entregado en esta tarea."))
        return 0
    say("")
    say(_warn("Retirará tu entrega: " + ", ".join(before["files"])))
    if not args.si:
        if args.json or not _interactive():
            return fail("Confirma con --si para retirarla sin preguntar.")
        if _ask("¿Retirar? [s/N] ").strip().casefold() not in _YES:
            say("No se ha cambiado nada.")
            return 0
    try:
        preview = await service.preview_remove_submission(None, cmid)
        if not preview.get("allowed"):
            return fail(str(preview.get("warning") or "Moodle no deja retirar esta entrega."))
        result = await service.remove_submission(None, preview["confirmation_token"], cmid)
        diagnostic = result.get("diagnostic") or {}
        if diagnostic:
            return fail(f"No se retiró nada: {diagnostic.get('message')}.")
        after = _state(await inspect(service, cmid))
    except AuthenticationRequired:
        return fail("La sesión del Campus caducó: ejecuta `campus login`.")
    except (CampusError, ValueError) as exc:
        return fail(f"No se pudo retirar: {exc}")
    say("")
    if after["files"]:
        say("  " + paint("✗ Moodle aún muestra: ", RED, bold=True) + ", ".join(after["files"]))
        return 1
    say("  " + paint("✓ Entrega retirada.", GREEN, bold=True))
    for line in status_lines(after, cells):
        say(line)
    sources.refresh_in_background(["pendientes"])
    return 0


async def _hand_in(
    course: dict[str, Any], task: dict[str, Any], files: list[Path], args: argparse.Namespace
) -> int:
    from mcp_usc.campus import AuthenticationRequired, CampusError

    json_mode = bool(args.json)
    say = (lambda text: sys.stderr.write(str(text) + "\n")) if json_mode else out
    cells = term_width()
    cmid = int(task["module_id"])
    title = course_title(course.get("full_name"))
    name = clean_text(task.get("name"))
    alias = course_alias(course.get("full_name")) or str(course["id"])
    root = Path(os.path.commonpath([str(path.parent) for path in files])) if files else None
    service = _new_service(root)
    user = ((store.read("perfil") or ({}, 0))[0] or {}).get("fullname")
    report: dict[str, Any] = {
        "tarea": {"module_id": cmid, "name": name, "course_id": course["id"]},
    }

    def finish(code: int) -> int:
        if json_mode:
            print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return code

    say(navbar(["Os meus cursos", title, "Engadir entrega"], user, cells))
    say(block("Engadir entrega", truncate(title, cells // 2), cells))
    say("")
    say(f"  {course_chip(course['id'], course.get('full_name'))}")
    say(f"  {activity_icon('assign')} {bold(truncate(name, cells - 6))}")
    due = _due(cmid)
    moment = parse_moment(due.get("sort_at")) if due else None
    if moment:
        left, tone = countdown(moment)
        say(
            "    "
            + muted(f"Data límite: {long_day(moment.date())} · {moment:%H:%M}  ")
            + paint(left, tone)
        )
    try:
        before = _state(await inspect(service, cmid))
    except AuthenticationRequired:
        return fail("La sesión del Campus caducó: ejecuta `campus login`.")
    except (CampusError, ValueError) as exc:
        return fail(f"No pude abrir la tarea: {exc}")
    report["antes"] = before
    say("")
    if before["unknown"]:
        return fail("Moodle no respondió como esperaba al abrir la tarea; prueba en la web.")
    for line in status_lines(before, cells):
        say(line)
    if not before["open"]:
        fail("Esta tarea no admite cambios ahora: el plazo cerró o ya se envió para cualificar.")
        return finish(1)
    if not before["takes_files"]:
        fail(
            "Esta tarea no recibe archivos por el Campus (es de texto en línea o se entrega "
            "fuera del Campus)."
        )
        return finish(1)
    limits = []
    if before["max_files"]:
        limits.append(f"máx. {before['max_files']} ficheiro(s)")
    if before["max_bytes"]:
        limits.append(f"{_size(before['max_bytes'])} cada un")
    say(
        "  "
        + paint(" Aberta ", WHITE, GREEN, bold=True)
        + (muted("  " + " · ".join(limits)) if limits else "")
    )
    if before["files"]:
        say("  " + muted("Ficheiros enviados: ") + ", ".join(before["files"]))
    else:
        say("  " + muted("Aínda non entregaches nada."))

    if args.retirar:
        return finish(await _withdraw(service, cmid, before, args, say, cells))
    if not files and not args.enviar:  # just looking
        say("")
        say(muted(f"  Para entregar: campus entregar {alias} {cmid} ficheiro.pdf"))
        return finish(0)
    if not files and not before["files"]:
        return fail("No hay nada que enviar: entrega antes algún archivo.")
    if not files and not before["submit_step"]:
        say("")
        say(muted("  Esta tarea no tiene el paso «Enviar para cualificar»: ya está entregada."))
        return finish(0)
    if before["max_files"] and len(files) > before["max_files"]:
        return fail(f"Esta tarea admite como mucho {before['max_files']} archivo(s).")

    say("")
    if files:
        say("  " + bold("Vas entregar:"))
        for path in files:
            say(
                f"    {paint('↑', BLUE, bold=True)} {path.name}  "
                + muted(_size(path.stat().st_size))
            )
        if before["files"]:
            say(_warn("Sustituirá lo que ya tienes entregado: " + ", ".join(before["files"])))
    if args.enviar:
        say(_warn("La enviará para cualificar: normalmente después ya no podrás cambiarla."))
    if not args.si:
        if json_mode or not _interactive():
            return fail("Confirma con --si para entregar sin preguntar.")
        say("")
        if _ask("¿Entregar? [s/N] ").strip().casefold() not in _YES:
            say("No se ha entregado nada.")
            return finish(0)

    say("")
    after = before
    if files:
        say(muted(f"  Subindo {len(files)} ficheiro(s)…"))
        paths = [str(path) for path in files]
        try:
            preview = await service.preview_replace_submission_files(None, paths, cmid)
            if not preview.get("allowed"):
                return fail(
                    str(preview.get("warning") or "Moodle no permite cambiar esta entrega.")
                )
            result = await service.replace_submission_files(
                None, paths, preview["confirmation_token"], cmid
            )
        except AuthenticationRequired:
            return fail("La sesión del Campus caducó: ejecuta `campus login`.")
        except (CampusError, ValueError) as exc:
            return fail(f"No se pudo entregar: {exc}")
        diagnostic = result.get("diagnostic") or {}
        if diagnostic:
            return fail(f"No se entregó nada: {diagnostic.get('message')}.")
        if result.get("draft_may_be_partial"):
            return fail(
                "Moodle falló a mitad de la entrega: revísala en la web antes de repetir. "
                + str(result.get("reason") or "")
            )
        try:
            after = _state(await inspect(service, cmid))
        except (AuthenticationRequired, CampusError, ValueError) as exc:
            return fail(f"Subido, pero no pude comprobarlo: {exc}. Revísalo en la web.")
        expected = sorted(path.name for path in files)
        report["entregado"] = sorted(str(item) for item in after["files"]) == expected
        report["despois"] = after
        if not report["entregado"]:
            say(
                "  "
                + paint("✗ Moodle no muestra los archivos esperados.", RED, bold=True)
                + muted("  Ahora tiene: " + (", ".join(after["files"]) or "nada"))
            )
            return finish(1)
        say(
            "  "
            + paint("✓ Subido.", GREEN, bold=True)
            + " Moodle ten agora: "
            + ", ".join(expected)
        )

    if args.enviar:
        try:
            ask = await service.preview_submit_assignment(None, True, cmid)
            if not ask.get("allowed"):
                fail(f"Moodle no deja enviarla para cualificar: {ask.get('warning')}")
                return finish(1)
            report["enviada"] = await service.submit_assignment(
                None, True, ask["confirmation_token"], cmid
            )
            after = _state(await inspect(service, cmid))
            report["despois"] = after
        except AuthenticationRequired:
            return fail("La sesión del Campus caducó: ejecuta `campus login`.")
        except (CampusError, ValueError) as exc:
            fail(f"No se pudo enviar para cualificar: {exc}")
            return finish(1)

    sources.refresh_in_background(["pendientes"])
    for line in status_lines(after, cells):
        say(line)
    if after["submit_step"]:
        say(
            _warn(
                "Queda como borrador: el profesorado no la ve hasta «Enviar para cualificar». "
                f"Cuando quieras: campus entregar {alias} {cmid} --enviar"
            )
        )
    elif args.enviar:
        say("  " + paint("✓ Enviada para cualificar.", GREEN, bold=True))
    return finish(0)


def run(args: argparse.Namespace) -> int:
    import asyncio

    course = resolve_course(args.asignatura)
    if course is None:
        return 1
    key = f"contenidos/{course['id']}"
    contents = sources.load([key], force=args.fresco)[key]
    if not contents.ok:
        return fail(contents.error or "No pude leer las actividades de la asignatura.")
    tasks = assignments(contents.data)
    cells = term_width()
    alias = course_alias(course.get("full_name")) or str(course["id"])
    if not args.tarea:
        if args.json:
            print(json.dumps(tasks, ensure_ascii=False, indent=2, default=str))
            return 0
        user = ((store.read("perfil") or ({}, 0))[0] or {}).get("fullname")
        title = course_title(course.get("full_name"))
        lines = [navbar(["Os meus cursos", title, "Tarefas"], user, cells)]
        lines.append(block("Tarefas", f"{len(tasks)}", cells))
        lines.append("")
        lines.extend(task_lines(tasks, cells) or [empty("Esta asignatura no tiene tareas.")])
        lines.append("")
        lines.append(
            muted(
                f"  campus entregar {alias} <número> ficheiro.pdf  ·  sin ficheiro, ves cómo está"
            )
        )
        out(lines)
        return 0
    try:
        task = find_task(tasks, args.tarea)
    except TaskNotFound as exc:
        fail(str(exc))
        for line in task_lines(exc.options, cells):
            sys.stderr.write(line + "\n")
        return 1
    if args.retirar and (args.ficheiros or args.enviar):
        return fail("--retirar va solo: sin archivos ni --enviar.")
    files, problem = _check_files(args.ficheiros)
    if problem:
        return fail(problem)
    try:
        return asyncio.run(_hand_in(course, task, files, args))
    except KeyboardInterrupt:
        fail(
            "Interrumpido. Si ya estaba subiendo, mira cómo quedó con "
            f"`campus entregar {alias} {task.get('module_id')}` antes de repetir."
        )
        return 130


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("asignatura", help="Alias, código G, número o parte del nombre (aed, ia…)")
    parser.add_argument("tarea", nargs="?", help="Número de la lista, id de Moodle o nombre")
    parser.add_argument("ficheiros", nargs="*", metavar="FICHEIRO", help="Archivos a entregar")
    parser.add_argument("--si", action="store_true", help="No preguntes antes de entregar")
    parser.add_argument(
        "--retirar",
        action="store_true",
        help="Retira tu entrega de esa tarea (como «Eliminar entrega» en la web)",
    )
    parser.add_argument(
        "--enviar",
        action="store_true",
        help="Además, envíala para cualificar (si la tarea lo pide; luego no se puede cambiar)",
    )


COMMANDS = [
    Command(
        "entregar",
        "Entrega archivos en una tarea (pregunta antes)",
        run,
        configure,
        aliases=("entrega",),
    )
]

__all__ = ["COMMANDS", "assignments", "find_task", "inspect"]
