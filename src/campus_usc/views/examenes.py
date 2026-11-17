"""«Exames»: the official exam dates of your subjects, in the terminal.

Data is the official schedule (``get_my_official_exam_schedule``): each subject has
calls with a start, an end and rooms, and the Moodle course it matches. The screen shows
the next exam in a card, a one-line timeline of the current round, and the upcoming
calls grouped by month, each in its course's Moodle colour.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from .. import sources
from ..courses import CourseNotFound, find
from ..style import (
    AMBER,
    BLUE,
    GRAY,
    RED,
    bold,
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
    block,
    box,
    course_chip,
    course_color,
    course_title,
    empty,
    long_day,
)
from . import Command, fail, show

_YEAR = re.compile(r"^\s*(\d{4})\s*[/-]?\s*(\d{4})?\s*$")
_ROUND_DAYS = 75  # calls this close to the next exam belong to the same round

# Why a subject has no dates, by the status the official-exams module reports.
_REASONS = {
    "not_published_or_not_found": "aún no hay fechas publicadas",
    "not_found_in_study_plans": "no aparece en los planes de estudio",
    "source_changed_or_unavailable": "no se pudo leer la ficha oficial",
    "ambiguous": "hay fechas distintas según el plan de estudios",
    "conflict_between_official_sources": "las fuentes oficiales no coinciden",
}


def _now() -> datetime:
    return datetime.now()


def _today() -> date:
    return date.today()


@dataclass(frozen=True, slots=True)
class Call:
    """One exam call of one subject (wall-clock times as the faculty publishes them)."""

    start: datetime
    end: datetime | None
    rooms: tuple[str, ...]
    groups: tuple[str, ...]
    course_id: int | None
    name: str
    code: str

    @property
    def last(self) -> datetime:
        return self.end or self.start


@dataclass(frozen=True, slots=True)
class Subject:
    code: str
    course_id: int | None
    name: str
    status: str
    calls: tuple[Call, ...]


def _wall(value: Any) -> datetime | None:
    """The time as printed on the official sheet: the offset is dropped, not converted."""

    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).replace(tzinfo=None)
    except ValueError:
        return None


def subjects_of(data: dict[str, Any] | None) -> list[Subject]:
    """The schedule's subjects with their calls parsed and sorted."""

    if not isinstance(data, dict):
        return []
    matched = {
        str(item.get("subject_code")): item
        for item in data.get("matched_moodle_courses") or []
        if isinstance(item, dict)
    }
    found: list[Subject] = []
    for entry in data.get("subjects") or []:
        if not isinstance(entry, dict):
            continue
        code = str(entry.get("subject_code") or "")
        course = matched.get(code) or {}
        name = course_title(course.get("course_name"))
        if not name:
            for candidate in entry.get("candidates") or []:
                name = str(candidate.get("subject_name") or "").strip()
                if name:
                    break
        name = name or code or "Asignatura"
        course_id = course.get("course_id")
        calls: list[Call] = []
        for call in entry.get("calls") or []:
            start = _wall(call.get("starts_at"))
            if start is None:
                continue
            end = _wall(call.get("ends_at"))
            calls.append(
                Call(
                    start,
                    end if end and end >= start else None,
                    tuple(str(room) for room in call.get("rooms") or []),
                    tuple(str(group) for group in call.get("groups") or []),
                    int(course_id) if course_id else None,
                    name,
                    code,
                )
            )
        calls.sort(key=lambda item: item.start)
        found.append(
            Subject(
                code,
                int(course_id) if course_id else None,
                name,
                str(entry.get("status") or ""),
                tuple(calls),
            )
        )
    return found


def all_calls(data: dict[str, Any] | None) -> list[Call]:
    """Every call of every subject, by date (also used by the calendar)."""

    calls = [call for subject in subjects_of(data) for call in subject.calls]
    calls.sort(key=lambda item: (item.start, item.name))
    return calls


def _timespan(call: Call) -> str:
    if call.end and call.end != call.start:
        return f"{call.start:%H:%M}–{call.end:%H:%M}"
    return f"{call.start:%H:%M}"


def _rooms(call: Call) -> str:
    return ", ".join(call.rooms)


