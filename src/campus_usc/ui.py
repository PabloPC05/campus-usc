"""Building blocks shared by every screen: the Campus navbar, blocks, icons and dates.

The chrome mirrors cv.usc.es: its navy navbar with the USC mark and the user's
initials, Moodle blocks with a title rule, activity icons in Moodle 4's purpose
colours, and each course in the colour Moodle gives its card in «Os meus cursos».
Visible labels are the Campus's own, in Galician, as the Campus shows them.
"""

from __future__ import annotations

import re
import sys
import time
import unicodedata
from collections.abc import Iterable
from datetime import date, datetime
from typing import Any

from .style import (
    AMBER,
    BLUE,
    GRAY,
    MINT,
    NAVY,
    PURPOSE,
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

CAMPUS_URL = "https://cv.usc.es"

# Galician, as the Campus prints dates («martes, 17 de novembro»).
WEEKDAYS = ("luns", "martes", "mércores", "xoves", "venres", "sábado", "domingo")
WEEKDAYS_SHORT = ("lun", "mar", "mér", "xov", "ven", "sáb", "dom")
MONTHS = (
    "xaneiro",
    "febreiro",
    "marzo",
    "abril",
    "maio",
    "xuño",
    "xullo",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "decembro",
)

# Moodle's course card colours: core_course course_summary_exporter::coursecolor
# picks basecolors[courseid % 10] when a course has no image.
COURSE_COLORS = (
    "#81ecec",
    "#74b9ff",
    "#a29bfe",
    "#dfe6e9",
    "#00b894",
    "#0984e3",
    "#b2bec3",
    "#fdcb6e",
    "#fd79a8",
    "#6c5ce7",
)

# module → (glyph, Moodle 4 purpose)
ACTIVITY = {
    "assign": ("✎", "assessment"),
    "quiz": ("✓", "assessment"),
    "workshop": ("⚑", "assessment"),
    "lesson": ("◫", "content"),
    "forum": ("❞", "collaboration"),
    "glossary": ("◰", "collaboration"),
    "wiki": ("◰", "collaboration"),
    "data": ("◰", "collaboration"),
    "chat": ("✉", "communication"),
    "choice": ("◉", "communication"),
    "feedback": ("★", "communication"),
    "survey": ("★", "communication"),
    "resource": ("▤", "content"),
    "folder": ("▣", "content"),
    "page": ("≡", "content"),
    "book": ("◫", "content"),
    "url": ("↗", "content"),
    "label": ("¶", "interface"),
    "h5pactivity": ("▶", "content"),
    "scorm": ("▶", "content"),
    "lti": ("▶", "administration"),
    "course": ("◆", "administration"),
    "site": ("◆", "administration"),
    "user": ("●", "administration"),
}

_COURSE_SUFFIX = re.compile(r"\s*\[(?:G\d{4}[0-9A-Z]{3}[A-Z]?|\d{4}/\d{4})\]", re.IGNORECASE)
_CODE = re.compile(r"\[(G\d{4}[0-9A-Z]{3}[A-Z]?)\]", re.IGNORECASE)
_STOPWORDS = frozenset(
    {
        "a",
        "de",
        "del",
        "da",
        "do",
        "das",
        "dos",
        "e",
        "en",
        "y",
        "la",
        "el",
        "o",
        "os",
        "as",
        "the",
        "of",
        "and",
    }
)
_ROMAN = frozenset({"i", "ii", "iii", "iv", "v", "vi"})


# --- text helpers -------------------------------------------------------------------


def fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def course_title(name: str | None) -> str:
    """«Redes [G4012224] [2026/2027]» → «Redes»."""

    return _COURSE_SUFFIX.sub("", name or "").strip()


def course_code(name: str | None) -> str | None:
    match = _CODE.search(name or "")
    return match.group(1).upper() if match else None


def course_alias(name: str | None) -> str:
    """Short handle the commands accept: «ia», «soi», «asr», «redes»."""

    tokens = [token for token in re.split(r"[^0-9a-z]+", fold(course_title(name))) if token]
    words = [token for token in tokens if token not in _STOPWORDS]
    if not words:
        return ""
    if len(words) == 1:
        return words[0]
    return "".join(token if token in _ROMAN or token.isdigit() else token[0] for token in words)


def course_color(course_id: int | None) -> str:
    return COURSE_COLORS[int(course_id or 0) % 10]


def course_chip(course_id: int | None, name: str | None, cells: int | None = None) -> str:
    """Coloured square plus the course's short title, like a Moodle course card."""

    title = course_title(name)
    if cells is not None:
        title = truncate(title, max(1, cells - 2))
    return paint("▌", course_color(course_id)) + " " + title


def activity_icon(module: str | None) -> str:
    """A 3-cell icon in the activity's purpose colour, like Moodle's icon container."""

    glyph, purpose = ACTIVITY.get(str(module or ""), ("•", "interface"))
    return paint(f" {glyph} ", WHITE, PURPOSE[purpose], bold=True)


def initials(fullname: str | None) -> str:
    parts = [part for part in (fullname or "").split() if part]
    if not parts:
        return "··"
    return (parts[0][0] + (parts[1][0] if len(parts) > 1 else "")).upper()


# --- dates --------------------------------------------------------------------------


def parse_moment(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if moment.tzinfo is not None:
        moment = moment.astimezone().replace(tzinfo=None)
    return moment


def long_day(day: date) -> str:
    """«martes, 17 de novembro»."""

    return f"{WEEKDAYS[day.weekday()]}, {day.day} de {MONTHS[day.month - 1]}"


def day_label(day: date, today: date | None = None) -> str:
    today = today or date.today()
    delta = (day - today).days
    if delta == 0:
        return "Hoxe"
    if delta == 1:
        return "Mañá"
    if delta == -1:
        return "Onte"
    return long_day(day).capitalize()


def countdown(moment: datetime, now: datetime | None = None) -> tuple[str, str | None]:
    """Human time left and its urgency colour: («quedan 5 h», RED)."""

    now = now or datetime.now()
    seconds = (moment - now).total_seconds()
    if seconds < 0:
        days = int(-seconds // 86400)
        hours = int(-seconds // 3600)
        if days >= 1:
            return f"atrasada {days} {'día' if days == 1 else 'días'}", RED
        return f"atrasada {max(1, hours)} h", RED
    hours = seconds / 3600
    if hours < 1:
        return f"quedan {max(1, int(seconds // 60))} min", RED
    if hours < 24:
        return f"quedan {int(hours)} h", RED
    days = (moment.date() - now.date()).days
    color = AMBER if days <= 3 else None
    return f"en {days} {'día' if days == 1 else 'días'}", color


# --- layout -------------------------------------------------------------------------


def navbar(crumbs: Iterable[str] = (), user: str | None = None, cells: int | None = None) -> str:
    """The Campus top bar (navy, USC mark, user initials) plus a breadcrumb line."""

    cells = cells or term_width()
    mark = paint(" USC ", NAVY, MINT, bold=True)
    brand = paint("  Campus Virtual", WHITE, NAVY, bold=True)
    right = ""
    if user:
        right = paint(f" {initials(user)} ", NAVY, MINT, bold=True) + paint(
            f" {truncate(user, 28)} ", WHITE, NAVY
        )
    gap = max(1, cells - width(mark) - width(brand) - width(right))
    bar = mark + brand + paint(" " * gap, bg=NAVY) + right
    trail = list(crumbs)
    if not trail:
        return bar
    parts = [paint(item, GRAY) for item in trail[:-1]] + [paint(trail[-1], BLUE, bold=True)]
    return bar + "\n " + paint(" › ", GRAY).join(parts)


def block(title: str, right: str = "", cells: int | None = None) -> str:
    """A Moodle block heading: bold title, a thin rule, an optional filter on the right."""

    cells = cells or term_width()
    left = paint(title, bold=True)
    tail = f" {muted(right)}" if right else ""
    rule = max(2, cells - width(left) - width(tail) - 2)
    return f"\n{left} {paint('─' * rule, GRAY)}{tail}"


def box(title: str, lines: list[str], cells: int | None = None, accent: str = GRAY) -> list[str]:
    """Lines inside a rounded card, like a Moodle block card."""

    cells = cells or term_width()
    inner = cells - 4
    head = paint("╭─ ", accent) + bold(title) + " "
    top = head + paint("─" * max(1, cells - width(head) - 1) + "╮", accent)
    body = [paint("│ ", accent) + pad(line, inner) + paint(" │", accent) for line in lines]
    bottom = paint("╰" + "─" * (cells - 2) + "╯", accent)
    return [top, *body, bottom]


def columns(left: list[str], right: list[str], cells: int | None = None, gap: int = 3) -> list[str]:
    """Two blocks of lines side by side (each already fits half the width)."""

    cells = cells or term_width()
    half = (cells - gap) // 2
    rows = max(len(left), len(right))
    left = left + [""] * (rows - len(left))
    right = right + [""] * (rows - len(right))
    return [
        pad(clip(a, half), half) + " " * gap + clip(b, cells - half - gap)
        for a, b in zip(left, right, strict=True)
    ]


def empty(text: str) -> str:
    return "  " + paint(text, GRAY, italic=True)


def campus_link(text: str, url: str | None) -> str:
    return link(text, url)


def status_line(results: dict[str, Any], started: float | None = None) -> str:
    """Footer: data age, background refresh, errors and how long this took."""

    ages = [r.age for r in results.values() if r.ok and r.age is not None]
    parts: list[str] = []
    if ages:
        from .sources import describe_age

        oldest = max(ages)
        parts.append(f"datos {describe_age(oldest)}")
    if any(r.refreshing for r in results.values()):
        parts.append("actualizando en segundo plano")
    if started is not None:
        parts.append(f"{time.perf_counter() - started:.2f} s")
    line = paint("  " + " · ".join(parts), GRAY) if parts else ""
    problems = []
    if any(r.login_needed for r in results.values()):
        from .auth import has_screen, session_saved

        what = "La sesión del Campus caducó" if session_saved() else "No has entrado en el Campus"
        how = "campus login" if has_screen() else "campus login --pegar"
        problems.append(
            paint(" ! ", WHITE, RED, bold=True)
            + f" {what}: ejecuta "
            + bold(how)
            + (" (mostrando lo último guardado)" if ages else "")
        )
    for result in results.values():
        if result.error and not result.login_needed:
            label = result.key.split("/")[0]
            problems.append(paint(" ! ", WHITE, AMBER, bold=True) + f" {label}: {result.error}")
    return "\n".join(filter(None, [*problems, line]))


def out(lines: Iterable[str] | str) -> None:
    text = lines if isinstance(lines, str) else "\n".join(lines)
    try:
        sys.stdout.write(text + "\n")
        sys.stdout.flush()
    except BrokenPipeError:  # `campus | head`
        pass
