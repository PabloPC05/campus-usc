"""«Taboleiro»: the Campus dashboard, what `campus` shows with no arguments.

Every block comes from the local cache, so it opens instantly. A block whose source is
slow and not cached yet (the first timetable or exam lookup) never makes the screen
wait: it is fetched in the background and appears the next time.
"""

from __future__ import annotations

import argparse
import importlib
from datetime import date, datetime
from typing import Any

from .. import sources
from ..style import BLUE, GRAY, RED, WHITE, clip, muted, pad, paint, term_width
from ..ui import block, empty, long_day
from . import Command, show

_CALENDAR_CELLS = 30


def _view(name: str) -> Any | None:
    """Another screen's module, if present (they render the compact blocks)."""

    try:
        return importlib.import_module(f"{__package__}.{name}")
    except ModuleNotFoundError:
        return None


def _greeting(now: datetime) -> str:
    if now.hour < 13:
        return "Bos días"
    if now.hour < 21:
        return "Boas tardes"
    return "Boas noites"


def _side_by_side(left: list[str], right: list[str], cells: int, right_cells: int) -> list[str]:
    left_cells = cells - right_cells - 3
    rows = max(len(left), len(right))
    left = left + [""] * (rows - len(left))
    right = right + [""] * (rows - len(right))
    return [
        pad(clip(a, left_cells), left_cells) + "   " + clip(b, right_cells)
        for a, b in zip(left, right, strict=True)
    ]


def _pending(result: sources.Result) -> str:
    if result.refreshing and not result.ok:
        return muted("  cargando en segundo plano… aparecerá la próxima vez que abras campus")
    return ""


def _counts(events: list[dict[str, Any]] | None, now: datetime) -> tuple[int, int, int]:
    """(overdue, due in 24 h, due in 7 days)."""

    from ..ui import parse_moment

    overdue = soon = week = 0
    for event in events or []:
        moment = parse_moment(event.get("sort_at"))
        if moment is None:
            continue
        seconds = (moment - now).total_seconds()
        if seconds < 0:
            overdue += 1 if event.get("actionable") else 0  # closed ones are not to do
        elif seconds < 86400:
            soon += 1
            week += 1
        elif seconds < 7 * 86400:
            week += 1
    return overdue, soon, week


def _summary(
    results: dict[str, sources.Result], profile: dict[str, Any] | None, now: datetime
) -> list[str]:
    first = (profile or {}).get("firstname") or ""
    hello = f"{_greeting(now)}{', ' + first.split()[0] if first else ''}"
    lines = [
        "",
        " " + paint(hello, bold=True) + muted(f"  ·  {long_day(now.date())} de {now.year}"),
    ]
    overdue, soon, week = _counts(results["pendientes"].data, now)
    chips = []
    if soon:
        chips.append(paint(f" {soon} ", WHITE, RED, bold=True) + paint(" vencen hoxe", RED))
    chips.append(paint(f" {week} ", WHITE, BLUE, bold=True) + " esta semana")
    if overdue:
        chips.append(paint(f" {overdue} ", WHITE, GRAY, bold=True) + muted(" atrasadas"))
    notices = results.get("notificaciones")
    unread = (notices.data or {}).get("unread", 0) if notices and notices.ok else 0
    if unread:
        chips.append(paint(f" {unread} ", WHITE, BLUE, bold=True) + " notificacións sen ler")
    lines.append(" " + "   ".join(chips))
    return lines


