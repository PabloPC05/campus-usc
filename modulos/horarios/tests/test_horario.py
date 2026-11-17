"""`campus horario`, `hoy` and `mañana`: rendering from the cache, never the network.

Synthetic data only; «today» is frozen with ``horario._now``.
"""

from __future__ import annotations

import json
from datetime import date, datetime

import pytest
from campus_usc_horarios import horario

from campus_usc import app, config, modulos, sources, store
from campus_usc.style import caps, width

TODAY = datetime(2026, 11, 17, 11, 20)  # a Tuesday
MONDAY = date(2026, 11, 16)
WEEK_KEY = sources.horario_key(MONDAY)


def session(day, start, end, code, name, kind, group, room):
    return {
        "date": f"2026-11-{day}",
        "weekday": "x",
        "start_time": start,
        "end_time": end,
        "subject_name": name,
        "activity_type": kind,
        "group_code": f"/{group}",
        "room": room,
        "subject_code": code,
    }


def timetable(sessions, subjects=None):
    return {
        "academic_year": "2026/2027",
        "semester": 1,
        "matched_moodle_courses": [
            {"course_id": 101, "subject_code": "G0000001", "course_academic_year": "2026/2027"},
            {"course_id": 102, "subject_code": "G0000002", "course_academic_year": "2026/2027"},
            {"course_id": 103, "subject_code": "G0000003", "course_academic_year": "2026/2027"},
        ],
        "subjects": subjects
        or [
            {"subject_code": code, "subject_name": name, "status": "included"}
            for code, name in (
                ("G0000001", "Asignatura Alfa"),
                ("G0000002", "Asignatura Beta"),
                ("G0000003", "Asignatura Gamma"),
            )
        ],
        "sessions": sessions,
    }


ALFA = ("G0000001", "Asignatura Alfa")
BETA = ("G0000002", "Asignatura Beta")
GAMMA = ("G0000003", "Asignatura Gamma")

SESSIONS = [
    session("16", "09:00", "11:00", *ALFA, "laboratory", "CLIL_01", "Aula Uno"),
    session("16", "09:00", "11:00", *ALFA, "laboratory", "CLIL_02", "Aula Uno"),  # merges
    session("16", "11:00", "12:00", *BETA, "expository", "CLE_01", "Aula Tres"),
    session("17", "10:00", "12:00", *BETA, "laboratory+seminar", "CLIL_02", "Sala Cuatro"),
    session("17", "10:00", "12:00", *BETA, "laboratory+seminar", "CLIL_01", "Sala Cinco"),
    session("17", "15:00", "16:00", *GAMMA, "expository", "CLE_01", "Aula Seis"),
    session("19", "17:00", "18:30", *ALFA, "tutorship", "CLIT_01", "Despacho 7"),
]

DELIVERY = {
    "sort_at": "2026-11-17T23:59:00",
    "name": "Entrega práctica 2 pendiente de entrega",
    "module": "assign",
    "course_id": 101,
    "course_name": "Asignatura Alfa [G0000001] [2026/2027]",
    "url": "https://campus.example/mod/assign/view.php?id=1",
}


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_USC_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MCP_USC_NO_BACKGROUND", "1")
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("MCP_USC_CLI_CONFIG", str(tmp_path / "c.json"))
    monkeypatch.setenv("COLUMNS", "110")
    monkeypatch.setattr(horario, "_now", lambda: TODAY)
    caps.reset()
    store.write("perfil", {"fullname": "Ana Prueba"})
    store.write("pendientes", [DELIVERY])
    store.write(WEEK_KEY, timetable(SESSIONS))
    modulos.reset()  # the installed module is found again in each test
    yield
    caps.reset()


def run(capsys, *argv):
    with pytest.raises(SystemExit) as exit_info:
        app.main(list(argv))
    captured = capsys.readouterr()
    return exit_info.value.code, captured.out, captured.err


