"""«Horario»: the week timetable of your own subjects, and the agenda of one day.

``campus horario`` draws the week as a grid (one column per day, one coloured block per
class, in the colour Moodle gives each course) when the terminal is wide enough and the
classes do not pile up, and as a list otherwise. ``campus hoxe`` / ``campus mañá`` list
one day: classes plus the deliveries that fall due that day.

The timetable the USC publishes lists *every* group of a subject, so the screen merges
identical sessions and lets you keep only yours (``--grupos CLE_01 CLIL_02``, saved with
``--guardar-grupos``). Everything renders from the local cache.
"""

from __future__ import annotations

import argparse
import re
import zlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from campus_usc import config, sources, store
from campus_usc.style import (
    GRAY,
    GREEN,
    MINT,
    NAVY,
    RED,
    WHITE,
    _rgb,
    bold,
    caps,
    muted,
    pad,
    paint,
    term_width,
    truncate,
    width,
)
from campus_usc.ui import (
    MONTHS,
    WEEKDAYS,
    WEEKDAYS_SHORT,
    activity_icon,
    block,
    countdown,
    course_alias,
    course_color,
    course_title,
    day_label,
    empty,
    link,
    long_day,
    parse_moment,
)
from campus_usc.views import Command, fail, show
from campus_usc.views.cronograma import activity_name

SLOT = 30  # minutes per grid row
GUTTER = 6  # "09:00 "
MIN_LANE = 8  # narrowest readable block, in cells
GRID_MIN_WIDTH = 90
HOURLINE = "╌"

_KIND_ORDER = ("expository", "laboratory", "seminar", "tutorship")
_KIND_LONG = {
    "expository": "teoría",
    "laboratory": "laboratorio",
    "seminar": "seminario",
    "tutorship": "titoría",
}
_KIND_SHORT = {"expository": "teo", "laboratory": "lab", "seminar": "sem", "tutorship": "tit"}
_STATUS_TEXT = {
    "other_semester": "otro cuatrimestre",
    "not_found_in_study_plans": "no está en los planes de estudio",
    "course_unknown_in_study_plan": "curso desconocido en el plan",
}
_WEEK_RELATIVE = re.compile(r"[+-]\d+")
_WEEK_LIKE = re.compile(r"[+-]\d+|\d{4}-\d\d-\d\d|\d{1,2}[/.-]\d{1,2}(?:[/.-]\d{2,4})?")


def _now() -> datetime:
    """Wall clock; tests replace it to freeze «today»."""

    return datetime.now()


# --- data ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Block:
    """One class slot; several groups with the same subject, time, kind and room merge."""

    day: date
    start: int  # minutes since midnight
    end: int
    code: str
    name: str
    course_id: int | None
    kinds: tuple[str, ...]
    room: str
    groups: tuple[str, ...]

    @property
    def top(self) -> int:
        return self.start // SLOT * SLOT

    @property
    def bottom(self) -> int:
        return -(-self.end // SLOT) * SLOT

    @property
    def color(self) -> str:
        return course_color(self.course_id)

    @property
    def title(self) -> str:
        return course_title(self.name) or self.code

    def clock(self) -> str:
        return f"{_hhmm(self.start)}–{_hhmm(self.end)}"

    def active(self, now: datetime | None) -> bool:
        if now is None or now.date() != self.day:
            return False
        minute = now.hour * 60 + now.minute
        return self.start <= minute < self.end

    def to_json(self) -> dict[str, Any]:
        return {
            "date": self.day.isoformat(),
            "start_time": _hhmm(self.start),
            "end_time": _hhmm(self.end),
            "subject_code": self.code,
            "subject_name": self.name,
            "course_id": self.course_id,
            "activity_type": "+".join(self.kinds),
            "groups": [f"/{group}" for group in self.groups],
            "room": self.room,
        }


def _hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _minutes(text: Any) -> int | None:
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(text or ""))
    return int(match[1]) * 60 + int(match[2]) if match else None


def norm_group(value: Any) -> str:
    return str(value or "").strip().lstrip("/").strip().upper()


def _kinds(text: Any) -> tuple[str, ...]:
    found = [part.strip() for part in str(text or "").split("+") if part.strip()]
    found.sort(key=lambda kind: _KIND_ORDER.index(kind) if kind in _KIND_ORDER else 99)
    return tuple(found)


def kind_label(kinds: tuple[str, ...], *, short: bool = False) -> str:
    names = _KIND_SHORT if short else _KIND_LONG
    return "+".join(names.get(kind, kind) for kind in kinds)


