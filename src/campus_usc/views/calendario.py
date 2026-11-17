"""«Calendario»: a Moodle-style month grid with its «Próximos eventos», in the terminal.

Deliveries come from the cached «Cronograma» (about 60 days ahead, plus this year's
overdue work) and exams from the official schedule. Days with a delivery are marked in
Moodle's assessment pink, exam days in red, today in the Campus navy.
"""

from __future__ import annotations

import argparse
import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from .. import sources
from ..style import (
    BLUE,
    GRAY,
    MINT,
    NAVY,
    PURPOSE,
    RED,
    WHITE,
    bold,
    caps,
    link,
    muted,
    pad,
    paint,
    term_width,
    truncate,
    width,
)
from ..ui import (
    MONTHS,
    WEEKDAYS_SHORT,
    activity_icon,
    block,
    course_chip,
    course_title,
    empty,
    fold,
    long_day,
    parse_moment,
)
from . import Command, fail, show
from .cronograma import activity_name
from .examenes import Call, all_calls

PINK = PURPOSE["assessment"]
GRID = 28  # 7 cells of 4
_WIDE = 88  # the grid goes beside the events from this width on
_AHEAD = 60  # days the «Cronograma» source reaches
_HEADERS = ("Lu", "Ma", "Mé", "Xo", "Ve", "Sá", "Do")
_MONTHS_ES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


def _today() -> date:
    return date.today()


def _now() -> datetime:
    return datetime.now()


# --- the grid --------------------------------------------------------------------------


def _cell(day: int, weekday: int, has_delivery: bool, has_exam: bool, is_today: bool) -> str:
    """4 cells: a pad, the day number and one marker («•» entrega, «▲» exame, «◆» both)."""

    number = f"{day:>2}"
    if has_delivery and has_exam:
        marker, number_color, marker_color = "◆", PINK, RED
    elif has_exam:
        marker, number_color, marker_color = "▲", RED, RED
    elif has_delivery:
        marker, number_color, marker_color = "•", PINK, PINK
    else:
        marker, number_color, marker_color = " ", (GRAY if weekday >= 5 else None), None
    strong = has_delivery or has_exam
    if is_today:
        if caps.color:
            body = paint(" " + number, MINT, NAVY, bold=True)
        else:  # no colour: brackets say «today»
            body = "[" + number
            marker = marker if marker != " " else "]"
        return body + (paint(marker, marker_color, bold=True) if marker_color else marker)
    body = paint(" " + number, number_color, bold=strong) if number_color else " " + number
    return body + (paint(marker, marker_color, bold=True) if marker_color else marker)


def month_grid(
    year: int,
    month: int,
    deadlines: dict[date, int],
    exams: dict[date, int],
    today: date,
) -> list[str]:
    """Title, weekday header and weeks of the month: 28 cells wide, no navbar."""

    title = f"{MONTHS[month - 1]} de {year}"
    lines = [pad(bold(title), GRID, "^")]
    lines.append(
        "".join(
            paint(f" {name} ", GRAY, bold=True) if index >= 5 else paint(f" {name} ", bold=True)
            for index, name in enumerate(_HEADERS)
        )
    )
    for week in calendar.Calendar(firstweekday=0).monthdatescalendar(year, month):
        cells = []
        for index, day in enumerate(week):
            if day.month != month:
                cells.append("    ")
                continue
            cells.append(
                _cell(day.day, index, day in deadlines, day in exams, day == today),
            )
        lines.append("".join(cells))
    return lines


def _legend() -> list[str]:
    return [
        paint("•", PINK, bold=True)
        + muted(" entrega  ")
        + paint("▲", RED, bold=True)
        + muted(" exame"),
        paint("◆", RED, bold=True) + muted(" ambos   ") + muted("[ ] hoxe"),
    ]


# --- entries ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Entry:
    when: datetime
    kind: str  # "deadline" | "exam"
    title: str
    course_id: int | None
    course_name: str | None
    module: str | None = None
    url: str | None = None
    span: str = ""  # exams: time range
    rooms: str = ""  # exams: where


def _deadline_entries(events: list[dict[str, Any]] | None) -> list[Entry]:
    found = []
    for item in events or []:
        moment = parse_moment(item.get("sort_at") or item.get("starts_at"))
        if moment is None:
            continue
        found.append(
            Entry(
                moment,
                "deadline",
                activity_name(item),
                item.get("course_id"),
                item.get("course_name"),
                item.get("module"),
                item.get("url"),
            )
        )
    return found


def _exam_entry(call: Call) -> Entry:
    span = f"{call.start:%H:%M}"
    if call.end and call.end != call.start:
        span += f"–{call.end:%H:%M}"
    return Entry(
        call.start,
        "exam",
        call.name,
        call.course_id,
        call.name,
        span=span,
        rooms=", ".join(call.rooms),
    )


