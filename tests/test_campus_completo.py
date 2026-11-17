"""Grades, announcements and forums, messages and quizzes: the rest of the Campus.

Everything reads invented data from the cache; ``escribir`` talks to a fake engine.
"""

from __future__ import annotations

import time

import pytest

from campus_usc import app, sources, store, style
from campus_usc.views import cuestionarios, foros, mensajes, notas

YEAR = sources.academic_year()
OLD = f"{int(YEAR[:4]) - 1}/{YEAR[:4]}"
COURSES = [
    {"id": 301, "full_name": f"Redes [G0000001] [{YEAR}]"},
    {"id": 302, "full_name": f"Intelixencia Artificial [G0000002] [{YEAR}]"},
    {"id": 303, "full_name": f"Cálculo [G0000003] [{OLD}]"},
]


def _forum(cmid: int, name: str, section: int = 0) -> dict:
    return {"module_id": cmid, "module_type": "forum", "name": name, "section_number": section}


def _discussion(did: int, subject: str, *, unread: int = 0, replies: int = 0) -> dict:
    return {
        "discussion_id": did,
        "subject": subject,
        "url": f"https://cv.usc.es/mod/forum/discuss.php?d={did}",
        "started_by": "Ana Proba",
        "started_at": "3 de nov. de 2026",
        "last_post_by": "Ana Proba",
        "last_post_at": "3 de nov. de 2026",
        "replies": replies,
        "unread": unread,
        "pinned": False,
        "locked": False,
    }


