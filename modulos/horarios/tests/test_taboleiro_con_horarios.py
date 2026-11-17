"""With the module installed, the Taboleiro, calendar and actualizar include it."""

from __future__ import annotations

import pytest

from campus_usc import app, modulos, sources, store, style


@pytest.fixture(autouse=True)
def _terminal(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("COLUMNS", "100")
    style.caps.reset()
    modulos.reset()
    store.write("perfil", {"fullname": "Ana Proba"})
    store.write("cursos", [])
    store.write("pendientes", [])
    store.write("notificaciones", {"unread": 0, "items": []})
    yield
    style.caps.reset()
    modulos.reset()


def _run(capsys, *argv: str) -> tuple[int, str, str]:
    with pytest.raises(SystemExit) as exit_info:
        app.main(list(argv))
    captured = capsys.readouterr()
    return int(exit_info.value.code or 0), captured.out, captured.err


def test_the_module_is_found_and_joins_everything(capsys, monkeypatch):
    assert modulos.installed("horarios")
    wanted: list[str] = []
    real_load = sources.load

    def load(keys, **options):
        wanted.extend(keys)
        return real_load(keys, **options)

    monkeypatch.setattr(sources, "load", load)
    monkeypatch.setattr(
        sources,
        "fetch_now",
        lambda keys, quiet=False: {key: sources.Result(key, error="sin red") for key in keys},
    )
    _, output, _ = _run(capsys, "inicio")
    assert sources.horario_key() in wanted and sources.examenes_key() in wanted
    assert "Próximos exames" in output and "campus modulos" not in output
    _, output, _ = _run(capsys, "ayuda")
    assert "Módulo horarios" in output and "examenes" in output
