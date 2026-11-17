"""Timetable and exams are optional: off until you ask for them once."""

from __future__ import annotations

from datetime import date

import pytest

from campus_usc import app, optional, sources, store, style


@pytest.fixture(autouse=True)
def _terminal(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("COLUMNS", "100")
    asked: list[list[str]] = []

    def fetch(keys, quiet=False):
        asked.append(list(keys))
        return {key: sources.Result(key, error="sin red") for key in keys}

    monkeypatch.setattr(sources, "fetch_now", fetch)
    style.caps.reset()
    store.write("perfil", {"fullname": "Ana Proba"})
    store.write("cursos", [])
    store.write("pendientes", [])
    store.write("notificaciones", {"unread": 0, "items": []})
    yield asked
    style.caps.reset()


def _run(capsys, *argv: str) -> tuple[int, str, str]:
    with pytest.raises(SystemExit) as exit_info:
        app.main(list(argv))
    captured = capsys.readouterr()
    return int(exit_info.value.code or 0), captured.out, captured.err


def test_the_taboleiro_never_touches_usc_gal_by_default(capsys, _terminal):
    code, output, _ = _run(capsys, "inicio")
    assert code == 0
    asked = [key for keys in _terminal for key in keys]
    assert not any(key.startswith(("horario", "examenes")) for key in asked)
    assert "Próximos exames" not in output
    assert "Opcional, de usc.gal" in output and "campus horario" in output


def test_asking_once_turns_it_on_and_ocultar_turns_it_off(capsys):
    assert not optional.enabled("horario")
    _run(capsys, "horario")
    assert optional.enabled("horario")
    _, output, error = _run(capsys, "horario", "--ocultar")
    assert not optional.enabled("horario") and "campus horario" in output
    _run(capsys, "examenes")
    assert optional.enabled("examenes")


def test_once_on_the_taboleiro_asks_for_it(capsys, monkeypatch):
    wanted: list[str] = []
    real_load = sources.load

    def load(keys, **options):
        wanted.extend(keys)
        return real_load(keys, **options)

    monkeypatch.setattr(sources, "load", load)
    _run(capsys, "inicio")
    assert not any(key.startswith(("horario", "examenes")) for key in wanted)
    optional.enable("horario")
    optional.enable("examenes")
    wanted.clear()
    _, output, _ = _run(capsys, "inicio")
    assert sources.horario_key(date.today()) in wanted and sources.examenes_key() in wanted
    assert "Próximos exames" in output and "Opcional, de usc.gal" not in output


def test_hoy_without_timetable_shows_deliveries_and_how_to_add_classes(capsys, _terminal):
    code, output, _ = _run(capsys, "hoy")
    assert code == 0 and "As clases son opcionais" in output
    assert not any(key.startswith("horario") for keys in _terminal for key in keys)


def test_actualizar_skips_the_optional_parts(capsys, _terminal):
    _run(capsys, "actualizar")
    asked = [key for keys in _terminal for key in keys]
    assert "pendientes" in asked and not any(
        key.startswith(("horario", "examenes")) for key in asked
    )
    optional.enable("examenes")
    _terminal.clear()
    _run(capsys, "actualizar")
    asked = [key for keys in _terminal for key in keys]
    assert any(key.startswith("examenes") for key in asked)


def test_help_puts_the_campus_first(capsys):
    _, output, _ = _run(capsys, "ayuda")
    assert output.index("entregar") < output.index("Opcional") < output.index("horario ")
