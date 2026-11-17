"""Expired or missing sessions: silent renewal first, the window only with someone there."""

from __future__ import annotations

import pytest

from campus_usc import auth, sources, store


class _Engine:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.renews = False


@pytest.fixture
def engine(monkeypatch):
    fake = _Engine()

    async def renew(settings, timeout=45):
        fake.calls.append("silent")
        return fake.renews

    async def window(settings, timeout):
        fake.calls.append("window")
        return {"authenticated": True}

    monkeypatch.setattr("mcp_usc.campus.renew_session_silently", renew)
    monkeypatch.setattr("mcp_usc.campus.interactive_login", window)
    monkeypatch.setattr(auth, "available", lambda: True)
    monkeypatch.setattr(auth, "_settings", lambda: object())
    return fake


def test_silent_renewal_needs_no_window(engine):
    engine.renews = True
    assert auth.ensure(interactive=True) is True
    assert engine.calls == ["silent"]


def test_background_never_opens_a_window_and_waits_before_retrying(engine):
    assert auth.ensure(interactive=False) is False
    assert auth.ensure(interactive=False) is False
    assert engine.calls == ["silent"]  # the second time it does not even try (10 min)


def test_with_someone_there_the_window_follows(engine, capsys):
    assert auth.ensure(interactive=True) is True
    assert engine.calls == ["silent", "window"]
    assert "Mantener la sesión iniciada" in capsys.readouterr().err
    # A good login clears the wait: the next expiry tries the silent way first again.
    assert store.read("login")[0] == {}


def test_expired_session_is_renewed_and_the_screen_asked_again(monkeypatch):
    monkeypatch.delenv("CAMPUS_NO_LOGIN", raising=False)
    answers = iter(
        [
            {"cursos": sources.Result("cursos", error="caducó", login_needed=True)},
            {"cursos": sources.Result("cursos", [{"id": 1}], 0.0)},
        ]
    )

    async def fake_fetch_all(keys):
        return next(answers)

    renewals: list[bool] = []
    monkeypatch.setattr(sources, "_fetch_all", fake_fetch_all)
    monkeypatch.setattr(auth, "ensure", lambda interactive: renewals.append(interactive) or True)
    result = sources.fetch_now(["cursos"], quiet=True)["cursos"]
    assert result.ok and result.data == [{"id": 1}]
    assert renewals == [False]  # quiet (background): silent only


def test_no_login_when_disabled(monkeypatch):
    async def fake_fetch_all(keys):
        return {"cursos": sources.Result("cursos", error="caducó", login_needed=True)}

    monkeypatch.setattr(sources, "_fetch_all", fake_fetch_all)
    monkeypatch.setattr(auth, "ensure", lambda interactive: pytest.fail("no debía entrar"))
    assert sources.fetch_now(["cursos"], quiet=True)["cursos"].login_needed
