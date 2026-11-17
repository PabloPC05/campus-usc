"""The installer's menu: what it recommends for each computer, and the line it runs."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "instalar", Path(__file__).resolve().parents[1] / "instalar.py"
)
instalar = importlib.util.module_from_spec(spec)
sys.modules["instalar"] = instalar  # dataclasses look their module up there
spec.loader.exec_module(instalar)


def machine(**changes):
    values = {"system": "Windows", "browser": "Edge", "screen": True, "installed": False}
    return instalar.Machine(**{**values, **changes})


@pytest.mark.parametrize(
    ("situation", "bundled", "words"),
    [
        (machine(), False, "tienes Edge"),
        (machine(system="macOS", browser=None, others=["Safari"]), True, "veo Safari"),
        (machine(system="Linux", browser=None, screen=False), False, "SSH"),
        (machine(system="Linux", browser="Chromium"), False, "tienes Chromium"),
    ],
)
def test_the_bundled_browser_only_when_it_helps(situation, bundled, words):
    wanted, why = instalar.recommend_browser(situation)
    assert wanted is bundled and words in why


def test_the_install_line_and_size():
    assert instalar.Plan(False, False).target().startswith("campus-usc @ https://github.com/")
    both = instalar.Plan(True, True)
    assert both.target().startswith("campus-usc[horarios,navegador] @ ")
    assert both.size_mb() == instalar.CORE_MB + instalar.BROWSER_MB


def test_si_takes_the_recommendation_without_asking(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt: pytest.fail("asked"))
    options = instalar.argparse.Namespace(si=True, horarios=None, navegador=None)
    plan = instalar.choose(machine(system="macOS", browser=None), options)
    assert plan == instalar.Plan(horarios=False, navegador=True)
    plan = instalar.choose(machine(), options)
    assert plan == instalar.Plan(horarios=False, navegador=False)


def test_answers_choose_the_parts(monkeypatch):
    answers = iter(["", "s"])  # keep the recommendation for the browser, add horarios
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    options = instalar.argparse.Namespace(si=False, horarios=None, navegador=None)
    plan = instalar.choose(machine(), options)
    assert plan == instalar.Plan(horarios=True, navegador=False)


def test_without_a_screen_it_never_offers_the_window(monkeypatch):
    asked = []
    monkeypatch.setattr("builtins.input", lambda prompt: asked.append(prompt) or "n")
    options = instalar.argparse.Namespace(si=False, horarios=None, navegador=None)
    plan = instalar.choose(machine(system="Linux", browser=None, screen=False), options)
    assert plan.navegador is False and all("navegador" not in q for q in asked)
    text = "\n".join(instalar.describe(machine(system="Linux", browser=None, screen=False)))
    assert "campus login --pegar" in text


def test_simulating_installs_nothing(monkeypatch, capsys):
    monkeypatch.setattr(instalar, "look", lambda: machine())
    monkeypatch.setattr(instalar, "install", lambda plan: pytest.fail("installed"))
    assert instalar.main(["--simular", "--si"]) == 0
    output = capsys.readouterr().out
    assert "Se instalará: el Campus" in output and "simulación" in output
