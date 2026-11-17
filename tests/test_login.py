"""`campus login`: the browser window, or your own browser plus the pasted cookie.

No browser opens and nothing reaches the Campus: the engine's calls are fakes.
"""

from __future__ import annotations

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


def test_login_is_silent_when_the_browser_remembers_you(capsys, monkeypatch):
    from campus_usc import auth

    windows = []
    monkeypatch.setattr(auth, "available", lambda: True)
    monkeypatch.setattr(auth, "has_screen", lambda: True)
    monkeypatch.setattr(auth, "silent", lambda settings=None: True)
    monkeypatch.setattr(auth, "remembers_someone", lambda settings=None: True)
    monkeypatch.setattr(auth, "window", lambda *a, **k: windows.append(a))
    monkeypatch.setattr(auth, "_settings", lambda: object())
    code, output, error = _run(capsys, "login")
    assert code == 0 and windows == []
    assert "Sesión iniciada como Ana Proba" in output and "contraseña" not in error


def test_login_opens_the_window_when_microsoft_needs_you(capsys, monkeypatch):
    from campus_usc import auth

    timeouts = []

    async def fake_login(settings, timeout):
        timeouts.append(timeout)
        return {"authenticated": True}

    monkeypatch.setattr(auth, "available", lambda: True)
    monkeypatch.setattr(auth, "has_screen", lambda: True)
    monkeypatch.setattr(auth, "silent", lambda settings=None: False)
    monkeypatch.setattr(auth, "_settings", lambda: object())
    monkeypatch.setattr("mcp_usc.campus.interactive_login", fake_login)
    code, output, error = _run(capsys, "login", "--minutos", "5")
    assert code == 0 and timeouts == [300]
    assert "cuenta de la USC" in error and "«Sí»" in error
    assert "Sesión iniciada como Ana Proba" in output


def test_without_a_browser_it_asks_for_the_session_right_away(capsys, monkeypatch):
    from campus_usc import auth

    stored = []

    async def fake_import(settings, cookie):
        stored.append(cookie)
        return {"authenticated": True}

    monkeypatch.setattr(auth, "available", lambda: False)
    monkeypatch.setattr(auth, "has_screen", lambda: True)
    monkeypatch.setattr("sys.stdin", _Terminal())
    monkeypatch.setattr(app, "_secret", lambda prompt: "abc123")
    monkeypatch.setattr("mcp_usc.session_auth.import_session_cookie", fake_import)
    code, output, _ = _run(capsys, "entrar")
    text = " ".join(output.split())
    assert code == 0 and stored == ["abc123"]
    assert "No encuentro Chrome, Edge, Brave ni Chromium" in text and "MoodleSession" in text


def test_your_own_browser_is_enough(monkeypatch):
    from campus_usc import auth

    monkeypatch.setattr("mcp_usc.system_browser.find_browser", lambda: ("msedge", "/x"))
    monkeypatch.setattr(auth, "bundled_browser", lambda: False)
    assert auth.available() is True
    monkeypatch.setattr("mcp_usc.system_browser.find_browser", lambda: None)
    assert auth.available() is False


def test_paste_login_opens_your_browser_and_checks_the_cookie(capsys, monkeypatch):
    stored = []

    async def fake_import(settings, cookie):
        stored.append(cookie)
        return {"authenticated": True, "user_name": "Ana Proba"}

    monkeypatch.setattr("sys.stdin", _Terminal())
    monkeypatch.setattr(app, "_secret", lambda prompt: "  abc123def456  ")
    monkeypatch.setattr("mcp_usc.session_auth.import_session_cookie", fake_import)
    code, output, _ = _run(capsys, "entrar", "pegar")
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


def test_paste_login_reads_a_piped_cookie(capsys, monkeypatch):
    import io

    stored = []

    async def fake_import(settings, cookie):
        stored.append(cookie)
        return {"authenticated": True}

    monkeypatch.setattr("sys.stdin", io.StringIO("piped-cookie\n"))
    monkeypatch.setattr("mcp_usc.session_auth.import_session_cookie", fake_import)
    code, output, _ = _run(capsys, "login", "--pegar")
    assert code == 0 and stored == ["piped-cookie"] and "piped-cookie" not in output
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    code, _, error = _run(capsys, "login", "--pegar")
    assert code == 1 and "No pegaste nada" in error