def format_groups(groups: tuple[str, ...]) -> str:
    """('CLIL_01', 'CLIL_02', 'CLE_01') → «CLE_01 · CLIL_01/02»."""

    by_prefix: dict[str, list[str]] = {}
    for group in groups:
        prefix, sep, number = group.rpartition("_")
        by_prefix.setdefault(prefix if sep else group, []).append(number if sep else "")
    parts = []
    for prefix, numbers in sorted(by_prefix.items()):
        numbers = [number for number in numbers if number]
        parts.append(f"{prefix}_{'/'.join(sorted(numbers))}" if numbers else prefix)
    return " · ".join(parts)


def _course_ids(data: dict[str, Any]) -> dict[str, int]:
    year = data.get("academic_year")
    found: dict[str, int] = {}
    for course in data.get("matched_moodle_courses") or []:
        code, course_id = course.get("subject_code"), course.get("course_id")
        if not code or not course_id:
            continue
        if code not in found or course.get("course_academic_year") == year:
            found[code] = int(course_id)
    return found


def effective_groups(args: argparse.Namespace | None = None) -> list[str]:
    """Groups to keep: this run's ``--grupos``, else the saved ones; none = everything."""

    if args is not None and getattr(args, "todos_los_grupos", False):
        return []
    given = getattr(args, "grupos", None) if args is not None else None
    chosen = given if given else config.get("grupos")
    if not isinstance(chosen, list):
        return []
    return list(dict.fromkeys(norm_group(group) for group in chosen if norm_group(group)))


@dataclass(slots=True)
class Timetable:
    blocks: list[Block]
    hidden: int  # sessions left out by the group filter
    without_groups: list[str]  # subjects that lost every session to the filter
    not_listed: list[str]  # subjects the timetable could not place, with the reason


def build(
    data: dict[str, Any] | None,
    groups: list[str],
    *,
    first: date | None = None,
    last: date | None = None,
) -> Timetable:
    """Merged blocks of ``data`` between ``first`` and ``last`` (inclusive) for ``groups``."""

    data = data or {}
    ids = _course_ids(data)
    wanted = set(groups)
    merged: dict[tuple[Any, ...], list[str]] = {}
    names: dict[str, str] = {}
    present: dict[str, set[str]] = {}
    shown: set[str] = set()
    hidden = 0
    for session in data.get("sessions") or []:
        try:
            day = date.fromisoformat(str(session.get("date")))
        except ValueError:
            continue
        start, end = _minutes(session.get("start_time")), _minutes(session.get("end_time"))
        if start is None or end is None or end <= start:
            continue
        if (first and day < first) or (last and day > last):
            continue
        code = str(session.get("subject_code") or session.get("subject_name") or "")
        name = str(session.get("subject_name") or code)
        names[code] = name
        group = norm_group(session.get("group_code"))
        present.setdefault(code, set()).add(group)
        if wanted and group and group not in wanted:
            hidden += 1
            continue
        shown.add(code)
        key = (day, start, end, code, _kinds(session.get("activity_type")), session.get("room"))
        slot = merged.setdefault(key, [])
        if group and group not in slot:
            slot.append(group)
    blocks = [
        Block(
            day=day,
            start=start,
            end=end,
            code=code,
            name=names.get(code, code),
            course_id=ids.get(code) or _fallback_id(code),
            kinds=kinds,
            room=str(room or "").strip(),
            groups=tuple(sorted(slot)),
        )
        for (day, start, end, code, kinds, room), slot in merged.items()
    ]
    blocks.sort(key=lambda b: (b.day, b.start, b.end, b.title.casefold(), b.groups))
    lost = sorted(names[code] for code in present if code not in shown)
    not_listed = []
    for subject in data.get("subjects") or []:
        status = str(subject.get("status") or "")
        if status and status != "included":
            label = course_title(subject.get("subject_name")) or str(subject.get("subject_code"))
            not_listed.append(f"{label} ({_STATUS_TEXT.get(status, status)})")
    return Timetable(blocks, hidden, [course_title(n) for n in lost], not_listed)


def _fallback_id(code: str) -> int:
    return zlib.crc32(code.encode()) % 10


# --- week argument ------------------------------------------------------------------


