"""`campus entregas`: only assignments, soonest first, each with its `campus entregar`."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from campus_usc import app, sources, store, style
from campus_usc.views import entregas

YEAR = sources.academic_year()
NOW = datetime.now()


def _event(name, days, *, module="assign", course=301, cmid=1001, actionable=True):
    return {
        "name": f"{name} pendente de entrega",
        "module": module,
        "course_id": course,
        "course_name": {
            301: f"Redes [G0000001] [{YEAR}]",
            302: f"Intelixencia Artificial [G0000002] [{YEAR}]",
        }[course],
        "sort_at": (NOW + timedelta(days=days)).astimezone().isoformat(),
        "url": f"https://cv.usc.es/mod/{module}/view.php?id={cmid}",
        "action_name": "Engadir entrega",
        "actionable": actionable,
    }


EVENTS = [
    _event("Práctica 3", 0.3, cmid=1001),
    _event("P3.3", 5, course=302, cmid=2002),
    _event("T8", 9, cmid=1003, actionable=False),  # not open yet
    _event("Cuestionario 4", 2, module="quiz", cmid=3001),  # not an assignment
    _event("Práctica 9", 45, cmid=1009),  # beyond 30 days
    _event("Práctica 2", -3, cmid=1002),  # late, still open
    _event("Práctica 1", -20, cmid=1000, actionable=False),  # late and closed
]


@pytest.fixture(autouse=True)
def _terminal(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("COLUMNS", "100")
    monkeypatch.setattr(
        sources,
        "fetch_now",
        lambda keys, quiet=False: {key: sources.Result(key, error="sin red") for key in keys},
    )
    style.caps.reset()
    store.write("pendientes", EVENTS)
    store.write("perfil", {"fullname": "Ana Proba"})
    store.write(
        "cursos",
        [
            {"id": 301, "full_name": f"Redes [G0000001] [{YEAR}]"},
            {"id": 302, "full_name": f"Intelixencia Artificial [G0000002] [{YEAR}]"},
        ],
    )
    yield
    style.caps.reset()


def _run(capsys, *argv: str) -> tuple[int, str, str]:
    with pytest.raises(SystemExit) as exit_info:
        app.main(list(argv))
    captured = capsys.readouterr()
    return int(exit_info.value.code or 0), captured.out, captured.err


def test_only_upcoming_assignments_in_order():
    soon, late = entregas.upcoming(EVENTS, days=30, now=NOW)
    assert [entregas.module_id(item) for item in soon] == [1001, 2002, 1003]
    assert [entregas.module_id(item) for item in late] == [1002]


def test_screen_numbers_each_task_for_entregar(capsys):
    code, output, _ = _run(capsys, "entregas")
    assert code == 0
    assert "Próximas entregas" in output and "3 nos próximos 30 días" in output
    assert output.index("Práctica 3") < output.index("P3.3") < output.index("T8")
    rows = {
        name: next(line for line in output.splitlines() if name in line)
        for name in ("Práctica 3", "P3.3")
    }
    assert rows["Práctica 3"].startswith("  1 ") and rows["P3.3"].startswith("  2 ")
    assert "campus entregar <número> ficheiro.pdf" in output
    assert "aínda non aberta" in output
    assert "Cuestionario" not in output and "Práctica 9" not in output
    assert "1  atrasadas que aínda admiten entrega" in output and "Práctica 2" not in output


def test_numbers_do_not_change_with_the_view():
    numbers = {entregas.module_id(item): n for n, item in entregas.numbered(EVENTS, NOW)}
    assert numbers == {1001: 1, 2002: 2, 1003: 3, 1009: 4, 1002: 5}


def test_late_ones_with_a(capsys):
    code, output, _ = _run(capsys, "entregas", "-a")
    assert code == 0 and "Práctica 2" in output and "Práctica 1 " not in output


def test_course_filter_limit_and_window(capsys):
    _, output, _ = _run(capsys, "entregas", "ia")
    assert "P3.3" in output and "Práctica 3" not in output
    _, output, _ = _run(capsys, "entregas", "-n", "1")
    assert "Práctica 3" in output and "P3.3" not in output and "e 2 máis" in output
    _, output, _ = _run(capsys, "entregas", "-d", "60")
    assert "Práctica 9" in output


def test_json_has_the_command(capsys):
    code, output, _ = _run(capsys, "entregas", "--json")
    items = json.loads(output)
    assert code == 0 and [item["module_id"] for item in items] == [1001, 2002, 1003]
    assert items[0]["numero"] == 1 and items[0]["entregar"] == "campus entregar 1"


@pytest.mark.parametrize("columns", ["80", "120"])
def test_fits(capsys, monkeypatch, columns):
    monkeypatch.setenv("COLUMNS", columns)
    _, output, _ = _run(capsys, "entregas", "-a")
    assert max(style.width(line) for line in output.splitlines()) <= int(columns)
