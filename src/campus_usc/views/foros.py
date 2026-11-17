"""«Novas» and forums: what the teachers announce, and every forum's discussions.

* ``campus avisos``           the latest announcements of all this year's courses;
* ``campus avisos redes``     those of one course;
* ``campus foros redes``      the course's forums, numbered; ``campus foros redes 2`` lists
                              the discussions of forum 2;
* ``campus debate 900``       a discussion in full: every post, threaded, with its text.

Listing reads the forum's page, like opening it on the web (Moodle logs the visit, nothing
is marked as read). Reading a discussion is opening it: Moodle marks its posts as read,
as on the web.
"""

from __future__ import annotations

import argparse
import re
import textwrap
from datetime import datetime
from typing import Any

from .. import sources
from ..courses import current
from ..style import BLUE, GRAY, bold, clip, link, muted, paint, term_width, truncate, width
from ..ui import (
    activity_icon,
    block,
    course_alias,
    course_chip,
    course_title,
    empty,
    fold,
    long_day,
    parse_moment,
)
from . import Command, fail, show
from .curso import resolve_course

_NEWS = re.compile(r"anuncio|nova|novas|noticia|aviso|novidade|news|announce", re.I)


def forums_of(contents: dict[str, Any] | None) -> list[dict[str, Any]]:
    items = (contents or {}).get("items") or []
    return [item for item in items if item.get("module_type") == "forum"]


def news_forum(contents: dict[str, Any] | None) -> dict[str, Any] | None:
    """The course's «Anuncios»/«Foro de novas»: the announcements forum of section 0."""

    forums = forums_of(contents)
    first_section = [item for item in forums if not item.get("section_number")]
    for item in first_section or forums:
        if _NEWS.search(fold(str(item.get("name") or ""))):
            return item
    return first_section[0] if first_section else None


def _contents(courses: list[dict[str, Any]]) -> dict[int, sources.Result]:
    keys = [f"contenidos/{course['id']}" for course in courses]
    loaded = sources.load(keys)
    return {int(key.split("/")[1]): loaded[key] for key in keys}


def discussion_lines(
    discussion: dict[str, Any], cells: int, course: dict[str, Any] | None = None
) -> list[str]:
    unread = int(discussion.get("unread") or 0)
    dot = paint("●", BLUE, bold=True) if unread else muted("○")
    when = str(discussion.get("last_post_at") or discussion.get("started_at") or "")
    pin = paint("📌 ", GRAY) if discussion.get("pinned") else ""
    room = max(8, cells - 6 - width(pin) - width(when) - 2)
    subject = link(
        bold(truncate(str(discussion.get("subject") or ""), room)), discussion.get("url")
    )
    first = f"  {dot} {pin}{subject}"
    first += " " * max(2, cells - width(first) - width(when)) + muted(when)
    parts = []
    if course:
        parts.append(course_chip(course.get("id"), course.get("full_name"), 28))
    parts.append(muted(str(discussion.get("started_by") or "")))
    replies = int(discussion.get("replies") or 0)
    if replies:
        parts.append(muted(f"{replies} {'resposta' if replies == 1 else 'respostas'}"))
    if unread:
        parts.append(paint(f"{unread} sen ler", BLUE))
    parts.append(muted(f"campus debate {discussion.get('discussion_id')}"))
    second = "    " + muted(" · ").join(parts)
    return [first, clip(second, cells)]


# --- avisos ---------------------------------------------------------------------------------