def _left(call: Call, now: datetime) -> tuple[str, str | None, bool]:
    """«en 31 días», its urgency colour (AMBER ≤ 14 days, RED ≤ 3) and bold-ness."""

    if call.last < now:
        return "feito", GRAY, False
    if call.start <= now:
        return "en curso", RED, True
    days = (call.start.date() - now.date()).days
    if days == 0:
        return "hoxe", RED, True
    if days == 1:
        return "mañá", RED, True
    text = f"en {days} días"
    if days <= 3:
        return text, RED, True
    if days <= 14:
        return text, AMBER, True
    return text, None, False


def _tag(call: Call, now: datetime) -> str:
    text, color, strong = _left(call, now)
    return paint(text, color, bold=strong) if color else text


def _chip(call: Call, cells: int, *, past: bool = False) -> str:
    if not past:
        return course_chip(call.course_id, call.name, cells)
    return paint("▌", course_color(call.course_id)) + " " + muted(truncate(call.name, cells - 2))


def _short_day(day: date) -> str:
    return f"{WEEKDAYS_SHORT[day.weekday()]} {day.day} {MONTHS[day.month - 1][:3]}"


# --- pieces of the screen --------------------------------------------------------------


def _card(calls: list[Call], now: datetime, cells: int) -> list[str]:
    """The highlighted next exam (plus any other exam that same day)."""

    call = calls[0]
    text, color, _ = _left(call, now)
    accent = color if color in {RED, AMBER} else BLUE
    inner = cells - 4
    tag = paint(text, accent, bold=True)
    title = paint("▌", course_color(call.course_id)) + " "
    title += bold(truncate(call.name, inner - width(tag) - 4))
    head = pad(title, inner - width(tag)) + tag
    parts = [long_day(call.start.date()), _timespan(call)]
    if call.rooms:
        parts.append(_rooms(call))
    lines = [head, "  " + " · ".join(parts)]
    for other in calls[1:]:
        if other.start.date() != call.start.date():
            break
        extra = [_timespan(other)] + ([_rooms(other)] if other.rooms else [])
        label = muted("Tamén ese día  ") + course_chip(other.course_id, other.name, inner - 20)
        lines.append(label + muted("  " + " · ".join(extra)))
    return box("Próximo exame", lines, cells, accent=accent)


def _timeline(calls: list[Call], now: datetime, cells: int) -> list[str]:
    """«Hoxe ◆────●──●●───● 21 xan»: one marker per exam of the current round."""

    upcoming = [call for call in calls if call.last >= now]
    if not upcoming:
        return []
    horizon = upcoming[0].start + timedelta(days=_ROUND_DAYS)
    first_per_subject: dict[str, Call] = {}
    for call in upcoming:
        if call.start <= horizon:
            first_per_subject.setdefault(call.code or call.name, call)
    round_calls = sorted(first_per_subject.values(), key=lambda item: item.start)
    if len(round_calls) < 2:
        return []
    today = now.date()
    last = round_calls[-1].start.date()
    span = max(1, (last - today).days)
    left = "Hoxe "
    right = " " + _short_day(last).split(" ", 1)[1]
    rail = cells - 2 - width(left) - width(right)
    if rail < 12:
        return []
    slots: list[Call | None] = [None] * rail
    for call in round_calls:
        wanted = round(max(0, (call.start.date() - today).days) / span * (rail - 1))
        wanted = min(max(wanted, 1), rail - 1)
        for shift in (0, 1, -1, 2, -2, 3, -3):
            slot = wanted + shift
            if 1 <= slot < rail and slots[slot] is None:
                slots[slot] = call
                break
    cells_out = [paint("◆", BLUE, bold=True)]
    for slot in slots[1:]:
        cells_out.append(
            paint("●", course_color(slot.course_id), bold=True) if slot else paint("─", GRAY)
        )
    return ["  " + muted(left) + "".join(cells_out) + muted(right)]


def _heading(year: int, month: int, count: int, cells: int) -> str:
    left = paint(f"{MONTHS[month - 1]} de {year}", BLUE, bold=True)
    tail = muted(f"{count} {'exame' if count == 1 else 'exames'}")
    rule = max(2, cells - 2 - width(left) - width(tail) - 2)
    return f" {left} {paint('─' * rule, GRAY)} {tail}"


@dataclass(frozen=True, slots=True)
class _Layout:
    """Column widths for the call rows, measured on what is shown."""

    date: int
    tag: int
    rooms: int
    chip: int  # cells left for the course chip on a single-line row
    wide: bool