def test_grid_at_110_columns(capsys):
    code, out, _ = run(capsys, "horario", "--grupos", "CLIL_02", "CLE_01", "CLIT_01")
    assert code == 0
    assert "Esta semana · Do 16 ao 22 de novembro" in out
    for heading in ("Luns 16", "Martes 17", "Mércores 18", "Xoves 19", "Venres 20"):
        assert heading in out
    assert "Sábado" not in out and "Domingo" not in out
    assert "▸ Martes 17 ◂" in out  # today, readable without colour
    assert "teo · CLE_01" in out and "╌" in out
    assert "teo teoría · lab laboratorio" in out
    assert all(width(line) <= 110 for line in out.splitlines())
    # Rows are trimmed to the week's classes: first class 09:00, last ends 18:30 → 19:00.
    assert "08:00" not in out and "09:00" in out and "18:00" in out and "20:00" not in out


def test_grid_marks_class_in_progress(capsys):
    _, out, _ = run(capsys, "horario", "--grupos", "CLIL_02", "CLE_01")
    assert "▶ " in out  # tue 10:00-12:00 is running at 11:20
    assert "11:20" in out  # now marker in the hour gutter


def test_grid_shows_weekend_only_with_sessions(capsys):
    data = timetable(
        [*SESSIONS, session("21", "10:00", "12:00", *ALFA, "expository", "CLE_01", "A")]
    )
    store.write(WEEK_KEY, data)
    _, out, _ = run(capsys, "horario", "-g", "CLE_01", "CLIL_02")
    assert "Domingo 22" not in out
    assert "Sábado 21" in out


def test_list_at_80_columns_merges_groups(capsys, monkeypatch):
    monkeypatch.setenv("COLUMNS", "80")
    code, out, _ = run(capsys, "horario")
    assert code == 0
    assert "Onte · luns, 16 de novembro" in out
    assert "Hoxe · martes, 17 de novembro" in out
    assert "Xoves, 19 de novembro" in out
    assert "Mércores" not in out and "Venres" not in out  # no sessions those days
    assert "Sábado" not in out
    assert "09:00–11:00" in out and "laboratorio" in out and "Aula Uno" in out
    assert "CLIL_01/02" in out  # two groups, same time and room: one line
    assert out.count("09:00–11:00") == 1
    assert "titoría" in out and "Despacho 7" in out
    assert "laboratorio+seminario" in out or "lab+sem" in out
    assert all(width(line) <= 80 for line in out.splitlines())


def test_list_forced_and_overlap_fallback(capsys):
    _, forced, _ = run(capsys, "horario", "--lista", "-g", "CLE_01", "CLIL_02")
    assert "Luns 16" not in forced and "Hoxe · martes" in forced
    # Without groups, Tuesday 10:00 has two blocks side by side (3 lanes would not fit).
    many = [
        session("17", "10:00", "12:00", *ALFA, "laboratory", f"CLIL_0{n}", f"Aula {n}")
        for n in range(1, 5)
    ]
    store.write(WEEK_KEY, timetable(many))
    _, out, _ = run(capsys, "horario")
    assert "Hay clases solapadas" in out
    assert "campus horario --grupos" in out and "--guardar-grupos" in out


def test_group_filter_is_case_insensitive_and_ignores_slash(capsys, monkeypatch):
    monkeypatch.setenv("COLUMNS", "80")
    _, out, _ = run(capsys, "horario", "--grupos", "/clil_02", "cle_01")
    assert "CLIL_02" in out and "CLE_01" in out
    assert "CLIL_01" not in out
    assert "sesiones de otros grupos ocultas" in out
    assert "Despacho 7" not in out  # CLIT_01 not requested


def test_save_groups_and_apply_later(capsys, monkeypatch):
    monkeypatch.setenv("COLUMNS", "80")
    code, out, _ = run(capsys, "horario", "--grupos", "CLIL_02", "/CLE_01", "--guardar-grupos")
    assert code == 0
    assert "Grupos guardados: CLIL_02 · CLE_01" in out
    assert config.get("grupos") == ["CLIL_02", "CLE_01"]
    _, later, _ = run(capsys, "horario")
    assert "Grupos: CLIL_02 · CLE_01" in later and "CLIL_01" not in later
    _, everything, _ = run(capsys, "horario", "--todos-los-grupos")
    assert "CLIL_01" in everything
    # ...and they apply to the day agenda too.
    _, today, _ = run(capsys, "hoy")
    assert "Sala Cuatro" in today and "Sala Cinco" not in today
    code, out, _ = run(capsys, "horario", "--todos-los-grupos", "--guardar-grupos")
    assert code == 0 and "olvidados" in out
    assert config.get("grupos") is None


