"""`campus login`: the browser window, or your own browser plus the pasted cookie.

No browser opens and nothing reaches the Campus: the engine's calls are fakes.
"""

from __future__ import annotations

import importlib.util

import pytest

from campus_usc import app, sources, style


class _Terminal:
    def isatty(self) -> bool:
        return True


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("COLUMNS", "100")
    monkeypatch.setattr(
        sources,
        "fetch_now",
        lambda keys, quiet=False: {
            key: sources.Result(key, {"fullname": "Ana Proba"}, 0.0) for key in keys
        },
    )
    monkeypatch.setattr("webbrowser.open", lambda url: True)
    style.caps.reset()
    yield
    style.caps.reset()


def _run(capsys, *argv: str) -> tuple[int, str, str]:
    with pytest.raises(SystemExit) as exit_info:
        app.main(list(argv))
    captured = capsys.readouterr()
    return int(exit_info.value.code or 0), captured.out, captured.err


def test_window_login_waits_for_the_campus_and_greets(capsys, monkeypatch):
    calls = []

    async def fake_login(settings, timeout):
        calls.append(timeout)
        return {"authenticated": True}

    real_find_spec = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *rest: object() if name == "playwright" else real_find_spec(name, *rest),
    )
    monkeypatch.setattr("mcp_usc.campus.interactive_login", fake_login)
    code, output, _ = _run(capsys, "login", "--minutos", "5")
    assert code == 0 and calls == [300]
    assert "cv.usc.es" in output and "Sesión iniciada como Ana Proba" in output


def test_window_login_without_playwright_points_to_pegar(capsys, monkeypatch):
    real_find_spec = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *rest: None if name == "playwright" else real_find_spec(name, *rest),
    )
    code, _, error = _run(capsys, "login")
    assert code == 1 and "campus login --pegar" in error


def test_paste_login_opens_your_browser_and_checks_the_cookie(capsys, monkeypatch):
    stored = []

    async def fake_import(settings, cookie):
        stored.append(cookie)
        return {"authenticated": True, "user_name": "Ana Proba"}

    monkeypatch.setattr("sys.stdin", _Terminal())
    monkeypatch.setattr(app, "_secret", lambda prompt: "  abc123def456  ")
    monkeypatch.setattr("mcp_usc.session_auth.import_session_cookie", fake_import)
    code, output, _ = _run(capsys, "login", "--pegar")
    assert code == 0 and stored == ["abc123def456"]
    assert "https://cv.usc.es/login/index.php" in output and "MoodleSession" in output
    assert "Sesión iniciada como Ana Proba" in output


def test_paste_login_reports_a_rejected_cookie(capsys, monkeypatch):
    from mcp_usc.session_auth import SessionImportError

    async def rejected(settings, cookie):
        raise SessionImportError("La cookie no está autorizada o ya ha caducado.")

    monkeypatch.setattr("sys.stdin", _Terminal())
    monkeypatch.setattr(app, "_secret", lambda prompt: "caducada")
    monkeypatch.setattr("mcp_usc.session_auth.import_session_cookie", rejected)
    code, output, error = _run(capsys, "login", "--pegar")
    assert code == 1 and "caducado" in error and "Sesión iniciada" not in output


def test_paste_login_needs_a_terminal(capsys):
    code, _, error = _run(capsys, "login", "--pegar")
    assert code == 1 and "terminal" in error


def test_version_names_the_project(capsys):
    code, output, _ = _run(capsys, "--version")
    assert code == 0 and output.startswith("campus-usc ")