def _by_day(entries: list[Entry]) -> dict[date, int]:
    counts: dict[date, int] = {}
    for entry in entries:
        counts[entry.when.date()] = counts.get(entry.when.date(), 0) + 1
    return counts


def _entry_lines(
    entry: Entry,
    cells: int,
    today: date,
    now: datetime,
    *,
    first_of_day: bool,
    two_line: bool,
    chip_cells: int = 24,
) -> list[str]:
    day = entry.when.date()
    label = f"{WEEKDAYS_SHORT[day.weekday()]} {day.day:>2}" if first_of_day else " " * 6
    if day == today:
        label = paint(label, BLUE, bold=True)
    elif day < today:
        label = muted(label)
    exam = entry.kind == "exam"
    icon = paint(" ▲ ", WHITE, RED, bold=True) if exam else activity_icon(entry.module)
    clock = entry.span if exam else f"{entry.when:%H:%M}"
    overdue = not exam and entry.when < now
    prefix = f"  {label}  {icon} "
    indent = " " * width(prefix)
    room = width(prefix)
    if two_line:
        if exam:
            first = (
                prefix
                + bold("Exame")
                + muted(" · " + " · ".join(filter(None, [clock, entry.rooms])))
            )
            return [first, indent + course_chip(entry.course_id, entry.course_name, cells - room)]
        first = prefix + link(bold(truncate(entry.title, cells - room)), entry.url)
        chip = course_chip(entry.course_id, entry.course_name, cells - room - len(clock) - 3)
        when = paint(clock + " · atrasada", RED, bold=True) if overdue else muted(clock)
        return [first, indent + chip + muted(" · ") + when]
    tail = paint(clock, RED, bold=True) if overdue else muted(clock)
    tail = pad(tail, 11, ">")
    name_cells = max(8, cells - room - chip_cells - 11 - 4)
    if exam:
        text = bold("Exame") + muted(
            truncate(" · " + entry.rooms, name_cells - 5) if entry.rooms else ""
        )
    else:
        text = link(bold(truncate(entry.title, name_cells)), entry.url)
    chip = course_chip(entry.course_id, entry.course_name, chip_cells)
    return [prefix + pad(text, name_cells) + "  " + pad(chip, chip_cells) + "  " + tail]


def _events_block(
    entries: list[Entry], cells: int, today: date, now: datetime, *, two_line: bool
) -> list[str]:
    title = paint("Próximos eventos", bold=True)
    lines = [f"{title} {paint('─' * max(2, cells - width(title) - 1), GRAY)}"]
    if not entries:
        return [*lines, "", empty("Non hai eventos este mes.")]
    lines.append("")
    previous: date | None = None
    chip_cells = min(24, max(width(course_title(entry.course_name)) + 2 for entry in entries))
    for entry in entries:
        day = entry.when.date()
        lines += _entry_lines(
            entry,
            cells,
            today,
            now,
            first_of_day=day != previous,
            two_line=two_line,
            chip_cells=chip_cells,
        )
        previous = day
    return lines


# --- month selection ---------------------------------------------------------------------


def parse_month(text: str | None, today: date) -> tuple[int, int]:
    """«12», «2026-12», «+1», «-1», «dec»… → (year, month). Raises ValueError."""

    value = (text or "").strip()
    if not value or fold(value) in {"hoxe", "hoy", "hoje", "0"}:
        return today.year, today.month
    index = today.year * 12 + today.month - 1
    if re.fullmatch(r"[+-]\d+", value):
        index += int(value)
        return index // 12, index % 12 + 1
    match = re.fullmatch(r"(\d{4})\s*[-/.]\s*(\d{1,2})", value) or re.fullmatch(
        r"(\d{1,2})\s*[-/.]\s*(\d{4})", value
    )
    if match:
        first, second = int(match.group(1)), int(match.group(2))
        year, month = (first, second) if first > 31 else (second, first)
        if 1 <= month <= 12:
            return year, month
        raise ValueError(value)
    if value.isdigit():
        month = int(value)
        if not 1 <= month <= 12:
            raise ValueError(value)
        # The next time that month comes round (this month counts), so «1» means January.
        return (today.year if month >= today.month else today.year + 1), month
    folded = fold(value)
    if len(folded) >= 3 and folded.isalpha():
        hits = {
            number
            for names in (MONTHS, _MONTHS_ES)
            for number, name in enumerate(names, 1)
            if fold(name).startswith(folded)
        }
        if len(hits) == 1:
            month = hits.pop()
            return (today.year if month >= today.month else today.year + 1), month
    raise ValueError(value)


