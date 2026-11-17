"""Notifications read in full, marked as read on request, and text that cannot hijack
the terminal."""

from __future__ import annotations

import asyncio
import json
import time

import pytest

from campus_usc import app, sources, store, style
from campus_usc.text import html_to_text, scrub
from campus_usc.views import notificaciones

NOW = time.time()
ITEMS = [
    {
        "id": 501,
        "subject": "Nova cualificación en Redes",
        "smallmessage": "Tes unha nova cualificación",
        "component": "mod_assign",
        "timecreated": NOW - 7200,
        "read": False,
        "contexturl": "https://cv.usc.es/mod/assign/view.php?id=21",
        "contexturlname": "Práctica de sockets",
        "text": "Ola Ana,\n\nTes unha nova cualificación na Práctica de sockets: 9,5.",
    },
    {
        "id": 502,
        "subject": "Novo tema no foro",
        "component": "mod_forum",
        "timecreated": NOW - 3 * 86400,
        "read": True,
        "text": "",
    },
]


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def student_action(self, function, arguments, token):
        self.calls.append((function, arguments, token))
        if token is None:
            return {"preview": True, "confirmation_token": "t-read"}
        return {"request_sent": True, "outcome": "reported_by_moodle", "result": {}}


@pytest.fixture(autouse=True)
def _terminal(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("COLUMNS", "90")
    monkeypatch.setattr(
        sources,
        "fetch_now",
        lambda keys, quiet=False: {key: sources.Result(key, error="sin red") for key in keys},
    )
    style.caps.reset()
    store.write("perfil", {"fullname": "Ana Proba"})
    store.write("notificaciones", {"unread": 1, "items": [dict(item) for item in ITEMS]})
    yield
    style.caps.reset()


@pytest.fixture
def service(monkeypatch):
    fake = FakeService()
    monkeypatch.setattr(notificaciones, "_new_service", lambda: fake)
    return fake


def _run(capsys, *argv: str) -> tuple[int, str, str]:
    with pytest.raises(SystemExit) as exit_info:
        app.main(list(argv))
    captured = capsys.readouterr()
    return int(exit_info.value.code or 0), captured.out, captured.err


def test_list_is_numbered_and_filtering_keeps_the_numbers(capsys):
    code, output, _ = _run(capsys, "notificaciones")
    assert code == 0
    assert "  1 ●" in output and "  2 ○" in output
    assert "campus notificaciones 1" in output
    store.write(
        "notificaciones",
        {"unread": 1, "items": [dict(ITEMS[1], read=True), dict(ITEMS[0], id=503)]},
    )
    code, output, _ = _run(capsys, "n", "--sin-leer")
    assert "  2 ●" in output and "Novo tema" not in output


def test_one_notification_in_full_without_marking_it(capsys, service):
    code, output, _ = _run(capsys, "notificaciones", "1")
    assert code == 0
    assert "Notificación 1" in output and "Nova cualificación en Redes" in output
    assert "Ola Ana," in output and "9,5." in output
    assert "Práctica de sockets" in output
    assert "Sigue sin leer" in output
    assert service.calls == []
    assert store.read("notificaciones")[0]["unread"] == 1


def test_marking_one_as_read_uses_the_confirmed_action(capsys, service):
    code, output, _ = _run(capsys, "notificaciones", "1", "--marcar-leida")
    assert code == 0 and "Marcada como lida" in output
    assert [call[2] for call in service.calls] == [None, "t-read"]
    assert service.calls[0][:2] == (
        "core_message_mark_notification_read",
        {"notificationid": 501},
    )
    cached = store.read("notificaciones")[0]
    assert cached["unread"] == 0 and cached["items"][0]["read"] is True


def test_already_read_ones_are_not_marked_again(capsys, service):
    code, _, _ = _run(capsys, "notificaciones", "2", "--marcar-leida")
    assert code == 0 and service.calls == []


def test_bad_number_and_mark_without_number(capsys, service):
    code, _, error = _run(capsys, "notificaciones", "9")
    assert code == 1 and "la lista tiene 2" in error
    code, _, error = _run(capsys, "notificaciones", "--marcar-leida")
    assert code == 1 and "Indica qué notificación" in error


def test_json_of_one(capsys):
    code, output, _ = _run(capsys, "notificaciones", "1", "--json")
    assert code == 0 and json.loads(output)["text"].startswith("Ola Ana")


@pytest.mark.parametrize("columns", ["80", "110"])
def test_detail_fits(capsys, monkeypatch, columns):
    monkeypatch.setenv("COLUMNS", columns)
    long = dict(ITEMS[0], subject="Moi longo " * 30, text="palabra " * 400)
    store.write("notificaciones", {"unread": 1, "items": [long]})
    _, output, _ = _run(capsys, "notificaciones", "1")
    assert max(style.width(line) for line in output.splitlines()) <= int(columns)


# --- text ----------------------------------------------------------------------------------


def test_scrub_removes_terminal_escapes_everywhere():
    evil = "Nota\x1b]0;pwned\x07 final\x1b[2J\x9b31m\r\nfin"
    cleaned = scrub({"a": [evil], "b": 3, "c": None})
    assert cleaned == {"a": ["Nota]0;pwned final[2J31m\nfin"], "b": 3, "c": None}
    assert "\x1b" not in cleaned["a"][0] and "\x07" not in cleaned["a"][0]


def test_html_to_text_keeps_paragraphs_and_lists():
    html = (
        "<p>Ola <b>Ana</b>,</p><p>Tes:</p><ul><li>Práctica 1</li><li>Práctica&nbsp;2</li></ul>"
        "<script>alert(1)</script><br>Saúdos"
    )
    assert html_to_text(html) == "Ola Ana,\n\nTes:\n\n• Práctica 1\n• Práctica 2\n\nSaúdos"
    assert html_to_text("a &amp; b") == "a & b"
    assert html_to_text("x" * 50, limit=10) == "x" * 9 + "…"


def test_fetched_notifications_keep_their_whole_text():
    class Service:
        async def list_notifications(self, status, offset, limit):
            return {
                "result": {
                    "unreadcount": 1,
                    "notifications": [
                        {
                            "id": 9,
                            "subject": "Aviso",
                            "fullmessagehtml": "<p>Primeira liña</p><p>Segunda</p>",
                            "useridfrom": 4,
                        }
                    ],
                }
            }

    data = asyncio.run(sources.SOURCES["notificaciones"].fetch(Service(), ""))
    assert data["items"][0]["text"] == "Primeira liña\n\nSegunda"
    assert "useridfrom" not in data["items"][0]