def run_avisos(args: argparse.Namespace) -> int:
    if args.curso:
        course = resolve_course(args.curso)
        if course is None:
            return 1
        courses = [course]
    else:
        loaded = sources.load(["cursos"]).get("cursos")
        courses = current(loaded.data or []) if loaded and loaded.ok else []
    contents = _contents(courses)
    forums: dict[str, dict[str, Any]] = {}
    for course in courses:
        forum = news_forum(contents[int(course["id"])].data)
        if forum:
            forums[f"foro/{forum['module_id']}"] = course

    def render(results: dict[str, sources.Result], args: argparse.Namespace) -> list[str]:
        cells = term_width()
        found: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for key, course in forums.items():
            result = results[key]
            for discussion in (result.data or {}).get("discussions") or []:
                found.append((discussion, course))
        found.sort(key=lambda pair: -int(pair[0].get("discussion_id") or 0))
        unread = sum(int(d.get("unread") or 0) for d, _ in found)
        right = f"{unread} sen ler" if unread else "Anuncios do profesorado"
        lines = [block("Novas", right, cells), ""]
        if not forums:
            return lines + [empty("Estas materias non teñen foro de anuncios.")]
        if not found:
            lines.append(empty("Non hai anuncios."))
        # The newest ones, plus every unread one wherever it is (they are the news).
        shown = [
            pair
            for position, pair in enumerate(found)
            if position < args.numero or int(pair[0].get("unread") or 0)
        ]
        for discussion, course in shown:
            lines.extend(discussion_lines(discussion, cells, course if len(courses) > 1 else None))
        if len(found) > len(shown):
            lines.append(muted(f"  … e {len(found) - len(shown)} máis · -n {len(found)}"))
        lines.append("")
        lines.append(muted("  Ver a lista non marca nada como lido; abrir un debate, si."))
        return lines

    crumbs = ["Novas"] + ([course_title(courses[0].get("full_name"))] if args.curso else [])
    if not forums:
        return show(args, ["cursos"], render, crumbs)
    return show(args, list(forums), render, crumbs)