def _layout(shown: list[Call], now: datetime, cells: int) -> _Layout:
    date_w = max((width(long_day(call.start.date())) for call in shown), default=0)
    tag_w = max((width(_left(call, now)[0]) for call in shown), default=0)
    rooms_w = min(max((width(_rooms(call)) for call in shown), default=0), 24)
    # 2 indent + date + 2 + time(11) + 2 + chip + 2 + rooms + 2 + tag
    chip = cells - (2 + date_w + 2 + 11 + 2 + 2 + rooms_w + 2 + tag_w)
    longest = max((width(call.name) + 2 for call in shown), default=0)
    return _Layout(date_w, tag_w, rooms_w, chip, chip >= min(longest, 34))


def _call_lines(call: Call, cells: int, now: datetime, layout: _Layout) -> list[str]:
    past = call.last < now
    day = long_day(call.start.date())
    date_text = muted(day) if past else bold(day)
    clock = muted(_timespan(call)) if past else _timespan(call)
    tag = muted("feito") if past else _tag(call, now)
    rooms = _rooms(call)
    if layout.wide:
        line = f"  {pad(date_text, layout.date)}  {pad(clock, 11)}  "
        line += pad(_chip(call, layout.chip, past=past), layout.chip) + "  "
        line += pad(muted(truncate(rooms, layout.rooms)), layout.rooms)
        return [line + " " * max(1, cells - width(line) - width(tag)) + tag]
    first = f"  {pad(date_text, layout.date)}  {clock}"
    first += " " * max(1, cells - width(first) - width(tag) - 1) + tag
    detail = _chip(call, cells - 4 - (width(rooms) + 3 if rooms else 0), past=past)
    if rooms:
        detail += muted(f" · {rooms}")
    return [first, "    " + detail]


def _silent(subjects: list[Subject], now: datetime, cells: int) -> list[str]:
    """Subjects that show no upcoming call, muted at the end, with the reason."""

    if not subjects:
        return []
    title = paint("Sen datas", GRAY, bold=True)
    lines = ["", f" {title} {paint('─' * max(2, cells - width(title) - 3), GRAY)}"]
    for subject in subjects:
        if subject.calls:
            reason = "ya pasaron todas sus convocatorias (--todas para verlas)"
        else:
            reason = _REASONS.get(subject.status, "sin fechas publicadas todavía")
        chip = paint("▌", course_color(subject.course_id)) + " " + muted(subject.name)
        lines.append(f"  {chip}{muted('  ·  ' + reason)}")
    return lines


def render_exams(
    data: dict[str, Any] | None,
    cells: int,
    *,
    now: datetime | None = None,
    show_all: bool = False,
    only_code: str | None = None,
    year: str | None = None,
) -> list[str]:
    """The whole «Exames» block as lines."""

    now = now or _now()
    year = year or (data or {}).get("academic_year") or sources.academic_year(now.date())
    subjects = subjects_of(data)
    if only_code:
        subjects = [subject for subject in subjects if subject.code == only_code]
    calls = sorted(
        (call for subject in subjects for call in subject.calls),
        key=lambda item: (item.start, item.name),
    )
    upcoming = [call for call in calls if call.last >= now]
    shown = calls if show_all else upcoming
    window = "Todos os exames" if show_all else "Próximos"
    lines = [block("Exames", f"Curso {year} · {window}", cells)]
    if not subjects:
        lines += ["", empty("Non hai exames para mostrar.")]
        return lines
    if upcoming:
        lines += ["", *_card(upcoming, now, cells)]
        timeline = _timeline(upcoming, now, cells)
        if timeline:
            lines += ["", *timeline]
    layout = _layout(shown, now, cells)
    group: tuple[int, int] | None = None
    members = 0
    for call in shown:
        key = (call.start.year, call.start.month)
        if key != group:
            group = key
            members = sum(1 for other in shown if (other.start.year, other.start.month) == key)
            lines += ["", _heading(key[0], key[1], members, cells)]
        lines += _call_lines(call, cells, now, layout)
    if not shown:
        lines += ["", empty("Non hai exames próximos.")]
    with_calls = {call.code for call in shown}
    lines += _silent(
        [subject for subject in subjects if subject.code not in with_calls], now, cells
    )
    if data and (data.get("complete") is False or data.get("degree_issues")):
        lines += [
            "",
            muted("  Lectura incompleta de los planes de estudio: puede faltar alguna fecha."),
        ]
    return lines