@pytest.fixture(autouse=True)
def _cache(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("COLUMNS", "100")
    monkeypatch.setattr(
        sources,
        "fetch_now",
        lambda keys, quiet=False: {key: sources.Result(key, error="sin red") for key in keys},
    )
    style.caps.reset()
    store.write("cursos", COURSES)
    store.write("perfil", {"fullname": "Ana Proba"})
    store.write(
        "contenidos/301",
        {
            "items": [
                _forum(11, "Anuncios"),
                _forum(12, "Foro de consultas"),
                _forum(13, "Dudas del tema 1", 1),
                {"module_id": 21, "module_type": "quiz", "name": "Test 1", "visible": True},
                {"module_id": 22, "module_type": "quiz", "name": "Test 2", "visible": False},
            ]
        },
    )
    store.write("contenidos/302", {"items": [_forum(31, "Foro de novas")]})
    old = [_discussion(n, f"Aviso vello {n}") for n in range(500, 520)]
    store.write(
        "foro/11",
        {"forum_name": "Anuncios", "discussions": [_discussion(900, "Data do exame", replies=2)]},
    )
    store.write(
        "foro/31",
        {
            "forum_name": "Foro de novas",
            "discussions": [_discussion(400, "Sen ler", unread=1), *old],
        },
    )
    store.write(
        "debate/900",
        {
            "items": [
                {
                    "post_id": 2,
                    "parent_post_id": 1,
                    "author": "Brais Exemplo",
                    "created_at": "2026-11-03T12:00:00+01:00",
                    "subject": "Re: Data do exame",
                    "message": "Grazas.",
                },
                {
                    "post_id": 1,
                    "parent_post_id": 0,
                    "author": "Ana Proba",
                    "created_at": "2026-11-03T10:00:00+01:00",
                    "subject": "Data do exame",
                    "message": "O exame será o día 20.\n\nTrae o DNI.",
                    "attachments": [{"filename": "normas.pdf", "url": "https://cv.usc.es/x"}],
                },
            ]
        },
    )
    store.write(
        "notas",
        {
            "courses": [
                {"course_id": 301, "course_name": COURSES[0]["full_name"], "grade": "7,5"},
                {"course_id": 302, "course_name": COURSES[1]["full_name"], "grade": "-"},
                {"course_id": 303, "course_name": COURSES[2]["full_name"], "grade": "3,0"},
            ]
        },
    )
    store.write(
        "notas/301",
        {
            "course_name": COURSES[0]["full_name"],
            "course_total": "7,5",
            "items": [
                {"kind": "category", "level": 1, "name": COURSES[0]["full_name"]},
                {"kind": "category", "level": 2, "name": "Prácticas"},
                {
                    "kind": "item",
                    "level": 3,
                    "name": "Práctica 1",
                    "module": "Tarefa",
                    "grade": "9,0",
                    "range": "0–10",
                    "feedback": "Moi ben, pero revisa o informe.",
                },
                {
                    "kind": "total",
                    "level": 1,
                    "name": "Total do curso",
                    "grade": "7,5",
                    "range": "0–10",
                },
            ],
        },
    )
    now = time.time()
    store.write(
        "mensajes",
        {
            "items": [
                {
                    "user_id_from": 8,
                    "user_id_to": 5,
                    "text": "Ola, mañá non hai clase",
                    "created_at": "2026-11-10T10:00:00+01:00",
                    "is_read": False,
                    "sent": False,
                },
                {
                    "user_id_from": 5,
                    "user_id_to": 9,
                    "text": "Podo ir á titoría?",
                    "created_at": "2026-11-12T10:00:00+01:00",
                    "is_read": True,
                    "sent": True,
                },
            ],
            "names": {"8": "Ana Proba", "9": "Brais Exemplo"},
        },
    )
    store.write(
        "conversa/8",
        {
            "other_name": "Ana Proba",
            "messages": [
                {
                    "from_me": False,
                    "author": "Ana Proba",
                    "text": "Ola,\n\nmañá non hai clase",
                    "created_at": now - 3600,
                },
                {"from_me": True, "author": "Eu", "text": "Grazas!", "created_at": now - 60},
            ],
        },
    )
    store.write(
        "cuestionario/21",
        {
            "name": "Test 1",
            "dates": {"Abertas": "luns, 2 de novembro", "Pechadas": "martes, 3 de novembro"},
            "info": {
                "Intentos permitidos": "2",
                "Método de cualificación": "Cualificación máis alta",
            },
            "attempts": [
                {"Estado": "Finalizada", "Cualificación": "8,00 alén dun máximo de 10,00 ( 80 %)"}
            ],
            "final_grade": "A súa cualificación final nesta proba é 8,00/10,00.",
            "can_attempt": False,
        },
    )
    yield
    style.caps.reset()


def _run(capsys, *argv: str) -> tuple[int, str, str]:
    with pytest.raises(SystemExit) as exit_info:
        app.main(list(argv))
    captured = capsys.readouterr()
    return int(exit_info.value.code or 0), captured.out, captured.err


# --- notas -------------------------------------------------------------------------------------


def test_grades_overview_this_year_and_all(capsys):
    code, output, _ = _run(capsys, "notas")
    assert code == 0 and "Cualificacións" in output and "7,5" in output
    assert "Cálculo" not in output
    _, output, _ = _run(capsys, "notas", "--todos")
    assert "Cálculo" in output and "3,0" in output


def test_grades_of_one_course_with_feedback(capsys):
    code, output, _ = _run(capsys, "notas", "redes")
    text = " ".join(output.split())
    assert code == 0 and "Total do curso 7,5 / 10" in text
    assert "Prácticas" in output and "Práctica 1" in output and "9,0" in output
    assert "Moi ben, pero revisa o informe." in text


# --- avisos, foros, debate ---------------------------------------------------------------------


def test_news_forum_is_the_announcements_one():
    assert foros.news_forum(store.read("contenidos/301")[0])["module_id"] == 11
    assert (
        foros.news_forum({"items": [_forum(5, "Xeral"), _forum(6, "Outro", 2)]})["module_id"] == 5
    )


def test_announcements_of_every_course_unread_always_shown(capsys):
    code, output, _ = _run(capsys, "avisos", "-n", "2")
    assert code == 0 and "Novas" in output and "1 sen ler" in output
    assert "Data do exame" in output and "campus avisos <número>" in output
    assert "campus debate" not in output  # no Moodle ids to type
    row = next(line for line in output.splitlines() if "Data do exame" in line)
    assert row.lstrip().startswith("1 ")  # the newest is number 1
    assert "Sen ler" in output  # unread: listed even beyond -n
    assert "Aviso vello 500" not in output and "máis" in output


def test_an_announcement_is_read_by_its_number(capsys):
    code, output, _ = _run(capsys, "avisos", "1")
    assert code == 0 and "O exame será o día 20." in output and "Grazas." in output
    code, output, _ = _run(capsys, "avisos", "redes", "1")  # numbered within one course
    assert code == 0 and "O exame será o día 20." in output
    code, _, error = _run(capsys, "avisos", "99")
    assert code == 1 and "No hay aviso número 99" in error


def test_a_forum_discussion_is_read_by_its_number(capsys):
    code, output, _ = _run(capsys, "foros", "redes", "1")
    assert code == 0 and "campus foros redes 1 <número>" in output
    code, output, _ = _run(capsys, "foros", "redes", "1", "1")
    assert code == 0 and "O exame será o día 20." in output


def test_course_forums_and_their_discussions(capsys):
    code, output, _ = _run(capsys, "foros", "redes")
    assert code == 0 and "Foro de consultas" in output and "Dudas del tema 1" in output
    code, output, _ = _run(capsys, "foros", "redes", "1")
    assert code == 0 and "Data do exame" in output and "2 respostas" in output
    code, _, error = _run(capsys, "foros", "redes", "9")
    assert code == 1 and "No encuentro el foro" in error


def test_debate_is_threaded_with_paragraphs_and_files(capsys):
    code, output, _ = _run(capsys, "debate", "900")
    assert code == 0 and "2 mensaxes" in output
    assert output.index("O exame será o día 20.") < output.index("Grazas.")
    assert "Trae o DNI." in output and "normas.pdf" in output
    reply = next(line for line in output.splitlines() if "Brais Exemplo" in line)
    assert "│" in reply  # the answer hangs under the post it answers
    assert "marca estas mensaxes como lidas" in output


# --- mensajes ----------------------------------------------------------------------------------


def test_messages_by_person_newest_first(capsys):
    code, output, _ = _run(capsys, "mensajes")
    assert code == 0 and "1 sen ler" in output
    body = output.split("Mensaxes ─", 1)[1]  # the navbar also shows the profile's name
    assert body.index("Brais Exemplo") < body.index("Ana Proba")
    assert "Ti: Podo ir á titoría?" in output


def test_a_conversation(capsys):
    code, output, _ = _run(capsys, "mensajes", "2")
    assert code == 0 and "Ana Proba" in output and "mañá non hai clase" in output
    assert "Ti" in output and "Grazas!" in output and 'campus escribir 2 "…"' in output


class _Messenger:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str, str | None]] = []

    async def search_message_contacts(self, query: str, limit: int) -> list[dict]:
        return [
            {"user_id": 8, "full_name": "Ana Proba"},
            {"user_id": 10, "full_name": "Ana Outra"},
        ]

    async def send_message(self, user_id: int, text: str, *, confirmation_token=None) -> dict:
        self.sent.append((user_id, text, confirmation_token))
        if confirmation_token is None:
            return {"preview": True, "confirmation_token": "t-msg"}
        return {"sent": True}


