"""Installable modules: found by package name, adding commands, data and Taboleiro pieces."""

from __future__ import annotations

import sys
import types
from datetime import date

import pytest

from campus_usc import app, modulos, sources, store, style
from campus_usc.views import Command


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
    store.write("perfil", {"fullname": "Ana Proba"})
    store.write("cursos", [])
    store.write("pendientes", [])
    store.write("notificaciones", {"unread": 0, "items": []})
    yield
    style.caps.reset()


def _run(capsys, *argv: str) -> tuple[int, str, str]:
    with pytest.raises(SystemExit) as exit_info:
        app.main(list(argv))
    captured = capsys.readouterr()
    return int(exit_info.value.code or 0), captured.out, captured.err


@pytest.fixture
def fake_module(monkeypatch):
    """A module named «proba» installed as the package campus_usc_proba."""

    module = types.ModuleType("campus_usc_proba")
    module.__spec__ = types.SimpleNamespace(name="campus_usc_proba")

    def saudo(args):
        print("ola dende o módulo")
        return 0

    async def fetch(service, param):
        return {"ok": True}

    module.COMMANDS = [Command("saudo", "Un comando dun módulo", saudo)]
    module.SOURCES = {"proba": sources.Source("Proba", 60, 3600, fetch, slow=True)}
    module.actualizar_keys = lambda today: ["proba/x"]
    module.taboleiro_keys = lambda today: ["proba/x"]
    module.taboleiro_blocks = lambda results, cells, now: ["", "BLOQUE DO MÓDULO"]
    monkeypatch.setitem(sys.modules, "campus_usc_proba", module)
    monkeypatch.setattr(
        modulos,
        "KNOWN",
        (modulos.Module("proba", "campus_usc_proba", "Un módulo de proba", "saudo"),),
    )
    monkeypatch.setattr(
        "importlib.util.find_spec",
        lambda name, *rest: object() if name == "campus_usc_proba" else None,
    )
    modulos.reset()
    return module


def test_without_modules_the_core_is_just_the_campus(capsys):
    code, output, _ = _run(capsys, "ayuda")
    rows = [
        line.split()[0] for line in output.splitlines() if line.startswith("  ") and line.split()
    ]
    assert code == 0 and "horario" not in rows and "examenes" not in rows


def test_a_missing_module_is_offered_with_its_install_line(capsys, monkeypatch):
    monkeypatch.setattr(
        modulos, "KNOWN", (modulos.Module("horarios", "non_existe_xa", "Horario", "horario"),)
    )
    modulos.reset()
    _, output, _ = _run(capsys, "ayuda")
    assert "Módulos que puedes añadir: horarios" in output
    _, output, _ = _run(capsys, "modulos")
    assert "sin instalar" in output and "campus-usc[horarios] @ https://github.com" in output
    _, output, _ = _run(capsys, "inicio")
    assert "campus modulos" in output


def test_an_installed_module_adds_its_commands_data_and_blocks(capsys, fake_module):
    code, output, _ = _run(capsys, "saudo")
    assert code == 0 and "ola dende o módulo" in output
    assert sources.SOURCES["proba"].label == "Proba"
    _, output, _ = _run(capsys, "ayuda")
    assert "Módulo proba" in output and "saudo" in output
    _, output, _ = _run(capsys, "inicio")
    assert "BLOQUE DO MÓDULO" in output
    _, output, _ = _run(capsys, "modulos")
    assert "● instalado" in output and 'uv tool install --reinstall "campus-usc @' in output


def test_actualizar_asks_for_the_modules_data(capsys, fake_module, monkeypatch):
    asked = []
    monkeypatch.setattr(
        sources,
        "fetch_now",
        lambda keys, quiet=False: (
            asked.extend(keys) or {key: sources.Result(key, error="sin red") for key in keys}
        ),
    )
    _run(capsys, "actualizar")
    assert "proba/x" in asked and "pendientes" in asked


def test_a_broken_module_never_breaks_the_campus(capsys, monkeypatch):
    monkeypatch.setattr(
        modulos, "KNOWN", (modulos.Module("roto", "campus_usc_roto", "Roto", "nada"),)
    )
    monkeypatch.setattr(
        "importlib.util.find_spec",
        lambda name, *rest: object() if name == "campus_usc_roto" else None,
    )

    def boom(name, *args, **kwargs):
        raise RuntimeError("roto")

    monkeypatch.setattr(
        "importlib.import_module",
        lambda name, *a: boom(name) if name == "campus_usc_roto" else __import__(name),
    )
    modulos.reset()
    assert modulos.loaded() == []


def test_install_command_keeps_the_other_modules():
    assert modulos.install_command(set()).startswith('uv tool install --reinstall "campus-usc @')
    assert "campus-usc[a,b] @" in modulos.install_command({"b", "a"})
    assert date  # (imported for the hooks' signature)
