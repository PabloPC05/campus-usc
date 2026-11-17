"""`campus entregar`: finding the assignment, asking first, uploading, checking, withdrawing.

Everything runs against a fake engine: the real Campus is never touched.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from campus_usc import app, sources, store, style
from campus_usc.views import entregar

YEAR = sources.academic_year()
OLD_YEAR = f"{int(YEAR[:4]) - 1}/{YEAR[:4]}"
COURSES = [
    {"id": 301, "full_name": f"Redes [G0000001] [{YEAR}]"},
    {"id": 302, "full_name": f"Algoritmos e Estruturas de Datos [G0000002] [{OLD_YEAR}]"},
]


def _assign(module_id: int, name: str, visible: bool = True) -> dict:
    return {
        "section_number": 1,
        "section_name": "Prácticas",
        "module_id": module_id,
        "module_type": "assign",
        "name": name,
        "visible": visible,
    }


CONTENTS = {
    "items": [
        {"section_number": 0, "module_id": 1, "module_type": "forum", "name": "Anuncios"},
        _assign(11, "Ejercicio 1"),
        _assign(12, "Ejercicio 10"),
        _assign(13, "Práctica 3 (G1). Árbores", visible=False),
    ]
}


class FakeService:
    """The few engine calls `entregar` makes, with the state Moodle would keep."""

    def __init__(
        self,
        *,
        files: list[str] | None = None,
        open_: bool = True,
        takes_files: bool = True,
        max_files: int | None = 1,
        submit_step: bool = False,
    ) -> None:
        self.files = list(files or [])
        self.open = open_
        self.takes_files = takes_files
        self.max_files = max_files
        self.submit_step = submit_step
        self.calls: list[tuple] = []

    async def inspect_submission_status(self, cmid, token):
        self.calls.append(("inspect", cmid, token))
        if token is None:
            return {"preview": True, "confirmation_token": "t-inspect"}
        state = (
            ("Borrador (non enviado)" if self.submit_step else "Entregado para cualificacións")
            if self.files
            else "Aínda non se realizaron entregas"
        )
        return {
            "editable": self.open,
            "inspection": {
                "filemanager": {
                    "supported": self.takes_files,
                    "current_files": [{"filename": name, "filepath": "/"} for name in self.files],
                    "max_files": self.max_files,
                    "max_bytes": None,
                }
            },
            "submission_status": {
                "rows": {"Estado da entrega": state, "Número do intento": "1"},
                "submit_for_grading_available": bool(self.files) and self.submit_step,
            },
        }

    async def preview_replace_submission_files(self, assignment_id, paths, cmid):
        self.calls.append(("preview_replace", assignment_id, paths, cmid))
        return {"allowed": True, "confirmation_token": "t-replace"}

    async def replace_submission_files(self, assignment_id, paths, token, cmid):
        self.calls.append(("replace", token))
        self.files = [Path(path).name for path in paths]
        return {"request_sent": True, "outcome": "unknown"}

    async def preview_submit_assignment(self, assignment_id, accept, cmid):
        self.calls.append(("preview_submit", accept, cmid))
        return {"allowed": True, "confirmation_token": "t-submit"}

    async def submit_assignment(self, assignment_id, accept, token, cmid):
        self.calls.append(("submit", token))
        self.submit_step = False
        return {"request_sent": True, "outcome": "unknown"}

    async def preview_remove_submission(self, assignment_id, cmid):
        self.calls.append(("preview_remove", cmid))
        return {"allowed": True, "confirmation_token": "t-remove"}

    async def remove_submission(self, assignment_id, token, cmid):
        self.calls.append(("remove", token))
        self.files = []
        return {"request_sent": True, "outcome": "unknown"}

    def writes(self) -> list[str]:
        return [call[0] for call in self.calls if call[0] in {"replace", "submit", "remove"}]


@pytest.fixture(autouse=True)
def _terminal(tmp_path, monkeypatch):
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
    store.write("contenidos/302", CONTENTS)
    store.write("contenidos/301", {"items": [_assign(21, "Práctica de sockets")]})
    store.write(
        "pendientes",
        [
            {
                "name": "Práctica de sockets",
                "course_id": 301,
                "url": "https://cv.usc.es/mod/assign/view.php?id=21",
                "sort_at": (datetime.now() + timedelta(days=2)).astimezone().isoformat(),
            }
        ],
    )
    yield
    style.caps.reset()


@pytest.fixture
def service(monkeypatch):
    fake = FakeService()
    roots: list = []

    def new_service(upload_root=None):
        roots.append(upload_root)
        return fake

    monkeypatch.setattr(entregar, "_new_service", new_service)
    monkeypatch.setattr(entregar, "_interactive", lambda: False)
    fake.roots = roots
    return fake


@pytest.fixture
def upload(tmp_path) -> Path:
    path = tmp_path / "entrega" / "practica.pdf"
    path.parent.mkdir()
    path.write_bytes(b"%PDF-1.4 proba")
    return path


def _run(capsys, *argv: str) -> tuple[int, str, str]:
    with pytest.raises(SystemExit) as exit_info:
        app.main(list(argv))
    captured = capsys.readouterr()
    return int(exit_info.value.code or 0), captured.out, captured.err


def test_lists_the_course_assignments_with_numbers(capsys, service):
    code, output, _ = _run(capsys, "entregar", "aed")
    assert code == 0
    assert "Tarefas" in output and "Algoritmos e Estruturas de Datos" in output
    assert "  1" in output and "Ejercicio 1" in output and "Anuncios" not in output
    assert "(non dispoñible)" in output
    assert service.calls == []  # listing never opens the Campus


def test_task_by_words_number_position_or_id():
    tasks = entregar.assignments(CONTENTS)
    assert entregar.find_task(tasks, "ejercicio 1")["module_id"] == 11
    assert entregar.find_task(tasks, "ejercicio 10")["module_id"] == 12
    assert entregar.find_task(tasks, "2")["module_id"] == 12
    assert entregar.find_task(tasks, "13")["module_id"] == 13
    assert entregar.find_task(tasks, "arbores")["module_id"] == 13
    with pytest.raises(entregar.TaskNotFound) as error:
        entregar.find_task(tasks, "ejercicio")
    assert len(error.value.options) == 2


def test_looking_opens_the_page_but_writes_nothing(capsys, service):
    code, output, _ = _run(capsys, "entregar", "aed", "ejercicio 1")
    assert code == 0
    assert "Aínda non entregaches nada" in output and "máx. 1 ficheiro(s)" in output
    assert "Estado da entrega: Aínda non se realizaron entregas" in output
    assert "Número do intento" not in output
    assert service.writes() == []


def test_hand_in_uploads_checks_and_reports(capsys, service, upload):
    code, output, _ = _run(capsys, "entregar", "aed", "1", str(upload), "--si")
    assert code == 0, output
    assert service.writes() == ["replace"]
    preview = next(call for call in service.calls if call[0] == "preview_replace")
    assert preview[1] is None and preview[2] == [str(upload)] and preview[3] == 11
    assert service.roots == [upload.parent]  # only the folder you named can be read
    assert "Vas entregar" in output and "practica.pdf" in output
    assert "✓ Subido. Moodle ten agora: practica.pdf" in output
    assert "Entregado para cualificacións" in output and "borrador" not in output


def test_due_date_comes_from_the_cronograma(capsys, service, upload):
    code, output, _ = _run(capsys, "entregar", "redes", "sockets")
    assert code == 0 and "Data límite:" in output


def test_without_a_terminal_it_needs_si(capsys, service, upload):
    code, output, error = _run(capsys, "entregar", "aed", "1", str(upload))
    assert code == 1 and "--si" in error
    assert service.writes() == []


def test_answering_no_hands_in_nothing(capsys, service, upload, monkeypatch):
    monkeypatch.setattr(entregar, "_interactive", lambda: True)
    monkeypatch.setattr(entregar, "_ask", lambda prompt: "n")
    code, output, _ = _run(capsys, "entregar", "aed", "1", str(upload))
    assert code == 0 and "No se ha entregado nada" in output
    assert service.writes() == []


def test_replacing_says_what_will_be_lost(capsys, service, upload):
    service.files = ["vella.pdf"]
    code, output, _ = _run(capsys, "entregar", "aed", "1", str(upload), "--si")
    assert code == 0
    assert "Sustituirá lo que ya tienes entregado: vella.pdf" in output


def test_more_files_than_allowed_is_refused_before_uploading(capsys, service, upload):
    other = upload.parent / "anexo.pdf"
    other.write_bytes(b"anexo")
    code, _, error = _run(capsys, "entregar", "aed", "1", str(upload), str(other), "--si")
    assert code == 1 and "como mucho 1" in error
    assert service.writes() == []


def test_closed_or_fileless_assignments_are_explained(capsys, service, upload):
    service.open = False
    code, _, error = _run(capsys, "entregar", "aed", "1", str(upload), "--si")
    assert code == 1 and "no admite cambios" in error
    service.open, service.takes_files = True, False
    code, _, error = _run(capsys, "entregar", "aed", "1", str(upload), "--si")
    assert code == 1 and "no recibe archivos" in error
    assert service.writes() == []


def test_missing_file_fails_before_the_campus(capsys, service, tmp_path):
    code, _, error = _run(capsys, "entregar", "aed", "1", str(tmp_path / "non.pdf"), "--si")
    assert code == 1 and "No encuentro el archivo" in error
    assert service.calls == []


def test_draft_assignments_say_so_and_enviar_sends_them(capsys, service, upload):
    service.submit_step = True
    code, output, _ = _run(capsys, "entregar", "aed", "1", str(upload), "--si")
    assert code == 0 and "Queda como borrador" in " ".join(output.split())
    assert "--enviar" in output and service.writes() == ["replace"]
    code, output, _ = _run(capsys, "entregar", "aed", "1", "--enviar", "--si")
    assert code == 0 and "Enviada para cualificar" in output
    assert service.writes() == ["replace", "submit"]


def test_withdraw_takes_the_submission_back(capsys, service):
    service.files = ["proba.txt"]
    code, output, _ = _run(capsys, "entregar", "aed", "1", "--retirar", "--si")
    assert code == 0
    assert "Retirará tu entrega: proba.txt" in output and "Entrega retirada" in output
    assert service.writes() == ["remove"]
    code, output, _ = _run(capsys, "entregar", "aed", "1", "--retirar", "--si")
    assert code == 0 and "No tienes nada entregado" in output
    assert service.writes() == ["remove"]


def test_json_report(capsys, service, upload):
    code, output, _ = _run(capsys, "entregar", "aed", "1", str(upload), "--si", "--json")
    assert code == 0
    report = json.loads(output)
    assert report["entregado"] is True and report["despois"]["files"] == ["practica.pdf"]


@pytest.mark.parametrize("columns", ["80", "100"])
def test_screens_fit_the_terminal(capsys, service, upload, monkeypatch, columns):
    monkeypatch.setenv("COLUMNS", columns)
    for argv in (["aed"], ["aed", "1"], ["aed", "1", str(upload), "--si"]):
        _, output, _ = _run(capsys, "entregar", *argv)
        assert max(style.width(line) for line in output.splitlines()) <= int(columns), argv


def test_expired_session_is_renewed_before_anything_changes(capsys, service, upload, monkeypatch):
    from mcp_usc.campus import AuthenticationRequired

    from campus_usc import auth

    original = service.inspect_submission_status
    expired = {"once": True}

    async def inspect_once_expired(cmid, token):
        if expired.pop("once", False):
            raise AuthenticationRequired("caducó")
        return await original(cmid, token)

    renewals = []
    monkeypatch.setattr(service, "inspect_submission_status", inspect_once_expired)
    monkeypatch.setattr(auth, "ensure", lambda interactive: renewals.append(interactive) or True)
    code, output, _ = _run(capsys, "entregar", "aed", "1", str(upload), "--si")
    assert code == 0 and renewals == [False]
    assert service.writes() == ["replace"] and "✓ Subido" in output


def test_a_graded_closed_task_shows_its_grade_and_feedback(capsys, service, monkeypatch):
    original = service.inspect_submission_status

    async def graded(cmid, token):
        result = await original(cmid, token)
        if token is not None:
            result["editable"] = False
            result["submission_status"]["feedback"] = {
                "Cualificación": "9,0 / 10,0",
                "Cualificado por": "Ana Proba",
                "Comentarios": "Moi ben.\n\nRevisa o apartado 3.",
            }
            result["submission_status"]["feedback_files"] = [
                {"name": "correccion.pdf", "url": "https://cv.usc.es/pluginfile.php/x"}
            ]
        return result

    monkeypatch.setattr(service, "inspect_submission_status", graded)
    code, output, _ = _run(capsys, "entregar", "aed", "1")
    text = " ".join(output.split())
    assert code == 0 and "Comentarios" in output
    assert "Cualificación: 9,0 / 10,0" in text and "Cualificado por: Ana Proba" in text
    assert "Moi ben." in output and "Revisa o apartado 3." in output
    assert "correccion.pdf" in output and service.writes() == []
