"""`campus examenes` and `campus calendario`: rendering from the local cache (synthetic data)."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pytest
from campus_usc_horarios import examenes

from campus_usc import app, modulos, sources, store, style
from campus_usc.views import calendario

NOW = datetime(2026, 11, 17, 9, 0)
TODAY = NOW.date()


def _call(start: str, end: str, rooms: list[str]) -> dict:
    return {
        "starts_at": f"{start}+01:00",
        "ends_at": f"{end}+01:00",
        "rooms": rooms,
        "groups": ["Grupo /A_01"],
    }


def schedule() -> dict:
    return {
        "academic_year": "2026/2027",
        "complete": True,
        "matched_moodle_courses": [
            {
                "course_id": 101,
                "subject_code": "G0000001",
                "course_name": "Variable Complexa [G0000001] [2026/2027]",
            },
            {
                "course_id": 102,
                "subject_code": "G0000002",
                "course_name": "Redes de Proba [G0000002] [2026/2027]",
            },
            {
                "course_id": 103,
                "subject_code": "G0000003",
                "course_name": "Álxebra Local [G0000003] [2026/2027]",
            },
            {
                "course_id": 104,
                "subject_code": "G0000004",
                "course_name": "Física Moderna [G0000004] [2026/2027]",
            },
        ],
        "subjects": [
            {
                "subject_code": "G0000001",
                "status": "matched",
                "calls": [
                    _call("2026-12-18T10:00:00", "2026-12-18T14:00:00", ["Aula 06"]),
                    _call("2027-06-09T16:00:00", "2027-06-09T20:00:00", ["Aula 06"]),
                ],
            },
            {
                "subject_code": "G0000002",
                "status": "matched",
                "calls": [
                    _call("2026-11-10T10:00:00", "2026-11-10T14:00:00", ["Aula A1"]),
                    _call("2027-01-21T10:00:00", "2027-01-21T14:00:00", ["Aula A3", "Aula A4"]),
                ],
            },
            {
                "subject_code": "G0000003",
                "status": "matched",
                "calls": [_call("2027-01-08T10:00:00", "2027-01-08T14:00:00", ["Aula A2"])],
            },
            {"subject_code": "G0000004", "status": "not_published_or_not_found", "calls": []},
        ],
    }


def pending() -> list[dict]:
    def event(day: str, name: str, course: int, title: str) -> dict:
        return {
            "name": name,
            "module": "assign",
            "course_id": course,
            "course_name": f"{title} [G000000{course - 100}] [2026/2027]",
            "starts_at": f"{day}T12:00:00+01:00",
            "sort_at": f"{day}T12:00:00+01:00",
            "url": "https://cv.example/mod/assign/view.php?id=1",
        }

    return [
        event("2026-12-03", "Práctica A pendente de entrega", 102, "Redes de Proba"),
        event("2026-12-18", "Tarefa final pendente de entrega", 101, "Variable Complexa"),
    ]


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("MCP_USC_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("MCP_USC_NO_BACKGROUND", "1")
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.setenv("COLUMNS", "100")
    monkeypatch.setattr(examenes, "_now", lambda: NOW)
    monkeypatch.setattr(examenes, "_today", lambda: TODAY)
    monkeypatch.setattr(calendario, "_now", lambda: NOW)
    monkeypatch.setattr(calendario, "_today", lambda: TODAY)
    style.caps.reset()
    store.write("perfil", {"fullname": "Ana Proba"})
    store.write(sources.examenes_key("2026/2027"), schedule())
    store.write("pendientes", pending())
    modulos.reset()
    yield tmp_path
    style.caps.reset()


def run(capsys, *argv: str) -> tuple[int, str]:
    with pytest.raises(SystemExit) as stop:
        app.main(list(argv))
    return int(stop.value.code or 0), capsys.readouterr().out


# --- examenes -------------------------------------------------------------------------


def test_next_exam_card(env, capsys) -> None:
    code, out = run(capsys, "examenes", "--curso-academico", "2026/2027")
    assert code == 0
    card = out.split("╰", 1)[0]
    assert "Próximo exame" in card
    assert "Variable Complexa" in card
    assert "venres, 18 de decembro" in card
    assert "10:00–14:00" in card
    assert "Aula 06" in card
    assert "en 31 días" in card


def test_month_grouping_and_order(env, capsys) -> None:
    _, out = run(capsys, "exames", "--curso-academico", "2026/2027")
    months = ["decembro de 2026", "xaneiro de 2027", "xuño de 2027"]
    positions = [out.index(month) for month in months]
    assert positions == sorted(positions)
    january = out[positions[1] : positions[2]]
    assert january.index("venres, 8 de xaneiro") < january.index("xoves, 21 de xaneiro")
    assert "2 exames" in january
    assert "Aula A3, Aula A4" in january
    assert "en 52 días" in january


def test_past_calls_hidden_unless_todas(env, capsys) -> None:
    _, default = run(capsys, "e", "--curso-academico", "2026/2027")
    assert "10 de novembro" not in default
    _, everything = run(capsys, "e", "--todas", "--curso-academico", "2026/2027")
    assert "martes, 10 de novembro" in everything
    assert "novembro de 2026" in everything
    assert "feito" in everything
    assert everything.index("novembro de 2026") < everything.index("decembro de 2026")


def test_single_subject_filter(env, capsys) -> None:
    _, out = run(capsys, "examenes", "redes", "--curso-academico", "2026/2027")
    assert "Redes de Proba" in out
    assert "Variable Complexa" not in out
    assert "Álxebra" not in out
    assert "Próximo exame" in out
    assert "xoves, 21 de xaneiro" in out


def test_unknown_subject_is_explained(env, capsys) -> None:
    _, out = run(capsys, "examenes", "zzzz", "--curso-academico", "2026/2027")
    assert "No encontré ninguna asignatura" in out


def test_subject_without_calls_is_listed_last(env, capsys) -> None:
    _, out = run(capsys, "examenes", "--curso-academico", "2026/2027")
    assert "Sen datas" in out
    tail = out[out.index("Sen datas") :]
    assert "Física Moderna" in tail
    assert "aún no hay fechas publicadas" in tail
    assert out.index("xuño de 2027") < out.index("Sen datas")


def test_timeline_marks_every_exam_of_the_round(env, capsys) -> None:
    _, out = run(capsys, "examenes", "--curso-academico", "2026/2027")
    line = next(line for line in out.splitlines() if line.strip().startswith("Hoxe"))
    assert "◆" in line
    assert line.count("●") == 3  # Variable, Álxebra and Redes: first call of each subject
    assert line.rstrip().endswith("21 xan")


def test_json_is_structured_and_respects_filters(env, capsys) -> None:
    code, out = run(capsys, "examenes", "--json", "--curso-academico", "2026/2027")
    assert code == 0
    data = json.loads(out)
    assert data["academic_year"] == "2026/2027"
    assert [exam["subject_code"] for exam in data["exams"]][:2] == ["G0000001", "G0000003"]
    assert all(exam["starts_at"] >= "2026-11-17" for exam in data["exams"])
    assert data["exams"][0]["days_left"] == 31
    assert data["without_dates"][0]["subject_code"] == "G0000004"
    _, filtered = run(
        capsys, "examenes", "--json", "--todas", "redes", "--curso-academico", "2026/2027"
    )
    assert {exam["subject_code"] for exam in json.loads(filtered)["exams"]} == {"G0000002"}
    assert len(json.loads(filtered)["exams"]) == 2


def test_empty_schedule(env, capsys) -> None:
    store.write(sources.examenes_key("2026/2027"), {"academic_year": "2026/2027", "subjects": []})
    code, out = run(capsys, "examenes", "--curso-academico", "2026/2027")
    assert code == 0
    assert "Non hai exames para mostrar." in out
    assert "Próximo exame" not in out


def test_all_calls_past_says_so(env, capsys, monkeypatch) -> None:
    monkeypatch.setattr(examenes, "_now", lambda: datetime(2027, 8, 1, 9, 0))
    _, out = run(capsys, "examenes", "--curso-academico", "2026/2027")
    assert "Non hai exames próximos." in out
    assert "ya pasaron todas sus convocatorias" in out


def test_invalid_academic_year(env, capsys) -> None:
    code, _ = run(capsys, "examenes", "--curso-academico", "hola")
    assert code == 1


def test_urgency_colours() -> None:
    def left(days: int):
        call = examenes.Call(NOW + timedelta(days=days, hours=1), None, (), (), 1, "X", "G1")
        return examenes._left(call, NOW)

    assert left(0)[0] == "hoxe" and left(0)[1] == style.RED
    assert left(1)[0] == "mañá"
    assert left(3)[1] == style.RED
    assert left(4)[1] == style.AMBER
    assert left(13)[1] == style.AMBER
    assert left(14)[1] == style.AMBER
    assert left(15)[1] is None
    assert left(15)[0] == "en 15 días"


def test_urgency_is_painted(env, capsys, monkeypatch) -> None:
    monkeypatch.delenv("NO_COLOR")
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.setenv("COLORTERM", "truecolor")
    monkeypatch.setattr(examenes, "_now", lambda: datetime(2026, 12, 16, 9, 0))
    style.caps.reset()
    _, out = run(capsys, "examenes", "--curso-academico", "2026/2027")
    assert "38;2;202;49;32" in out  # RED: the exam is in two days
    assert "38;2;0;184;148" in out or "38;2;" in out  # course chip colour


def test_compact_exams(env) -> None:
    result = sources.Result("examenes", schedule(), 0.0)
    lines = examenes.compact_exams(result, 60, limit=2, now=NOW)
    assert len(lines) == 2
    plain = [style.strip(line) for line in lines]
    assert "ven 18 dec" in plain[0] and "Variable Complexa" in plain[0] and "en 31 días" in plain[0]
    assert "ven 8 xan" in plain[1]
    assert all(style.width(line) <= 60 for line in lines)


def test_compact_exams_without_data(env) -> None:
    lines = examenes.compact_exams(sources.Result("examenes"), 60, now=NOW)
    assert len(lines) == 1 and "Aún no hay datos" in style.strip(lines[0])
    done = examenes.compact_exams(sources.Result("examenes", {"subjects": []}, 0.0), 60, now=NOW)
    assert "Non hai exames próximos." in style.strip(done[0])


@pytest.mark.parametrize("command", ["examenes", "calendario"])
@pytest.mark.parametrize("columns", [80, 110])
def test_never_wider_than_the_terminal(env, capsys, monkeypatch, command, columns) -> None:
    monkeypatch.setenv("COLUMNS", str(columns))
    argv = [command, "--curso-academico", "2026/2027"] if command == "examenes" else [command, "12"]
    _, out = run(capsys, *argv)
    assert out
    assert max(style.width(line) for line in out.splitlines()) <= columns


# --- calendario -------------------------------------------------------------------------


def test_month_grid_marks() -> None:
    style.caps.reset(color=False)
    try:
        lines = calendario.month_grid(
            2026, 11, {date(2026, 11, 19): 2, date(2026, 11, 27): 1}, {date(2026, 11, 27): 1}, TODAY
        )
    finally:
        style.caps.reset()
    assert lines[0].strip() == "novembro de 2026"
    assert lines[1].split() == ["Lu", "Ma", "Mé", "Xo", "Ve", "Sá", "Do"]
    assert max(style.width(line) for line in lines) <= 30
    first_week = lines[2]
    assert first_week.strip() == "1"  # 1 November 2026 is a Sunday: the rest of the row is blank
    assert first_week.index("1") == 26
    body = "\n".join(lines)
    assert "[17]" in body  # today, readable without colour
    assert "19•" in body  # delivery
    assert "27◆" in body  # delivery and exam on the same day
    assert "30" in lines[-1] and len(lines) == 8


def test_month_grid_exam_only_and_colours(monkeypatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.setenv("COLORTERM", "truecolor")
    style.caps.reset()
    try:
        lines = calendario.month_grid(
            2026, 12, {date(2026, 12, 3): 1}, {date(2026, 12, 18): 1}, TODAY
        )
        body = "\n".join(lines)
        assert "48;2;249;0;134" not in body  # pink is a foreground, not a background
        assert "38;2;249;0;134" in body  # delivery
        assert "38;2;202;49;32" in body  # exam
        today = calendario.month_grid(2026, 11, {}, {}, TODAY)
        assert "48;2;0;0;102" in "\n".join(today)  # NAVY background on today
        assert "38;2;225;244;241" in "\n".join(today)  # MINT text
        assert "▲" in body and "•" in body
    finally:
        style.caps.reset()


def test_month_grid_five_and_six_week_months() -> None:
    style.caps.reset(color=False)
    try:
        feb = calendario.month_grid(2027, 2, {}, {}, TODAY)
        assert len(feb) == 2 + 4  # 1 Feb 2027 is a Monday and the month has 28 days
        aug = calendario.month_grid(2026, 8, {}, {}, TODAY)
        assert len(aug) == 2 + 6
    finally:
        style.caps.reset()


def test_parse_month() -> None:
    assert calendario.parse_month(None, TODAY) == (2026, 11)
    assert calendario.parse_month("+1", TODAY) == (2026, 12)
    assert calendario.parse_month("+2", TODAY) == (2027, 1)
    assert calendario.parse_month("-1", TODAY) == (2026, 10)
    assert calendario.parse_month("-11", TODAY) == (2025, 12)
    assert calendario.parse_month("12", TODAY) == (2026, 12)
    assert calendario.parse_month("1", TODAY) == (2027, 1)
    assert calendario.parse_month("2027-06", TODAY) == (2027, 6)
    assert calendario.parse_month("06/2027", TODAY) == (2027, 6)
    assert calendario.parse_month("xan", TODAY) == (2027, 1)
    assert calendario.parse_month("diciembre", TODAY) == (2026, 12)
    for bad in ("13", "0000-13", "foo", "xx"):
        with pytest.raises(ValueError):
            calendario.parse_month(bad, TODAY)


def test_current_month_screen(env, capsys) -> None:
    code, out = run(capsys, "calendario")
    assert code == 0
    assert "Calendario" in out and "Próximos eventos" in out
    assert "novembro de 2026" in out
    assert "Lu  Ma  Mé  Xo  Ve  Sá  Do" in out
    assert "[17]" in out
    assert "Las entregas" not in out
    assert "Práctica A" not in out  # the cached deliveries are in December
    # November only has Redes' exam, on the 10th
    assert "Exame" in out and "10:00–14:00 · Aula A1" in out
    assert "10▲" in out


def test_december_shows_deliveries_and_exams(env, capsys) -> None:
    _, out = run(capsys, "cal", "+1")
    assert "decembro de 2026" in out
    assert "18▲" not in out  # the 18th has a delivery too: both cues
    assert "18◆" in out
    assert " 3•" in out
    assert "Práctica A" in out and "pendente de entrega" not in out
    assert "Exame · 10:00–14:00 · Aula 06" in out
    assert "‹ campus cal 2026-11" in out and "campus cal 2027-01 ›" in out
    assert out.index("Práctica A") < out.index("Tarefa final")


def test_month_navigation_forms(env, capsys) -> None:
    for argument, title in [
        ("12", "decembro de 2026"),
        ("2027-01", "xaneiro de 2027"),
        ("-1", "outubro de 2026"),
        ("+2", "xaneiro de 2027"),
    ]:
        code, out = run(capsys, "calendario", argument)
        assert code == 0
        assert title in out.splitlines()[5]


def test_month_beyond_deliveries_shows_exams_and_note(env, capsys) -> None:
    _, out = run(capsys, "calendario", "2027-06")
    assert "xuño de 2027" in out
    assert "9▲" in out
    assert "Las entregas solo alcanzan unos 60 días" in out
    _, partial = run(capsys, "calendario", "2027-01")
    assert "Las entregas llegan hasta el" in partial
    assert "8▲" in partial and "21▲" in partial


def test_invalid_month(env, capsys) -> None:
    code, _ = run(capsys, "calendario", "13")
    assert code == 1


def test_calendar_json(env, capsys) -> None:
    code, out = run(capsys, "calendario", "+1", "--json")
    assert code == 0
    data = json.loads(out)
    assert data["month"] == "2026-12"
    assert len(data["deadlines"]) == 2
    assert [exam["subject_code"] for exam in data["exams"]] == ["G0000001"]


def test_calendar_with_empty_data(env, capsys) -> None:
    store.write("pendientes", [])
    store.write(sources.examenes_key("2026/2027"), {"academic_year": "2026/2027", "subjects": []})
    code, out = run(capsys, "calendario")
    assert code == 0
    assert "Non hai eventos este mes." in out
    assert "[17]" in out


def test_narrow_calendar_puts_events_below_the_grid(env, capsys, monkeypatch) -> None:
    monkeypatch.setenv("COLUMNS", "80")
    _, out = run(capsys, "calendario", "12")
    assert out.index("Do") < out.index("Próximos eventos")
    lines = out.splitlines()
    heading = next(i for i, line in enumerate(lines) if "Próximos eventos" in line)
    assert not lines[heading].startswith(" ")  # full-width heading, not a side column
    monkeypatch.setenv("COLUMNS", "110")
    _, wide = run(capsys, "calendario", "12")
    side = next(line for line in wide.splitlines() if "Próximos eventos" in line)
    assert side.index("Próximos eventos") > 20  # beside the grid