def test_save_groups_needs_groups(capsys):
    code, out, err = run(capsys, "horario", "--guardar-grupos")
    assert code == 1 and "Indica qué grupos" in err
    assert config.get("grupos") is None


def test_week_argument_variants(capsys):
    empty = timetable([])
    for key in ("2026-11-23", "2026-11-09", "2026-11-30"):
        store.write(f"horario/{key}", empty)
    _, out, _ = run(capsys, "horario", "+1")
    assert "Semana seguinte · Do 23 ao 29 de novembro" in out
    _, out, _ = run(capsys, "horario", "-1")
    assert "Semana anterior · Do 9 ao 15 de novembro" in out
    _, out, _ = run(capsys, "semana", "2026-11-26")
    assert "Do 23 ao 29 de novembro" in out
    _, out, _ = run(capsys, "h", "30/11")
    assert "Do 30 de novembro ao 6 de decembro" in out
    # The greedy --grupos option does not swallow a trailing week.
    _, out, _ = run(capsys, "horario", "--grupos", "CLE_01", "+1")
    assert "Do 23 ao 29 de novembro" in out


def test_bad_week_argument(capsys):
    code, _, err = run(capsys, "horario", "pronto")
    assert code == 1 and "No entiendo la semana" in err


def test_parse_week_picks_nearest_year():
    assert horario.parse_week("2/1", date(2026, 12, 20)) == date(2026, 12, 28)
    assert horario.parse_week("23/11/26", date(2026, 1, 1)) == date(2026, 11, 23)
    with pytest.raises(ValueError):
        horario.parse_week("31/02", date(2026, 1, 1))


def test_empty_week(capsys):
    store.write("horario/2026-11-23", timetable([]))
    code, out, _ = run(capsys, "horario", "+1")
    assert code == 0
    assert "Non hai clases esta semana." in out


def test_groups_hiding_everything(capsys):
    _, out, _ = run(capsys, "horario", "--grupos", "NOEXISTE")
    assert "Ningunha sesión cos teus grupos esta semana." in out
    assert "sin clases con tus grupos" in out


def test_footnote_for_subjects_not_in_this_timetable(capsys):
    subjects = [
        {"subject_code": "G0000001", "subject_name": "Asignatura Alfa", "status": "included"},
        {
            "subject_code": "G0000009",
            "subject_name": "Asignatura Delta",
            "status": "other_semester",
        },
        {"subject_code": "G0000008", "status": "not_found_in_study_plans"},
    ]
    store.write(WEEK_KEY, timetable(SESSIONS, subjects))
    _, out, _ = run(capsys, "horario")
    assert "Asignatura Delta (otro cuatrimestre)" in out
    assert "G0000008 (no está en los planes de estudio)" in out


def test_prefetches_following_week(capsys, monkeypatch):
    asked = []
    monkeypatch.setattr(sources, "refresh_in_background", lambda keys: asked.append(keys) or True)
    run(capsys, "horario")
    assert asked == [["horario/2026-11-23"]]
    asked.clear()
    store.write("horario/2026-11-23", timetable([]))
    run(capsys, "horario")
    assert asked == []  # already cached


def test_json_week(capsys):
    code, out, _ = run(capsys, "horario", "--json", "-g", "CLIL_02")
    assert code == 0
    payload = json.loads(out)
    assert payload["week_start"] == "2026-11-16"
    assert payload["groups"] == ["CLIL_02"]
    first = payload["sessions"][0]
    assert first["subject_code"] == "G0000001" and first["course_id"] == 101
    assert first["groups"] == ["/CLIL_02"] and first["start_time"] == "09:00"
    assert payload["hidden_sessions"] == 5


