"""`campus cursos`, `curso`, `materiales`, `descargar`, `abrir` and `notificaciones`."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from campus_usc import app, sources, store, style
from campus_usc.views import curso as curso_view

YEAR = sources.academic_year()
OLD_YEAR = f"{int(YEAR[:4]) - 1}/{YEAR[:4]}"
COURSES = [
    {
        "id": 201,
        "full_name": f"Redes [G0000001] [{YEAR}]",
        "url": "https://cv.usc.es/course/view.php?id=201",
    },
    {"id": 202, "full_name": f"Administración de Sistemas e Redes [G0000002] [{YEAR}]"},
    {"id": 203, "full_name": f"Sistemas Operativos I [G0000003] [{YEAR}]"},
    {"id": 199, "full_name": f"Cálculo [G0000009] [{OLD_YEAR}]"},
]


def _item(section: int, name: str, module: str, title: str, module_id: int) -> dict:
    return {
        "section_number": section,
        "section_name": name,
        "module_id": module_id,
        "module_type": module,
        "module_type_label": {"resource": "Ficheiro", "forum": "Foro", "folder": "Cartafol"}.get(
            module, module
        ),
        "name": title,
        "activity_url": f"https://cv.usc.es/mod/{module}/view.php?id={module_id}",
        "files": [],
        "downloadable": False,
        "visible": True,
    }


CONTENTS = {
    "items": [
        _item(0, "Xeral", "forum", "Anuncios", 1),
        _item(1, "Tema 1: Sockets", "resource", "Transparencias tema 1", 11),
        _item(1, "Tema 1: Sockets", "folder", "Código de exemplo", 12),
        _item(2, "Prácticas", "assign", "Práctica 3", 21),
    ],
    "has_more": False,
}


@pytest.fixture(autouse=True)
def _plain_terminal(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_USC_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MCP_USC_NO_BACKGROUND", "1")
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("COLUMNS", "110")
    monkeypatch.setattr(
        sources,
        "fetch_now",
        lambda keys, quiet=False: {key: sources.Result(key, error="sin red") for key in keys},
    )
    style.caps.reset()
    store.write("cursos", COURSES)
    store.write("perfil", {"fullname": "Ana Proba"})
    now = datetime.now()
    store.write(
        "pendientes",
        [
            {
                "name": "Práctica 3 pendente de entrega",
                "module": "assign",
                "course_id": 201,
                "course_name": COURSES[0]["full_name"],
                "sort_at": (now + timedelta(days=2)).astimezone().isoformat(),
            },
            {
                "name": "Boletín pendente de entrega",
                "module": "assign",
                "course_id": 201,
                "course_name": COURSES[0]["full_name"],
                "sort_at": (now - timedelta(days=2)).astimezone().isoformat(),
                "actionable": True,  # late, still takes it
                "url": "https://cv.usc.es/mod/assign/view.php?id=21",
            },
            {
                "name": "Práctica de outro grupo pendente de entrega",
                "module": "assign",
                "course_id": 201,
                "course_name": COURSES[0]["full_name"],
                "sort_at": (now - timedelta(days=5)).astimezone().isoformat(),
                "actionable": False,  # closed: no longer something to do
            },
        ],
    )
    store.write("contenidos/201", CONTENTS)
    yield
    style.caps.reset()


def _run(capsys, *argv: str) -> tuple[int, str, str]:
    with pytest.raises(SystemExit) as exit_info:
        app.main(list(argv))
    captured = capsys.readouterr()
    return int(exit_info.value.code or 0), captured.out, captured.err


def _widest(text: str) -> int:
    return max(style.width(line) for line in text.splitlines())


@pytest.mark.parametrize("columns", ["80", "110"])
def test_course_cards_fit_and_show_alias_and_pending(capsys, monkeypatch, columns):
    monkeypatch.setenv("COLUMNS", columns)
    code, output, _ = _run(capsys, "cursos")
    assert code == 0
    assert "Os meus cursos" in output
    assert "campus curso redes" in output and "campus curso asr" in output
    assert "1 atrasada" in output
    assert "Cálculo" not in output
    assert _widest(output) <= int(columns)


def test_all_years_include_past_courses(capsys):
    code, output, _ = _run(capsys, "cursos", "--todos")
    assert code == 0 and "Cálculo" in output and OLD_YEAR in output


def test_course_page_lists_sections_and_pending(capsys):
    code, output, _ = _run(capsys, "curso", "redes")
    assert code == 0
    assert "Os meus cursos › Redes" in output
    for text in ("Xeral", "Tema 1: Sockets", "Transparencias tema 1", "Práctica 3", "Pendente"):
        assert text in output
    code, output, _ = _run(capsys, "curso", "redes", "-s", "1")
    assert "Transparencias tema 1" in output and "Anuncios" not in output


def test_ambiguous_course_lists_candidates(capsys):
    code, _, error = _run(capsys, "curso", "sistemas")
    assert code == 1
    assert "coincide con varias" in error and "campus curso asr" in error


def test_materials_only_list_files_and_folders(capsys):
    code, output, _ = _run(capsys, "materiales", "redes")
    assert code == 0
    assert "Transparencias tema 1" in output and "Código de exemplo" in output
    assert "Anuncios" not in output and "11" in output
    code, output, _ = _run(capsys, "materiales", "redes", "--json")
    assert [item["module_id"] for item in json.loads(output)] == [11, 12]


@dataclass
class _Material:
    module_id: int
    name: str


class _FakeService:
    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.downloaded = False

    async def course_download_plan(self, course_id, module_ids=None):
        return {
            "course_id": course_id,
            "items": [_Material(11, "Transparencias tema 1"), _Material(12, "Código")],
            "records_views": True,
            "folder": self.folder,
        }

    async def download_course_files_now(self, plan, *, folder, force, progress):
        self.downloaded = True
        progress(plan["items"][0], "descargado")
        progress(plan["items"][1], "ya estaba")
        return {
            "downloaded": ["a"],
            "already_downloaded": ["b"],
            "failed": [],
            "folder": str(folder),
        }


def test_download_needs_confirmation_without_a_terminal(capsys, monkeypatch, tmp_path):
    service = _FakeService(tmp_path / "Redes")
    monkeypatch.setattr(curso_view, "_new_service", lambda: service)
    monkeypatch.setattr(curso_view, "_interactive", lambda: False)
    code, output, error = _run(capsys, "descargar", "redes")
    assert code == 1 and not service.downloaded
    assert "quedará registrado" in " ".join(output.split()) and "--si" in error


def test_download_with_yes_shows_progress_and_summary(capsys, monkeypatch, tmp_path):
    service = _FakeService(tmp_path / "Redes")
    monkeypatch.setattr(curso_view, "_new_service", lambda: service)
    code, output, _ = _run(capsys, "descargar", "redes", "--si")
    assert code == 0 and service.downloaded
    assert "1/2" in output and "2/2" in output
    assert "1 descargados" in output and "1 ya estaban" in output


def test_download_asks_and_respects_no(capsys, monkeypatch, tmp_path):
    service = _FakeService(tmp_path / "Redes")
    monkeypatch.setattr(curso_view, "_new_service", lambda: service)
    monkeypatch.setattr(curso_view, "_interactive", lambda: True)
    monkeypatch.setattr(curso_view, "_ask", lambda prompt: "n")
    code, output, _ = _run(capsys, "descargar", "redes")
    assert code == 0 and not service.downloaded and "No se ha descargado nada" in output


def test_open_course_or_campus_page(capsys, monkeypatch):
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url) or True)
    code, output, _ = _run(capsys, "abrir", "redes")
    assert code == 0 and opened == ["https://cv.usc.es/course/view.php?id=201"]
    code, output, _ = _run(capsys, "abrir", "calendario")
    assert opened[-1].startswith("https://cv.usc.es/calendar/view.php")


def test_notifications_are_read_only_and_filterable(capsys):
    now = time.time()
    store.write(
        "notificaciones",
        {
            "unread": 1,
            "items": [
                {
                    "id": 1,
                    "subject": "Nova cualificación en Redes",
                    "component": "mod_assign",
                    "timecreated": now - 7200,
                    "read": False,
                },
                {
                    "id": 2,
                    "subject": "Novo tema no foro",
                    "component": "mod_forum",
                    "timecreated": now - 3 * 86400,
                    "read": True,
                },
            ],
        },
    )
    code, output, _ = _run(capsys, "notificaciones")
    assert code == 0
    assert "Notificacións" in output and "1 sen ler" in output
    assert "hai 2 h" in output and "hai 3 días" in output
    code, output, _ = _run(capsys, "n", "--sin-leer")
    assert "Nova cualificación" in output and "Novo tema" not in output


def test_dashboard_course_block(capsys):
    from campus_usc.views.cursos import compact_courses

    lines = compact_courses(
        sources.Result("cursos", COURSES, 0.0),
        sources.Result("pendientes", store.read("pendientes")[0], 0.0),
        100,
    )
    text = "\n".join(lines)
    assert "Redes" in text and "redes" in text and "Cálculo" not in text


def test_course_page_badges_each_pending_task(capsys):
    code, output, _ = _run(capsys, "curso", "redes")
    row = next(line for line in output.splitlines() if "Práctica 3" in line and "Atrasada" in line)
    assert "Tarefa" not in row  # the badge says more than the kind
    assert "1 atrasada sen entregar" in " ".join(output.split())


def test_closed_overdue_tasks_are_not_to_do(capsys):
    code, output, _ = _run(capsys, "pendientes", "-a")
    closed = next(line for line in output.splitlines() if "outro grupo" in line)
    assert "pechada" in closed
    code, output, _ = _run(capsys, "pendientes")
    assert "1 atrasada sin entregar" in " ".join(output.split())


def test_every_page_of_a_long_course_is_kept():
    import asyncio

    class Service:
        async def list_course_contents(self, course_id, section, offset, limit):
            total = 230
            items = [{"module_id": n} for n in range(offset, min(offset + limit, total))]
            return {
                "items": items,
                "has_more": offset + limit < total,
                "next_offset": offset + limit,
                "total_count": total,
            }

    data = asyncio.run(sources.SOURCES["contenidos"].fetch(Service(), "201"))
    assert len(data["items"]) == 230 and data["has_more"] is False
    assert data["items"][-1]["module_id"] == 229


def test_labels_show_the_teachers_text(capsys):
    long = "Profesorado. Ana Proba: catedrática e coordinadora da materia. " * 6
    items = [dict(CONTENTS["items"][0])]
    items.append(
        {
            "section_number": 0,
            "section_name": "Xeral",
            "module_id": 5,
            "module_type": "label",
            "module_type_label": "Etiqueta",
            "name": "ProfesoradoAna...",
            "description": long,
            "visible": True,
        }
    )
    store.write("contenidos/201", {"items": items + CONTENTS["items"][1:], "has_more": False})
    code, output, _ = _run(capsys, "curso", "redes")
    text = " ".join(output.split())
    assert code == 0 and "Ana Proba: catedrática e coordinadora" in text
    assert "ProfesoradoAna" not in text
    label_rows = [
        line for line in output.splitlines() if "coordinadora" in line or "Profesorado." in line
    ]
    assert 1 < len(label_rows) <= 4