def compact_exams(
    result: Any, cells: int, limit: int = 3, now: datetime | None = None
) -> list[str]:
    """The next ``limit`` exams, one line each, for the dashboard (no navbar, no heading)."""

    now = now or _now()
    data = getattr(result, "data", result)
    if not isinstance(data, dict):
        return [empty("Aún no hay datos de exámenes (campus actualizar)")]
    upcoming = [call for call in all_calls(data) if call.last >= now][: max(1, limit)]
    if not upcoming:
        return [empty("Non hai exames próximos.")]
    lines = []
    for call in upcoming:
        tag = _tag(call, now)
        left = f"  {pad(muted(_short_day(call.start.date())), 10)}  "
        chip_cells = max(8, cells - width(left) - width(tag) - 2)
        line = left + pad(_chip(call, chip_cells), chip_cells)
        lines.append(line + " " * max(1, cells - width(line) - width(tag)) + tag)
    return lines


# --- command ----------------------------------------------------------------------------


def _year_key(value: str | None) -> str | None:
    """«2026/2027», «2026-2027» or «2026» → «2026/2027»; None when it is not a year."""

    if not value:
        return sources.academic_year()
    match = _YEAR.match(value)
    if not match:
        return None
    start = int(match.group(1))
    end = int(match.group(2) or start + 1)
    return f"{start}/{end}" if end == start + 1 else None


def _courses_of(data: dict[str, Any] | None) -> list[dict[str, Any]]:
    courses = []
    for subject in subjects_of(data):
        courses.append(
            {
                "id": subject.course_id,
                "full_name": f"{subject.name} [{subject.code}]",
                "subject_code": subject.code,
            }
        )
    return courses


def _pick(data: dict[str, Any] | None, query: str | None) -> tuple[str | None, str | None]:
    """(subject code, error message) for the optional subject argument."""

    if not query:
        return None, None
    try:
        return find(_courses_of(data), query)["subject_code"], None
    except CourseNotFound as exc:
        names = ", ".join(course_title(option["full_name"]) for option in exc.options)
        return None, str(exc) + (f" {names}." if names else "")


def run(args: argparse.Namespace) -> int:
    year = _year_key(args.curso_academico)
    if year is None:
        return fail("Curso académico no válido: usa 2026/2027 (o solo 2026).")
    key = sources.examenes_key(year)

    def render(results: dict[str, sources.Result], parsed: argparse.Namespace) -> list[str]:
        result = results[key]
        if not result.ok:
            return [block("Exames", f"Curso {year}", term_width())]
        code, problem = _pick(result.data, parsed.curso)
        if problem:
            return ["", empty(problem)]
        return render_exams(
            result.data,
            term_width(),
            now=_now(),
            show_all=parsed.todas,
            only_code=code,
            year=year,
        )

    def payload(results: dict[str, sources.Result]) -> Any:
        data = results[key].data
        code, _ = _pick(data, args.curso)
        now = _now()
        exams, without = [], []
        for subject in subjects_of(data):
            if code and subject.code != code:
                continue
            kept = [c for c in subject.calls if args.todas or c.last >= now]
            if not subject.calls:
                without.append(
                    {
                        "subject_code": subject.code,
                        "course_id": subject.course_id,
                        "name": subject.name,
                        "status": subject.status,
                    }
                )
            for call in kept:
                exams.append(
                    {
                        "subject_code": call.code,
                        "course_id": call.course_id,
                        "course_name": call.name,
                        "starts_at": call.start.isoformat(),
                        "ends_at": call.end.isoformat() if call.end else None,
                        "rooms": list(call.rooms),
                        "groups": list(call.groups),
                        "days_left": (call.start.date() - now.date()).days,
                    }
                )
        exams.sort(key=lambda item: item["starts_at"])
        return {"academic_year": year, "exams": exams, "without_dates": without}

    return show(args, [key], render, ["Taboleiro", "Exames"], json_payload=payload)


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("curso", nargs="?", help="Solo esta asignatura (ia, redes, soi…)")
    parser.add_argument("-t", "--todas", action="store_true", help="Incluye convocatorias pasadas")
    parser.add_argument(
        "--curso-academico",
        metavar="AAAA/AAAA",
        help="Curso académico (por defecto el actual, p. ej. 2026/2027)",
    )


COMMANDS = [
    Command(
        "examenes",
        "Exames: fechas oficiales de tus asignaturas",
        run,
        configure,
        aliases=("exames", "e"),
    )
]

__all__ = ["COMMANDS", "all_calls", "compact_exams", "render_exams", "subjects_of"]