def test_hoy_with_delivery_and_agora_marker(capsys):
    code, out, _ = run(capsys, "hoy", "-g", "CLIL_02", "CLE_01")
    assert code == 0
    assert "Hoxe" in out and "martes, 17 de novembro" in out
    assert "10:00–12:00" in out and "Asignatura Beta" in out
    assert "▶ agora" in out and "quedan 40 min" in out
    assert "▷ a seguir" in out and "en 3 h 40 min" in out  # Gamma at 15:00
    assert "Entrega práctica 2" in out and "pendente de entrega" not in out
    assert "quedan 12 h" in out
    # chronological: class, class, delivery
    assert out.index("10:00–12:00") < out.index("15:00–16:00") < out.index("23:59")
    assert all(width(line) <= 110 for line in out.splitlines())


def test_hoy_alias_and_nothing_to_do(capsys):
    store.write(WEEK_KEY, timetable([]))
    store.write("pendientes", [])
    for name in ("hoxe", "hoy"):
        code, out, _ = run(capsys, name)
        assert code == 0
        assert "Hoxe non tes clases nin entregas." in out


def test_manana_reads_next_day(capsys):
    code, out, _ = run(capsys, "mañana", "--todos-los-grupos")
    assert code == 0
    assert "Mañá" in out and "mércores, 18 de novembro" in out
    assert "Non tes clases" not in out
    for alias in ("manana", "mana"):
        code, out, _ = run(capsys, alias)
        assert code == 0 and "Mañá" in out


def test_manana_next_week_needs_its_own_cache(capsys, monkeypatch):
    monkeypatch.setattr(horario, "_now", lambda: datetime(2026, 11, 22, 20, 0))  # Sunday
    store.write(
        "horario/2026-11-23",
        timetable([session("23", "09:00", "10:00", *ALFA, "expository", "CLE_01", "Aula Uno")]),
    )
    code, out, _ = run(capsys, "mañana")
    assert code == 0 and "09:00–10:00" in out and "luns, 23 de novembro" in out


def test_json_day(capsys):
    code, out, _ = run(capsys, "hoy", "--json", "-g", "CLIL_02", "CLE_01")
    assert code == 0
    payload = json.loads(out)
    assert payload["date"] == "2026-11-17"
    assert [c["subject_code"] for c in payload["classes"]] == ["G0000002", "G0000003"]
    assert payload["deliveries"][0]["course_id"] == 101


def test_compact_today(capsys):
    horario_result = sources.Result(WEEK_KEY, timetable(SESSIONS), 0.0)
    pending = sources.Result("pendientes", [DELIVERY], 0.0)
    lines = horario.compact_today(horario_result, pending, 80, now=TODAY)
    text = "\n".join(lines)
    assert len(lines) <= 8
    assert "Asignatura Beta" in text and "▶ agora" in text and "Entrega práctica 2" in text
    assert all(width(line) <= 80 for line in lines)
    # Either side may be missing.
    only_deliveries = horario.compact_today(None, pending, 80, now=TODAY)
    assert len(only_deliveries) == 1 and "Entrega práctica 2" in only_deliveries[0]
    only_classes = horario.compact_today(horario_result, None, 80, now=TODAY)
    assert "Asignatura Gamma" in "\n".join(only_classes)
    assert "campus actualizar" in "\n".join(horario.compact_today(None, None, 80, now=TODAY))
    quiet = horario.compact_today(sources.Result(WEEK_KEY, timetable([]), 0.0), None, 80, now=TODAY)
    assert "nin entregas" in quiet[0]


def test_compact_today_caps_at_eight_lines():
    many = [
        session("17", f"{8 + n:02d}:00", f"{8 + n:02d}:50", *ALFA, "expository", "CLE_01", "A")
        for n in range(11)
    ]
    result = sources.Result(WEEK_KEY, timetable(many), 0.0)
    lines = horario.compact_today(result, None, 100, now=datetime(2026, 11, 17, 8, 5))
    assert len(lines) == 8
    assert "máis" in lines[-1]


def test_colour_output_still_fits(capsys, monkeypatch):
    monkeypatch.delenv("NO_COLOR")
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.setenv("COLORTERM", "truecolor")
    caps.reset()
    _, out, _ = run(capsys, "horario", "-g", "CLIL_02", "CLE_01", "CLIT_01")
    assert "\x1b[" in out
    assert all(width(line) <= 110 for line in out.splitlines())