def test_without_a_screen_it_asks_for_the_session_right_away(capsys, monkeypatch):
    from campus_usc import auth

    stored = []

    async def fake_import(settings, cookie):
        stored.append(cookie)
        return {"authenticated": True}

    monkeypatch.setattr(auth, "available", lambda: True)
    monkeypatch.setattr(auth, "has_screen", lambda: False)
    monkeypatch.setattr(auth, "silent", lambda settings=None: False)
    monkeypatch.setattr(auth, "_settings", lambda: object())
    monkeypatch.setattr("sys.stdin", _Terminal())
    monkeypatch.setattr(app, "_secret", lambda prompt: "desde-otro-equipo")
    monkeypatch.setattr("mcp_usc.session_auth.import_session_cookie", fake_import)
    code, output, _ = _run(capsys, "entrar")
    assert code == 0 and stored == ["desde-otro-equipo"] and "SSH" in output


def test_without_a_screen_a_remembered_account_needs_nothing(capsys, monkeypatch):
    from campus_usc import auth

    monkeypatch.setattr(auth, "available", lambda: True)
    monkeypatch.setattr(auth, "has_screen", lambda: False)
    monkeypatch.setattr(auth, "silent", lambda settings=None: True)
    monkeypatch.setattr(auth, "remembers_someone", lambda settings=None: True)
    monkeypatch.setattr(auth, "_settings", lambda: object())
    monkeypatch.setattr(app, "_secret", lambda prompt: pytest.fail("no debía pedir nada"))
    code, output, _ = _run(capsys, "entrar")
    assert code == 0 and "MoodleSession" not in output


def test_an_unknown_word_is_explained(capsys):
    code, _, error = _run(capsys, "entrar", "ventana")
    assert code == 1 and "campus entrar pegar" in error


def test_screen_detection_on_linux(monkeypatch):
    from campus_usc import auth

    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert auth.has_screen() is False
    monkeypatch.setenv("DISPLAY", ":0")
    assert auth.has_screen() is True


def _salir_setup(tmp_path, monkeypatch, *, remote):
    from types import SimpleNamespace

    from campus_usc import store

    profile = tmp_path / "browser-profile" / "chromium"
    profile.mkdir(parents=True)
    store.write("notas", {"courses": []})
    calls = []

    async def fake_end(settings):
        calls.append("end")
        return {"remote_logout": remote, "local_session_removed": True}

    def fake_forget():
        calls.append("forget")
        return {"local_session_removed": True}

    monkeypatch.setattr(
        app, "_new_settings", lambda: SimpleNamespace(browser_profile_dir=profile.parent)
    )
    monkeypatch.setattr("mcp_usc.session_auth.end_campus_session", fake_end)
    monkeypatch.setattr("mcp_usc.session_auth.forget_session_cookie", fake_forget)
    return profile, calls


def test_salir_closes_on_the_campus_and_forgets_everything_here(capsys, tmp_path, monkeypatch):
    from campus_usc import store

    profile, calls = _salir_setup(tmp_path, monkeypatch, remote=True)
    code, output, _ = _run(capsys, "salir")
    text = " ".join(output.split())
    assert code == 0 and calls == ["end"]
    assert "Sesión cerrada en el Campus" in text and "campus entrar" in text
    assert not profile.parent.exists() and store.read("notas") is None
    assert "ya no recuerda tu cuenta de Microsoft" in text


def test_salir_solo_aqui_keeps_the_campus_session(capsys, tmp_path, monkeypatch):
    profile, calls = _salir_setup(tmp_path, monkeypatch, remote=True)
    code, output, _ = _run(capsys, "salir", "--solo-aqui")
    assert code == 0 and calls == ["forget"]
    assert "en el Campus sigue abierta" in " ".join(output.split())
    assert not profile.parent.exists()


def test_version_names_the_project(capsys):
    code, output, _ = _run(capsys, "--version")
    assert code == 0 and output.startswith("campus-usc ")