def _shift(year: int, month: int, step: int) -> str:
    index = year * 12 + month - 1 + step
    return f"{index // 12}-{index % 12 + 1:02d}"


def _notes(year: int, month: int, today: date, have_deliveries: bool) -> list[str]:
    """What the data cannot say about this month, as muted hints."""

    first = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])
    horizon = today + timedelta(days=_AHEAD)
    if not have_deliveries:
        return []
    if first > horizon:
        return [
            "Las entregas solo alcanzan unos 60 días: de este mes solo se muestran los exámenes."
        ]
    if last > horizon:
        return [
            f"Las entregas llegan hasta el {long_day(horizon)}; después solo se muestran exámenes."
        ]
    if last < today.replace(day=1):
        return ["De meses pasados solo se conservan las entregas atrasadas y los exámenes."]
    return []


def render_month(
    year: int,
    month: int,
    events: list[dict[str, Any]] | None,
    exam_data: dict[str, Any] | None,
    cells: int,
    *,
    today: date | None = None,
    now: datetime | None = None,
    have_deliveries: bool = True,
) -> list[str]:
    today = today or _today()
    now = now or datetime.combine(today, datetime.now().time())
    deliveries = _deadline_entries(events)
    exam_entries = [_exam_entry(call) for call in all_calls(exam_data)]
    grid = month_grid(year, month, _by_day(deliveries), _by_day(exam_entries), today)
    in_month = sorted(
        (
            entry
            for entry in [*deliveries, *exam_entries]
            if (entry.when.year, entry.when.month) == (year, month)
        ),
        key=lambda entry: (entry.when, entry.kind),
    )
    lines = [block("Calendario", "Mes", cells), ""]
    if cells >= _WIDE:
        left = [*grid, "", *_legend()]
        right = _events_block(in_month, cells - GRID - 4, today, now, two_line=True)
        rows = max(len(left), len(right))
        left += [""] * (rows - len(left))
        right += [""] * (rows - len(right))
        lines += [pad(a, GRID) + "    " + b for a, b in zip(left, right, strict=True)]
    else:
        lines += [" " + line for line in grid]
        lines += ["", " " + "   ".join(_legend())]
        lines += [
            "",
            *_events_block(in_month, cells, today, now, two_line=cells < 96),
        ]
    for note in _notes(year, month, today, have_deliveries):
        lines += ["", muted("  " + note)]
    previous, following = _shift(year, month, -1), _shift(year, month, 1)
    lines += ["", muted(f"  ‹ campus cal {previous}   ·   campus cal {following} ›")]
    return lines


# --- command ----------------------------------------------------------------------------


def run(args: argparse.Namespace) -> int:
    today = _today()
    try:
        year, month = parse_month(args.mes, today)
    except ValueError:
        return fail(
            f"Mes no válido: «{args.mes}». Usa 12, 2026-12, +1, -1 o un nombre (xan, dic…)."
        )
    keys = ["pendientes", sources.examenes_key(sources.academic_year(today))]

    def render(results: dict[str, sources.Result], _args: argparse.Namespace) -> list[str]:
        pending, exams = results["pendientes"], results[keys[1]]
        return render_month(
            year,
            month,
            pending.data if pending.ok else None,
            exams.data if exams.ok else None,
            term_width(),
            today=today,
            now=_now(),
            have_deliveries=pending.ok,
        )

    def payload(results: dict[str, sources.Result]) -> Any:
        pending, exams = results["pendientes"], results[keys[1]]
        in_month = [
            item
            for item in pending.data or []
            if (moment := parse_moment(item.get("sort_at")))
            and (moment.year, moment.month) == (year, month)
        ]
        calls = [
            {
                "subject_code": call.code,
                "course_id": call.course_id,
                "course_name": call.name,
                "starts_at": call.start.isoformat(),
                "ends_at": call.end.isoformat() if call.end else None,
                "rooms": list(call.rooms),
            }
            for call in all_calls(exams.data)
            if (call.start.year, call.start.month) == (year, month)
        ]
        return {"month": f"{year}-{month:02d}", "deadlines": in_month, "exams": calls}

    return show(args, keys, render, ["Taboleiro", "Calendario"], json_payload=payload)


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "mes",
        nargs="?",
        help="Mes a mostrar: 12, 2026-12, +1, -1 o nombre (por defecto, el actual)",
    )


COMMANDS = [
    Command(
        "calendario",
        "Calendario: mes con entregas y exámenes",
        run,
        configure,
        aliases=("cal",),
    )
]

__all__ = ["COMMANDS", "month_grid", "parse_month", "render_month"]