def parse_week(text: str, today: date) -> date:
    """«+1», «-1», «2026-11-23», «23/11» or «23/11/2026» → that week's Monday."""

    value = text.strip().casefold()
    if _WEEK_RELATIVE.fullmatch(value):
        return sources.monday_of(today) + timedelta(weeks=int(value))
    if value in {"0", "hoy", "hoxe", "esta", "actual"}:
        return sources.monday_of(today)
    try:
        return sources.monday_of(date.fromisoformat(value))
    except ValueError:
        pass
    match = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2}|\d{4}))?", value)
    if match:
        day, month = int(match[1]), int(match[2])
        try:
            if match[3]:
                year = int(match[3]) + (2000 if len(match[3]) == 2 else 0)
                return sources.monday_of(date(year, month, day))
            # No year: the occurrence nearest to today.
            options = [date(today.year + shift, month, day) for shift in (-1, 0, 1)]
            return sources.monday_of(min(options, key=lambda d: abs((d - today).days)))
        except ValueError:
            pass
    raise ValueError(
        f"No entiendo la semana «{text}». Usa +1, -1, una fecha (2026-11-23) o día/mes (23/11)."
    )


def week_label(monday: date) -> str:
    sunday = monday + timedelta(days=6)
    if monday.month == sunday.month:
        return f"Do {monday.day} ao {sunday.day} de {MONTHS[sunday.month - 1]}"
    return (
        f"Do {monday.day} de {MONTHS[monday.month - 1]} ao {sunday.day} de "
        f"{MONTHS[sunday.month - 1]}"
    )


def _relative_week(monday: date, today: date) -> str:
    delta = (monday - sources.monday_of(today)).days // 7
    return {0: "Esta semana", 1: "Semana seguinte", -1: "Semana anterior"}.get(delta, "")


# --- colours ------------------------------------------------------------------------


def _luminance(color: str) -> float:
    def channel(value: int) -> float:
        value /= 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = _rgb(color)
    return 0.2126 * channel(red) + 0.7152 * channel(green) + 0.0722 * channel(blue)


def _ink(background: str) -> str:
    """Dark text on light blocks, white on dark ones (whichever contrasts more)."""

    return "#10102e" if _luminance(background) > 0.22 else WHITE


def _darker(color: str, factor: float = 0.55) -> str:
    red, green, blue = _rgb(color)
    return f"#{int(red * factor):02x}{int(green * factor):02x}{int(blue * factor):02x}"


# --- grid ---------------------------------------------------------------------------


@dataclass(slots=True)
class Placed:
    block: Block
    lane: int
    lanes: int


def layout_day(blocks: list[Block]) -> list[Placed]:
    """Assign overlapping blocks of one day to side-by-side lanes, cluster by cluster."""

    ordered = sorted(blocks, key=lambda b: (b.top, -b.bottom, b.title.casefold(), b.groups))
    clusters: list[list[Block]] = []
    current: list[Block] = []
    current_end = -1
    for item in ordered:
        if current and item.top >= current_end:
            clusters.append(current)
            current, current_end = [], -1
        current.append(item)
        current_end = max(current_end, item.bottom)
    if current:
        clusters.append(current)
    placed: list[Placed] = []
    for cluster in clusters:
        lane_ends: list[int] = []
        assigned: list[tuple[Block, int]] = []
        for item in cluster:
            for index, end in enumerate(lane_ends):
                if end <= item.top:
                    lane_ends[index] = item.bottom
                    assigned.append((item, index))
                    break
            else:
                lane_ends.append(item.bottom)
                assigned.append((item, len(lane_ends) - 1))
        placed.extend(Placed(item, lane, len(lane_ends)) for item, lane in assigned)
    return placed


def _fit_title(item: Block, cells: int, prefix: str = "") -> str:
    full = item.title
    room = cells - width(prefix)
    if width(full) <= room:
        return prefix + full
    alias = course_alias(item.name).upper()
    return prefix + truncate(alias or full, room)


def _block_rows(item: Block, rows: int, cells: int, active: bool) -> list[str]:
    """The styled rows (each exactly ``cells`` wide) of one grid block."""

    gap = 1 if cells >= 12 else 0
    inner = cells - 1 - gap
    bg, ink = item.color, _ink(item.color)
    kind = kind_label(item.kinds, short=True)
    groups = format_groups(item.groups)
    detail = f"{kind} · {groups}" if groups else kind
    room = item.room if width(item.room) <= inner else _short_room(item.room)
    title = _fit_title(item, inner, "▶ " if active else "")
    if cells < 14:  # narrow lane: the group code already says teoría/laboratorio/seminario
        lines = [title, groups or kind, room]
        if rows == 2:
            lines = [title, groups or kind]
    elif rows == 2:
        options = [f"{detail} · {room}" if room else detail, detail, groups or kind]
        fits = next((text for text in options if width(text) <= inner), options[-1])
        lines = [title, fits]
    else:
        lines = [title, detail, room]
    if rows == 1:
        lines = [title]
    out = []
    for index in range(rows):
        text = truncate(lines[index], inner) if index < len(lines) else ""
        out.append(
            paint("▌", _darker(bg), bg)
            + paint(" " * gap + pad(text, inner), ink, bg, bold=index == 0)
        )
    return out