def configure_avisos(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("curso", nargs="?", help="Solo los de esta asignatura")
    parser.add_argument("-n", "--numero", type=int, default=15, help="Cuántos mostrar (15)")


# --- foros ----------------------------------------------------------------------------------


def _pick_forum(forums: list[dict[str, Any]], query: str) -> dict[str, Any] | None:
    text = query.strip()
    if text.isdigit():
        number = int(text)
        for forum in forums:
            if forum.get("module_id") == number:
                return forum
        if 1 <= number <= len(forums):
            return forums[number - 1]
    matches = [forum for forum in forums if fold(text) in fold(str(forum.get("name") or ""))]
    return matches[0] if len(matches) == 1 else None


def run_foros(args: argparse.Namespace) -> int:
    course = resolve_course(args.curso)
    if course is None:
        return 1
    key = f"contenidos/{course['id']}"
    contents = sources.load([key], force=args.fresco)[key]
    if not contents.ok:
        return fail(contents.error or "No pude leer las actividades de la asignatura.")
    forums = forums_of(contents.data)
    title = course_title(course.get("full_name"))
    alias = course_alias(course.get("full_name")) or str(course["id"])
    if not args.foro:

        def render_list(results: dict[str, sources.Result], args: argparse.Namespace) -> list:
            cells = term_width()
            lines = [block("Foros", truncate(title, cells // 2), cells), ""]
            if not forums:
                return lines + [empty("Esta materia non ten foros.")]
            for number, forum in enumerate(forums, start=1):
                name = truncate(str(forum.get("name") or ""), cells - 20)
                section = muted(truncate(str(forum.get("section_name") or ""), 30))
                row = f"  {muted(f'{number:>3}')}  {activity_icon('forum')} {bold(name)}"
                lines.append(row + " " * max(2, cells - width(row) - width(section)) + section)
            lines.append("")
            lines.append(muted(f"  campus foros {alias} <número> para ver os seus debates"))
            return lines

        return show(args, [key], render_list, ["Os meus cursos", title, "Foros"])
    forum = _pick_forum(forums, args.foro)
    if forum is None:
        return fail(f"No encuentro el foro «{args.foro}»: mira la lista con campus foros {alias}.")
    forum_key = f"foro/{forum['module_id']}"

    def render_forum(results: dict[str, sources.Result], args: argparse.Namespace) -> list:
        cells = term_width()
        data = results[forum_key].data or {}
        name = data.get("forum_name") or forum.get("name") or "Foro"
        lines = [block(truncate(str(name), cells // 2), truncate(title, cells // 3), cells), ""]
        discussions = data.get("discussions") or []
        if not discussions:
            lines.append(empty("Aínda non hai debates."))
        for discussion in discussions:
            lines.extend(discussion_lines(discussion, cells))
        if data.get("has_more"):
            lines += ["", muted("  Hai máis debates no Campus: campus abrir " + alias)]
        return lines

    return show(args, [forum_key], render_forum, ["Os meus cursos", title, "Foros"])


def configure_foros(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("curso", help="La asignatura (redes, ia…)")
    parser.add_argument("foro", nargs="?", help="Número de la lista, id o parte del nombre")


# --- debate ---------------------------------------------------------------------------------


def _when(value: Any) -> str:
    moment = parse_moment(value)
    if moment is None:
        return ""
    year = f" de {moment.year}" if moment.year != datetime.now().year else ""
    return f"{long_day(moment.date())}{year} · {moment:%H:%M}"


def thread(posts: list[dict[str, Any]]) -> list[tuple[int, dict[str, Any]]]:
    """Posts in reading order with their depth: each reply under the post it answers."""

    children: dict[int, list[dict[str, Any]]] = {}
    ids = {int(post.get("post_id") or 0) for post in posts}
    for post in sorted(posts, key=lambda item: str(item.get("created_at") or "")):
        parent = int(post.get("parent_post_id") or 0)
        children.setdefault(parent if parent in ids else 0, []).append(post)
    ordered: list[tuple[int, dict[str, Any]]] = []

    def walk(parent: int, depth: int) -> None:
        for post in children.get(parent, []):
            ordered.append((depth, post))
            walk(int(post.get("post_id") or 0), min(depth + 1, 4))

    walk(0, 0)
    return ordered


def post_lines(post: dict[str, Any], depth: int, cells: int) -> list[str]:
    indent = "  " + "│ " * depth
    author = bold(str(post.get("author") or ""))
    lines = [f"{indent}{paint('▌', BLUE)} {author}  {muted(_when(post.get('created_at')))}"]
    subject = str(post.get("subject") or "")
    if depth == 0 and subject:
        lines.append(f"{indent}  {bold(truncate(subject, cells - width(indent) - 4))}")
    wrap = max(20, cells - width(indent) - 4)
    for paragraph in str(post.get("message") or "").split("\n"):
        if not paragraph.strip():
            lines.append(indent.rstrip())
            continue
        lines.extend(f"{indent}  {row}" for row in textwrap.wrap(paragraph, wrap))
    for attachment in post.get("attachments") or []:
        name = attachment.get("filename") or attachment.get("name") or "anexo"
        lines.append(f"{indent}  {paint('📎', GRAY)} {link(str(name), attachment.get('url'))}")
    lines.append("")
    return lines


def run_debate(args: argparse.Namespace) -> int:
    key = f"debate/{args.debate}"

    def render(results: dict[str, sources.Result], args: argparse.Namespace) -> list[str]:
        cells = term_width()
        posts = list((results[key].data or {}).get("items") or [])
        lines = [block("Debate", f"{len(posts)} mensaxes", cells), ""]
        if not posts:
            return lines + [empty("Este debate non ten mensaxes.")]
        for depth, post in thread(posts):
            lines.extend(post_lines(post, depth, cells))
        lines.append(muted("  Ao abrilo, Moodle marca estas mensaxes como lidas, como na web."))
        return lines

    return show(args, [key], render, ["Foros", "Debate"])


def configure_debate(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("debate", type=int, help="El número de debate (sale en avisos y foros)")


COMMANDS = [
    Command(
        "avisos",
        "Novas: los anuncios del profesorado de tus asignaturas",
        run_avisos,
        configure_avisos,
        aliases=("novas", "anuncios"),
    ),
    Command(
        "foros",
        "Foros de una asignatura y sus debates",
        run_foros,
        configure_foros,
        aliases=("foro",),
    ),
    Command(
        "debate",
        "Lee un debate entero (lo marca como leído, como la web)",
        run_debate,
        configure_debate,
    ),
]

__all__ = ["COMMANDS", "discussion_lines", "news_forum", "thread"]