def render(
    results: dict[str, sources.Result],
    args: argparse.Namespace,
    *,
    profile: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> list[str]:
    now = now or datetime.now()
    today = now.date()
    cells = term_width()
    horario_key = sources.horario_key(today)
    examenes_key = sources.examenes_key()
    lines = _summary(results, profile, now)

    # Hoxe (classes + deliveries) beside the month calendar, as on the Campus dashboard.
    horario = _view("horario")
    calendario = _view("calendario")
    today_lines: list[str] = []
    if horario is not None:
        today_lines = horario.compact_today(
            results[horario_key], results["pendientes"], cells - _CALENDAR_CELLS - 3, now=now
        )
        if not results[horario_key].ok:
            today_lines.append(_pending(results[horario_key]))
    grid: list[str] = []
    if calendario is not None and cells >= 80:
        grid = calendario.month_grid(
            today.year,
            today.month,
            _deadline_days(results["pendientes"].data),
            _exam_days(results[examenes_key].data),
            today,
        )
    left = [block("Hoxe", "", cells - _CALENDAR_CELLS - 3).lstrip("\n"), *today_lines]
    if grid:
        right = [block("Calendario", "", _CALENDAR_CELLS).lstrip("\n"), *grid]
        lines.append("")
        lines.extend(_side_by_side(left, right, cells, _CALENDAR_CELLS))
    elif today_lines:
        lines.append("")
        lines.extend(left)

    # Cronograma: the next deliveries, like the timeline block.
    cronograma = _view("cronograma")
    if cronograma is not None:
        items, hidden = cronograma.items_in_window(
            results["pendientes"].data, days=7, overdue=False, now=now
        )
        lines.append(block("Cronograma", "Próximos 7 días", cells))
        if items:
            lines.extend(cronograma.render_timeline(items[:6], cells, today=today, now=now))
            if len(items) > 6:
                lines.append(muted(f"\n  …e {len(items) - 6} máis  ·  campus pendientes"))
        elif results["pendientes"].ok:
            lines.append(empty("Non hai actividades que requiran accións."))
        if hidden:
            lines.append(
                "  " + paint(f"{hidden} atrasadas", RED) + muted("  ·  campus pendientes -a")
            )

    examenes = _view("examenes")
    if examenes is not None:
        lines.append(block("Próximos exames", "", cells))
        lines.extend(examenes.compact_exams(results[examenes_key], cells, limit=3, now=now))
        if not results[examenes_key].ok:
            lines.append(_pending(results[examenes_key]))

    cursos = _view("cursos")
    if cursos is not None:
        lines.append(block("Os meus cursos", "", cells))
        lines.extend(cursos.compact_courses(results["cursos"], results["pendientes"], cells))

    lines.append("")
    lines.append(
        muted("  campus ")
        + paint("pendientes", BLUE)
        + muted(" · ")
        + paint("horario", BLUE)
        + muted(" · ")
        + paint("examenes", BLUE)
        + muted(" · ")
        + paint("cursos", BLUE)
        + muted(" · ")
        + paint("curso ia", BLUE)
        + muted(" · ")
        + paint("ayuda", BLUE)
    )
    return [line for line in lines if line is not None]


def _deadline_days(events: list[dict[str, Any]] | None) -> dict[date, int]:
    from ..ui import parse_moment

    days: dict[date, int] = {}
    for event in events or []:
        moment = parse_moment(event.get("sort_at"))
        if moment is not None:
            days[moment.date()] = days.get(moment.date(), 0) + 1
    return days


def _exam_days(data: dict[str, Any] | None) -> dict[date, int]:
    from ..ui import parse_moment

    days: dict[date, int] = {}
    for subject in (data or {}).get("subjects") or []:
        for call in subject.get("calls") or []:
            moment = parse_moment(call.get("starts_at"))
            if moment is not None:
                days[moment.date()] = days.get(moment.date(), 0) + 1
    return days


def run(args: argparse.Namespace) -> int:
    today = date.today()
    keys = [
        "pendientes",
        "cursos",
        "notificaciones",
        sources.horario_key(today),
        sources.examenes_key(),
    ]
    profile: dict[str, Any] = {}

    def draw(results: dict[str, sources.Result], parsed: argparse.Namespace) -> list[str]:
        return render(results, parsed, profile=profile)

    # The navbar's profile is cached too; read it here for the greeting.
    from .. import store

    cached = store.read("perfil")
    if cached is not None:
        profile.update(cached[0] or {})
    return show(args, keys, draw, ["Taboleiro"], defer_slow=True)


def configure(parser: argparse.ArgumentParser) -> None:
    del parser


COMMANDS = [
    Command(
        "inicio",
        "Taboleiro: hoxe, cronograma, exames e cursos",
        run,
        configure,
        aliases=("taboleiro", "t"),
    )
]