@pytest.fixture
def messenger(monkeypatch):
    fake = _Messenger()
    monkeypatch.setattr(mensajes, "_new_service", lambda: fake)
    monkeypatch.setattr(mensajes, "_interactive", lambda: False)
    return fake


def test_writing_needs_si_without_a_terminal(capsys, messenger):
    code, output, error = _run(capsys, "escribir", "2", "Ola")
    assert code == 1 and "--si" in error and messenger.sent == []
    assert "Para: Ana Proba" in " ".join(output.split())


def test_writing_previews_then_sends_with_the_token(capsys, messenger):
    code, output, _ = _run(capsys, "escribir", "2", "Ola,", "grazas", "--si")
    assert code == 0 and "Enviada" in output
    assert messenger.sent == [(8, "Ola, grazas", None), (8, "Ola, grazas", "t-msg")]


def test_writing_to_an_ambiguous_name_lists_the_people(capsys, messenger):
    code, _, error = _run(capsys, "escribir", "Ana", "Ola", "--si")
    assert code == 1 and "Ana Proba" in error and "Ana Outra" in error
    assert messenger.sent == []


def test_answering_no_sends_nothing(capsys, messenger, monkeypatch):
    monkeypatch.setattr(mensajes, "_interactive", lambda: True)
    monkeypatch.setattr(mensajes, "_ask", lambda prompt: "n")
    code, output, _ = _run(capsys, "escribir", "Ana Proba", "Ola")
    assert code == 0 and "No se ha enviado nada" in output and messenger.sent == []


# --- cuestionarios -----------------------------------------------------------------------------


def test_quizzes_list_and_detail(capsys):
    code, output, _ = _run(capsys, "cuestionarios")
    assert code == 0 and "Test 1" in output and "Redes" in output
    code, output, _ = _run(capsys, "cuestionarios", "redes")
    assert "1" in output and "non dispoñible" in output
    code, output, _ = _run(capsys, "cuestionarios", "redes", "1")
    text = " ".join(output.split())
    assert code == 0 and "Cualificación 8,00 / 10,00" in text
    assert "Método de cualificación: Cualificación máis alta" in text
    assert "(80 %)" in text and "Non se pode intentar agora" in text


def test_quiz_score_is_extracted():
    lines = cuestionarios.detail_lines({"final_grade": "A nota é 6,5 / 10,0."}, 80)
    assert any("6,5 / 10,0" in line for line in lines)


@pytest.mark.parametrize("columns", ["80", "120"])
def test_every_new_screen_fits(capsys, monkeypatch, columns):
    monkeypatch.setenv("COLUMNS", columns)
    for argv in (
        ["notas"],
        ["notas", "redes"],
        ["avisos"],
        ["foros", "redes"],
        ["foros", "redes", "1"],
        ["debate", "900"],
        ["mensajes"],
        ["mensajes", "2"],
        ["cuestionarios"],
        ["cuestionarios", "redes", "1"],
    ):
        _, output, _ = _run(capsys, *argv)
        assert max(style.width(line) for line in output.splitlines()) <= int(columns), argv


def test_grade_colours_follow_the_range():
    assert notas.grade_text("-").endswith("–")
    assert notas.grade_text("9,0", "0–10") == "9,0"
