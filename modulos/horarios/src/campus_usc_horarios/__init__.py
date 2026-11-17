"""campus-usc-horarios: class timetable and official exam dates, from usc.gal.

An installable module of `campus` (``campus-usc[horarios]``). It is apart from the core
because it is not the Campus: it reads usc.gal's public pages, and the first lookup of
your subjects in the study plans takes a minute or two. Installed, it adds:

* ``campus horario``, ``hoy``, ``mañana`` and ``examenes``;
* today's classes in the Taboleiro's «Hoxe», a «Próximos exames» block and exam days in
  the calendars;
* this week's and next week's timetable and the exam dates to ``campus actualizar``.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from campus_usc import sources
from campus_usc.sources import DAY, HOUR, Source
from campus_usc.style import muted
from campus_usc.ui import block

from . import examenes, horario

__version__ = "0.1.0"


async def _horario(service: Any, monday: str) -> Any:
    return await service.get_my_subjects_timetable(date_in_week=monday or None)


async def _examenes(service: Any, year: str) -> Any:
    return await service.get_my_official_exam_schedule(year.replace("-", "/"))


SOURCES = {
    "horario": Source("Horario", 12 * HOUR, 14 * DAY, _horario, slow=True),
    "examenes": Source("Exames", DAY, 60 * DAY, _examenes, slow=True),
}
COMMANDS = [*horario.COMMANDS, *examenes.COMMANDS]


def _loading(result: sources.Result | None) -> list[str]:
    if result is not None and result.refreshing and not result.ok:
        return [muted("  cargando en segundo plano… aparecerá la próxima vez que abras campus")]
    return []


def actualizar_keys(today: date) -> list[str]:
    return [
        sources.horario_key(today),
        sources.horario_key(today + timedelta(days=7)),
        sources.examenes_key(),
    ]


def taboleiro_keys(today: date) -> list[str]:
    return [sources.horario_key(today), sources.examenes_key()]


def taboleiro_hoxe(
    results: dict[str, sources.Result],
    pendientes: sources.Result,
    cells: int,
    now: datetime,
) -> list[str]:
    result = results.get(sources.horario_key(now.date()))
    return horario.compact_today(result, pendientes, cells, now=now) + _loading(result)


def taboleiro_blocks(results: dict[str, sources.Result], cells: int, now: datetime) -> list[str]:
    key = sources.examenes_key()
    result = results.get(key) or sources.Result(key)
    lines = [block("Próximos exames", "", cells)]
    return lines + examenes.compact_exams(result, cells, limit=3, now=now) + _loading(result)


def _year_key(today: date | None = None) -> str:
    return sources.examenes_key(sources.academic_year(today or date.today()))


def calendar_keys(today: date) -> list[str]:
    return [_year_key(today)]


def calendar_entries(results: dict[str, sources.Result]) -> list[Any]:
    from campus_usc.views.calendario import Entry

    result = results.get(_year_key()) or results.get(sources.examenes_key())
    entries = []
    for call in examenes.all_calls(result.data if result is not None and result.ok else None):
        span = f"{call.start:%H:%M}"
        if call.end and call.end != call.start:
            span += f"–{call.end:%H:%M}"
        entries.append(
            Entry(
                call.start,
                "exam",
                call.name,
                call.course_id,
                call.name,
                span=span,
                rooms=", ".join(call.rooms),
            )
        )
    return entries


def calendar_json(results: dict[str, sources.Result], year: int, month: int) -> dict[str, Any]:
    result = results.get(_year_key())
    calls = [
        {
            "subject_code": call.code,
            "course_id": call.course_id,
            "course_name": call.name,
            "starts_at": call.start.isoformat(),
            "ends_at": call.end.isoformat() if call.end else None,
            "rooms": list(call.rooms),
        }
        for call in examenes.all_calls(result.data if result is not None and result.ok else None)
        if (call.start.year, call.start.month) == (year, month)
    ]
    return {"exams": calls}


__all__ = ["COMMANDS", "SOURCES"]