def _short_room(room: str) -> str:
    """«Aula de Informática I6» → «Inf. I6», for narrow blocks."""

    return re.sub(r"(?i)^aula de inform[aá]tica\s*", "Inf. ", room).strip()


def _header(day: date, cells: int, today: date) -> str:
    name = WEEKDAYS[day.weekday()].capitalize() if cells >= 14 else WEEKDAYS_SHORT[day.weekday()]
    text = f"{name} {day.day}"
    if day == today:
        if not caps.color:
            text = f"▸ {text} ◂"
        return paint(pad(text, cells, "^"), MINT, NAVY, bold=True)
    return bold(pad(text, cells, "^"))


def render_grid(
    blocks: list[Block],
    days: list[date],
    cells: int,
    *,
    today: date,
    now: datetime | None = None,
) -> list[str] | None:
    """The week as columns, or None when it cannot be drawn readably."""

    gap = 1
    lane_total = (cells - GUTTER - gap * (len(days) - 1)) // len(days)
    if lane_total < 12 or not blocks:
        return None
    layouts = {day: layout_day([b for b in blocks if b.day == day]) for day in days}
    for placed in layouts.values():
        if any(lane_total // item.lanes < MIN_LANE for item in placed):
            return None
    first = min(b.top for b in blocks) // 60 * 60
    last = -(-max(b.bottom for b in blocks) // 60) * 60
    rendered: dict[int, list[str]] = {}  # id(placed) → styled rows
    for placed in layouts.values():
        for item in placed:
            size = lane_total // item.lanes + (1 if item.lane < lane_total % item.lanes else 0)
            rows = (item.block.bottom - item.block.top) // SLOT
            rendered[id(item)] = _block_rows(item.block, rows, size, item.block.active(now))
    lines = [
        " " * GUTTER + (" " * gap).join(_header(day, lane_total, today) for day in days),
    ]
    now_slot = None
    if now is not None and now.date() in days:
        minute = now.hour * 60 + now.minute
        if first <= minute < last:
            now_slot = minute // SLOT * SLOT
    for slot in range(first, last, SLOT):
        if slot == now_slot and now is not None:
            gutter = paint(f"{now:%H:%M}", WHITE, RED, bold=True) + " "
        else:
            gutter = muted(_hhmm(slot)) + " " if slot % 60 == 0 else " " * GUTTER
        columns = []
        for day in days:
            here = [p for p in layouts[day] if p.block.top <= slot < p.block.bottom]
            if not here:
                columns.append(muted(HOURLINE * lane_total) if slot % 60 == 0 else " " * lane_total)
                continue
            lanes = here[0].lanes
            parts = []
            for lane in range(lanes):
                size = lane_total // lanes + (1 if lane < lane_total % lanes else 0)
                match = next((p for p in here if p.lane == lane), None)
                if match is None:
                    parts.append(" " * size)
                else:
                    parts.append(rendered[id(match)][(slot - match.block.top) // SLOT])
            columns.append("".join(parts))
        lines.append(gutter + (" " * gap).join(columns))
    return lines


# --- list ---------------------------------------------------------------------------


def _day_heading(day: date, today: date) -> str:
    label = day_label(day, today)
    if label in {"Hoxe", "Mañá", "Onte"}:
        label += " · " + long_day(day)
    color = RED if day == today else None
    return " " + paint(label, color, bold=True)


def render_list(blocks: list[Block], cells: int, *, today: date, now: datetime | None) -> list[str]:
    lines: list[str] = []

    def kind_text(item: Block) -> str:
        text = kind_label(item.kinds)
        return text if width(text) <= 13 else kind_label(item.kinds, short=True)

    title_w = min(max((width(b.title) for b in blocks), default=8), 24)
    kind_w = max((width(kind_text(b)) for b in blocks), default=6)
    group_w = min(max((width(format_groups(b.groups)) for b in blocks), default=0), 16)
    wanted = min(max((width(b.room) for b in blocks), default=6), 22)
    fixed = 2 + 11 + 2 + 2 + 2 + kind_w + 2 + (group_w + 2 if group_w else 0)
    # The classroom is what people look for: let the subject's name give way first.
    title_w = max(min(title_w, 14), min(title_w, cells - fixed - 2 - wanted))
    room_w = max(6, cells - fixed - title_w)
    current: date | None = None
    for item in blocks:
        if item.day != current:
            current = item.day
            lines.append("")
            lines.append(_day_heading(item.day, today))
        active = item.active(now)
        kind = kind_text(item)
        name = bold(pad(truncate(item.title, title_w), title_w))
        line = (
            "  "
            + (paint(item.clock(), GREEN, bold=True) if active else muted(item.clock()))
            + "  "
            + paint("▌", item.color)
            + " "
            + name
            + "  "
            + pad(truncate(kind, kind_w), kind_w)
            + "  "
        )
        if group_w:
            line += pad(truncate(format_groups(item.groups), group_w), group_w) + "  "
        line += muted(truncate(item.room, room_w - (10 if active else 0)))
        if active:
            line = line.rstrip() + paint("  ▶ agora", GREEN, bold=True)
        lines.append(line)
    return lines


# --- week screen --------------------------------------------------------------------


def _legend() -> str:
    return muted("  teo teoría · lab laboratorio · sem seminario · tit titoría")


def _notes(table: Timetable, groups: list[str]) -> list[str]:
    notes = []
    if table.hidden:
        notes.append(f"{table.hidden} sesiones de otros grupos ocultas")
    if table.without_groups:
        notes.append("sin clases con tus grupos: " + ", ".join(table.without_groups))
    if table.not_listed:
        notes.append("fuera de este horario: " + "; ".join(table.not_listed))
    lines = [muted("  " + note) for note in notes]
    if groups and table.hidden:
        lines.append(muted("  Todos los grupos: campus horario --todos-los-grupos"))
    return lines


def _group_hint(data: dict[str, Any] | None) -> str:
    codes: list[str] = []
    for session in (data or {}).get("sessions") or []:
        group = norm_group(session.get("group_code"))
        if group and group not in codes:
            codes.append(group)
        if len(codes) == 2:
            break
    example = " ".join(codes) or "CLE_01 CLIL_02"
    return muted(f"  Solo tus grupos: campus horario --grupos {example} --guardar-grupos")


def _days_of(monday: date, blocks: list[Block]) -> list[date]:
    days = [monday + timedelta(days=offset) for offset in range(5)]
    days += [
        day
        for day in (monday + timedelta(days=5), monday + timedelta(days=6))
        if any(b.day == day for b in blocks)
    ]
    return days


def _render_week(
    results: dict[str, sources.Result],
    args: argparse.Namespace,
    monday: date,
    groups: list[str],
    notice: str | None,
) -> list[str]:
    result = results[sources.horario_key(monday)]
    cells = term_width()
    now = _now()
    today = now.date()
    heading = " · ".join(filter(None, [_relative_week(monday, today), week_label(monday)]))
    lines = [block("Horario", heading, cells)]
    if not result.ok:
        return lines
    table = build(result.data, groups, first=monday, last=monday + timedelta(days=6))
    if notice:
        lines += ["", "  " + paint(" ✓ ", WHITE, GREEN, bold=True) + " " + notice]
    if groups and not notice:
        lines += ["", muted("  Grupos: ") + " · ".join(groups)]
    if not table.blocks:
        lines.append("")
        if table.hidden:
            lines.append(empty("Ningunha sesión cos teus grupos esta semana."))
        else:
            lines.append(empty("Non hai clases esta semana."))
        lines += ["", *_notes(table, groups)]
        return lines
    grid = None
    if cells >= GRID_MIN_WIDTH and not args.lista:
        grid = render_grid(
            table.blocks, _days_of(monday, table.blocks), cells, today=today, now=now
        )
    lines.append("")
    if grid is not None:
        lines += grid
        lines += ["", _legend()]
    else:
        lines += render_list(table.blocks, cells, today=today, now=now)[1:]
        if not args.lista and cells >= GRID_MIN_WIDTH:
            lines += ["", muted("  Hay clases solapadas (varios grupos): la lista es más clara.")]
    notes = _notes(table, groups)
    if notes:
        lines += ["", *notes]
    if not groups:
        lines.append(_group_hint(result.data))
    lines.append(muted("  Otras semanas: campus horario +1 · -1 · 23/11"))
    return lines


def _week_json(
    results: dict[str, sources.Result], monday: date, groups: list[str]
) -> dict[str, Any] | None:
    result = results[sources.horario_key(monday)]
    if not result.ok:
        return None
    table = build(result.data, groups, first=monday, last=monday + timedelta(days=6))
    return {
        "week_start": monday.isoformat(),
        "groups": groups,
        "sessions": [item.to_json() for item in table.blocks],
        "hidden_sessions": table.hidden,
    }


def _handle_saving(args: argparse.Namespace) -> tuple[str | None, str | None]:
    """(notice, error) after ``--guardar-grupos``."""

    if not args.guardar_grupos:
        return None, None
    if args.todos_los_grupos:
        config.set_value("grupos", None)
        return "Grupos olvidados: desde ahora verás todos los grupos.", None
    groups = effective_groups(args) if args.grupos else []
    if not groups:
        return (
            None,
            "Indica qué grupos guardar: campus horario --grupos CLE_01 CLIL_02 --guardar-grupos",
        )
    config.set_value("grupos", groups)
    return (
        "Grupos guardados: " + " · ".join(groups) + ". Se aplican a horario, hoy y mañana.",
        None,
    )


def _week_arg(args: argparse.Namespace, today: date) -> date:
    text = args.semana
    if text is None:
        # `--grupos A B +1`: the greedy option swallowed the week.
        for item in list(args.grupos or []):
            if _WEEK_LIKE.fullmatch(item):
                args.grupos.remove(item)
                text = item
                break
    return parse_week(text, today) if text is not None else sources.monday_of(today)


def run_week(args: argparse.Namespace) -> int:
    today = _now().date()
    try:
        monday = _week_arg(args, today)
    except ValueError as exc:
        return fail(str(exc))
    notice, error = _handle_saving(args)
    if error:
        return fail(error)
    groups = effective_groups(args)
    key = sources.horario_key(monday)

    def render(results: dict[str, sources.Result], parsed: argparse.Namespace) -> list[str]:
        return _render_week(results, parsed, monday, groups, notice)

    code = show(
        args,
        [key],
        render,
        ["Taboleiro", "Horario"],
        json_payload=lambda results: _week_json(results, monday, groups),
    )
    if code == 0:
        _prefetch(monday + timedelta(days=7))
    return code


def _prefetch(monday: date) -> None:
    """Warm the following week: the first fetch is slow, `campus horario +1` is instant."""

    key = sources.horario_key(monday)
    if store.read(key) is None:
        sources.refresh_in_background([key])


def configure_week(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("semana", nargs="?", help="+1, -1, 2026-11-23 o 23/11 (por defecto, esta)")
    _group_options(parser)
    parser.add_argument("--lista", action="store_true", help="Fuerza la vista de lista")


def _group_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-g", "--grupos", nargs="+", metavar="GRUPO", help="Solo estos grupos (CLE_01 CLIL_02…)"
    )
    parser.add_argument(
        "--guardar-grupos", action="store_true", help="Recuerda --grupos para próximas veces"
    )
    parser.add_argument(
        "--todos-los-grupos", action="store_true", help="Ignora los grupos guardados"
    )


# --- day agenda ---------------------------------------------------------------------


@dataclass(slots=True)
class Entry:
    """One line of a day agenda: a class or a delivery."""

    at: datetime
    block: Block | None = None
    item: dict[str, Any] | None = None


def day_entries(
    horario: dict[str, Any] | None,
    pendientes: list[dict[str, Any]] | None,
    day: date,
    groups: list[str],
) -> tuple[list[Entry], Timetable]:
    table = build(horario, groups, first=day, last=day)
    entries = [
        Entry(datetime.combine(item.day, datetime.min.time()) + timedelta(minutes=item.start), item)
        for item in table.blocks
    ]
    for event in pendientes or []:
        moment = parse_moment(event.get("sort_at") or event.get("starts_at"))
        if moment is not None and moment.date() == day:
            entries.append(Entry(moment, item=event))
    entries.sort(key=lambda entry: (entry.at, entry.block is None))
    return entries, table


def _span(minutes: float) -> str:
    total = max(1, int(round(minutes)))
    hours, rest = divmod(total, 60)
    if not hours:
        return f"{rest} min"
    return f"{hours} h" + (f" {rest} min" if rest else "")


def _focus(entries: list[Entry], now: datetime | None) -> tuple[Block | None, Block | None]:
    """(class in progress, next class) for today's agenda."""

    if now is None:
        return None, None
    current = nxt = None
    for entry in entries:
        item = entry.block
        if item is None:
            continue
        if item.active(now):
            current = item
        elif entry.at > now and nxt is None:
            nxt = item
    return current, nxt


def _class_tag(item: Block, current: Block | None, nxt: Block | None, now: datetime | None) -> str:
    if now is None:
        return ""
    minute = now.hour * 60 + now.minute
    if item is current:
        return paint(" ▶ agora ", MINT, NAVY, bold=True) + muted(
            f" quedan {_span(item.end - minute)}"
        )
    if item is nxt:
        return paint("▷ a seguir", GRAY, bold=True) + muted(f" · en {_span(item.start - minute)}")
    return ""


def _class_lines(item: Block, cells: int, tag: str, *, past: bool) -> list[str]:
    badge = paint(" ◉ ", _ink(item.color), item.color, bold=True)
    title = truncate(item.title, max(10, cells - 11 - 8 - 4 - width(tag) - 4))
    title = muted(title) if past else bold(title)
    first = f"  {muted(item.clock())}  {badge} {title}"
    if tag:
        first += " " * max(1, cells - width(first) - width(tag)) + tag
    bits = [kind_label(item.kinds), format_groups(item.groups), item.room]
    detail = " · ".join(bit for bit in bits if bit)
    return [first, " " * 19 + muted(truncate(detail, max(10, cells - 19)))]


def _delivery_lines(event: dict[str, Any], cells: int, now: datetime | None) -> list[str]:
    moment = parse_moment(event.get("sort_at") or event.get("starts_at"))
    left, color = countdown(moment, now) if moment else ("", None)
    tag = paint(left, color, bold=color == RED) if color else muted(left)
    name = link(
        bold(truncate(activity_name(event), max(8, cells - 11 - 4 - 4 - width(tag) - 4))),
        event.get("url"),
    )
    first = f"  {muted(pad(f'{moment:%H:%M}' if moment else '--:--', 11))}  "
    first += f"{activity_icon(event.get('module'))} {name}"
    first += " " * max(1, cells - width(first) - width(tag)) + tag
    detail = paint("▌", course_color(event.get("course_id"))) + " "
    detail += course_title(event.get("course_name")) + muted(" · entrega")
    return [first, " " * 19 + detail]


def render_agenda(
    entries: list[Entry], cells: int, *, now: datetime | None, day: date
) -> list[str]:
    today_now = now if now is not None and now.date() == day else None
    current, nxt = _focus(entries, today_now)
    lines: list[str] = []
    for entry in entries:
        lines.append("")
        if entry.block is not None:
            past = today_now is not None and entry.block.end <= (
                today_now.hour * 60 + today_now.minute
            )
            tag = _class_tag(entry.block, current, nxt, today_now)
            lines += _class_lines(entry.block, cells, tag, past=past)
        elif entry.item is not None:
            lines += _delivery_lines(entry.item, cells, now)
    return lines


def _render_day(
    results: dict[str, sources.Result],
    args: argparse.Namespace,
    day: date,
    groups: list[str],
) -> list[str]:
    cells = term_width()
    now = _now()
    horario = results[sources.horario_key(day)]
    pendientes = results["pendientes"]
    label = day_label(day, now.date())
    heading = long_day(day) if label in {"Hoxe", "Mañá"} else ""
    lines = [block(label, heading, cells)]
    entries, table = day_entries(horario.data, pendientes.data, day, groups)
    if entries:
        lines += render_agenda(entries, cells, now=now, day=day)
    else:
        lines += ["", empty(_nothing(label, horario.ok, table))]
    if not horario.ok:
        lines += ["", muted("  Sin horario en caché: campus actualizar")]
    notes = _notes(table, groups)
    if notes:
        lines += ["", *notes]
    return lines


def _nothing(label: str, has_timetable: bool, table: Timetable) -> str:
    when = label.lower() if label in {"Hoxe", "Mañá"} else "ese día"
    if table.hidden:
        return f"Ningunha clase cos teus grupos {when}, nin entregas."
    return f"{when.capitalize() if when != 'ese día' else 'Ese día'} non tes clases nin entregas."


def _run_day(args: argparse.Namespace, offset: int) -> int:
    day = _now().date() + timedelta(days=offset)
    groups = effective_groups(args)
    key = sources.horario_key(day)

    def payload(results: dict[str, sources.Result]) -> dict[str, Any]:
        timetable = results[key].data if key in results else None
        entries, _ = day_entries(timetable, results["pendientes"].data, day, groups)
        return {
            "date": day.isoformat(),
            "groups": groups,
            "classes": [e.block.to_json() for e in entries if e.block is not None],
            "deliveries": [e.item for e in entries if e.item is not None],
        }

    def draw(results: dict[str, sources.Result], parsed: argparse.Namespace) -> list[str]:
        return _render_day({key: sources.Result(key), **results}, parsed, day, groups)

    return show(
        args,
        [key, "pendientes"],
        draw,
        ["Taboleiro", "Horario", "Hoxe" if offset == 0 else "Mañá"],
        json_payload=payload,
    )


def run_today(args: argparse.Namespace) -> int:
    return _run_day(args, 0)


def run_tomorrow(args: argparse.Namespace) -> int:
    return _run_day(args, 1)


def configure_day(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-g", "--grupos", nargs="+", metavar="GRUPO", help="Solo estos grupos (CLE_01 CLIL_02…)"
    )
    parser.add_argument(
        "--todos-los-grupos", action="store_true", help="Ignora los grupos guardados"
    )


# --- dashboard ----------------------------------------------------------------------


def compact_today(
    horario_result: sources.Result | None,
    pendientes_result: sources.Result | None,
    cells: int,
    now: datetime | None = None,
) -> list[str]:
    """Today in at most 8 lines, no navbar, for the dashboard. Either result may be empty."""

    now = now or _now()
    day = now.date()
    horario = horario_result.data if horario_result is not None and horario_result.ok else None
    pendientes = (
        pendientes_result.data if pendientes_result is not None and pendientes_result.ok else None
    )
    if horario is None and pendientes is None:
        return [empty("Sen datos do horario: campus actualizar")]
    entries, _ = day_entries(horario, pendientes, day, effective_groups())
    if not entries:
        return [empty("Hoxe non tes clases nin entregas.")]
    current, nxt = _focus(entries, now)
    minute = now.hour * 60 + now.minute
    rows: list[tuple[bool, str]] = []  # (finished, line)
    for entry in entries:
        item = entry.block
        if item is not None:
            done = item.end <= minute
            kind = kind_label(item.kinds, short=True)
            groups = format_groups(item.groups)
            tag = _class_tag(item, current, nxt, now)
            head = f" {muted(item.clock())} {paint('▌', item.color)} "
            avail = cells - width(head) - width(tag) - (2 if tag else 0)
            text = truncate(item.title, max(8, avail - 12))
            left = avail - width(text) - 3
            options = [
                " · ".join(filter(None, [kind, groups, item.room])),
                " · ".join(filter(None, [kind, groups])),
                groups or kind,
            ]
            tail = next((option for option in options if width(option) <= left), "")
            line = head + (muted(text) if done else bold(text))
            line += muted(" · " + tail) if tail else ""
            if tag:
                line += " " * max(1, cells - width(line) - width(tag)) + tag
            rows.append((done, line))
        elif entry.item is not None:
            moment = entry.at
            left, color = countdown(moment, now)
            tag = paint(left, color, bold=color == RED) if color else muted(left)
            head = f" {muted(pad(f'{moment:%H:%M}', 10))}{activity_icon(entry.item.get('module'))} "
            name = truncate(activity_name(entry.item), max(8, cells - width(head) - width(tag) - 2))
            line = head + bold(name)
            line += " " * max(1, cells - width(line) - width(tag)) + tag
            rows.append((moment < now, line))
    if len(rows) > 8:
        extra = len(rows) - 8 + 1
        # Drop what already happened first, then whatever is furthest away.
        kept = list(rows)
        for index in [i for i, (done, _) in enumerate(kept) if done][:extra]:
            kept[index] = (True, "")
        kept = [row for row in kept if row[1]]
        if len(kept) > 8:
            hidden = len(kept) - 7
            kept = kept[:7] + [(False, muted(f"  +{hidden} máis"))]
        rows = kept
    return [line for _, line in rows]


COMMANDS = [
    Command(
        "horario",
        "Horario de la semana de tus asignaturas",
        run_week,
        configure_week,
        aliases=("h", "semana"),
    ),
    Command(
        "hoy",
        "Agenda de hoy: clases y entregas",
        run_today,
        configure_day,
        aliases=("hoxe",),
    ),
    Command(
        "mañana",
        "Agenda de mañana: clases y entregas",
        run_tomorrow,
        configure_day,
        aliases=("manana", "mana", "mañá"),
    ),
]

__all__ = ["COMMANDS", "Block", "build", "compact_today", "parse_week", "render_grid"]
